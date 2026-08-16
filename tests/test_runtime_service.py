import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from service import runtime_server


class RuntimeServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.jobs = Path(self.temporary.name) / "jobs"
        self.session = Path(self.temporary.name) / "qianfan-session.json"
        self.qr_state = Path(self.temporary.name) / "qianfan-qr-login.json"
        self.jobs.mkdir()
        self.jobs_patch = mock.patch.object(runtime_server, "JOBS_DIR", self.jobs)
        self.session_patch = mock.patch.object(runtime_server, "SESSION_FILE", self.session)
        self.qr_state_patch = mock.patch.object(runtime_server, "QR_STATE_FILE", self.qr_state)
        self.jobs_patch.start()
        self.session_patch.start()
        self.qr_state_patch.start()

    def tearDown(self):
        self.jobs_patch.stop()
        self.session_patch.stop()
        self.qr_state_patch.stop()
        self.temporary.cleanup()

    def test_authorization_is_optional_for_local_service(self):
        with mock.patch.object(runtime_server, "TOKEN", ""):
            self.assertTrue(runtime_server.authorized(""))
        with mock.patch.object(runtime_server, "TOKEN", "secret"):
            self.assertTrue(runtime_server.authorized("Bearer secret"))
            self.assertFalse(runtime_server.authorized("Bearer wrong"))

    def test_background_job_persists_result(self):
        payload = {"kind": "steam", "title": "Example"}
        with mock.patch.object(runtime_server, "execute_import", return_value=payload):
            job_id = runtime_server.start_import("https://store.steampowered.com/app/123456/")
            path = self.jobs / f"{job_id}.json"
            for _ in range(50):
                result = json.loads(path.read_text(encoding="utf-8"))
                if result.get("status") == "complete":
                    break
                time.sleep(0.01)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["payload"], payload)

    def test_qr_login_state_is_private_and_persistent(self):
        runtime_server.update_qr_state({"status": "waiting", "qr_image": "data:image/png;base64,example"})
        result = json.loads(self.qr_state.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(self.qr_state.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
