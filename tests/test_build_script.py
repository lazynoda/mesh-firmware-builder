"""The compile step of docker/build_firmware.sh, run with a fake `pio`.

Only the compile block is executed (extracted between its phase banner and the
packaging phase), so these tests need no firmware checkout or Docker.
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docker" / "build_firmware.sh"
BASH = shutil.which("bash") or "/bin/bash"


def compile_block() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'phase "compile \$\{PIO_ENV\}"\n(?P<body>.*?)\n# Only what a flasher consumes', text, re.S)
    assert match, "compile block not found in build_firmware.sh"
    return match.group("body")


def platformio_functions() -> str:
    """select_platformio and next_platformio, as defined in build_firmware.sh."""
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'\nPIO_CORES_DIR=.*?\n(?=report_ccache\(\) \{)', text, re.S)
    assert match, "PlatformIO selection block not found in build_firmware.sh"
    return match.group(0)


def fake_pio(path: Path, version: str, calls: Path, output: str, fails: int) -> None:
    """A pio that reports `version`, logs each run and fails its first `fails` runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = "--version" ]; then echo "PlatformIO Core, version {version}"; exit 0; fi\n'
        f'echo "{version}" >> "{calls}"\n'
        f'n=$(grep -c . "{calls}")\n'
        f"cat <<'EOF'\n{output}\nEOF\n"
        f'[ "$n" -gt {fails} ]\n'
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def run_compile(
    pio_output: str,
    *,
    fails: int,
    wanted: str | None = None,
    cores: tuple[str, ...] = ("6.2.0",),
    default: str = "6.1.19",
) -> tuple[subprocess.CompletedProcess, int, list[str]]:
    """Run the PlatformIO selection and the compile block with fake Cores.

    `default` is the image's `pio`, `cores` the extra ones under the cores dir.
    Every run is logged with the version that ran it; the first `fails` runs fail.
    Returns (process, number of runs, versions that ran, in order).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        calls = tmp_path / "calls"
        calls.write_text("")
        fake_pio(tmp_path / "bin" / "pio", default, calls, pio_output, fails)
        for version in cores:
            fake_pio(tmp_path / "cores" / version / "bin" / "pio", version, calls, pio_output, fails)
        script = (
            "set -euo pipefail\n"
            "PIO_ENV=test-env\n"
            "phase() { :; }\n"
            "use_native_sreccat() { :; }\n"
            "report_ccache() { :; }\n"
            'fail() { echo "MB_FAILURE code=$1 phase=$2 detail=$3" >&2; exit "${4:-1}"; }\n'
            + platformio_functions().replace('PIO_CORES_DIR="/opt/pio-cores"', f'PIO_CORES_DIR="{tmp_path / "cores"}"')
            + "\nselect_platformio\n"
            + compile_block()
            + "\necho COMPILED\n"
        )
        env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}
        env.pop("MB_PLATFORMIO_VERSION", None)
        if wanted is not None:
            env["MB_PLATFORMIO_VERSION"] = wanted
        proc = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=30, env=env)
        ran = [line for line in calls.read_text().splitlines() if line]
        return proc, len(ran), ran


OVERFLOW = (
    "/opt/platformio/packages/toolchain-gccarmnoneeabi/bin/ld: "
    "region `FLASH' overflowed by 77752 bytes\n"
    "collect2: error: ld returned 1 exit status\n"
    "*** [.pio/build/test-env/firmware.elf] Error 1"
)


@unittest.skipUnless(Path(BASH).exists(), "bash not available")
class CompileRetryTests(unittest.TestCase):
    def test_flash_overflow_fails_once_without_retry(self):
        proc, calls, _ran = run_compile(OVERFLOW, fails=99)
        self.assertEqual(calls, 1)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(
            "MB_FAILURE code=firmware_too_big phase=compile detail=region `FLASH' overflowed by 77752 bytes",
            proc.stderr,
        )
        self.assertNotIn("COMPILED", proc.stdout)

    def test_other_failure_is_retried_once(self):
        # pioarduino swapping tool-scons mid-run: the second run succeeds.
        proc, calls, _ran = run_compile("ModuleNotFoundError: No module named 'SCons.Tool.FortranCommon'", fails=1)
        self.assertEqual(calls, 2)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("COMPILED", proc.stdout)

    def test_genuine_compile_error_still_fails_after_the_retry(self):
        proc, calls, _ran = run_compile("src/main.cpp:1:1: error: boom", fails=99)
        self.assertEqual(calls, 2)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("MB_FAILURE", proc.stderr)

    def test_success_runs_pio_once_and_keeps_its_output(self):
        proc, calls, _ran = run_compile("========== [SUCCESS] Took 1.00 seconds ==========", fails=0)
        self.assertEqual(calls, 1)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[SUCCESS]", proc.stdout)


INCOMPATIBLE = (
    "Error: Traceback ...\n"
    "IncompatiblePlatform: Development platform 'espressif32' is not compatible with "
    "PlatformIO Core v6.1.19 and depends on PlatformIO Core >=6.2.0."
)
SUCCESS = "========== [SUCCESS] Took 1.00 seconds =========="


@unittest.skipUnless(Path(BASH).exists(), "bash not available")
class PlatformioSelectionTests(unittest.TestCase):
    def test_named_core_runs_and_no_other(self):
        proc, _calls, ran = run_compile(SUCCESS, fails=0, wanted="6.2.0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(ran, ["6.2.0"])
        self.assertIn("PlatformIO: PlatformIO Core, version 6.2.0 (chosen for this board)", proc.stdout)

    def test_named_core_that_is_the_default_pio(self):
        proc, _calls, ran = run_compile(SUCCESS, fails=0, wanted="6.1.19")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(ran, ["6.1.19"])

    def test_without_a_name_the_lowest_core_runs(self):
        proc, _calls, ran = run_compile(SUCCESS, fails=0)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(ran, ["6.1.19"])
        self.assertIn("(default; this build did not name one)", proc.stdout)

    def test_without_a_name_a_refused_platform_moves_up_one_core(self):
        proc, _calls, ran = run_compile(INCOMPATIBLE, fails=1)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(ran, ["6.1.19", "6.2.0"])
        self.assertIn("retrying with PlatformIO Core, version 6.2.0", proc.stdout)

    def test_named_core_never_moves_even_when_refused(self):
        # The worker read the platform: a refusal then is a real problem, not a guess to correct.
        proc, _calls, ran = run_compile(INCOMPATIBLE, fails=99, wanted="6.1.19")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(ran, ["6.1.19", "6.1.19"])

    def test_refused_by_the_highest_core_fails_with_the_reason(self):
        proc, _calls, ran = run_compile(INCOMPATIBLE, fails=99, cores=())
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(ran, ["6.1.19"])
        self.assertIn("MB_FAILURE code=infrastructure phase=compile", proc.stderr)
        self.assertIn("depends on PlatformIO Core >=6.2.0", proc.stderr)

    def test_other_failures_retry_on_the_same_core(self):
        # The old FortranCommon hiccup must not be taken as "needs a newer Core".
        proc, _calls, ran = run_compile("ModuleNotFoundError: No module named 'SCons.Tool.FortranCommon'", fails=1)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(ran, ["6.1.19", "6.1.19"])

    def test_missing_named_core_fails_before_compiling(self):
        proc, _calls, ran = run_compile(SUCCESS, fails=0, wanted="7.0.0")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(ran, [])
        self.assertIn("This builder image has no PlatformIO 7.0.0.", proc.stderr)

    def test_malformed_version_is_refused(self):
        proc, _calls, ran = run_compile(SUCCESS, fails=0, wanted="6.2.0; rm -rf /")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(ran, [])
        self.assertIn("Invalid PlatformIO version", proc.stderr)


WRAP = ROOT / "docker" / "ccache_wrap.sh"

FAKE_CCACHE = """#!/bin/sh
# Records how it was called, then runs the compiler it was handed.
echo "ccache $MB_CCACHE_ACTIVE $CCACHE_COMPILERCHECK $*" >> "$CALL_LOG"
exec "$@"
"""

FAKE_COMPILER = """#!/bin/sh
echo "{name} $*" >> "$CALL_LOG"
{body}
"""


@unittest.skipUnless(Path(BASH).exists(), "bash not available")
class CcacheWrapTests(unittest.TestCase):
    """docker/ccache_wrap.sh against a fake PlatformIO packages tree."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.packages = self.tmp / "packages"
        self.cache = self.tmp / "cache"
        self.call_log = self.tmp / "calls.log"
        self.tools = self.tmp / "tools"
        self.tools.mkdir()
        self._exe(self.tools / "ccache", FAKE_CCACHE)

        arm = self.packages / "toolchain-gccarmnoneeabi"
        (arm / "bin").mkdir(parents=True)
        (arm / "package.json").write_text('{"name": "toolchain-gccarmnoneeabi", "version": "1.90301.200702"}')
        self._exe(arm / "bin" / "arm-none-eabi-gcc", FAKE_COMPILER.format(name="real-arm-gcc", body=""))
        self._exe(arm / "bin" / "arm-none-eabi-g++", FAKE_COMPILER.format(name="real-arm-g++", body=""))
        self._exe(arm / "bin" / "arm-none-eabi-objcopy", FAKE_COMPILER.format(name="objcopy", body=""))

        # The per-chip xtensa drivers call the generic xtensa-esp-elf-gcc, which
        # must not be cached a second time.
        xt = self.packages / "toolchain-xtensa-esp-elf"
        (xt / "bin").mkdir(parents=True)
        (xt / "package.json").write_text('{"name": "toolchain-xtensa-esp-elf", "version": "14.2.0+20251107"}')
        self._exe(xt / "bin" / "xtensa-esp-elf-gcc", FAKE_COMPILER.format(name="real-xtensa-gcc", body=""))
        self._exe(
            xt / "bin" / "xtensa-esp32s3-elf-gcc",
            FAKE_COMPILER.format(name="s3-driver", body=f'exec "{xt}/bin/xtensa-esp-elf-gcc" "$@"'),
        )
        (xt / "bin" / "xtensa-esp-elf-cc").symlink_to("xtensa-esp-elf-gcc")
        # The ARM toolchain loads libiconv from $ORIGIN, next to the compiler.
        (arm / "bin" / "libiconv.so.2").write_text("lib")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _exe(path, text):
        path.write_text(text)
        path.chmod(0o755)

    def _env(self, **extra):
        env = {
            **os.environ,
            "PATH": f"{self.tools}:{os.environ['PATH']}",
            "CALL_LOG": str(self.call_log),
            **extra,
        }
        env.pop("MB_CCACHE_ACTIVE", None)
        return env

    def wrap(self, **extra):
        env = self._env(**extra)
        return subprocess.run(
            [BASH, str(WRAP), str(self.packages)], capture_output=True, text=True, timeout=30, env=env
        )

    def compile(self, compiler, *args):
        self.call_log.write_text("")
        subprocess.run([str(compiler), *args], check=True, timeout=30, env=self._env())
        return self.call_log.read_text().splitlines()

    def test_compilers_go_through_ccache_and_other_tools_do_not(self):
        proc = self.wrap(CCACHE_DIR=str(self.cache))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("wrapped 4 compiler(s)", proc.stdout)

        arm_bin = self.packages / "toolchain-gccarmnoneeabi" / "bin"
        real = self.packages / "toolchain-gccarmnoneeabi" / ".mb-real-bin" / "arm-none-eabi-gcc"
        calls = self.compile(arm_bin / "arm-none-eabi-gcc", "-c", "a.c")
        self.assertEqual(
            calls,
            [
                f"ccache 1 string:toolchain-gccarmnoneeabi@1.90301.200702 {real} -c a.c",
                "real-arm-gcc -c a.c",
            ],
        )
        self.assertEqual(self.compile(arm_bin / "arm-none-eabi-objcopy", "x"), ["objcopy x"])

    def test_a_compiler_calling_another_is_cached_once(self):
        self.wrap(CCACHE_DIR=str(self.cache))
        xt_bin = self.packages / "toolchain-xtensa-esp-elf" / "bin"
        calls = self.compile(xt_bin / "xtensa-esp32s3-elf-gcc", "-c", "a.c")
        self.assertEqual([c.split()[0] for c in calls], ["ccache", "s3-driver", "real-xtensa-gcc"])
        self.assertIn("string:toolchain-xtensa-esp-elf@14.2.0+20251107", calls[0])

    def test_symlinked_compiler_names_still_reach_the_real_compiler(self):
        self.wrap(CCACHE_DIR=str(self.cache))
        xt = self.packages / "toolchain-xtensa-esp-elf"
        self.assertTrue((xt / "bin" / "xtensa-esp-elf-cc").is_symlink())
        calls = self.compile(xt / "bin" / "xtensa-esp-elf-cc", "-c", "a.c")
        self.assertEqual([c.split()[0] for c in calls], ["ccache", "real-xtensa-gcc"])

    def test_files_next_to_the_compiler_stay_next_to_the_real_one(self):
        self.wrap(CCACHE_DIR=str(self.cache))
        arm = self.packages / "toolchain-gccarmnoneeabi"
        self.assertEqual((arm / ".mb-real-bin" / "libiconv.so.2").read_text(), "lib")
        self.assertEqual(
            (arm / ".mb-real-bin" / "arm-none-eabi-objcopy").resolve(), (arm / "bin" / "arm-none-eabi-objcopy").resolve()
        )
        # The real compilers are copies, not links back to the wrappers in bin/.
        for name in ("arm-none-eabi-gcc", "arm-none-eabi-g++"):
            real = arm / ".mb-real-bin" / name
            self.assertFalse(real.is_symlink())
            self.assertNotIn("mb-ccache-wrapper", real.read_text())
        xt_real = self.packages / "toolchain-xtensa-esp-elf" / ".mb-real-bin"
        self.assertNotIn("mb-ccache-wrapper", (xt_real / "xtensa-esp-elf-cc").read_text())

    def test_running_twice_changes_nothing(self):
        self.wrap(CCACHE_DIR=str(self.cache))
        snapshot = {p: p.read_bytes() for p in self.packages.rglob("*") if p.is_file() and not p.is_symlink()}
        proc = self.wrap(CCACHE_DIR=str(self.cache))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("wrapped", proc.stdout)
        after = {p: p.read_bytes() for p in self.packages.rglob("*") if p.is_file() and not p.is_symlink()}
        self.assertEqual(snapshot, after)
        arm_bin = self.packages / "toolchain-gccarmnoneeabi" / "bin"
        calls = self.compile(arm_bin / "arm-none-eabi-gcc", "-c", "a.c")
        self.assertEqual([c.split()[0] for c in calls], ["ccache", "real-arm-gcc"])

    def test_without_a_cache_dir_nothing_is_touched(self):
        proc = self.wrap()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(list(self.packages.rglob(".mb-real-bin")))
        arm_bin = self.packages / "toolchain-gccarmnoneeabi" / "bin"
        self.assertEqual(self.compile(arm_bin / "arm-none-eabi-gcc", "-c", "a.c"), ["real-arm-gcc -c a.c"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write anywhere")
    def test_an_unwritable_cache_costs_speed_not_the_build(self):
        self.cache.mkdir()
        self.cache.chmod(0o500)
        try:
            proc = self.wrap(CCACHE_DIR=str(self.cache))
        finally:
            self.cache.chmod(0o700)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("not writable", proc.stdout)
        self.assertFalse(list(self.packages.rglob(".mb-real-bin")))

    def test_without_ccache_installed_nothing_is_touched(self):
        env = self._env(CCACHE_DIR=str(self.cache))
        env["PATH"] = "/usr/bin:/bin"  # no fake ccache; assumes no real one there
        if shutil.which("ccache", path=env["PATH"]):
            self.skipTest("a real ccache is installed")
        proc = subprocess.run([BASH, str(WRAP), str(self.packages)], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(list(self.packages.rglob(".mb-real-bin")))


def shared_downloads_block() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"\nuse_shared_downloads\(\) \{\n.*?\n\}\n", text, re.S)
    assert match, "use_shared_downloads not found in build_firmware.sh"
    idf = re.search(r"\nIDF_DIST_SUBDIR=.*?\nshare_idf_tool_downloads\(\) \{\n.*?\n\}\n", text, re.S)
    assert idf, "share_idf_tool_downloads not found in build_firmware.sh"
    return idf.group(0) + match.group(0)


@unittest.skipUnless(Path(BASH).exists(), "bash not available")
class SharedDownloadsTests(unittest.TestCase):
    """use_shared_downloads from docker/build_firmware.sh, against temp dirs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.core = self.tmp / "platformio"
        self.shared = self.tmp / "shared"
        # What the image ships: an installed package and a download cache dir.
        (self.core / "packages" / "toolchain-x").mkdir(parents=True)
        (self.core / "packages" / "toolchain-x" / "gcc").write_text("installed")
        (self.core / ".cache" / "downloads").mkdir(parents=True)
        (self.core / ".cache" / "http").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_block(self, shared=None):
        env = {**os.environ, "PLATFORMIO_CORE_DIR": str(self.core)}
        env.pop("MB_PIO_DOWNLOAD_DIR", None)
        if shared is not None:
            env["MB_PIO_DOWNLOAD_DIR"] = str(shared)
        script = "set -euo pipefail\n" + shared_downloads_block() + "use_shared_downloads\necho END\n"
        return subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=30, env=env)

    def test_downloads_go_to_the_shared_dir_and_nothing_else_moves(self):
        self.shared.mkdir()
        (self.shared / "a1b2c3").write_bytes(b"archive")
        proc = self.run_block(self.shared)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("END", proc.stdout)
        dl = self.core / ".cache" / "downloads"
        self.assertTrue(dl.is_symlink())
        self.assertEqual(dl.resolve(), self.shared.resolve())
        self.assertEqual((dl / "a1b2c3").read_bytes(), b"archive")
        # Installed packages and the rest of the cache stay in the container.
        self.assertFalse((self.core / "packages").is_symlink())
        self.assertEqual((self.core / "packages" / "toolchain-x" / "gcc").read_text(), "installed")
        self.assertTrue((self.core / ".cache" / "http").is_dir())
        self.assertIn("1 archives", proc.stdout)

    def test_stale_partial_downloads_are_dropped_and_fresh_ones_kept(self):
        self.shared.mkdir()
        old = self.shared / "tmpold123"
        fresh = self.shared / "tmpnew456"
        done = self.shared / "d4e5f6"
        for path in (old, fresh, done):
            path.write_bytes(b"x")
        four_hours_ago = time.time() - 4 * 3600
        os.utime(old, (four_hours_ago, four_hours_ago))
        os.utime(done, (four_hours_ago, four_hours_ago))
        proc = self.run_block(self.shared)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(done.exists())

    def test_idf_tool_downloads_are_shared_and_seeded_from_the_image(self):
        dist = self.core / "dist"
        dist.mkdir()
        (dist / "esptool.zip").write_bytes(b"from-image")
        (dist / "ninja.zip").write_bytes(b"image-ninja")
        (dist / "half.zip.tmp").write_bytes(b"partial")
        idf = self.shared / "idf-dist"
        idf.mkdir(parents=True)
        (idf / "ninja.zip").write_bytes(b"shared-ninja")  # already shared: kept as is
        proc = self.run_block(self.shared)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(dist.is_symlink())
        self.assertEqual(dist.resolve(), idf.resolve())
        self.assertEqual((idf / "esptool.zip").read_bytes(), b"from-image")
        self.assertEqual((idf / "ninja.zip").read_bytes(), b"shared-ninja")
        self.assertFalse((idf / "half.zip.tmp").exists())
        self.assertEqual(sorted(p.name for p in idf.iterdir()), ["esptool.zip", "ninja.zip"])
        self.assertIn("ESP-IDF tool downloads:", proc.stdout)
        self.assertIn("(2 archives)", proc.stdout)
        # The idf subdirectory is not counted as a PlatformIO archive.
        self.assertIn("Package downloads: ", proc.stdout)
        self.assertIn("(0 archives", proc.stdout)

    def test_idf_tool_downloads_without_a_dist_in_the_image(self):
        proc = self.run_block(self.shared)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        dist = self.core / "dist"
        self.assertTrue(dist.is_symlink())
        self.assertTrue((self.shared / "idf-dist").is_dir())

    def test_stale_partial_idf_downloads_are_dropped_and_fresh_ones_kept(self):
        idf = self.shared / "idf-dist"
        idf.mkdir(parents=True)
        old, fresh = idf / "a.zip.tmp", idf / "b.zip.tmp"
        old.write_bytes(b"x")
        fresh.write_bytes(b"x")
        four_hours_ago = time.time() - 4 * 3600
        os.utime(old, (four_hours_ago, four_hours_ago))
        proc = self.run_block(self.shared)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_running_twice_changes_nothing(self):
        (self.core / "dist").mkdir()
        (self.core / "dist" / "esptool.zip").write_bytes(b"z")
        self.assertEqual(self.run_block(self.shared).returncode, 0)
        proc = self.run_block(self.shared)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.core / "dist").is_symlink())
        self.assertEqual((self.core / "dist" / "esptool.zip").read_bytes(), b"z")

    def test_without_a_shared_dir_nothing_changes(self):
        proc = self.run_block()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        dl = self.core / ".cache" / "downloads"
        self.assertTrue(dl.is_dir())
        self.assertFalse(dl.is_symlink())
        self.assertFalse((self.core / "dist").exists())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write anywhere")
    def test_an_unwritable_shared_dir_costs_speed_not_the_build(self):
        self.shared.mkdir()
        self.shared.chmod(0o500)
        try:
            proc = self.run_block(self.shared)
        finally:
            self.shared.chmod(0o700)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("not writable", proc.stdout)
        self.assertFalse((self.core / ".cache" / "downloads").is_symlink())


if __name__ == "__main__":
    unittest.main()
