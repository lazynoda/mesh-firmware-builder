"""Which PlatformIO Core builds each board: platform specs, engine ranges, the lookup.

Shapes are copied from the real firmwares: upstream 2.7.x (registry platforms,
`arch/*/*.ini`), 2.8.0-2.8.1 / Jentastic 2.8.10x (pioarduino 55.03.311 archive),
2.8.2 / Jentastic 2.8.201 / Nodastic (pioarduino 55.03.312-1 release zip).
"""

import configparser
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from meshtastic_builder import platformio_versions as pv
from meshtastic_builder.platformio_versions import (
    UNSUPPORTED,
    PlatformLookupError,
    env_platform,
    extra_config_paths,
    extra_config_patterns,
    load_project,
    pick_platformio,
    platform_engine,
    platform_json_source,
    spec_allows,
)

PIOARDUINO_OLD = "https://github.com/meshtastic/pioarduino-platform-espressif32/archive/refs/heads/55.03.311.zip"
PIOARDUINO_NEW = (
    "https://github.com/pioarduino/platform-espressif32/releases/download/55.03.312-1/platform-espressif32.zip"
)
NATIVE = "https://github.com/meshtastic/platform-native/archive/86c62edfb7084d11669aa255411a70580e83823b.zip"
RP2040 = "https://github.com/maxgerhardt/platform-raspberrypi#5d4561a05e3b212660ac6fdd3fbfb328d1988aa1"
NRF54 = "https://github.com/meshtastic/platform-nordicnrf54.git#v0.3.1"
SEEED = "https://github.com/Seeed-Studio/platform-seeedboards.git"

# What each platform.json really declares (read from GitHub, Nov 2026).
ENGINES = {
    "meshtastic/pioarduino-platform-espressif32/55.03.311": ">=6.1.19",
    "pioarduino/platform-espressif32/55.03.312-1": ">=6.2.0",
    "platformio/platform-espressif32/v6.13.0": "^6",
    "platformio/platform-nordicnrf52/v11.0.0": "^6",
    "platformio/platform-ststm32/v20.0.0": "^5",
    "meshtastic/platform-native/86c62edfb7084d11669aa255411a70580e83823b": "^6",
    "maxgerhardt/platform-raspberrypi/5d4561a05e3b212660ac6fdd3fbfb328d1988aa1": "^6",
    "meshtastic/platform-nordicnrf54/v0.3.1": "^6",
    "Seeed-Studio/platform-seeedboards/HEAD": ">=6.1.16",
}


def fake_get(calls=None, engines=ENGINES):
    def get(url):
        if calls is not None:
            calls.append(url)
        prefix = "https://raw.githubusercontent.com/"
        assert url.startswith(prefix) and url.endswith("/platform.json"), url
        key = url[len(prefix) : -len("/platform.json")]
        if key not in engines:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return json.dumps({"name": "x", "engines": {"platformio": engines[key]}})

    return get


class PlatformSourceTests(unittest.TestCase):
    def test_every_spec_shape_the_firmwares_use(self):
        cases = {
            "platformio/espressif32@6.13.0": ("platformio/platform-espressif32", "v6.13.0", True),
            "platformio/nordicnrf52@11.0.0": ("platformio/platform-nordicnrf52", "v11.0.0", True),
            "espressif32@6.11.0": ("platformio/platform-espressif32", "v6.11.0", True),
            PIOARDUINO_OLD: ("meshtastic/pioarduino-platform-espressif32", "55.03.311", True),
            PIOARDUINO_NEW: ("pioarduino/platform-espressif32", "55.03.312-1", True),
            NATIVE: ("meshtastic/platform-native", "86c62edfb7084d11669aa255411a70580e83823b", True),
            RP2040: ("maxgerhardt/platform-raspberrypi", "5d4561a05e3b212660ac6fdd3fbfb328d1988aa1", True),
            NRF54: ("meshtastic/platform-nordicnrf54", "v0.3.1", False),
            SEEED: ("Seeed-Studio/platform-seeedboards", "HEAD", False),
        }
        for spec, expected in cases.items():
            with self.subTest(spec=spec):
                self.assertEqual(platform_json_source(spec), expected)

    def test_unresolvable_specs_are_left_unknown(self):
        # A version range depends on the registry on the day of the build.
        for spec in ("platformio/nordicnrf52@^10.8.0", "file:///tmp/platform", "https://example.com/p.zip", ""):
            with self.subTest(spec=spec):
                self.assertIsNone(platform_json_source(spec))


