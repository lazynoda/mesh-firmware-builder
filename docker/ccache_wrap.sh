#!/usr/bin/env bash
# Put ccache in front of every PlatformIO toolchain compiler in this container.
#
# usage: mb-ccache-wrap [<platformio-packages-dir>]
#
# build-firmware runs this before `pio run`, and again from a PlatformIO pre:
# script (ccache_pre.py) inside every run, so a toolchain PlatformIO installs
# during the build is wrapped before SCons compiles with it. Running it twice
# is a no-op: a compiler that is already a wrapper is left alone.
#
# Why wrappers and not a PATH shim or CC="ccache gcc": the platforms set CC to a
# bare name (arm-none-eabi-gcc, xtensa-esp32s3-elf-gcc) and prepend the
# package's bin/ to PATH inside SCons, so a shim earlier on PATH never wins, and
# rewriting CC would take a firmware-side extra_scripts file. The builder serves
# any firmware repository, so the toolchain is wrapped where it is installed.
#
# Each compiler is copied to <package>/.mb-real-bin/, a sibling of bin/ and so
# at the same depth: gcc finds cc1, as and ld relative to its own path. Every
# other file of bin/ is linked into .mb-real-bin/ too, because the toolchains
# also look next to themselves: the ARM gcc loads libiconv from $ORIGIN, and
# the per-chip xtensa drivers exec xtensa-esp-elf-gcc from their own directory
# (which then is the real one, so it is not cached twice). A small shell
# wrapper takes the compiler's name in bin/.
#
# Does nothing unless CCACHE_DIR is set, writable and ccache is installed: a
# missing or read-only cache must cost speed, never a build.

set -euo pipefail

MARKER="mb-ccache-wrapper"
packages_dir="${1:-${PLATFORMIO_CORE_DIR:-${HOME}/.platformio}/packages}"

[[ -n "${CCACHE_DIR:-}" ]] || exit 0
command -v ccache >/dev/null 2>&1 || exit 0
if ! mkdir -p "${CCACHE_DIR}" 2>/dev/null || [[ ! -w "${CCACHE_DIR}" ]]; then
  echo "ccache: ${CCACHE_DIR} is not writable; compiling without a cache."
  exit 0
fi
[[ -d "${packages_dir}" ]] || exit 0

ccache_bin="$(command -v ccache)"

# The compiler identity ccache hashes. The default (mtime) changes every time a
# package is unpacked again, and running `gcc -v` on every call costs a process
# per object; the package name and version from package.json are stable and
# change exactly when the toolchain does.
toolchain_id() {
  local pkg_dir="$1" name version
  name="$(basename "${pkg_dir}")"
  version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version", ""))' \
    "${pkg_dir}/package.json" 2>/dev/null || true)"
  # Only characters that are safe inside the single-quoted string below.
  printf '%s@%s' "${name}" "${version:-unknown}" | tr -c 'A-Za-z0-9._+@-' '_'
}

is_wrapper() {
  head -c 200 "$1" 2>/dev/null | grep -q "${MARKER}"
}

# Link every entry of bin/ into the real directory, keeping what is already
# there (real compilers copied by an earlier run).
mirror_bin() {
  local bin_dir="$1" real_dir="$2" entry name
  mkdir -p "${real_dir}"
  for entry in "${bin_dir}"/* "${bin_dir}"/.[!.]*; do
    [[ -e "${entry}" || -L "${entry}" ]] || continue
    name="$(basename "${entry}")"
    [[ -e "${real_dir}/${name}" || -L "${real_dir}/${name}" ]] && continue
    if [[ -L "${entry}" ]]; then
      # Keep links as links (xtensa-esp-elf-cc -> xtensa-esp-elf-gcc), so they
      # resolve inside the real directory to the real compiler.
      cp -P "${entry}" "${real_dir}/${name}"
    else
      ln -s "../bin/${name}" "${real_dir}/${name}"
    fi
  done
}

wrapped=0
shopt -s nullglob
for bin_dir in "${packages_dir}"/toolchain-*/bin; do
  pkg_dir="$(dirname "${bin_dir}")"
  real_dir="${pkg_dir}/.mb-real-bin"
  id="$(toolchain_id "${pkg_dir}")"
  mirrored=0
  for compiler in "${bin_dir}"/*-gcc "${bin_dir}"/*-g++ "${bin_dir}"/*-c++ "${bin_dir}"/*-cc; do
    [[ -e "${compiler}" ]] || continue
    # A symlinked name (xtensa-esp-elf-cc -> xtensa-esp-elf-gcc) already reaches
    # the wrapper of its target once that is wrapped, which this check sees by
    # reading through the link; one wrapped by an earlier run is skipped too.
    is_wrapper "${compiler}" && continue
    name="$(basename "${compiler}")"
    if [[ "${mirrored}" -eq 0 ]]; then
      mirror_bin "${bin_dir}" "${real_dir}"
      mirrored=1
    fi
    # -L: the real compiler must be a file of its own, never a link back into
    # bin/, which now holds the wrapper.
    rm -f "${real_dir}/${name}"
    cp -L "${compiler}" "${real_dir}/${name}"
    tmp="$(mktemp "${bin_dir}/.${name}.XXXXXX")"
    cat >"${tmp}" <<EOF
#!/bin/sh
# ${MARKER} (${id}), written by build-firmware's mb-ccache-wrap.
# A compiler that calls another one (the per-chip xtensa drivers call
# xtensa-esp-elf-gcc) must reach it without a second trip through ccache.
if [ -n "\${MB_CCACHE_ACTIVE:-}" ]; then
  exec "${real_dir}/${name}" "\$@"
fi
MB_CCACHE_ACTIVE=1 CCACHE_COMPILERCHECK='string:${id}' exec "${ccache_bin}" "${real_dir}/${name}" "\$@"
EOF
    chmod 755 "${tmp}"
    mv -f "${tmp}" "${compiler}"
    wrapped=$((wrapped + 1))
  done
done
shopt -u nullglob

if [[ "${wrapped}" -gt 0 ]]; then
  echo "ccache: wrapped ${wrapped} compiler(s) under ${packages_dir}."
fi
