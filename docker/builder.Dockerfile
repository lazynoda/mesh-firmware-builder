FROM debian:trixie

ARG MESHTASTIC_REPO=https://github.com/meshtastic/firmware.git
# Git ref the image is prewarmed against. "latest" resolves to the newest
# release tag at image build time; pass a tag to pin it.
ARG MESHTASTIC_REF=latest
ARG PREWARM_ENVS="heltec-v4 nrf52_promicro_diy_tcxo"
ARG PLATFORMIO_VERSION=6.1.19

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PLATFORMIO_CORE_DIR=/opt/platformio \
    PLATFORMIO_SETTING_ENABLE_TELEMETRY=No \
    PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL=3650

RUN apt-get update && apt-get install --no-install-recommends -y \
      ca-certificates \
      curl \
      git \
      g++ \
      make \
      python3 \
      python3-pip \
      python3-venv \
      unzip \
      zip \
    # 6.2.0 ships tool-scons 4.11, which dropped SCons.Tool.FortranCommon and breaks
    # the pioarduino ESP32 link step. 6.1.19 builds both ESP32-S3 and nRF52 targets.
    && pip3 install --no-cache-dir "platformio==${PLATFORMIO_VERSION}" \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip

# Full clone with tags and submodules so runtime builds of any supported tag
# resolve offline. build-firmware only fetches when the requested SHA is missing.
RUN git clone --recursive "${MESHTASTIC_REPO}" /opt/firmware \
    && cd /opt/firmware \
    && git fetch --tags --force \
    && mkdir -p /work/input /work/output

# Only the prewarm script, so the expensive layer below depends on as little as
# possible. Editing the runtime entrypoint must not invalidate it.
COPY docker/prewarm.sh /usr/local/bin/prewarm-firmware
RUN chmod +x /usr/local/bin/prewarm-firmware \
    && /usr/local/bin/prewarm-firmware "${MESHTASTIC_REF}" ${PREWARM_ENVS} \
    # Provenance for BUILD_INFO.txt. Written in this layer on purpose: a cached
    # prewarm layer means identical content, so the original date stays honest.
    && date -u +%Y-%m-%dT%H:%M:%SZ > /etc/builder-image-created-at \
    && rm -rf \
      /opt/firmware/.pio/build \
      /opt/platformio/.cache/downloads \
      /opt/platformio/.cache/tmp \
      /root/.cache/pip \
      /tmp/*

# Native srec_cat for build-firmware's use_native_sreccat: PlatformIO's
# tool-sreccat is a 32-bit ARM binary on arm64 hosts, which this image cannot
# run, and nRF54 builds need it. After the prewarm so adding it costs seconds.
RUN apt-get update \
    && apt-get install --no-install-recommends -y srecord \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ccache for the compiler cache the worker mounts (MB_CCACHE_VOLUME). The
# wrapper and the PlatformIO pre: script put it in front of each toolchain's
# compilers at build time, so the prewarmed packages above stay untouched and a
# build without a cache volume compiles exactly as before.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ccache \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
COPY docker/ccache_wrap.sh /usr/local/bin/mb-ccache-wrap
COPY docker/ccache_pre.py /usr/local/lib/meshtastic-builder/ccache_pre.py
RUN chmod 755 /usr/local/bin/mb-ccache-wrap \
    && chmod 644 /usr/local/lib/meshtastic-builder/ccache_pre.py

# After the prewarm on purpose. This script changes whenever a patch, a phase
# banner or a failure marker changes; copied in earlier, every such edit would
# discard about an hour of prewarming for a shell diff.
COPY docker/build_firmware.sh /usr/local/bin/build-firmware
RUN chmod +x /usr/local/bin/build-firmware

WORKDIR /opt/firmware
ENTRYPOINT ["/usr/local/bin/build-firmware"]

# Nothing runs this image between builds, so `docker system prune -a` counts it
# as unused and deletes an hour of prewarming. Prune with
# `--filter "label!=keep"` to spare it. Kept last so adding it never invalidates
# the prewarm layer above.
LABEL keep="true"
