import tempfile
import unittest
from pathlib import Path

from meshtastic_builder.device_sync import device_id_for, devices_json, flasher_boards, sync_devices
from meshtastic_builder.devices import Device, load_devices

ROOT = Path(__file__).resolve().parent.parent

INI = """
[env:keep_me]
custom_meshtastic_architecture = nrf52840
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Keep Me
board_level = release

[env:new_board]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Alpha Board

[env:extra_board]
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Extra
board_level = extra

[env:unsupported]
custom_meshtastic_actively_supported = false
custom_meshtastic_display_name = Old

[env:no_name]
custom_meshtastic_actively_supported = true
"""


def device(env, label, family="nrf52840", device_id=None):
    return Device(id=device_id or device_id_for(env), label=label, platformio_env=env, family=family, enabled=True)


class FlasherBoardsTests(unittest.TestCase):
    def test_reads_only_the_web_flasher_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "variants" / "x" / "platformio.ini"
            ini.parent.mkdir(parents=True)
            ini.write_text(INI, encoding="utf-8")
            boards = flasher_boards(Path(tmp))
        self.assertEqual(sorted(boards), ["keep_me", "new_board"])
        self.assertEqual(boards["new_board"].family, "esp32-s3")
        self.assertEqual(boards["new_board"].label, "Alpha Board")

    def test_rejects_a_directory_that_is_not_a_firmware_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                flasher_boards(Path(tmp))


# Shapes taken from upstream v2.8.1 variants (ThinkNode M9, RAK4631 family, T5
# E-paper, Wio Tracker L2), trimmed to the keys that decide what is offered.
INHERITED_INI = """
[thinknode_m9_base]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true ; trailing comment, as PlatformIO allows
custom_meshtastic_display_name = ThinkNode M9
custom_meshtastic_has_mui = true
extends = esp32s3_base
board_level = release

[env:thinknode_m9]
extends = thinknode_m9_base

[env:thinknode_m9-tft]
extends = thinknode_m9_base

[env:rak4631]
custom_meshtastic_architecture = nrf52840
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = RAK WisBlock 4631
board_level = release

[env:rak_wismesh_pocket]
extends = env:rak4631
custom_meshtastic_display_name = RAK WisMesh Pocket V3

[env:rak4631_dbg]
extends = env:rak4631
board_level = extra

[env:rak4631_eink]
extends = env:rak4631

[t5s3_base]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true

[env:t5s3-epaper-v1]
extends = t5s3_base
board_level = release
custom_meshtastic_display_name = LilyGo T5 E-paper S3 Pro V1

[env:seeed_wio_tracker_L2]
custom_meshtastic_architecture = esp32-s3
custom_meshtastic_actively_supported = true
custom_meshtastic_display_name = Seeed Wio Tracker L2
custom_meshtastic_has_mui = true
board_level = extra

[env:seeed_wio_tracker_L2-tft]
extends = env:seeed_wio_tracker_L2
board_level = release

[env:loop_a]
extends = env:loop_b
custom_meshtastic_display_name = Loop

[env:loop_b]
extends = env:loop_a
custom_meshtastic_actively_supported = true
"""


class InheritanceTests(unittest.TestCase):
    """Keys inherited through `extends`, resolved like PlatformIO's ProjectConfig."""

    def boards(self):
        from meshtastic_builder.device_sync import parse_boards

        return parse_boards([("variants/x/platformio.ini", INHERITED_INI)])

    def test_keys_from_a_base_section_count(self):
        boards = self.boards()
        self.assertEqual(boards["thinknode_m9"].label, "ThinkNode M9")
        self.assertEqual(boards["thinknode_m9"].family, "esp32-s3")
        self.assertEqual(boards["t5s3-epaper-v1"].label, "LilyGo T5 E-paper S3 Pro V1")
        # Own name, the rest inherited from the parent env.
        self.assertEqual(boards["rak_wismesh_pocket"].label, "RAK WisMesh Pocket V3")
        self.assertEqual(boards["rak_wismesh_pocket"].family, "nrf52840")

    def test_shared_base_tft_env_is_the_boards_meshtastic_ui_switch(self):
        boards = self.boards()
        self.assertEqual(boards["thinknode_m9"].mui_env, "thinknode_m9-tft")
        self.assertNotIn("thinknode_m9-tft", boards)

    def test_env_named_after_another_board_is_a_variant_not_a_board(self):
        boards = self.boards()
        self.assertIn("rak4631", boards)
        self.assertNotIn("rak4631_eink", boards)
        self.assertNotIn("rak4631_dbg", boards)

    def test_tft_env_of_an_extra_board_is_offered_as_the_board(self):
        boards = self.boards()
        self.assertNotIn("seeed_wio_tracker_L2", boards)
        self.assertEqual(boards["seeed_wio_tracker_L2-tft"].label, "Seeed Wio Tracker L2")
        self.assertIsNone(boards["seeed_wio_tracker_L2-tft"].mui_env)

    def test_extends_loops_terminate(self):
        self.assertEqual(self.boards()["loop_a"].label, "Loop")

    def test_offered_set(self):
        self.assertEqual(
            sorted(self.boards()),
            ["loop_a", "rak4631", "rak_wismesh_pocket", "seeed_wio_tracker_L2-tft", "t5s3-epaper-v1", "thinknode_m9"],
        )

    def test_a_file_that_does_not_parse_is_skipped(self):
        from meshtastic_builder.device_sync import parse_boards

        broken = "custom_meshtastic_display_name = before any section\n"
        boards = parse_boards([("variants/a/platformio.ini", broken), ("variants/x/platformio.ini", INHERITED_INI)])
        self.assertIn("thinknode_m9", boards)


