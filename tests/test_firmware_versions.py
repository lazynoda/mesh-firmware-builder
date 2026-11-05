import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from meshtastic_builder.config import load_config
from meshtastic_builder.db import get_firmware_version, upsert_firmware_versions
from meshtastic_builder.firmware import (
    _next_link,
    list_versions_with_refresh,
    refresh_firmware_versions,
    valid_tag,
)


class FirmwareVersionTests(unittest.TestCase):
    def test_next_link_parses_github_link_header(self):
        header = '<https://api.github.test/tags?page=2>; rel="next", <https://api.github.test/tags?page=9>; rel="last"'
        self.assertEqual(_next_link(header), "https://api.github.test/tags?page=2")

    def _config(self, tmp_path, **overrides):
        return replace(
            load_config(),
            data_dir=tmp_path,
            db_path=tmp_path / "test.sqlite",
            artifact_dir=tmp_path / "artifacts",
            job_dir=tmp_path / "jobs",
            cache_dir=tmp_path / "cache",
            github_tags_url="https://api.github.test/tags?page=1",
            **overrides,
        )

    def test_refresh_firmware_versions_follows_pagination(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp), github_max_tag_pages=5)

            def fake_http_get(url, timeout=15):
                if url.startswith(RELEASES_URL):
                    return json.dumps([release("v2.8.2.d5f1619"), release("v2.8.1.8e6a88d")]), {}
                if url.endswith("page=1"):
                    return (
                        json.dumps([{"name": "v2.8.2.d5f1619", "commit": {"sha": "222"}}]),
                        {"Link": '<https://api.github.test/tags?page=2>; rel="next"'},
                    )
                return (
                    json.dumps([{"name": "v2.8.1.8e6a88d", "commit": {"sha": "111"}}]),
                    {},
                )

            with patch("meshtastic_builder.firmware._http_get", fake_http_get):
                versions = refresh_firmware_versions(config)

            self.assertEqual([item["tag"] for item in versions], ["v2.8.2.d5f1619", "v2.8.1.8e6a88d"])

    def test_refresh_auto_supports_only_latest_configured_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp), github_max_tag_pages=1, auto_support_latest_tags=1)

            def fake_http_get(url, timeout=15):
                if url.startswith(RELEASES_URL):
                    return json.dumps([release("v2.8.2.d5f1619"), release("v2.8.1.8e6a88d")]), {}
                return (
                    json.dumps(
                        [
                            {"name": "v2.8.2.d5f1619", "commit": {"sha": "222"}},
                            {"name": "v2.8.1.8e6a88d", "commit": {"sha": "111"}},
                        ]
                    ),
                    {},
                )

            with patch("meshtastic_builder.firmware._http_get", fake_http_get):
                versions = refresh_firmware_versions(config)

            by_tag = {item["tag"]: item for item in versions}
            self.assertEqual(by_tag["v2.8.2.d5f1619"]["supported"], 1)
            self.assertEqual(by_tag["v2.8.1.8e6a88d"]["supported"], 0)


RELEASES_URL = "https://api.github.com/repos/meshtastic/firmware/releases"


def release(tag, name=None, published_at="2026-11-01T00:00:00Z", draft=False):
    return {"tag_name": tag, "name": name or tag, "published_at": published_at, "draft": draft}


class TagFormatTests(unittest.TestCase):
    def test_only_tags_the_version_gates_can_read_are_valid(self):
        for tag, ok in [
            ("v2.8.105", True),
            ("v2.8.2.d5f1619", True),  # upstream: x.y.z.<commit>
            ("v2.8.201-rc.3", True),  # SemVer pre-release
            ("v2.8.201-003", True),
            ("v2.8.104-001", True),
            ("rc-v2.8.201-003", False),  # the gates would read it as old firmware
            ("2.8.105", False),
            ("v2.8", False),
            ("v2.8.2.", False),
            ("v2.8.2.XYZ", False),
            ("v2.8.2-", False),
            ("v2.8.2-rc..1", False),
            ("v2.8.2 ", False),
            ("nodastic", False),
            ("v-new", False),
            ("v2.8.2-" + "a" * 80, False),
        ]:
            with self.subTest(tag=tag):
                self.assertEqual(valid_tag(tag), ok)


