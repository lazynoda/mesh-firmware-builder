import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path

from meshtastic_builder.app import MeshtasticBuilderHandler
from meshtastic_builder.config import load_config
from meshtastic_builder.db import connection, create_build_request, get_build_by_token, utc_now
from meshtastic_builder.queue_eta import DEFAULT_SECONDS, queue_view

FAMILIES = {"nrf52": "nrf52840", "rak4631": "nrf52840", "heltec-v3": "esp32s3", "tbeam": "esp32"}


def temp_config(tmp_path: Path):
    return replace(
        load_config(),
        data_dir=tmp_path,
        db_path=tmp_path / "test.sqlite",
        artifact_dir=tmp_path / "artifacts",
        job_dir=tmp_path / "jobs",
        cache_dir=tmp_path / "cache",
    )


class QueueEtaTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = temp_config(Path(self._tmp.name))
        self.now = utc_now()
        self.minute = 0

    def tearDown(self):
        self._tmp.cleanup()

    def add(self, env, status, *, created_ago_min, started_ago_min=None, duration_min=None):
        row = create_build_request(
            self.config,
            device_id=env,
            platformio_env=env,
            firmware_tag="v2.8.1",
            firmware_sha="a" * 40,
            prefs_jsonc='{"USERPREFS_CONFIG_OWNER_LONG_NAME": "x"}\n',
        )
        created = self.now - timedelta(minutes=created_ago_min)
        started = self.now - timedelta(minutes=started_ago_min) if started_ago_min is not None else None
        finished = started + timedelta(minutes=duration_min) if started and duration_min else None
        with connection(self.config) as conn:
            conn.execute(
                "UPDATE build_requests SET status=?, created_at=?, started_at=?, finished_at=? WHERE id=?",
                (
                    status,
                    created.isoformat(),
                    started.isoformat() if started else None,
                    finished.isoformat() if finished else None,
                    row["id"],
                ),
            )
        return get_build_by_token(self.config, row["public_token"])

    def history(self, env, minutes, status="succeeded"):
        # Finished long ago, so they never count as queued or running.
        for m in minutes:
            self.add(env, status, created_ago_min=1000, started_ago_min=1000, duration_min=m)

    def view(self, row):
        return queue_view(self.config, row, now=self.now, families=FAMILIES)

    def test_finished_builds_have_no_queue(self):
        row = self.add("nrf52", "succeeded", created_ago_min=10, started_ago_min=9, duration_min=7)
        self.assertIsNone(self.view(row))

    def test_alone_in_queue_has_nobody_ahead(self):
        self.history("nrf52", [7])
        row = self.add("nrf52", "queued", created_ago_min=0)
        view = self.view(row)
        self.assertEqual(view["ahead"], 0)
        self.assertEqual(view["remainingSeconds"], 7 * 60)

    def test_counts_running_and_older_queued_but_not_newer(self):
        self.history("nrf52", [7, 6, 8])
        self.history("heltec-v3", [30])
        self.add("heltec-v3", "running", created_ago_min=12, started_ago_min=10)
        self.add("nrf52", "queued", created_ago_min=3)
        mine = self.add("nrf52", "queued", created_ago_min=2)
        self.add("heltec-v3", "queued", created_ago_min=1)
        view = self.view(mine)
        self.assertEqual(view["ahead"], 2)
        # 20 min left on the Heltec, 7 for the nRF52 ahead, 7 for this one.
        self.assertEqual(view["remainingSeconds"], (20 + 7 + 7) * 60)

    def test_same_created_at_orders_by_id_like_the_worker(self):
        self.history("nrf52", [7])
        first = self.add("nrf52", "queued", created_ago_min=2)
        second = self.add("nrf52", "queued", created_ago_min=2)
        self.assertEqual(self.view(first)["ahead"], 0)
        self.assertEqual(self.view(second)["ahead"], 1)

    def test_estimate_is_median_of_successes_only(self):
        self.history("nrf52", [6, 7, 20])
        self.history("nrf52", [1, 1, 1, 1], status="failed")
        row = self.add("nrf52", "queued", created_ago_min=0)
        view = self.view(row)
        self.assertEqual(view["estimateSeconds"], 7 * 60)
        self.assertEqual(view["estimateBasis"], "board")

    def test_expired_builds_still_count_as_history(self):
        self.history("nrf52", [7], status="expired")
        row = self.add("nrf52", "queued", created_ago_min=0)
        self.assertEqual(self.view(row)["estimateSeconds"], 7 * 60)

    def test_unknown_board_falls_back_to_family_then_all_then_default(self):
        row = self.add("rak4631", "queued", created_ago_min=0)
        self.assertEqual(self.view(row)["estimateSeconds"], DEFAULT_SECONDS)
        self.assertEqual(self.view(row)["estimateBasis"], "default")
        self.history("heltec-v3", [30])
        self.assertEqual(self.view(row)["estimateBasis"], "all")
        self.assertEqual(self.view(row)["estimateSeconds"], 30 * 60)
        self.history("nrf52", [7])
        self.assertEqual(self.view(row)["estimateBasis"], "family")
        self.assertEqual(self.view(row)["estimateSeconds"], 7 * 60)

    def test_uses_only_the_latest_samples(self):
        # Ten new 7-minute builds push the old 30-minute ones out of the window.
        for _ in range(10):
            self.add("nrf52", "succeeded", created_ago_min=100, started_ago_min=100, duration_min=7)
        for _ in range(10):
            self.add("nrf52", "succeeded", created_ago_min=2000, started_ago_min=2000, duration_min=30)
        row = self.add("nrf52", "queued", created_ago_min=0)
        self.assertEqual(self.view(row)["estimateSeconds"], 7 * 60)

    def test_running_build_counts_down_and_flags_overrun(self):
        self.history("nrf52", [7])
        row = self.add("nrf52", "running", created_ago_min=5, started_ago_min=3)
        view = self.view(row)
        self.assertEqual(view["ahead"], 0)
        self.assertEqual(view["remainingSeconds"], 4 * 60)
        self.assertFalse(view["overrun"])
        late = self.add("nrf52", "running", created_ago_min=12, started_ago_min=10)
        view = self.view(late)
        self.assertEqual(view["remainingSeconds"], 0)
        self.assertTrue(view["overrun"])

    def test_running_past_its_estimate_contributes_zero_not_negative(self):
        self.history("nrf52", [7])
        self.add("nrf52", "running", created_ago_min=10, started_ago_min=9)
        mine = self.add("nrf52", "queued", created_ago_min=1)
        self.assertEqual(self.view(mine)["remainingSeconds"], 7 * 60)

    def test_stuck_running_build_hides_the_time(self):
        self.history("nrf52", [7])
        self.add("nrf52", "running", created_ago_min=20, started_ago_min=15)
        mine = self.add("nrf52", "queued", created_ago_min=1)
        view = self.view(mine)
        self.assertEqual(view["ahead"], 1)
        self.assertIsNone(view["remainingSeconds"])

    def test_idle_worker_hides_the_time(self):
        self.history("nrf52", [7])
        self.add("nrf52", "queued", created_ago_min=30)
        mine = self.add("nrf52", "queued", created_ago_min=1)
        view = self.view(mine)
        self.assertEqual(view["ahead"], 1)
        self.assertIsNone(view["remainingSeconds"])

    def test_response_has_no_detail_about_other_builds(self):
        self.history("heltec-v3", [30])
        self.add("heltec-v3", "running", created_ago_min=5, started_ago_min=4)
        mine = self.add("nrf52", "queued", created_ago_min=1)
        view = self.view(mine)
        self.assertEqual(set(view), {"ahead", "estimateSeconds", "estimateBasis", "remainingSeconds"})


class RecordingHandler(MeshtasticBuilderHandler):
    def __init__(self, config):  # noqa: D107
        self.config = config
        self.status = None
        self.payload = None

    def json_response(self, payload, status=HTTPStatus.OK):
        self.status = status
        self.payload = payload


class StatusEndpointTests(unittest.TestCase):
    def test_status_endpoint_returns_queue_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = temp_config(Path(tmp))
            row = create_build_request(
                config,
                device_id="nrf52",
                platformio_env="nrf52",
                firmware_tag="v2.8.1",
                firmware_sha="a" * 40,
                prefs_jsonc="{}\n",
            )
            handler = RecordingHandler(config)
            handler.path = f"/api/builds/{row['public_token']}"
            handler.do_GET()
            self.assertEqual(handler.status, HTTPStatus.OK)
            self.assertEqual(handler.payload["queue"]["ahead"], 0)
            self.assertIn("remainingSeconds", handler.payload["queue"])
            self.assertNotIn("prefs", str(handler.payload["queue"]))


if __name__ == "__main__":
    unittest.main()
