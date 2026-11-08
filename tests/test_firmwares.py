import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from meshtastic_builder.builder import build_info, builder_args, build_firmware_source, stage_patches
from meshtastic_builder.config import load_config
from meshtastic_builder.db import (
    connection,
    get_firmware_version,
    initialize_database,
    list_firmware_versions,
    upsert_firmware_versions,
)
from meshtastic_builder.firmware import (
    list_versions_with_refresh,
    parse_version_properties,
    resolve_supported_version,
    userprefs_cache_path,
)
from meshtastic_builder.firmwares import get_firmware, list_firmwares, load_firmware_catalog
from meshtastic_builder.submissions import create_build_submission

ROOT = Path(__file__).resolve().parent.parent
NODASTIC_SHA = "d" * 40
NAMED_PREFS = '{"USERPREFS_CONFIG_OWNER_LONG_NAME": "Test Node", "USERPREFS_CONFIG_OWNER_SHORT_NAME": "TST"}'
TEMPLATE = '{"USERPREFS_CONFIG_OWNER_LONG_NAME": "", "USERPREFS_CONFIG_OWNER_SHORT_NAME": "DEF", "USERPREFS_FIXED_GPS": ""}'


def temp_config(tmp_path: Path):
    return replace(
        load_config(),
        root_dir=ROOT,
        data_dir=tmp_path,
        db_path=tmp_path / "test.sqlite",
        artifact_dir=tmp_path / "artifacts",
        job_dir=tmp_path / "jobs",
        cache_dir=tmp_path / "cache",
        base_url="http://example.test",
    )


VARIANTS_SHA = "f" * 40
INI_BLOB = "b" * 40
BOARD_INI = """
[env:tbeam]
custom_meshtastic_architecture = esp32
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = LILYGO T-Beam

[env:nrf52_promicro_diy_e28]
custom_meshtastic_architecture = nrf52840
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = NRF52 Pro-micro E28 DIY
"""


def fake_github(url, timeout=15):
    if url == f"https://api.github.com/repos/lazynoda/meshtastic-firmware/git/trees/{NODASTIC_SHA}":
        return json.dumps({"tree": [{"path": "variants", "type": "tree", "sha": VARIANTS_SHA}]}), {}
    if url == f"https://api.github.com/repos/lazynoda/meshtastic-firmware/git/trees/{VARIANTS_SHA}?recursive=1":
        tree = [{"path": "diy/e28/platformio.ini", "type": "blob", "sha": INI_BLOB, "size": 300}]
        return json.dumps({"truncated": False, "tree": tree}), {}
    if url == f"https://raw.githubusercontent.com/lazynoda/meshtastic-firmware/{NODASTIC_SHA}/variants/diy/e28/platformio.ini":
        return BOARD_INI, {}
    if url.startswith("https://api.github.com/repos/derpyspike/jentastic/releases"):
        return json.dumps([{"tag_name": "v2.8.104", "name": "v2.8.104", "published_at": "2026-10-21T00:00:00Z"}]), {}
    if url.startswith("https://api.github.com/repos/derpyspike/jentastic/tags"):
        return json.dumps([{"name": "v2.8.104", "commit": {"sha": "j" * 40}}]), {}
    if url == "https://api.github.com/repos/lazynoda/meshtastic-firmware/commits/nodastic":
        return json.dumps({"sha": NODASTIC_SHA}), {}
    if url == f"https://raw.githubusercontent.com/lazynoda/meshtastic-firmware/{NODASTIC_SHA}/version.properties":
        return "[VERSION]  \nmajor = 2\nminor = 8\nbuild = 1\n", {}
    raise AssertionError(f"unexpected URL {url}")


