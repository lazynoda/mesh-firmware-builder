#!/usr/bin/env bash
set -euo pipefail

BASE_REPO="/opt/firmware"

# Prewarming lives in docker/prewarm.sh, which the image runs in an earlier
# layer. Keeping it out of here is what lets this file be edited without
# rebuilding an hour of prewarmed PlatformIO packages.
if [[ "$#" -ne 3 && "$#" -ne 4 ]]; then
  echo "usage: build-firmware <firmware-tag> <firmware-sha> <platformio-env> [<repo-url>]" >&2
  exit 2
fi

# The image is a clone of upstream Meshtastic. Other firmwares (forks or not)
# are fetched into that same clone at build time from <repo-url>, so the image
# and its prewarmed PlatformIO packages serve every firmware.
UPSTREAM_REPO="https://github.com/meshtastic/firmware.git"
FIRMWARE_TAG="$1"
FIRMWARE_SHA="$2"
PIO_ENV="$3"
FIRMWARE_REPO="${4:-${UPSTREAM_REPO}}"
WORK_DIR="${BASE_REPO}"
OUTPUT_DIR="/work/output"
INPUT_DIR="/work/input"

case "${PIO_ENV}" in
  *[!A-Za-z0-9._-]*)
    echo "Invalid PlatformIO environment: ${PIO_ENV}" >&2
    exit 2
    ;;
esac

if [[ ! "${FIRMWARE_REPO}" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$ ]]; then
  echo "Invalid firmware repository: ${FIRMWARE_REPO}" >&2
  exit 2