class SyncTests(unittest.TestCase):
    def boards(self, *items):
        from meshtastic_builder.device_sync import FlasherBoard

        return {env: FlasherBoard(env=env, label=label, family=family, source="x") for env, label, family in items}

    def test_keeps_ids_and_labels_adds_new_and_drops_gone(self):
        current = [
            device("nrf52_promicro_diy_tcxo", "NRF52 Pro-micro DIY", device_id="nrf52-promicro-diy"),
            device("zeta", "Zeta"),
            device("gone_board", "Gone"),
        ]
        boards = self.boards(
            ("nrf52_promicro_diy_tcxo", "Different upstream label", "nrf52840"),
            ("zeta", "Zeta", "nrf52840"),
            ("seeed_wio_tracker_L2", "Beta", "esp32-s3"),
        )
        result = sync_devices(current, boards)
        self.assertEqual([d.id for d in result.devices], ["nrf52-promicro-diy", "seeed-wio-tracker-l2", "zeta"])
        self.assertEqual(result.devices[0].label, "NRF52 Pro-micro DIY")
        self.assertEqual([d.id for d in result.added], ["seeed-wio-tracker-l2"])
        self.assertEqual([d.id for d in result.removed], ["gone-board"])

    def test_shared_display_name_gets_a_suffix(self):
        result = sync_devices([device("a", "Same")], self.boards(("a", "Same", "esp32"), ("b", "Same", "esp32")))
        self.assertEqual(result.added[0].label, "Same (b)")

    def test_family_follows_the_firmware(self):
        result = sync_devices([device("a", "A", family="esp32")], self.boards(("a", "A", "esp32-s3")))
        self.assertEqual(result.devices[0].family, "esp32-s3")
        self.assertEqual(len(result.family_changed), 1)

    def test_no_change_is_a_no_op(self):
        current = [device("a", "A")]
        result = sync_devices(current, self.boards(("a", "A", "nrf52840")))
        self.assertFalse(result.changed)

    def test_shipped_file_round_trips_byte_for_byte(self):
        # The generator's output format is the file's format, so a sync that
        # changes nothing leaves no diff.
        path = ROOT / "data" / "devices.json"
        self.assertEqual(devices_json(load_devices(ROOT)), path.read_text(encoding="utf-8"))

    def test_excluded_family_is_kept_out_and_reported(self):
        result = sync_devices(
            [device("a", "A")],
            self.boards(("a", "A", "nrf52840"), ("xiao_nrf54l15_lr2021", "XIAO", "nrf54l15")),
        )
        self.assertEqual([d.platformio_env for d in result.devices], ["a"])
        self.assertEqual([env for env, _ in result.excluded], ["xiao_nrf54l15_lr2021"])

    def test_excluded_family_is_dropped_from_cached_lists_too(self):
        from unittest.mock import patch as mock_patch

        from meshtastic_builder import board_catalog
        from meshtastic_builder.firmwares import get_firmware

        cached = [device("a", "A"), device("xiao_nrf54l15_lr2021", "XIAO", family="nrf54l15")]
        with mock_patch.object(board_catalog, "catalog_for", return_value=(cached, {}, True)):
            devices, _ = board_catalog.devices_for(None, get_firmware(ROOT, "meshtastic"), "a" * 40)
        self.assertEqual([d.platformio_env for d in devices], ["a"])

    def test_shipped_list_has_no_excluded_board(self):
        from meshtastic_builder.device_sync import exclusion_reason

        self.assertFalse([d.id for d in load_devices(ROOT) if exclusion_reason(d.platformio_env, d.family)])

    def test_generated_ids_follow_the_existing_convention(self):
        self.assertEqual(device_id_for("tlora-v2-1-1_6"), "tlora-v2-1-1-6")
        self.assertEqual(device_id_for("CDEBYTE_EoRa-S3"), "cdebyte-eora-s3")
        self.assertEqual(device_id_for("seeed_wio_tracker_L1_Pro_1W"), "seeed-wio-tracker-l1-pro-1w")


if __name__ == "__main__":
    unittest.main()