class ReleaseFilterTests(unittest.TestCase):
    def _refresh(self, tmp, releases, tags):
        config = replace(
            load_config(),
            data_dir=Path(tmp),
            db_path=Path(tmp) / "test.sqlite",
            artifact_dir=Path(tmp) / "artifacts",
            job_dir=Path(tmp) / "jobs",
            cache_dir=Path(tmp) / "cache",
            github_tags_url="https://api.github.test/tags?page=1",
        )

        def fake_http_get(url, timeout=15):
            if url.startswith(RELEASES_URL):
                return json.dumps(releases), {}
            return json.dumps([{"name": tag, "commit": {"sha": tag[-7:]}} for tag in tags]), {}

        with patch("meshtastic_builder.firmware._http_get", fake_http_get):
            refresh_firmware_versions(config)
            return config, list_versions_with_refresh(config)

    def test_only_published_releases_with_a_valid_tag_are_offered(self):
        with tempfile.TemporaryDirectory() as tmp:
            _config, versions = self._refresh(
                tmp,
                releases=[
                    release("v2.8.2.d5f1619"),
                    release("rc-v2.8.201-003"),  # a release, but a tag the gates cannot read
                    release("v2.8.3.aaaaaaa", draft=True),  # drafts are not published
                ],
                tags=["v2.8.3.aaaaaaa", "rc-v2.8.201-003", "v2.8.2.d5f1619", "v2.8.2.bbbbbbb"],  # last: no release
            )
            self.assertEqual([item["tag"] for item in versions], ["v2.8.2.d5f1619"])
            self.assertEqual(versions[0]["release_name"], "v2.8.2.d5f1619")

    def test_revoked_releases_are_offered_and_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            _config, versions = self._refresh(
                tmp,
                releases=[
                    release("v2.8.2.d5f1619", "Meshtastic Firmware 2.8.2.d5f1619 Alpha", "2026-11-04T00:00:00Z"),
                    release(
                        "v2.8.2.4c89b69", "Meshtastic Firmware 2.8.2.4c89b69 Alpha (Revoked)", "2026-11-02T00:00:00Z"
                    ),
                ],
                tags=["v2.8.2.4c89b69", "v2.8.2.d5f1619"],
            )
            by_tag = {item["tag"]: item for item in versions}
            self.assertTrue(by_tag["v2.8.2.4c89b69"]["revoked"])
            self.assertFalse(by_tag["v2.8.2.d5f1619"]["revoked"])

    def test_a_release_that_disappears_stops_being_offered(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._refresh(tmp, [release("v2.8.2.d5f1619"), release("v2.8.1.8e6a88d")],
                          ["v2.8.2.d5f1619", "v2.8.1.8e6a88d"])
            config, versions = self._refresh(tmp, [release("v2.8.2.d5f1619")], ["v2.8.2.d5f1619", "v2.8.1.8e6a88d"])
            self.assertEqual([item["tag"] for item in versions], ["v2.8.2.d5f1619"])
            # Kept, unsupported, so builds made from it still resolve.
            self.assertEqual(get_firmware_version(config, "v2.8.1.8e6a88d")["supported"], 0)


class VersionOrderTests(unittest.TestCase):
    def test_versions_are_listed_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = replace(
                load_config(),
                data_dir=tmp_path,
                db_path=tmp_path / "test.sqlite",
                artifact_dir=tmp_path / "artifacts",
                job_dir=tmp_path / "jobs",
                cache_dir=tmp_path / "cache",
            )
            # Insertion order is deliberately wrong: a later refresh appends newer tags.
            upsert_firmware_versions(
                config,
                [
                    {"tag": "v2.7.25.104df5f", "sha": "a", "supported": 1},
                    {"tag": "v2.6.4.abc", "sha": "b", "supported": 1},
                    {"tag": "v2.8.0.47db0e3", "sha": "c", "supported": 1},
                ],
            )

            tags = [item["tag"] for item in list_versions_with_refresh(config)]

            self.assertEqual(tags, ["v2.8.0.47db0e3", "v2.7.25.104df5f", "v2.6.4.abc"])

    def test_same_version_is_ordered_by_release_date_not_tag_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = replace(
                load_config(),
                data_dir=tmp_path,
                db_path=tmp_path / "test.sqlite",
                artifact_dir=tmp_path / "artifacts",
                job_dir=tmp_path / "jobs",
                cache_dir=tmp_path / "cache",
            )
            upsert_firmware_versions(
                config,
                [
                    # As text, d5f1619 > 4c89b69 and rc.9 > rc.10: both wrong here.
                    {"tag": "v2.8.2.4c89b69", "sha": "a", "published_at": "2026-11-04T00:00:00Z"},
                    {"tag": "v2.8.2.d5f1619", "sha": "b", "published_at": "2026-11-02T00:00:00Z"},
                    {"tag": "v2.8.201-rc.9", "sha": "c", "published_at": "2026-11-05T00:00:00Z"},
                    {"tag": "v2.8.201-rc.10", "sha": "d", "published_at": "2026-11-06T00:00:00Z"},
                    # Published last, but an older version: the date never crosses versions.
                    {"tag": "v2.7.26.54e0d8d", "sha": "e", "published_at": "2026-11-07T00:00:00Z"},
                    {"tag": "v2.8.99", "sha": "f", "published_at": "2026-10-01T00:00:00Z"},
                ],
            )

            tags = [item["tag"] for item in list_versions_with_refresh(config)]

            self.assertEqual(
                tags,
                ["v2.8.201-rc.10", "v2.8.201-rc.9", "v2.8.99", "v2.8.2.4c89b69", "v2.8.2.d5f1619", "v2.7.26.54e0d8d"],
            )


if __name__ == "__main__":
    unittest.main()