fi
if [[ ! "${FIRMWARE_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid firmware commit: ${FIRMWARE_SHA}" >&2
  exit 2
fi

# Every build log is read by someone hunting for the step that broke. Name the
# steps so they can be found by eye, and emit one machine-readable line when we
# already know what went wrong - the worker turns that into a user-facing reason
# instead of handing over four kilobytes of PlatformIO output.
phase() {
  echo "##### phase: $1 #####"
}

fail() {
  local code="$1" phase_name="$2" detail="$3"
  echo "MB_FAILURE code=${code} phase=${phase_name} detail=${detail}" >&2
  exit "${4:-1}"
}

# Print the basename of the first file matching any of the patterns, or nothing.
first_match() {
  local dir="$1"
  shift
  local pattern path
  for pattern in "$@"; do
    shopt -s nullglob
    for path in "${dir}"/${pattern}; do
      shopt -u nullglob
      basename "${path}"
      return 0
    done
    shopt -u nullglob
  done
}

# A short note in the ZIP, because the web flasher covers the common case but says
# nothing about the other files. The spiffs offset is read out of this build's own
# partition table rather than hardcoded: it differs per board.
write_flashing_notes() {
  local dir="$1"
  local factory update littlefs uf2 hex spiffs
  # nullglob, not ls: under `set -o pipefail` an ls that matches nothing fails
  # the whole command substitution and set -e takes the script down with it.
  factory=$(first_match "${dir}" "*.factory.bin")
  update=$(first_match "${dir}" "*-update.bin")
  littlefs=$(first_match "${dir}" "littlefs-*.bin" "spiffs-*.bin")
  uf2=$(first_match "${dir}" "*.uf2")
  hex=$(first_match "${dir}" "*.hex")

  {
    echo "Flashing this firmware"
    echo "======================"
    echo ""
    if [[ -n "${factory}" ]]; then
      spiffs=$(python3 - "${dir}/partitions.bin" <<'PY' 2>/dev/null || true
import struct, sys
raw = open(sys.argv[1], "rb").read()
for off in range(0, len(raw), 32):
    entry = raw[off:off + 32]
    if entry[:2] != b"\xaa\x50":
        break
    _, _, _, addr, _, label, _ = struct.unpack("<HBBII16sI", entry)
    if label.rstrip(b"\x00") in (b"spiffs", b"littlefs"):
        print(hex(addr))
        break
PY
)
      echo "Easiest: https://flasher.meshtastic.org"
      echo "  Pick your device, choose the custom firmware option and select this ZIP."
      echo "  That is an update and keeps the settings already on the node."
      echo ""
      echo "Full install with esptool, for a blank node or one that will not boot:"
      echo "  esptool erase-flash"
      echo "  esptool write-flash 0x0 ${factory}"
      [[ -n "${littlefs}" && -n "${spiffs}" ]] && echo "  esptool write-flash ${spiffs} ${littlefs}"
      echo ""
      echo "Files:"
      [[ -n "${update}" ]] && echo "  ${update}"
      echo "      app image only, written at 0x10000. This is what the web flasher uses."
      echo "  ${factory}"
      echo "      bootloader + partition table + app, written at 0x0."
      [[ -n "${littlefs}" ]] && echo "  ${littlefs}" && echo "      empty filesystem for the spiffs partition."
      echo "  bootloader.bin / partitions.bin"
      echo "      the pieces already inside the factory image, at 0x0 and 0x8000."
    else
      echo "This is an nRF52 board, so esptool is not involved."
      echo ""
      echo "Double-tap the reset button. The node appears as a USB drive."
      [[ -n "${uf2}" ]] && echo "Copy ${uf2} onto it. The node reboots on its own."
      echo ""
      echo "Files:"
      [[ -n "${uf2}" ]] && echo "  ${uf2}" && echo "      drag-and-drop image. This is the one you want."
      [[ -n "${hex}" ]] && echo "  ${hex}" && echo "      for a SWD or J-Link programmer."
    fi
    echo "  userPrefs.jsonc"
    echo "      the settings compiled into this build."
    echo "  BUILD_INFO.txt"
    echo "      firmware tag, commit and build metadata."
  } >"${dir}/FLASHING.txt"
}

# PlatformIO's tool-sreccat ships a 32-bit ARM srec_cat for every ARM host, and
# a 64-bit-only image cannot run it ("not found", exit 127). The nRF54 platform
# calls it to write the .hex, so those builds died at the very end. When the
# bundled binary does not run, point it at Debian's native one (package
# srecord in the image). On x86 the bundled binary runs and is left alone.
use_native_sreccat() {
  local bundled="${PLATFORMIO_CORE_DIR:-${HOME}/.platformio}/packages/tool-sreccat/srec_cat"
  local native
  [[ -f "${bundled}" && ! -L "${bundled}" ]] || return 0
  native="$(command -v srec_cat || true)"
  [[ -n "${native}" ]] || return 0
  if "${bundled}" --version >/dev/null 2>&1; then
    return 0
  fi
  ln -sf "${native}" "${bundled}"
  echo "PlatformIO's srec_cat cannot run on this host; using ${native}."
}

# Compiler cache (ccache), only when the worker mounted one and set CCACHE_DIR.
# It caches each object file below SCons, so every target and every post-action
# still runs and the .uf2/.factory.bin are always generated (PlatformIO's own
# build_cache_dir skips post-actions on a hit; see docs/worker-and-builder.md).
# A cache hit needs the same compiler, flags and preprocessed source, so a
# changed userPrefs.jsonc misses for exactly the files it reaches.
CCACHE_PRE_SCRIPT="/usr/local/lib/meshtastic-builder/ccache_pre.py"
enable_ccache() {
  if [[ -z "${CCACHE_DIR:-}" ]]; then
    echo "No compiler cache configured; full compile."
    return 0
  fi
  if ! command -v ccache >/dev/null 2>&1 || [[ ! -x /usr/local/bin/mb-ccache-wrap ]]; then
    echo "This builder image has no ccache; full compile."
    unset CCACHE_DIR
    return 0
  fi
  # Toolchains already in the image are wrapped now; ones PlatformIO installs
  # during this build are wrapped by the pre: script before the first compile.
  /usr/local/bin/mb-ccache-wrap || echo "ccache: wrapping the toolchain failed; continuing."
  # Also store the cap in the cache's own ccache.conf, so stats and cleanups run
  # outside a build (an operator's `ccache --show-stats`) see the same limit.
  if [[ -n "${CCACHE_MAXSIZE:-}" ]]; then
    ccache --max-size "${CCACHE_MAXSIZE}" >/dev/null 2>&1 || true
  fi
  export PLATFORMIO_EXTRA_SCRIPTS="pre:${CCACHE_PRE_SCRIPT}"
  # Counters for this build only: the cache directory is shared by every build.
  CCACHE_STATSLOG="$(mktemp)"
  export CCACHE_STATSLOG
  echo "Compiler cache: ${CCACHE_DIR} (max ${CCACHE_MAXSIZE:-ccache default})"
}

# Shared PlatformIO download store, only when the worker mounted one and set
# MB_PIO_DOWNLOAD_DIR. Only the archives PlatformIO downloads are shared (kept by
# URL + checksum, written by an atomic rename once complete). Every package is
# still unpacked into this container's own /opt/platformio, which some ESP32
# boards then rewrite for themselves and which is thrown away with the container.
use_shared_downloads() {
  local shared="${MB_PIO_DOWNLOAD_DIR:-}" core="${PLATFORMIO_CORE_DIR:-${HOME}/.platformio}" dl
  if [[ -z "${shared}" ]]; then
    echo "No shared package downloads; packages missing from the image are downloaded."
    return 0
  fi
  if ! mkdir -p "${shared}" 2>/dev/null || [[ ! -w "${shared}" ]]; then
    echo "Package downloads: ${shared} is not writable; downloading packages for this build only."
    return 0
  fi
  # A build killed mid-download leaves its temporary file behind (the finished
  # archive only ever appears by rename). Drop old ones; a running download is
  # never this old because builds time out sooner.
  find "${shared}" -maxdepth 1 -type f -name 'tmp*' -mmin +180 -delete 2>/dev/null || true
  dl="${core}/.cache/downloads"
  mkdir -p "${core}/.cache"
  rm -rf "${dl}"
  ln -s "${shared}" "${dl}"
  echo "Package downloads: ${shared} ($(find "${shared}" -maxdepth 1 -type f ! -name '*.lock' ! -name usage.db ! -name 'tmp*' | wc -l) archives, $(du -sh "${shared}" 2>/dev/null | cut -f1))"
}


# PlatformIO Core for this build. The image carries several (see
# docker/builder.Dockerfile): `pio` is the lowest, the others live in their own
# venvs as /opt/pio-cores/<x.y.z>/bin/pio. The worker passes
# MB_PLATFORMIO_VERSION when it read, from the firmware's platformio.ini and
# the platform's platform.json, which one this board needs. Without it the
# lowest runs first and the build moves up only when PlatformIO itself refuses
# the platform (IncompatiblePlatform), which it does before compiling anything.
# Never the other way round: a newer Core accepts an older platform and then
# breaks it halfway through the link (SCons 4.11 dropped FortranCommon).
PIO_CORES_DIR="/opt/pio-cores"
PIO_BIN="pio"
select_platformio() {
  local wanted="${MB_PLATFORMIO_VERSION:-}"
  if [[ -z "${wanted}" ]]; then
    echo "PlatformIO: $(pio --version) (default; this build did not name one)"
    return 0
  fi
  if [[ ! "${wanted}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    fail infrastructure caches "Invalid PlatformIO version: ${wanted}" 2
  fi
  if [[ "$(pio --version)" == *" ${wanted}" ]]; then
    PIO_BIN="pio"
  elif [[ -x "${PIO_CORES_DIR}/${wanted}/bin/pio" ]]; then
    PIO_BIN="${PIO_CORES_DIR}/${wanted}/bin/pio"
  else
    fail infrastructure caches "This builder image has no PlatformIO ${wanted}."
  fi
  echo "PlatformIO: $("${PIO_BIN}" --version) (chosen for this board)"
}

# The next Core up from the one that just refused the platform, or nothing.
next_platformio() {
  local current version
  current="$("${PIO_BIN}" --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+$')"
  shopt -s nullglob
  for version in $(printf '%s\n' "${PIO_CORES_DIR}"/*/ | xargs -r -n1 basename | sort -V); do
    shopt -u nullglob
    if [[ "$(printf '%s\n%s\n' "${current}" "${version}" | sort -V | tail -1)" == "${version}" \
      && "${version}" != "${current}" && -x "${PIO_CORES_DIR}/${version}/bin/pio" ]]; then
      echo "${PIO_CORES_DIR}/${version}/bin/pio"
      return 0
    fi
  done
  shopt -u nullglob
}

report_ccache() {
  [[ -n "${CCACHE_STATSLOG:-}" && -s "${CCACHE_STATSLOG}" ]] || return 0
  echo "Compiler cache for this build:"
  ccache --show-log-stats 2>/dev/null | sed -n '1,6p' || true
  ccache --show-stats 2>/dev/null | grep -E '^ *(Cache size|Local storage)' || true
}

cd "${WORK_DIR}"
phase "checkout ${FIRMWARE_TAG} (${FIRMWARE_SHA}) from ${FIRMWARE_REPO}"
if [[ "${FIRMWARE_REPO}" == "${UPSTREAM_REPO}" ]]; then
  # Only hit the network when the image does not already contain the requested commit.
  if ! git cat-file -e "${FIRMWARE_SHA}^{commit}" 2>/dev/null; then
    git fetch --tags --force origin || true
  fi
  git checkout --force "${FIRMWARE_SHA}" || git checkout --force "${FIRMWARE_TAG}"
else
  # Another repository: fetch exactly the commit the worker resolved, without its
  # tags (they could shadow upstream's in this clone). The first build of a
  # firmware downloads whatever history it does not share with upstream.
  if ! git cat-file -e "${FIRMWARE_SHA}^{commit}" 2>/dev/null; then
    git fetch --no-tags --force "${FIRMWARE_REPO}" "${FIRMWARE_SHA}" \
      || git fetch --no-tags --force "${FIRMWARE_REPO}" "${FIRMWARE_TAG}" \
      || fail infrastructure checkout "Could not fetch ${FIRMWARE_SHA} from ${FIRMWARE_REPO}."
  fi
  # No fallback to the tag name: here it could resolve to an upstream tag and
  # compile the wrong firmware.
  git checkout --force "${FIRMWARE_SHA}" \
    || fail infrastructure checkout "Commit ${FIRMWARE_SHA} is not in ${FIRMWARE_REPO}."
  # Submodule URLs come from this commit's .gitmodules, not from the image's.
  git submodule sync --recursive
fi
git submodule update --init --recursive
echo "Checked out $(git rev-parse HEAD)"

# Every patch the worker staged, in name order. The worker decides which ones a
# given firmware tag needs; this only applies what it was handed, and a patch
# that does not apply stops the build before pio run rather than silently
# compiling firmware without the change the user asked for.
phase "patches"
shopt -s nullglob
patches=("${INPUT_DIR}/patches"/*.patch)
shopt -u nullglob
if [[ ${#patches[@]} -eq 0 ]]; then
  echo "No firmware patches requested for this build."
fi
for patch in "${patches[@]}"; do
  patch_name="$(basename "${patch}")"
  echo "Applying ${patch_name}"
  if ! git apply --verbose "${patch}"; then
    fail patch_failed patches "${patch_name}" 3
  fi
done

phase "inputs"
if [[ ! -f "${INPUT_DIR}/userPrefs.jsonc" ]]; then
  fail infrastructure inputs "userPrefs.jsonc never reached the builder container."
fi
cp "${INPUT_DIR}/userPrefs.jsonc" ./userPrefs.jsonc
echo "userPrefs.jsonc in place ($(wc -c <./userPrefs.jsonc) bytes)"

phase "caches"
enable_ccache
use_shared_downloads
select_platformio

phase "compile ${PIO_ENV}"
# Retry once: pioarduino may replace tool-scons mid-run on the first build of a
# platform version (platform-espressif32#529). A genuine compile error fails twice.
# Also between the two attempts: a platform installed during the first run can
# bring its own tool-sreccat, which only the retry can then use.
# Except when the linker says the image does not fit: a retry links the same
# objects again and fails the same way, so it would only waste a minute of CPU.
# And when no Core was named and the default one refuses the platform, move up
# one Core instead of retrying the same one (see select_platformio).
use_native_sreccat
pio_log="$(mktemp)"
if ! "${PIO_BIN}" run -e "${PIO_ENV}" 2>&1 | tee "${pio_log}"; then
  if grep -qE "region [\`'\"]?[A-Za-z0-9_]+[\`'\"]? overflowed by [0-9,]+ bytes" "${pio_log}"; then
    fail firmware_too_big compile "$(grep -m1 -oE "region [^ ]+ overflowed by [0-9,]+ bytes" "${pio_log}")"
  fi
  if [[ -z "${MB_PLATFORMIO_VERSION:-}" ]] && grep -q "IncompatiblePlatform" "${pio_log}"; then
    next="$(next_platformio)"
    if [[ -z "${next}" ]]; then
      fail infrastructure compile "$(grep -m1 -oE "is not compatible with PlatformIO Core [^ ]+ and depends on PlatformIO Core [^ .]+(\.[0-9]+)*" "${pio_log}" || echo "No PlatformIO in this image accepts this platform.")"
    fi
    PIO_BIN="${next}"
    echo "PlatformIO: the platform needs a newer Core; retrying with $("${PIO_BIN}" --version)"
  fi
  use_native_sreccat
  "${PIO_BIN}" run -e "${PIO_ENV}"
fi
rm -f "${pio_log}"
report_ccache

# Only what a flasher consumes. .elf and .map are dropped on purpose: they were
# 81% of the ZIP and nothing in bin/device-install.sh reads them, so they only
# matter for decoding a backtrace. Everything else stays, including the
# littlefs image: device-install.sh writes it to the spiffs partition after
# erase_flash, and it aborts if the file is missing.
phase "package"
mkdir -p "${OUTPUT_DIR}/files"
find ".pio/build/${PIO_ENV}" -maxdepth 1 -type f \
  \( -name "*.bin" -o -name "*.uf2" -o -name "*.hex" \) \
  -exec cp {} "${OUTPUT_DIR}/files/" \;

# flasher.meshtastic.org only reads a release manifest for firmware it hosts, so a
# ZIP the user picks themselves always takes the legacy path, which searches the
# archive for firmware-<target>-<version>-update.bin. Ship the app-only image
# under that name and the ZIP can be selected as-is. The factory image keeps its
# own name; the flasher's pattern deliberately excludes *-update.bin.
for app in "${OUTPUT_DIR}/files/"firmware-*.bin; do
  [[ -e "${app}" ]] || continue
  case "${app}" in
    *.factory.bin | *-update.bin) continue ;;
  esac
  # Only ESP32 builds emit a factory image, and only they have an app slot at
  # 0x10000. nRF52 ships a .uf2 and must not be touched. This has to be an if,
  # not a && chain: as the last statement in the loop it would return 1 on an
  # nRF52 build and set -e would kill the script.
  if [[ -e "${app%.bin}.factory.bin" ]]; then
    mv "${app}" "${app%.bin}-update.bin"
  fi
done

cp "${INPUT_DIR}/userPrefs.jsonc" "${OUTPUT_DIR}/files/userPrefs.jsonc"
cp "${INPUT_DIR}/BUILD_INFO.txt" "${OUTPUT_DIR}/files/BUILD_INFO.txt"
write_flashing_notes "${OUTPUT_DIR}/files"

{
  echo ""
  # When this firmware was compiled, not when the image was prewarmed: the
  # image stamp is written into the prewarm layer, so it only moves when the
  # prewarmed content itself is rebuilt.
  echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "builder_image_created_at=$(cat /etc/builder-image-created-at 2>/dev/null || echo unknown)"
  echo "actual_git_sha=$(git rev-parse HEAD)"
  echo "platformio_env=${PIO_ENV}"
  echo "platformio_version=$("${PIO_BIN}" --version)"
} >> "${OUTPUT_DIR}/files/BUILD_INFO.txt"

if [[ -z "$(find "${OUTPUT_DIR}/files" -type f ! -name BUILD_INFO.txt ! -name userPrefs.jsonc -print -quit)" ]]; then
  fail no_artifacts package "PlatformIO produced no firmware files for ${PIO_ENV}."
fi

ZIP_NAME="meshtastic-${FIRMWARE_TAG}-${PIO_ENV}.zip"
(
  cd "${OUTPUT_DIR}/files"
  zip -r "${OUTPUT_DIR}/${ZIP_NAME}" .
)