class CatalogTests(unittest.TestCase):
    def test_shipped_catalog_lists_the_three_firmwares_with_upstream_default(self):
        default, firmwares = load_firmware_catalog(ROOT)
        self.assertEqual(default, "meshtastic")
        self.assertEqual([item.id for item in firmwares], ["meshtastic", "jentastic", "nodastic"])
        nodastic = get_firmware(ROOT, "nodastic")
        self.assertEqual(nodastic.versioning, "branch")
        self.assertEqual(nodastic.branch, "nodastic")
        self.assertEqual(nodastic.clone_url, "https://github.com/lazynoda/meshtastic-firmware.git")

    def test_shipped_catalog_marks_jentastic_boards_that_do_not_fit(self):
        jentastic = get_firmware(ROOT, "jentastic")
        boards = (
            "heltec-mesh-node-t096",
            "heltec-mesh-pocket-5000",
            "heltec-mesh-pocket-5000-inkhud",
            "heltec-mesh-pocket-10000",
            "heltec-mesh-pocket-10000-inkhud",
            "t-echo",
            "t-echo-inkhud",
        )
        for env in boards:
            item = jentastic.unavailable(env, "v2.8.104")
            self.assertIsNotNone(item, env)
            self.assertEqual(item.reason, "firmware_too_big")
            self.assertEqual(item.issue, "https://github.com/lazynoda/meshtastic-builder/issues/3")
            self.assertEqual(item.fixed_since, "2.8.105")
            # Jentastic's fix for issue #3 ships in 2.8.105.
            self.assertIsNone(jentastic.unavailable(env, "v2.8.105"), env)
        self.assertIsNone(jentastic.unavailable("heltec-mesh-node-t114-inkhud", "v2.8.104"))
        self.assertIsNone(get_firmware(ROOT, "meshtastic").unavailable("heltec-mesh-node-t096"))
        self.assertIsNone(get_firmware(ROOT, "nodastic").unavailable("heltec-mesh-node-t096"))

    def test_unavailable_board_is_scoped_to_versions_before_the_fix(self):
        from meshtastic_builder.firmwares import UnavailableBoard

        issue = "https://github.com/a/b/issues/1"
        fixed = UnavailableBoard("t-echo", "firmware_too_big", issue, fixed_since="2.8.105")
        for version, blocked in [
            ("v2.8.103", True),
            ("v2.8.104", True),
            ("2.8.104", True),
            ("v2.8.105", False),
            ("v2.8.105-001", False),
            ("v2.9.0", False),
            ("v3.0.0", False),
            # Unknown or unparsable: refuse, the safe side.
            (None, True),
            ("nodastic", True),
        ]:
            with self.subTest(version=version):
                self.assertEqual(fixed.applies_to(version), blocked)
        forever = UnavailableBoard("t-echo", "firmware_too_big", issue)
        self.assertTrue(forever.applies_to("v9.9.9"))
        self.assertEqual(
            fixed.public(), {"reason": "firmware_too_big", "issue": issue, "fixedSinceFirmwareVersion": "2.8.105"}
        )
        self.assertNotIn("fixedSinceFirmwareVersion", forever.public())

    def test_catalog_rejects_malformed_unavailable_boards(self):
        base = {"id": "x", "name": "X", "url": "https://github.com/a/b", "versioning": "tags"}
        cases = [
            {"t096": {"reason": "firmware_too_big", "issue": "https://github.com/a/b/issues/1", "fixedSinceFirmwareVersion": "v2.8.105"}},
            {"t096": {"reason": "firmware_too_big", "issue": "https://github.com/a/b/issues/1", "fixedSinceFirmwareVersion": 2.8}},
            {"t096": {"reason": "firmware_too_big", "issue": "https://github.com/a/b/issues/1", "fixedSinceFirmwareVersion": "2.8"}},
            ["t096"],
            {"bad env!": {"reason": "firmware_too_big", "issue": "https://github.com/a/b/issues/1"}},
            {"t096": {"issue": "https://github.com/a/b/issues/1"}},
            {"t096": {"reason": "firmware_too_big", "issue": "https://evil.test/issues/1"}},
            {"t096": {"reason": "firmware_too_big"}},
        ]
        for unavailable in cases:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "data").mkdir()
                entry = {**base, "unavailableBoards": unavailable}
                (Path(tmp) / "data" / "firmwares.json").write_text(json.dumps({"firmwares": [entry]}))
                with self.assertRaises(ValueError, msg=repr(unavailable)):
                    load_firmware_catalog(Path(tmp))

    def test_missing_catalog_falls_back_to_upstream_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([item.id for item in list_firmwares(Path(tmp))], ["meshtastic"])

    def test_catalog_rejects_non_github_urls_and_bad_branches(self):
        cases = [
            {"id": "x", "name": "X", "url": "https://evil.test/a/b", "versioning": "tags"},
            {"id": "x", "name": "X", "url": "https://github.com/a/b", "versioning": "branch", "branch": "a b"},
            {"id": "x", "name": "X", "url": "https://github.com/a/b", "versioning": "branch"},
        ]
        for entry in cases:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "data").mkdir()
                (Path(tmp) / "data" / "firmwares.json").write_text(json.dumps({"firmwares": [entry]}))
                with self.assertRaises(ValueError):
                    load_firmware_catalog(Path(tmp))

    def test_unknown_firmware_is_a_user_error(self):
        with self.assertRaises(ValueError):
            get_firmware(ROOT, "nope")


class MigrationTests(unittest.TestCase):
    def test_legacy_tag_cache_becomes_upstream_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            config.db_path.parent.mkdir(parents=True, exist_ok=True)
            legacy = sqlite3.connect(config.db_path)
            legacy.executescript(
                """
                CREATE TABLE firmware_versions (
                  tag TEXT PRIMARY KEY, sha TEXT NOT NULL, release_name TEXT, published_at TEXT,
                  supported INTEGER NOT NULL DEFAULT 1,
                  smoke_test_status TEXT NOT NULL DEFAULT 'untested', last_checked_at TEXT NOT NULL
                );
                INSERT INTO firmware_versions VALUES ('v2.8.1.8e6a88d', 'abc', 'v2.8.1.8e6a88d', NULL, 0, 'untested', 'x');
                """
            )
            legacy.commit()
            legacy.close()

            initialize_database(config)
            initialize_database(config)  # idempotent

            row = get_firmware_version(config, "v2.8.1.8e6a88d", firmware_id="meshtastic")
            self.assertEqual(row["sha"], "abc")
            self.assertEqual(row["supported"], 0)
            conn = sqlite3.connect(config.db_path)
            build_columns = {r[1] for r in conn.execute("PRAGMA table_info(build_requests)")}
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
            self.assertIn("firmware_id", build_columns)
            self.assertIn("firmware_version", build_columns)
            self.assertNotIn("firmware_versions_legacy", tables)


