# PlatformIO pre: script that build-firmware adds through PLATFORMIO_EXTRA_SCRIPTS
# when a compiler cache is configured. It lives in the builder image, not in the
# firmware: the builder serves any firmware repository and carries no patch for it.
#
# PlatformIO installs any missing platform and toolchain before SCons starts, and
# pre: scripts run before the first compile, so this is the one point where every
# toolchain this build will use is on disk and nothing has been compiled yet.
# mb-ccache-wrap is idempotent and does nothing without CCACHE_DIR.
import subprocess

result = subprocess.run(["/usr/local/bin/mb-ccache-wrap"], check=False)
if result.returncode != 0:
    print("ccache: wrapping the toolchain failed; this build compiles without a cache.")