class EngineRangeTests(unittest.TestCase):
    def test_ranges_against_the_cores_in_the_image(self):
        cases = [
            (">=6.1.19", "6.1.19", True),
            (">=6.1.19", "6.2.0", True),  # allowed on paper; see pick_platformio for why it is not picked
            (">=6.2.0", "6.1.19", False),
            (">=6.2.0", "6.2.0", True),
            ("^6", "6.1.19", True),
            ("^6", "7.0.0", False),
            ("^6.1.16", "6.1.15", False),
            ("~6.1.0", "6.2.0", False),
            ("~6.1.0", "6.1.19", True),
            (">=6.1.0,<6.2.0", "6.2.0", False),
            ("6.x", "6.2.0", True),
            ("*", "6.2.0", True),
        ]
        for spec, version, expected in cases:
            with self.subTest(spec=spec, version=version):
                self.assertEqual(spec_allows(spec, version), expected)

    def test_garbage_is_unknown_not_allowed(self):
        self.assertIsNone(spec_allows("whatever", "6.2.0"))
        self.assertIsNone(spec_allows(">=six", "6.2.0"))


class PickTests(unittest.TestCase):
    def test_the_lowest_core_that_fits(self):
        self.assertEqual(pick_platformio(">=6.1.19"), "6.1.19")  # never 6.2.0: it breaks this platform
        self.assertEqual(pick_platformio(">=6.2.0"), "6.2.0")
        self.assertEqual(pick_platformio("^6"), "6.1.19")
        self.assertEqual(pick_platformio(""), "6.1.19")  # no requirement at all

    def test_platforms_for_older_cores_count_as_compatible(self):
        # PlatformIO 6 accepts platforms written for Core 2-5 (ststm32 says ^5).
        self.assertEqual(pick_platformio("^5"), "6.1.19")

    def test_a_core_the_image_lacks_is_unsupported(self):
        self.assertEqual(pick_platformio(">=7.0.0"), UNSUPPORTED)

    def test_unknown_stays_unknown(self):
        self.assertIsNone(pick_platformio(None))
        self.assertIsNone(pick_platformio("nonsense"))


class EngineLookupTests(unittest.TestCase):
    def setUp(self):
        pv._engine_cache.clear()

    def test_reads_platform_json_and_caches_immutable_refs(self):
        calls = []
        get = fake_get(calls)
        self.assertEqual(platform_engine(PIOARDUINO_NEW, get), ">=6.2.0")
        self.assertEqual(platform_engine(PIOARDUINO_NEW, get), ">=6.2.0")
        self.assertEqual(len(calls), 1)

    def test_moving_refs_are_read_again(self):
        calls = []
        get = fake_get(calls)
        platform_engine(SEEED, get)
        platform_engine(SEEED, get)
        self.assertEqual(len(calls), 2)

    def test_missing_platform_json_is_final_unknown(self):
        self.assertIsNone(platform_engine("https://github.com/someone/platform-x/archive/abc.zip", fake_get()))

    def test_network_trouble_is_not_a_final_answer(self):
        def down(url):
            raise urllib.error.URLError("timed out")

        with self.assertRaises(PlatformLookupError):
            platform_engine(PIOARDUINO_NEW, down)

        def rate_limited(url):
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

        with self.assertRaises(PlatformLookupError):
            platform_engine(PIOARDUINO_NEW, rate_limited)

    def test_no_engines_key_means_any_core(self):
        self.assertEqual(platform_engine(PIOARDUINO_NEW, lambda url: json.dumps({"name": "x"})), "")


ROOT_INI_27 = """
[platformio]
default_envs = tbeam
extra_configs =
\tarch/*/*.ini
\tvariants/*/*/platformio.ini
\tvariants/*/diy/*/platformio.ini
\tsrc/graphics/niche/InkHUD/PlatformioConfig.ini

[env]
test_build_src = true
"""
ROOT_INI_28 = ROOT_INI_27.replace("arch/*/*.ini", "variants/*/*.ini")