class VersionTests(unittest.TestCase):
    def test_same_tag_name_is_kept_apart_per_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            upsert_firmware_versions(config, [{"tag": "v2.8.104", "sha": "a"}], firmware_id="meshtastic")
            upsert_firmware_versions(config, [{"tag": "v2.8.104", "sha": "b"}], firmware_id="jentastic")
            self.assertEqual(get_firmware_version(config, "v2.8.104", "meshtastic")["sha"], "a")
            self.assertEqual(get_firmware_version(config, "v2.8.104", "jentastic")["sha"], "b")
            self.assertEqual(len(list_firmware_versions(config, firmware_id="jentastic")), 1)

    def test_jentastic_tags_come_from_its_own_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            with patch("meshtastic_builder.firmware._http_get", fake_github):
                versions = list_versions_with_refresh(config, firmware_id="jentastic")
            self.assertEqual([item["tag"] for item in versions], ["v2.8.104"])
            self.assertEqual(versions[0]["version"], "v2.8.104")
            self.assertFalse(versions[0]["branch"])
            self.assertEqual(list_firmware_versions(config, firmware_id="meshtastic"), [])

    def test_branch_firmware_resolves_head_and_its_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            with patch("meshtastic_builder.firmware._http_get", fake_github):
                versions = list_versions_with_refresh(config, firmware_id="nodastic")
                # Whatever tag a client sends, a branch firmware builds its head.
                resolved = resolve_supported_version(config, "v9.9.9", firmware_id="nodastic")
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["tag"], "nodastic")
            self.assertEqual(versions[0]["sha"], NODASTIC_SHA)
            self.assertEqual(versions[0]["version"], "2.8.1")
            self.assertTrue(versions[0]["branch"])
            self.assertEqual(resolved["sha"], NODASTIC_SHA)

    def test_branch_head_falls_back_to_cache_when_github_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            with patch("meshtastic_builder.firmware._http_get", fake_github):
                list_versions_with_refresh(config, firmware_id="nodastic")

            def broken(url, timeout=15):
                raise TimeoutError("down")

            with patch("meshtastic_builder.firmware._http_get", broken):
                versions = list_versions_with_refresh(config, firmware_id="nodastic", force_refresh=True)
            self.assertEqual(versions[0]["sha"], NODASTIC_SHA)

    def test_tags_deleted_upstream_stop_being_offered(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            pages = {
                "before": [{"name": "v2.8.104", "commit": {"sha": "a" * 40}},
                           {"name": "v2.8.104-001", "commit": {"sha": "b" * 40}}],
                "after": [{"name": "v2.8.104", "commit": {"sha": "a" * 40}}],
            }
            state = {"page": "before"}

            def github(url, timeout=15):
                if "/releases" in url:
                    return json.dumps([{"tag_name": i["name"], "name": i["name"]} for i in pages[state["page"]]]), {}
                return json.dumps(pages[state["page"]]), {}

            with patch("meshtastic_builder.firmware._http_get", github):
                list_versions_with_refresh(config, firmware_id="jentastic")
                state["page"] = "after"
                tags = [v["tag"] for v in list_versions_with_refresh(config, firmware_id="jentastic", force_refresh=True)]
            self.assertEqual(tags, ["v2.8.104"])
            # Kept, unsupported, so builds made from it still resolve.
            self.assertEqual(get_firmware_version(config, "v2.8.104-001", "jentastic")["supported"], 0)

    def test_a_page_cap_never_retires_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(temp_config(Path(tmp)), github_max_tag_pages=1)
            upsert_firmware_versions(config, [{"tag": "v2.8.103", "sha": "o"}], firmware_id="jentastic")

            def github(url, timeout=15):
                if "/releases" in url:
                    return json.dumps([{"tag_name": "v2.8.105", "name": "v2.8.105"}]), {}
                return (
                    json.dumps([{"name": "v2.8.105", "commit": {"sha": "n" * 40}}]),
                    {"Link": '<https://api.github.test/tags?page=2>; rel="next"'},
                )

            with patch("meshtastic_builder.firmware._http_get", github):
                list_versions_with_refresh(config, firmware_id="jentastic", force_refresh=True)
            self.assertEqual(get_firmware_version(config, "v2.8.103", "jentastic")["supported"], 1)

    def test_version_properties_parsing(self):
        self.assertEqual(parse_version_properties("[VERSION]  \nmajor = 2\nminor = 8\nbuild = 104\n"), "2.8.104")
        self.assertIsNone(parse_version_properties("[VERSION]\nmajor = 2\n"))
        self.assertIsNone(parse_version_properties(""))

    def test_template_cache_is_per_firmware_and_upstream_path_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            self.assertEqual(
                userprefs_cache_path(config, "v2.8.1"), config.cache_dir / "userprefs" / "v2.8.1.jsonc"
            )
            self.assertNotEqual(
                userprefs_cache_path(config, "v2.8.1", "jentastic"), userprefs_cache_path(config, "v2.8.1")
            )


class SubmissionTests(unittest.TestCase):
    def submit(self, config, payload):
        return create_build_submission(
            config,
            {"deviceId": "tbeam", "prefsJsonc": NAMED_PREFS, **payload},
        )

    def test_nodastic_submission_stores_branch_head_and_firmware_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            cache = userprefs_cache_path(config, NODASTIC_SHA, "nodastic")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(TEMPLATE, encoding="utf-8")
            with patch("meshtastic_builder.firmware._http_get", fake_github):
                result = self.submit(config, {"firmwareId": "nodastic"})
            row = result["row"]
            self.assertEqual(row["firmware_id"], "nodastic")
            self.assertEqual(row["firmware_tag"], "nodastic")
            self.assertEqual(row["firmware_sha"], NODASTIC_SHA)
            self.assertEqual(row["firmware_version"], "2.8.1")
            self.assertEqual(result["public"]["firmwareId"], "nodastic")

    def test_submission_without_firmware_id_means_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            upsert_firmware_versions(config, [{"tag": "v-test", "sha": "abc"}])
            cache = userprefs_cache_path(config, "v-test")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(TEMPLATE, encoding="utf-8")
            row = self.submit(config, {"firmwareTag": "v-test"})["row"]
            self.assertEqual(row["firmware_id"], "meshtastic")
            self.assertEqual(row["firmware_version"], "v-test")

    def test_tag_firmware_still_requires_a_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            with self.assertRaises(ValueError):
                self.submit(config, {"firmwareId": "jentastic"})

    def test_upstream_tag_is_not_accepted_for_another_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            upsert_firmware_versions(config, [{"tag": "v2.8.1.8e6a88d", "sha": "abc"}])
            with patch("meshtastic_builder.firmware._http_get", fake_github):
                with self.assertRaises(Exception):
                    self.submit(config, {"firmwareId": "jentastic", "firmwareTag": "v2.8.1.8e6a88d"})


class BoardCatalogTests(unittest.TestCase):
    def test_boards_come_from_the_firmware_commit_and_are_cached(self):
        from meshtastic_builder.board_catalog import devices_for

        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            calls = []

            def counting(url, timeout=15):
                calls.append(url)
                return fake_github(url, timeout)

            source = get_firmware(ROOT, "nodastic")
            with patch("meshtastic_builder.firmware._http_get", counting):
                devices, from_firmware = devices_for(config, source, NODASTIC_SHA)
                first_calls = len(calls)
                again, _ = devices_for(config, source, NODASTIC_SHA)
            self.assertTrue(from_firmware)
            by_env = {d.platformio_env: d for d in devices}
            # Known board keeps the id from data/devices.json; the fork's own one gets a new id.
            self.assertEqual(by_env["tbeam"].id, "tbeam")
            self.assertEqual(by_env["nrf52_promicro_diy_e28"].id, "nrf52-promicro-diy-e28")
            self.assertEqual(by_env["nrf52_promicro_diy_e28"].label, "NRF52 Pro-micro E28 DIY")
            self.assertEqual(len(devices), 2)
            self.assertEqual(first_calls, 3)
            self.assertEqual(len(calls), first_calls)  # second lookup served from SQLite
            self.assertEqual([d.id for d in again], [d.id for d in devices])

    def test_platformio_version_is_read_with_the_boards_and_stored(self):
        from meshtastic_builder import platformio_versions
        from meshtastic_builder.board_catalog import catalog_for, platformio_for_build

        platformio_versions._engine_cache.clear()
        root_ini = "[platformio]\nextra_configs =\n  variants/*/*.ini\n  variants/*/*/platformio.ini\n"
        esp = (
            "[esp32_common]\nplatform =\n  # TODO renovate\n"
            "  https://github.com/pioarduino/platform-espressif32/releases/download/55.03.312-1/platform-espressif32.zip\n"
        )
        boards = BOARD_INI.replace(
            "[env:tbeam]\n", "[env:tbeam]\nextends = esp32_common\n"
        ).replace("[env:nrf52_promicro_diy_e28]\n", "[env:nrf52_promicro_diy_e28]\nplatform = platformio/nordicnrf52@11.0.0\n")
        files = {
            "platformio.ini": root_ini,
            "variants/esp32/esp32-common.ini": esp,
            "variants/diy/e28/platformio.ini": boards,
        }
        engines = {
            "pioarduino/platform-espressif32/55.03.312-1": ">=6.2.0",
            "platformio/platform-nordicnrf52/v11.0.0": "^6",
        }
        calls = []

        def github(url, timeout=15):
            calls.append(url)
            base = "https://api.github.com/repos/lazynoda/meshtastic-firmware/git/trees/"
            if url == base + NODASTIC_SHA:
                tree = [
                    {"path": "variants", "type": "tree", "sha": VARIANTS_SHA},
                    {"path": "platformio.ini", "type": "blob", "sha": "c" * 40, "size": 80},
                ]
                return json.dumps({"tree": tree}), {}
            if url == base + VARIANTS_SHA + "?recursive=1":
                tree = [
                    {"path": "diy/e28/platformio.ini", "type": "blob", "sha": INI_BLOB, "size": 300},
                    {"path": "esp32/esp32-common.ini", "type": "blob", "sha": "e" * 40, "size": 200},
                ]
                return json.dumps({"truncated": False, "tree": tree}), {}
            raw = f"https://raw.githubusercontent.com/lazynoda/meshtastic-firmware/{NODASTIC_SHA}/"
            if url.startswith(raw) and url[len(raw):] in files:
                return files[url[len(raw):]], {}
            for key, engine in engines.items():
                if url == f"https://raw.githubusercontent.com/{key}/platform.json":
                    return json.dumps({"engines": {"platformio": engine}}), {}
            raise AssertionError(f"unexpected URL {url}")

        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            source = get_firmware(ROOT, "nodastic")
            with patch("meshtastic_builder.firmware._http_get", github):
                _devices, platformio, from_firmware = catalog_for(config, source, NODASTIC_SHA)
                first = len(calls)
                self.assertEqual(platformio_for_build(config, source, NODASTIC_SHA, "tbeam"), "6.2.0")
            self.assertTrue(from_firmware)
            self.assertEqual(platformio, {"tbeam": "6.2.0", "nrf52_promicro_diy_e28": "6.1.19"})
            self.assertEqual(len(calls), first)  # the worker's lookup is served from SQLite
            with connection(config) as conn:
                stored = json.loads(conn.execute("SELECT devices_json FROM board_catalogs").fetchone()[0])
            self.assertEqual(stored["format"], 5)
            self.assertEqual(stored["platformio"]["tbeam"], "6.2.0")

    def test_platformio_lookup_down_serves_boards_but_stores_nothing(self):
        from meshtastic_builder import platformio_versions
        from meshtastic_builder.board_catalog import catalog_for

        platformio_versions._engine_cache.clear()

        def github(url, timeout=15):
            base = "https://api.github.com/repos/lazynoda/meshtastic-firmware/git/trees/"
            if url == base + NODASTIC_SHA:
                tree = [
                    {"path": "variants", "type": "tree", "sha": VARIANTS_SHA},
                    {"path": "platformio.ini", "type": "blob", "sha": "c" * 40, "size": 80},
                ]
                return json.dumps({"tree": tree}), {}
            if url.endswith("/platformio.ini") and "/variants/" not in url:
                return "[platformio]\nextra_configs = variants/*/*/platformio.ini\n", {}
            if url.endswith("/platform.json"):
                raise TimeoutError("down")
            body = BOARD_INI.replace("[env:tbeam]\n", "[env:tbeam]\nplatform = platformio/espressif32@6.13.0\n")
            if url.endswith("variants/diy/e28/platformio.ini"):
                return body, {}
            return fake_github(url, timeout)

        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            source = get_firmware(ROOT, "nodastic")
            with patch("meshtastic_builder.firmware._http_get", github):
                devices, platformio, from_firmware = catalog_for(config, source, NODASTIC_SHA)
            self.assertTrue(from_firmware)
            self.assertEqual(len(devices), 2)
            self.assertIsNone(platformio["tbeam"])
            with connection(config) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM board_catalogs").fetchone()[0], 0)

    def test_board_needing_a_core_the_image_lacks_is_listed_but_refused(self):
        from meshtastic_builder.board_catalog import get_device_for_build
        from meshtastic_builder.devices import Device
        from meshtastic_builder.app import device_json

        board = Device(id="tbeam", label="LILYGO T-Beam", platformio_env="tbeam", family="esp32", enabled=True)
        source = get_firmware(ROOT, "nodastic")
        payload = device_json(board, source, "2.8.1", {"tbeam": "unsupported"})
        self.assertEqual(payload["unavailable"]["reason"], "platformio_unsupported")
        self.assertNotIn("unavailable", device_json(board, source, "2.8.1", {"tbeam": "6.2.0"}))
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            with patch(
                "meshtastic_builder.board_catalog.catalog_for", return_value=([board], {"tbeam": "unsupported"}, True)
            ):
                with self.assertRaisesRegex(ValueError, "PlatformIO"):
                    get_device_for_build(config, source, NODASTIC_SHA, "tbeam", version="2.8.1")

    def test_github_down_falls_back_to_the_static_list(self):
        from meshtastic_builder.board_catalog import devices_for
        from meshtastic_builder.devices import enabled_devices

        def broken(url, timeout=15):
            raise TimeoutError("down")

        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            with patch("meshtastic_builder.firmware._http_get", broken):
                devices, from_firmware = devices_for(config, get_firmware(ROOT, "nodastic"), NODASTIC_SHA)
            self.assertFalse(from_firmware)
            self.assertEqual(len(devices), len(enabled_devices(ROOT)))

    def test_submission_refuses_a_board_the_firmware_does_not_have(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            cache = userprefs_cache_path(config, NODASTIC_SHA, "nodastic")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(TEMPLATE, encoding="utf-8")
            with patch("meshtastic_builder.firmware._http_get", fake_github):
                with self.assertRaises(ValueError):
                    create_build_submission(
                        config,
                        {"deviceId": "heltec-v4", "firmwareId": "nodastic", "prefsJsonc": NAMED_PREFS},
                    )
                row = create_build_submission(
                    config,
                    {"deviceId": "nrf52-promicro-diy-e28", "firmwareId": "nodastic", "prefsJsonc": NAMED_PREFS},
                )["row"]
            self.assertEqual(row["platformio_env"], "nrf52_promicro_diy_e28")
            self.assertEqual(row["device_label"], "NRF52 Pro-micro E28 DIY")

    def test_unavailable_board_is_listed_with_its_reason_but_refused(self):
        from meshtastic_builder.app import device_json
        from meshtastic_builder.board_catalog import devices_for
        from meshtastic_builder.firmwares import UnavailableBoard

        issue = "https://github.com/lazynoda/meshtastic-builder/issues/3"
        source = replace(
            get_firmware(ROOT, "nodastic"),
            unavailable_boards=(UnavailableBoard("nrf52_promicro_diy_e28", "firmware_too_big", issue),),
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            cache = userprefs_cache_path(config, NODASTIC_SHA, "nodastic")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(TEMPLATE, encoding="utf-8")
            with patch("meshtastic_builder.firmware._http_get", fake_github), patch(
                "meshtastic_builder.submissions.get_firmware", return_value=source
            ):
                devices, _ = devices_for(config, source, NODASTIC_SHA)
                listed = {d.platformio_env: device_json(d, source) for d in devices}
                with self.assertRaises(ValueError) as refused:
                    create_build_submission(
                        config,
                        {"deviceId": "nrf52-promicro-diy-e28", "firmwareId": "nodastic", "prefsJsonc": NAMED_PREFS},
                    )
                # Another board of the same firmware still builds.
                row = create_build_submission(
                    config,
                    {"deviceId": "tbeam", "firmwareId": "nodastic", "prefsJsonc": NAMED_PREFS},
                )["row"]
            self.assertEqual(
                listed["nrf52_promicro_diy_e28"]["unavailable"], {"reason": "firmware_too_big", "issue": issue}
            )
            self.assertNotIn("unavailable", listed["tbeam"])
            self.assertIn(issue, str(refused.exception))
            self.assertEqual(row["platformio_env"], "tbeam")
            with connection(config) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM build_requests").fetchone()[0], 1)

    def test_board_fixed_in_a_later_version_is_refused_only_before_it(self):
        from meshtastic_builder.app import device_json
        from meshtastic_builder.board_catalog import devices_for
        from meshtastic_builder.firmwares import UnavailableBoard

        issue = "https://github.com/lazynoda/meshtastic-builder/issues/3"
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            cache = userprefs_cache_path(config, NODASTIC_SHA, "nodastic")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(TEMPLATE, encoding="utf-8")
            # The fake Nodastic head is 2.8.1: fixed in 2.8.2 = still broken; fixed in 2.8.1 = builds.
            for fixed_since, refused in (("2.8.2", True), ("2.8.1", False)):
                source = replace(
                    get_firmware(ROOT, "nodastic"),
                    unavailable_boards=(
                        UnavailableBoard("nrf52_promicro_diy_e28", "firmware_too_big", issue, fixed_since=fixed_since),
                    ),
                )
                with self.subTest(fixed_since=fixed_since), patch(
                    "meshtastic_builder.firmware._http_get", fake_github
                ), patch("meshtastic_builder.submissions.get_firmware", return_value=source):
                    devices, _ = devices_for(config, source, NODASTIC_SHA)
                    listed = {d.platformio_env: device_json(d, source, "2.8.1") for d in devices}
                    payload = {"deviceId": "nrf52-promicro-diy-e28", "firmwareId": "nodastic", "prefsJsonc": NAMED_PREFS}
                    if refused:
                        self.assertEqual(
                            listed["nrf52_promicro_diy_e28"]["unavailable"]["fixedSinceFirmwareVersion"], "2.8.2"
                        )
                        with self.assertRaises(ValueError) as error:
                            create_build_submission(config, payload)
                        self.assertIn("2.8.2", str(error.exception))
                        self.assertIn(issue, str(error.exception))
                    else:
                        self.assertNotIn("unavailable", listed["nrf52_promicro_diy_e28"])
                        row = create_build_submission(config, payload)["row"]
                        self.assertEqual(row["platformio_env"], "nrf52_promicro_diy_e28")

    def test_hostile_env_names_are_dropped(self):
        from meshtastic_builder.device_sync import parse_boards

        text = """
[env:ok]
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Ok
[env:bad;rm -rf]
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Bad
"""
        self.assertEqual(sorted(parse_boards([("variants/x/platformio.ini", text)])), ["ok"])


MUI_INI = """
[env:t-deck]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = LILYGO T-Deck
custom_meshtastic_has_mui = true
board_level = release

[env:t-deck-tft]
extends = env:t-deck
board_level = pr

[env:t-watch-ultra]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = T-Watch Ultra
custom_meshtastic_has_mui = true

[env:t-watch-ultra-tft]
extends = env:t-watch-ultra
board_level = extra

[env:heltec-v4]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Heltec V4
custom_meshtastic_has_mui = true

[env:heltec-v4-tft]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Heltec V4 TFT

[env:elecrow-adv-35-tft]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Crowpanel Adv 3.5 TFT
custom_meshtastic_has_mui = true

[env:unphone]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = unPhone
custom_meshtastic_has_mui = true

[env:tbeam]
custom_meshtastic_architecture = esp32
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = LILYGO T-Beam
"""
MUI_SHA = "e" * 40


def fake_github_mui(url, timeout=15):
    if url == f"https://api.github.com/repos/lazynoda/meshtastic-firmware/git/trees/{MUI_SHA}":
        return json.dumps({"tree": [{"path": "variants", "type": "tree", "sha": VARIANTS_SHA}]}), {}
    if url == f"https://api.github.com/repos/lazynoda/meshtastic-firmware/git/trees/{VARIANTS_SHA}?recursive=1":
        tree = [{"path": "esp32s3/all/platformio.ini", "type": "blob", "sha": "c" * 40, "size": 900}]
        return json.dumps({"truncated": False, "tree": tree}), {}
    if url == f"https://raw.githubusercontent.com/lazynoda/meshtastic-firmware/{MUI_SHA}/variants/esp32s3/all/platformio.ini":
        return MUI_INI, {}
    return fake_github(url, timeout)


class MeshtasticUiTests(unittest.TestCase):
    """The Web Flasher's "Meshtastic UI" switch builds the board's `<env>-tft` env."""

    def test_only_boards_with_a_hidden_tft_env_get_the_option(self):
        from meshtastic_builder.device_sync import parse_boards

        boards = parse_boards([("variants/esp32s3/all/platformio.ini", MUI_INI)])
        self.assertEqual(boards["t-deck"].mui_env, "t-deck-tft")
        # board_level = extra: the flasher never builds it.
        self.assertIsNone(boards["t-watch-ultra"].mui_env)
        # The -tft env is a board of its own in the list: picked directly, no switch.
        self.assertIsNone(boards["heltec-v4"].mui_env)
        self.assertIn("heltec-v4-tft", boards)
        # Already the MUI build, and a board with has_mui but no -tft env.
        self.assertIsNone(boards["elecrow-adv-35-tft"].mui_env)
        self.assertIsNone(boards["unphone"].mui_env)
        self.assertIsNone(boards["tbeam"].mui_env)
        self.assertNotIn("t-deck-tft", boards)

    def test_mui_build_uses_the_tft_env_and_is_labelled(self):
        from meshtastic_builder.app import device_json
        from meshtastic_builder.board_catalog import devices_for

        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            source = get_firmware(ROOT, "nodastic")
            cache = userprefs_cache_path(config, MUI_SHA, "nodastic")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(TEMPLATE, encoding="utf-8")

            def head(url, timeout=15):
                if url == "https://api.github.com/repos/lazynoda/meshtastic-firmware/commits/nodastic":
                    return json.dumps({"sha": MUI_SHA}), {}
                if url.endswith(f"{MUI_SHA}/version.properties"):
                    return "major = 2\nminor = 8\nbuild = 1\n", {}
                return fake_github_mui(url, timeout)

            with patch("meshtastic_builder.firmware._http_get", head):
                devices, _ = devices_for(config, source, MUI_SHA)
                listed = {d.id: device_json(d, source) for d in devices}

                def submit(device_id, **extra):
                    return create_build_submission(
                        config,
                        {"deviceId": device_id, "firmwareId": "nodastic", "prefsJsonc": NAMED_PREFS, **extra},
                    )

                mui_row = submit("t-deck", mui=True)["row"]
                plain_row = submit("t-deck")["row"]
                with self.assertRaises(ValueError):
                    submit("tbeam", mui=True)
                with self.assertRaises(ValueError):
                    submit("t-deck", mui="yes")
            self.assertTrue(listed["t-deck"]["mui"])
            self.assertNotIn("mui", listed["tbeam"])
            self.assertNotIn("t-deck-tft", listed)
            self.assertEqual(mui_row["platformio_env"], "t-deck-tft")
            self.assertEqual(mui_row["device_id"], "t-deck")
            self.assertEqual(mui_row["device_label"], "LILYGO T-Deck (Meshtastic UI)")
            self.assertEqual(plain_row["platformio_env"], "t-deck")
            self.assertEqual(plain_row["device_label"], "LILYGO T-Deck")

    def test_lists_cached_before_meshtastic_ui_are_read_again(self):
        from meshtastic_builder.board_catalog import devices_for

        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            initialize_database(config)
            old = [{"id": "t-deck", "label": "LILYGO T-Deck", "platformio_env": "t-deck", "family": "esp32-s3", "enabled": True}]
            with connection(config) as conn:
                conn.execute(
                    "INSERT INTO board_catalogs (firmware_id, sha, devices_json, created_at) VALUES (?, ?, ?, ?)",
                    ("nodastic", MUI_SHA, json.dumps(old), "2026-10-01T00:00:00+00:00"),
                )
            with patch("meshtastic_builder.firmware._http_get", fake_github_mui):
                devices, _ = devices_for(config, get_firmware(ROOT, "nodastic"), MUI_SHA)
            self.assertEqual({d.id: d.mui_env for d in devices}["t-deck"], "t-deck-tft")


HYBRID_INI = """
[nrf52840_base]
custom_meshtastic_architecture = nrf52840

[env:heltec-mesh-node-t096]
extends = nrf52840_base
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Heltec Mesh Node 096

[env:heltec-mesh-node-t096-hybrid]
extends = env:heltec-mesh-node-t096
build_flags = -DNEXUS_ENABLE_JENCORE=1 -DNEXUS_ENABLE_RNODE=1

[env:tbeam]
custom_meshtastic_architecture = esp32
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = LILYGO T-Beam

[env:tbeam-hybrid]
extends = env:tbeam
board_level = extra

[env:rak4631]
custom_meshtastic_architecture = nrf52840
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = RAK4631

[env:rak4631-hybrid]
extends = env:rak4631
custom_meshtastic_display_name = RAK4631 Hybrid

[env:noscreen]
extends = nrf52840_base
board_level = release

[env:noscreen-hybrid]
extends = env:noscreen
"""
HYBRID_SHA = "f" * 40


class HybridTests(unittest.TestCase):
    """Jentastic's `<env>-hybrid` (JenCore + RNode) is a switch on the board, like Meshtastic UI."""

    def test_only_boards_with_a_hidden_hybrid_env_get_the_option(self):
        from meshtastic_builder.device_sync import parse_boards

        boards = parse_boards([("variants/nrf52840/all/platformio.ini", HYBRID_INI)])
        self.assertEqual(boards["heltec-mesh-node-t096"].hybrid_env, "heltec-mesh-node-t096-hybrid")
        self.assertNotIn("heltec-mesh-node-t096-hybrid", boards)
        # board_level = extra: not offered.
        self.assertIsNone(boards["tbeam"].hybrid_env)
        # A hybrid env with its own display name is a board of its own, picked directly.
        self.assertIsNone(boards["rak4631"].hybrid_env)
        self.assertIn("rak4631-hybrid", boards)
        # Its base is not an offered board, so there is nothing to hang the switch on.
        self.assertNotIn("noscreen", boards)
        self.assertNotIn("noscreen-hybrid", boards)

    def test_hybrid_build_uses_the_hybrid_env_and_is_labelled(self):
        from meshtastic_builder.app import device_json
        from meshtastic_builder.board_catalog import devices_for

        def head(url, timeout=15):
            if url == "https://api.github.com/repos/lazynoda/meshtastic-firmware/commits/nodastic":
                return json.dumps({"sha": HYBRID_SHA}), {}
            if url.endswith(f"{HYBRID_SHA}/version.properties"):
                return "major = 2\nminor = 8\nbuild = 105\n", {}
            if url == f"https://api.github.com/repos/lazynoda/meshtastic-firmware/git/trees/{HYBRID_SHA}":
                return json.dumps({"tree": [{"path": "variants", "type": "tree", "sha": VARIANTS_SHA}]}), {}
            if url == f"https://api.github.com/repos/lazynoda/meshtastic-firmware/git/trees/{VARIANTS_SHA}?recursive=1":
                tree = [{"path": "nrf52840/all/platformio.ini", "type": "blob", "sha": "9" * 40, "size": 900}]
                return json.dumps({"truncated": False, "tree": tree}), {}
            if url == f"https://raw.githubusercontent.com/lazynoda/meshtastic-firmware/{HYBRID_SHA}/variants/nrf52840/all/platformio.ini":
                return HYBRID_INI, {}
            return fake_github(url, timeout)

        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            source = get_firmware(ROOT, "nodastic")
            cache = userprefs_cache_path(config, HYBRID_SHA, "nodastic")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(TEMPLATE, encoding="utf-8")
            with patch("meshtastic_builder.firmware._http_get", head):
                devices, _ = devices_for(config, source, HYBRID_SHA)
                listed = {d.platformio_env: device_json(d, source) for d in devices}

                def submit(device_id, **extra):
                    return create_build_submission(
                        config,
                        {"deviceId": device_id, "firmwareId": "nodastic", "prefsJsonc": NAMED_PREFS, **extra},
                    )

                t096 = listed["heltec-mesh-node-t096"]["id"]
                hybrid_row = submit(t096, hybrid=True)["row"]
                plain_row = submit(t096)["row"]
                with self.assertRaises(ValueError):
                    submit("tbeam", hybrid=True)
                with self.assertRaises(ValueError):
                    submit(t096, hybrid="yes")
                with self.assertRaises(ValueError):
                    submit(t096, hybrid=True, mui=True)
            self.assertTrue(listed["heltec-mesh-node-t096"]["hybrid"])
            self.assertNotIn("hybrid", listed["tbeam"])
            self.assertNotIn("heltec-mesh-node-t096-hybrid", listed)
            self.assertEqual(hybrid_row["platformio_env"], "heltec-mesh-node-t096-hybrid")
            self.assertEqual(hybrid_row["device_id"], t096)
            self.assertEqual(hybrid_row["device_label"], "Heltec Mesh Node 096 (JenCore + RNode)")
            self.assertEqual(plain_row["platformio_env"], "heltec-mesh-node-t096")


class BuilderTests(unittest.TestCase):
    def build_row(self, **overrides):
        row = {
            "public_token": "t" * 43,
            "device_id": "tbeam",
            "platformio_env": "tbeam",
            "firmware_id": "nodastic",
            "firmware_tag": "nodastic",
            "firmware_sha": NODASTIC_SHA,
            "firmware_version": "2.8.1",
            "prefs_jsonc": '{"USERPREFS_FIXED_GPS": ""}',
        }
        row.update(overrides)
        return row

    def test_builder_gets_the_firmware_repository(self):
        config = temp_config(Path("/tmp"))
        row = self.build_row()
        args = builder_args(row, build_firmware_source(config, row))
        self.assertEqual(args, ["nodastic", NODASTIC_SHA, "tbeam", "https://github.com/lazynoda/meshtastic-firmware.git"])

    def test_legacy_rows_build_upstream(self):
        config = temp_config(Path("/tmp"))
        row = self.build_row(firmware_tag="v2.8.1.8e6a88d")
        del row["firmware_id"], row["firmware_version"]
        self.assertEqual(builder_args(row, build_firmware_source(config, row))[-1], "https://github.com/meshtastic/firmware.git")

    def test_build_info_names_the_firmware_source(self):
        config = temp_config(Path("/tmp"))
        row = self.build_row()
        info = build_info(row, build_firmware_source(config, row))
        self.assertIn("source=https://github.com/lazynoda/meshtastic-firmware", info)
        self.assertIn("firmware=Nodastic", info)
        self.assertIn("firmware_version=2.8.1", info)

    def test_patch_gates_use_the_branch_version_not_the_branch_name(self):
        # Nodastic 2.8.1 already carries upstream's fixed-GPS fix: the patch must
        # not be staged. With the branch name as version it would be unparseable.
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            self.assertEqual(stage_patches(config, self.build_row(), Path(tmp)), [])
            staged = stage_patches(config, self.build_row(firmware_version="2.8.0"), Path(tmp))
            self.assertEqual(staged, ["fixed-gps-nodedb.patch"])


if __name__ == "__main__":
    unittest.main()
