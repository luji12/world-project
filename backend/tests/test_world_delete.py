import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import config
from server import AppHandler, ThreadingHTTPServer


class WorldDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_worlds_dir = config.WORLDS_DIR
        config.WORLDS_DIR = str(Path(self.temp_dir.name) / "worlds")
        Path(config.WORLDS_DIR).mkdir(parents=True, exist_ok=True)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        config.WORLDS_DIR = self.old_worlds_dir
        self.temp_dir.cleanup()

    def _make_world(self, name):
        world_path = Path(config.WORLDS_DIR) / name
        world_path.mkdir(parents=True, exist_ok=True)
        return world_path

    def _post_delete(self, name):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request(
            "POST",
            "/api/worlds/delete",
            body=json.dumps({"name": name}),
            headers={"Content-Type": "application/json"},
        )
        res = conn.getresponse()
        data = json.loads(res.read().decode("utf-8"))
        conn.close()
        return res.status, data

    def test_delete_non_current_world_keeps_current(self):
        self._make_world("alpha")
        self._make_world("beta")
        config.switch_world("alpha")

        status, data = self._post_delete("beta")

        self.assertEqual(status, 200)
        self.assertFalse((Path(config.WORLDS_DIR) / "beta").exists())
        self.assertTrue((Path(config.WORLDS_DIR) / "alpha").exists())
        self.assertEqual(data["current_world"], "alpha")
        self.assertTrue(data["has_world"])
        self.assertEqual(data["worlds_count"], 1)

    def test_delete_current_world_keeps_no_current_when_others_exist(self):
        self._make_world("alpha")
        self._make_world("beta")
        config.switch_world("alpha")

        status, data = self._post_delete("alpha")

        self.assertEqual(status, 200)
        self.assertFalse((Path(config.WORLDS_DIR) / "alpha").exists())
        self.assertTrue((Path(config.WORLDS_DIR) / "beta").exists())
        self.assertEqual(data["current_world"], "")
        self.assertTrue(data["has_world"])
        self.assertEqual(data["worlds_count"], 1)
        self.assertEqual(config.current_world_name(), "")

    def test_delete_last_world_returns_no_world(self):
        self._make_world("alpha")
        config.switch_world("alpha")

        status, data = self._post_delete("alpha")

        self.assertEqual(status, 200)
        self.assertFalse((Path(config.WORLDS_DIR) / "alpha").exists())
        self.assertEqual(data["current_world"], "")
        self.assertFalse(data["has_world"])
        self.assertEqual(data["worlds_count"], 0)

    def test_delete_missing_world_returns_404(self):
        status, data = self._post_delete("missing")

        self.assertEqual(status, 404)
        self.assertIn("不存在", data["error"])


if __name__ == "__main__":
    unittest.main()
