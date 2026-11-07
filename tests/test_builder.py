import os
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from meshtastic_builder import builder
from meshtastic_builder.build_failures import BuildFailure
from meshtastic_builder.builder import (
    docker_transport,
    run_build,
    run_docker_build,
)
from meshtastic_builder.config import load_config


def test_build(token="token-123"):
    return {
        "public_token": token,
        "device_id": "tbeam",
        "platformio_env": "tbeam",
        "firmware_tag": "v-test",
        "firmware_sha": "abc123",
        "prefs_jsonc": '{"USERPREFS_ALLOWED": true}\n',
    }


class BuilderTests(unittest.TestCase):
    def test_fake_build_creates_zip_with_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = replace(
                load_config(),
                data_dir=tmp_path,
                artifact_dir=tmp_path / "artifacts",
                job_dir=tmp_path / "jobs",
                builder_mode="fake",
            )

            artifact = run_build(config, test_build())

            self.assertTrue(artifact.path.exists())
            self.assertGreater(artifact.size_bytes, 0)
            with zipfile.ZipFile(artifact.path) as zf:
                names = set(zf.namelist())
                self.assertIn("BUILD_INFO.txt", names)
                self.assertIn("userPrefs.jsonc", names)
                self.assertIn("firmware-tbeam.txt", names)

    def test_docker_build_invokes_expected_command_and_copies_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            output_dir = tmp_path / "output"
            final_zip = tmp_path / "final.zip"
            input_dir.mkdir()
            output_dir.mkdir()
            produced = output_dir / "produced.zip"
            produced.write_bytes(b"zip-content")
            config = replace(
                load_config(),
                root_dir=tmp_path,
                docker_binary="docker",
                docker_network="none",
                docker_transport="bind",
                docker_cpus="3",
                docker_memory="5g",
                docker_pids_limit=256,
                builder_image="builder:test",
                build_timeout_seconds=123,
            )

            with patch("meshtastic_builder.builder.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "ok"
                run.return_value.stderr = ""
                log = run_docker_build(config, test_build(), input_dir, output_dir, final_zip)

            self.assertIn("ok", log)
            self.assertIn("===== build =====", log)
            self.assertEqual(final_zip.read_bytes(), b"zip-content")
            command = run.call_args.args[0]
            self.assertIn("--rm", command)
            self.assertIn("--network", command)
            self.assertIn("none", command)
            self.assertIn("--cpus", command)
            self.assertIn("3", command)
            self.assertIn("--memory", command)
            self.assertIn("5g", command)
            self.assertIn("--pids-limit", command)
            self.assertIn("256", command)
            self.assertIn("builder:test", command)
            self.assertEqual(
                command[-4:],
                ["v-test", "abc123", "tbeam", "https://github.com/meshtastic/firmware.git"],
            )

    def test_no_platformio_build_cache_is_mounted(self):
        """SCons skips a target's post-actions on a cache hit.

        Meshtastic writes the .uf2 and the .factory.bin inside post-actions, as
        side effects rather than declared targets, so a fully cached build ships
        a ZIP with nothing flashable in it. Reintroducing the cache brings that
        back; see the comment in builder.py.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            output_dir = tmp_path / "output"
            final_zip = tmp_path / "final.zip"
            input_dir.mkdir()
            output_dir.mkdir()
            (output_dir / "produced.zip").write_bytes(b"zip-content")
            config = replace(load_config(), root_dir=tmp_path, docker_transport="bind")

            with patch("meshtastic_builder.builder.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "ok"
                run.return_value.stderr = ""
                run_docker_build(config, test_build(), input_dir, output_dir, final_zip)

            command = " ".join(run.call_args.args[0])
            self.assertNotIn("pio-cache", command)
            self.assertNotIn("PLATFORMIO_BUILD_CACHE_DIR", command)

    def test_docker_build_failure_raises_with_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            output_dir = tmp_path / "output"
            final_zip = tmp_path / "final.zip"
            input_dir.mkdir()
            output_dir.mkdir()
            config = replace(load_config(), root_dir=tmp_path, docker_transport="bind")

            with patch("meshtastic_builder.builder.subprocess.run") as run:
                run.return_value.returncode = 42
                run.return_value.stdout = "stdout"
                run.return_value.stderr = "stderr"
                with self.assertRaises(BuildFailure) as ctx:
                    run_docker_build(config, test_build(), input_dir, output_dir, final_zip)

            # Nothing in the output looks like a diagnostic, so the code stays
            # unknown - but the full log still travels with the failure.
            self.assertEqual(ctx.exception.code, "unknown")
            self.assertIn("code 42", ctx.exception.detail)
            self.assertIn("stderr", ctx.exception.log)

    def test_compiler_error_is_named_and_quoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            output_dir = tmp_path / "output"
            final_zip = tmp_path / "final.zip"
            input_dir.mkdir()
            output_dir.mkdir()
            config = replace(load_config(), root_dir=tmp_path, docker_transport="bind")

            with patch("meshtastic_builder.builder.subprocess.run") as run:
                run.return_value.returncode = 1
                run.return_value.stdout = (
                    "Compiling NodeDB.cpp\n"
                    "src/mesh/NodeDB.cpp:705:27: error: 'info' was not declared in this scope\n"
                )
                run.return_value.stderr = ""
                with self.assertRaises(BuildFailure) as ctx:
                    run_docker_build(config, test_build(), input_dir, output_dir, final_zip)

            self.assertEqual(ctx.exception.code, "compile_error")
            self.assertIn("'info' was not declared", ctx.exception.detail)

    def test_auto_docker_transport_uses_copy_for_remote_docker_host(self):
        config = replace(load_config(), docker_transport="auto")
        with patch.object(builder, "CONTAINER_MARKER", Path("/nonexistent-container-marker")):
            with patch.dict(os.environ, {"DOCKER_HOST": "ssh://docker-host.example"}):
                self.assertEqual(docker_transport(config), "copy")
            with patch.dict(os.environ, {"DOCKER_HOST": ""}):
                self.assertEqual(docker_transport(config), "bind")

    def test_auto_docker_transport_uses_copy_inside_a_container(self):
        # The worker in Compose reaches the host daemon through a mounted socket,
        # so its own paths mean nothing to that daemon and bind would mount empty.
        config = replace(load_config(), docker_transport="auto")
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".dockerenv"
            marker.write_text("", encoding="utf-8")
            with patch.object(builder, "CONTAINER_MARKER", marker):
                with patch.dict(os.environ, {"DOCKER_HOST": ""}):
                    self.assertEqual(docker_transport(config), "copy")

    def test_docker_copy_transport_copies_inputs_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            output_dir = tmp_path / "output"
            final_zip = tmp_path / "final.zip"
            input_dir.mkdir()
            output_dir.mkdir()
            (input_dir / "userPrefs.jsonc").write_text("{}\n", encoding="utf-8")
            config = replace(
                load_config(),
                root_dir=tmp_path,
                docker_binary="docker",
                docker_network="none",
                docker_transport="copy",
                docker_cpus="3",
                docker_memory="5g",
                docker_pids_limit=256,
                builder_image="builder:test",
                build_timeout_seconds=123,
            )

            def fake_run(command, **kwargs):
                if command[:2] == ["docker", "create"]:
                    return CompletedProcess(command, 0, stdout="cid123\n", stderr="")
                if command == ["docker", "cp", f"{input_dir.resolve()}/.", "cid123:/work/input"]:
                    return CompletedProcess(command, 0, stdout="", stderr="")
                if command == ["docker", "start", "-a", "cid123"]:
                    return CompletedProcess(command, 0, stdout="build ok\n", stderr="")
                if command == ["docker", "cp", "cid123:/work/output/.", str(output_dir.resolve())]:
                    (output_dir / "produced.zip").write_bytes(b"zip-content")
                    return CompletedProcess(command, 0, stdout="", stderr="")
                if command == ["docker", "rm", "-f", "cid123"]:
                    return CompletedProcess(command, 0, stdout="", stderr="")
                raise AssertionError(f"unexpected command: {command}")

            with patch("meshtastic_builder.builder.subprocess.run", side_effect=fake_run) as run:
                log = run_docker_build(config, test_build(), input_dir, output_dir, final_zip)

            self.assertIn("build ok", log)
            self.assertEqual(final_zip.read_bytes(), b"zip-content")
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][:2], ["docker", "create"])
            self.assertIn("3", commands[0])
            self.assertIn("5g", commands[0])
            self.assertIn("256", commands[0])
            self.assertEqual(commands[-1], ["docker", "rm", "-f", "cid123"])


def captured_command(config, transport):
    """The docker run/create command the worker would issue for one build."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        (output_dir / "produced.zip").write_bytes(b"zip-content")
        config = replace(config, root_dir=tmp_path, docker_transport=transport, builder_image="builder:test")

        def fake_run(command, **kwargs):
            if command[1] == "create":
                return CompletedProcess(command, 0, stdout="cid123\n", stderr="")
            return CompletedProcess(command, 0, stdout="ok", stderr="")

        with patch("meshtastic_builder.builder.subprocess.run", side_effect=fake_run) as run:
            run_docker_build(config, test_build(), input_dir, output_dir, tmp_path / "final.zip")
        return run.call_args_list[0].args[0]


class CompilerCacheTests(unittest.TestCase):
    """ccache rides in a named volume mounted into every builder container."""

    def test_cache_volume_is_mounted_for_both_transports(self):
        config = replace(load_config(), ccache_volume="mb-ccache", ccache_maxsize="20G")
        for transport in ("bind", "copy"):
            with self.subTest(transport=transport):
                command = captured_command(config, transport)
                image_at = command.index("builder:test")
                options = command[:image_at]
                self.assertIn("mb-ccache:/ccache", options)
                self.assertIn("CCACHE_DIR=/ccache", options)
                self.assertIn("CCACHE_MAXSIZE=20G", options)
                # Arguments after the image belong to build-firmware, not docker.
                self.assertEqual(command[image_at + 1 :][:3], ["v-test", "abc123", "tbeam"])

    def test_no_cache_volume_means_no_cache(self):
        config = replace(load_config(), ccache_volume="", ccache_maxsize="20G")
        for transport in ("bind", "copy"):
            with self.subTest(transport=transport):
                command = " ".join(captured_command(config, transport))
                self.assertNotIn("CCACHE", command)
                self.assertNotIn("/ccache", command)

    def test_host_paths_and_bad_sizes_turn_the_cache_off_instead_of_failing(self):
        # A host path would resolve on the daemon's side, which may be remote or
        # rootless; a bad size would make ccache refuse every compile.
        for volume, maxsize in (
            ("/srv/ccache", "20G"),
            ("../ccache", "20G"),
            ("vol:/etc", "20G"),
            ("mb-ccache", "20 GB"),
            ("mb-ccache", "lots"),
        ):
            with self.subTest(volume=volume, maxsize=maxsize):
                config = replace(load_config(), ccache_volume=volume, ccache_maxsize=maxsize)
                self.assertEqual(builder.ccache_docker_args(config), [])

    def test_ccache_sizes_ccache_accepts(self):
        for maxsize in ("20G", "500M", "1.5G", "10Gi", "0"):
            with self.subTest(maxsize=maxsize):
                config = replace(load_config(), ccache_volume="mb-ccache", ccache_maxsize=maxsize)
                self.assertIn(f"CCACHE_MAXSIZE={maxsize}", builder.ccache_docker_args(config))

    def test_the_cache_is_ccache_not_platformio_build_cache(self):
        config = replace(load_config(), ccache_volume="mb-ccache", ccache_maxsize="20G")
        command = " ".join(captured_command(config, "bind"))
        self.assertNotIn("PLATFORMIO_BUILD_CACHE_DIR", command)
        self.assertNotIn("pio-cache", command)

    def test_download_volume_is_mounted_for_both_transports(self):
        config = replace(load_config(), ccache_volume="mb-ccache", pio_download_volume="mb-pio-dl")
        for transport in ("bind", "copy"):
            with self.subTest(transport=transport):
                command = captured_command(config, transport)
                options = command[: command.index("builder:test")]
                self.assertIn("mb-pio-dl:/pio-downloads", options)
                self.assertIn("MB_PIO_DOWNLOAD_DIR=/pio-downloads", options)
                # ccache stays mounted next to it.
                self.assertIn("mb-ccache:/ccache", options)

    def test_download_volume_never_replaces_the_installed_packages(self):
        # ESP32 builds rewrite their installed framework for their own board, so
        # only the download store may be shared, never /opt/platformio itself.
        config = replace(load_config(), pio_download_volume="mb-pio-dl")
        command = " ".join(captured_command(config, "bind"))
        self.assertNotIn(":/opt/platformio", command)
        self.assertNotIn("PLATFORMIO_CORE_DIR", command)

    def test_no_download_volume_and_bad_names_mount_nothing(self):
        for volume in ("", "/srv/pio", "../pio", "vol:/opt/platformio"):
            with self.subTest(volume=volume):
                config = replace(load_config(), pio_download_volume=volume)
                self.assertEqual(builder.pio_download_docker_args(config), [])
                self.assertNotIn("/pio-downloads", " ".join(captured_command(config, "bind")))

    def test_config_reads_the_cache_settings(self):
        with patch.dict(os.environ, {"MB_CCACHE_VOLUME": " mb-ccache ", "MB_CCACHE_MAXSIZE": "5G"}):
            config = load_config()
        self.assertEqual(config.ccache_volume, "mb-ccache")
        self.assertEqual(config.ccache_maxsize, "5G")
        with patch.dict(os.environ, {"MB_PIO_DOWNLOAD_VOLUME": " mb-pio-dl "}):
            self.assertEqual(load_config().pio_download_volume, "mb-pio-dl")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MB_CCACHE_VOLUME", None)
            os.environ.pop("MB_CCACHE_MAXSIZE", None)
            config = load_config()
        self.assertEqual(config.ccache_volume, "")
        self.assertEqual(config.ccache_maxsize, "20G")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MB_PIO_DOWNLOAD_VOLUME", None)
            self.assertEqual(load_config().pio_download_volume, "")


if __name__ == "__main__":
    unittest.main()