class ProjectTests(unittest.TestCase):
    def test_extra_configs_order_and_matching(self):
        patterns = extra_config_patterns(ROOT_INI_27)
        self.assertEqual(patterns[0], "arch/*/*.ini")
        paths = [
            "variants/esp32s3/heltec_v4/platformio.ini",
            "variants/nrf52840/diy/nrf52_promicro_diy_tcxo/platformio.ini",
            "variants/nrf52840/nrf52.ini",  # 2.8 layout only: not matched by 2.7's patterns
            "arch/esp32/esp32s3.ini",
            "arch/nrf52/nrf52840.ini",
            "src/graphics/niche/InkHUD/PlatformioConfig.ini",
            "variants/.hidden/x/platformio.ini",
        ]
        self.assertEqual(
            extra_config_paths(patterns, paths),
            [
                "arch/esp32/esp32s3.ini",
                "arch/nrf52/nrf52840.ini",
                "variants/esp32s3/heltec_v4/platformio.ini",
                "variants/nrf52840/diy/nrf52_promicro_diy_tcxo/platformio.ini",
                "src/graphics/niche/InkHUD/PlatformioConfig.ini",
            ],
        )

    def test_platform_through_extends_like_the_real_firmwares(self):
        files = [
            ("platformio.ini", ROOT_INI_28),
            (
                "variants/esp32/esp32-common.ini",
                f"[esp32_common]\nplatform =\n  # TODO renovate\n  {PIOARDUINO_NEW}\n  ; {PIOARDUINO_OLD}\n",
            ),
            ("variants/esp32s3/esp32s3.ini", "[esp32s3_base]\nextends = esp32_common\n"),
            ("variants/nrf52840/nrf52.ini", "[nrf52_base]\nplatform =\n  # renovate\n  platformio/nordicnrf52@11.0.0\n"),
            ("variants/esp32s3/heltec_v4/platformio.ini", "[env:heltec-v4]\nextends = esp32s3_base\n"),
            ("variants/nrf52840/diy/p/platformio.ini", "[env:promicro]\nextends = nrf52_base\n"),
            ("variants/x/own/platformio.ini", "[env:own]\nextends = esp32s3_base\nplatform = platformio/espressif32@6.13.0\n"),
        ]
        project = load_project(files)
        self.assertEqual(env_platform(project, "heltec-v4"), PIOARDUINO_NEW)
        self.assertEqual(env_platform(project, "promicro"), "platformio/nordicnrf52@11.0.0")
        self.assertEqual(env_platform(project, "own"), "platformio/espressif32@6.13.0")  # own key wins
        self.assertIsNone(env_platform(project, "missing"))

    def test_interpolated_platform_is_not_guessed(self):
        project = load_project([("a.ini", "[base]\np = x\n[env:e]\nplatform = ${base.p}\n")])
        self.assertIsNone(env_platform(project, "e"))

    def test_extends_loops_end(self):
        project = load_project([("a.ini", "[a]\nextends = b\n[b]\nextends = a\n[env:e]\nextends = a\n")])
        self.assertIsNone(env_platform(project, "e"))

    def test_platformio_for_envs(self):
        pv._engine_cache.clear()
        files = [
            ("variants/esp32/esp32-common.ini", f"[esp32_common]\nplatform = {PIOARDUINO_OLD}\n"),
            ("variants/esp32s3/heltec_v4/platformio.ini", "[env:old]\nextends = esp32_common\n"),
            ("variants/new/platformio.ini", f"[env:new]\nplatform = {PIOARDUINO_NEW}\n"),
            ("variants/stm/platformio.ini", "[env:stm]\nplatform = platformio/ststm32@20.0.0\n"),
            ("variants/odd/platformio.ini", "[env:odd]\nplatform = platformio/nordicnrf52@^10.8.0\n"),
            ("variants/none/platformio.ini", "[env:none]\nboard = x\n"),
        ]
        result = pv.platformio_for_envs(load_project(files), ["old", "new", "stm", "odd", "none"], fake_get())
        self.assertEqual(
            result, {"old": "6.1.19", "new": "6.2.0", "stm": "6.1.19", "odd": None, "none": None}
        )


if __name__ == "__main__":
    unittest.main()
