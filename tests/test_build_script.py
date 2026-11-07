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


def run_compile(pio_output: str, *, fails: int) -> tuple[subprocess.CompletedProcess, int]:
    """Run the compile block with a pio that prints `pio_output` and fails `fails` times."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        calls = tmp_path / "calls"
        calls.write_text("0")
        pio = tmp_path / "pio"
        pio.write_text(
            "#!/usr/bin/env bash\n"
            f'n=$(( $(cat "{calls}") + 1 )); echo "$n" > "{calls}"\n'
            f"cat <<'EOF'\n{pio_output}\nEOF\n"
            f'[ "$n" -gt {fails} ]\n'
        )
        pio.chmod(pio.stat().st_mode | stat.S_IEXEC)
        script = (
            "set -euo pipefail\n"
            "PIO_ENV=test-env\n"
            "phase() { :; }\n"
            "use_native_sreccat() { :; }\n"
            "report_ccache() { :; }\n"
            'fail() { echo "MB_FAILURE code=$1 phase=$2 detail=$3" >&2; exit "${4:-1}"; }\n'
            + compile_block()
            + "\necho COMPILED\n"
        )
        proc = subprocess.run(
            [BASH, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        )
        return proc, int(calls.read_text())


OVERFLOW = (
    "/opt/platformio/packages/toolchain-gccarmnoneeabi/bin/ld: "
    "region `FLASH' overflowed by 77752 bytes\n"
    "collect2: error: ld returned 1 exit status\n"
    "*** [.pio/build/test-env/firmware.elf] Error 1"
)


@unittest.skipUnless(Path(BASH).exists(), "bash not available")
class CompileRetryTests(unittest.TestCase):
    def test_flash_overflow_fails_once_without_retry(self):
        proc, calls = run_compile(OVERFLOW, fails=99)
        self.assertEqual(calls, 1)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(
            "MB_FAILURE code=firmware_too_big phase=compile detail=region `FLASH' overflowed by 77752 bytes",
            proc.stderr,
        )
        self.assertNotIn("COMPILED", proc.stdout)

    def test_other_failure_is_retried_once(self):
        # pioarduino swapping tool-scons mid-run: the second run succeeds.
        proc, calls = run_compile("ModuleNotFoundError: No module named 'SCons.Tool.FortranCommon'", fails=1)
        self.assertEqual(calls, 2)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("COMPILED", proc.stdout)

    def test_genuine_compile_error_still_fails_after_the_retry(self):
        proc, calls = run_compile("src/main.cpp:1:1: error: boom", fails=99)
        self.assertEqual(calls, 2)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("MB_FAILURE", proc.stderr)

    def test_success_runs_pio_once_and_keeps_its_output(self):
        proc, calls = run_compile("========== [SUCCESS] Took 1.00 seconds ==========", fails=0)
        self.assertEqual(calls, 1)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[SUCCESS]", proc.stdout)


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


if __name__ == "__main__":
    unittest.main()
