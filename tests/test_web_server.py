"""
Unit tests for ui.web_server HTTP endpoints, task tracking, and log streaming.
"""

import json
import pathlib
import threading
import unittest
from unittest.mock import MagicMock, patch

from core.config import MapConfig
from ui.web_server import (
    PRESETS,
    AroundWorldWebHandler,
    TaskState,
    _run_generator_thread,
    current_task,
)


class TestTaskState(unittest.TestCase):
    def setUp(self):
        self.state = TaskState()

    def test_initial_state(self):
        snapshot = self.state.get_snapshot()
        self.assertEqual(snapshot["status"], "idle")
        self.assertEqual(snapshot["progress"], 0)
        self.assertEqual(snapshot["logs"], [])

    def test_start_and_log_progress_inference(self):
        self.state.start("Test Track")
        self.assertEqual(self.state.status, "running")
        self.assertGreaterEqual(self.state.progress, 5)

        # Feed milestone log lines and verify stage and progress advancement
        self.state.add_log("AroundWorldNG — Generating Level: Test Track")
        self.assertGreaterEqual(self.state.progress, 10)

        self.state.add_log("[YandexSatFetcher] Fetching satellite imagery tiles...")
        self.assertGreaterEqual(self.state.progress, 25)

        self.state.add_log("[ElevationFetcher] Fetching elevation grid DEM...")
        self.assertGreaterEqual(self.state.progress, 40)

        self.state.add_log("[OSMFetcher] Fetched 15 roads and 40 buildings")
        self.assertGreaterEqual(self.state.progress, 55)

        self.state.add_log("[RoadCarver] Carving and smoothing road splines...")
        self.assertGreaterEqual(self.state.progress, 75)

        self.state.add_log("[HeightmapProcessor] Saved native Torque3D v9 binary terrain")
        self.assertGreaterEqual(self.state.progress, 85)

        # Snapshot slicing with ?since=
        total_logs = len(self.state.logs)
        self.assertGreater(total_logs, 4)
        snapshot_all = self.state.get_snapshot(since=0)
        self.assertEqual(len(snapshot_all["logs"]), total_logs)

        snapshot_recent = self.state.get_snapshot(since=total_logs - 2)
        self.assertEqual(len(snapshot_recent["logs"]), 2)

    def test_finish_success(self):
        self.state.start("Success Test")
        fake_path = pathlib.Path("build/test_track.zip")
        self.state.finish_success(fake_path, installed=True)

        snapshot = self.state.get_snapshot()
        self.assertEqual(snapshot["status"], "success")
        self.assertEqual(snapshot["progress"], 100)
        self.assertIsNotNone(snapshot["result"])
        self.assertEqual(snapshot["result"]["name"], "test_track.zip")
        self.assertTrue(snapshot["result"]["installed"])

    def test_finish_error(self):
        self.state.start("Fail Test")
        self.state.finish_error("Network timeout")

        snapshot = self.state.get_snapshot()
        self.assertEqual(snapshot["status"], "error")
        self.assertEqual(snapshot["error"], "Network timeout")


class TestPresets(unittest.TestCase):
    def test_presets_structure(self):
        self.assertGreaterEqual(len(PRESETS), 5)
        for p in PRESETS:
            self.assertIn("id", p)
            self.assertIn("name", p)
            self.assertIn("lat", p)
            self.assertIn("lon", p)
            self.assertIn("size", p)
            self.assertIn("title", p)
            self.assertIn("level_name", p)
            self.assertTrue(-90.0 <= p["lat"] <= 90.0)
            self.assertTrue(-180.0 <= p["lon"] <= 180.0)


class TestWebHandlerEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import HTTPServer
        cls.server = HTTPServer(("127.0.0.1", 0), AroundWorldWebHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_index(self):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))
            body = resp.read().decode("utf-8")
            self.assertIn("AroundWorldNG", body)

    def test_get_status(self):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}/api/status"
        with urllib.request.urlopen(url, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("status", data)
            self.assertIn("progress", data)
            self.assertIn("stage", data)
            self.assertIn("logs", data)

    def test_get_presets(self):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}/api/presets"
        with urllib.request.urlopen(url, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIsInstance(data, list)
            self.assertGreaterEqual(len(data), 5)
            self.assertEqual(data[0]["id"], "sochi_autodrom")

    def test_get_geocode_empty_query(self):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}/api/geocode?q="
        with urllib.request.urlopen(url, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data, [])

    def test_post_open_folder(self):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}/api/open_folder"
        payload = json.dumps({"path": "."}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("status", data)

    def test_post_generate_invalid_coordinates(self):
        import urllib.request
        import urllib.error
        url = f"http://127.0.0.1:{self.port}/api/generate"
        payload = json.dumps({"lat": 999.0, "lon": 0.0, "size": 1024}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(ctx.exception.code, 400)

    @patch("ui.web_server.AroundWorldGenerator")
    def test_post_generate_async_and_status_polling(self, mock_gen_class):
        import urllib.request
        import time

        mock_instance = MagicMock()
        mock_instance.generate.return_value = pathlib.Path("build/sochi_test.zip")
        mock_gen_class.return_value = mock_instance

        url_gen = f"http://127.0.0.1:{self.port}/api/generate"
        payload = json.dumps({
            "lat": 43.4056,
            "lon": 39.9547,
            "size": 1024,
            "res": 1025,
            "name": "sochi_test",
            "title": "Sochi Test",
            "install": False
        }).encode("utf-8")
        req = urllib.request.Request(url_gen, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 202)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "started")

        # Poll status until done
        url_status = f"http://127.0.0.1:{self.port}/api/status"
        done = False
        for _ in range(20):
            time.sleep(0.05)
            with urllib.request.urlopen(url_status, timeout=3) as resp:
                st = json.loads(resp.read().decode("utf-8"))
                if st["status"] in {"success", "error"}:
                    done = True
                    self.assertEqual(st["status"], "success")
                    self.assertEqual(st["progress"], 100)
                    self.assertIsNotNone(st["result"])
                    break
        self.assertTrue(done, "Task did not finish within timeout")

    def test_task_state_thread_safety(self):
        state = TaskState()
        threads = []

        def worker(num):
            for i in range(20):
                state.add_log(f"Thread {num} - message {i}")

        for t in range(5):
            th = threading.Thread(target=worker, args=(t,))
            threads.append(th)
            th.start()

        for th in threads:
            th.join()

        snapshot = state.get_snapshot()
        self.assertEqual(len(snapshot["logs"]), 100)


if __name__ == "__main__":
    unittest.main()
