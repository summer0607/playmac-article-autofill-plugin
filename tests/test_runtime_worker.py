import importlib.util
import json
import unittest
from pathlib import Path


WORKER_PATH = Path(__file__).resolve().parents[1] / "runtime" / "playmac_article_worker.py"
SPEC = importlib.util.spec_from_file_location("playmac_article_worker_test", WORKER_PATH)
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


class Response:
    def __init__(self, payload=None, text=""):
        self.payload = payload or {}
        self.text = text
        self.status_code = 200

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class RuntimeWorkerTests(unittest.TestCase):
    def test_qianfan_login_switches_to_account_form(self):
        class Locator:
            def __init__(self, page, kind):
                self.page = page
                self.kind = kind

            def count(self):
                return 1

            def nth(self, _index):
                return self

            def is_visible(self):
                return self.kind in {"account", "button"} or self.page.account_mode

            def is_checked(self):
                return self.page.agreement_checked

            def check(self, force=False):
                self.page.agreement_checked = force

            def click(self):
                if self.kind == "account":
                    self.page.account_mode = True
                if self.kind == "button":
                    self.page.submitted = True

            def fill(self, value):
                self.page.values[self.kind] = value

        class Page:
            def __init__(self):
                self.account_mode = False
                self.agreement_checked = False
                self.submitted = False
                self.values = {}

            def locator(self, selector):
                if "checkbox" in selector:
                    return Locator(self, "agreement")
                return Locator(self, "email" if "邮箱" in selector else "password")

            def get_by_text(self, _text, exact=False):
                return Locator(self, "account")

            def get_by_role(self, _role, name=None):
                return Locator(self, "button")

            def wait_for_timeout(self, _timeout):
                return None

        page = Page()
        WORKER.submit_qianfan_login_form(page, "user@example.com", "secret")
        self.assertTrue(page.account_mode)
        self.assertTrue(page.agreement_checked)
        self.assertTrue(page.submitted)
        self.assertEqual(page.values, {"email": "user@example.com", "password": "secret"})

    def test_qianfan_login_reports_password_mismatch(self):
        class Body:
            def inner_text(self):
                return "邮箱密码不匹配，请检查邮箱密码是否正确"

        class Page:
            def locator(self, _selector):
                return Body()

        self.assertIn("邮箱或密码不正确", WORKER.qianfan_login_error(Page()))

    def test_rejects_unrelated_source(self):
        with self.assertRaises(WORKER.WorkerError):
            WORKER.parse_source("https://example.com/article")

    def test_steam_body_keeps_game_format(self):
        def fake_request(url, **_kwargs):
            return Response({
                "620": {"data": {
                    "name": "Portal 2",
                    "short_description": "一款动作冒险游戏。",
                    "header_image": "https://cdn.example/cover.jpg",
                    "screenshots": [{"path_full": "https://cdn.example/shot.jpg"}],
                    "genres": [{"description": "Action"}],
                    "supported_languages": "English, 简体中文",
                    "mac_requirements": {"minimum": "macOS 10.15"},
                }}
            })

        original = WORKER.request
        WORKER.request = fake_request
        try:
            article = WORKER.import_steam("620", "/tmp/unused", skip_images=True)
        finally:
            WORKER.request = original
        self.assertLess(article["content"].index("经验建议"), article["content"].index("配置要求"))
        self.assertLess(article["content"].index("配置要求"), article["content"].index("安装方法"))
        self.assertIn("游戏截图", article["content"])
        self.assertNotIn("软件介绍", article["content"])

    def test_macked_body_keeps_software_format(self):
        document = """
        <html><head>
        <meta property='og:title' content='IINA Plus 0.8.30 开源软件 - IINA弹幕播放增强'>
        <meta property='og:description' content='IINA 是一款现代 macOS 视频播放器。'>
        <meta property='og:image' content='https://macked.app/cover.jpg'>
        </head><body><img src='https://macked.app/preview.jpg'></body></html>
        """
        original = WORKER.request
        WORKER.request = lambda *_args, **_kwargs: Response(text=document)
        try:
            article = WORKER.import_macked("https://macked.app/iina-plus.html", "/tmp/unused", skip_images=True)
        finally:
            WORKER.request = original
        self.assertTrue(article["title"].startswith("IINA Plus For Mac v0.8.30"))
        self.assertEqual(article["categories"], ["影音播放"])
        self.assertLess(article["content"].index("常见问题"), article["content"].index("激活方式"))
        self.assertLess(article["content"].index("激活方式"), article["content"].index("功能介绍"))
        self.assertNotIn("游戏截图", article["content"])

    def test_qianfan_session_requires_cookie(self):
        path = Path("/tmp/playmac-runtime-test-session.json")
        path.write_text(json.dumps({}), encoding="utf-8")
        with self.assertRaises(WORKER.WorkerError):
            WORKER.load_session(path)
        path.unlink()

    def test_failed_login_does_not_replace_session(self):
        source = Path(WORKER_PATH).read_text(encoding="utf-8")
        self.assertLess(source.index("verify_qianfan(cookie)", source.index("def login")), source.index("Path(session_path).write_text", source.index("def login")))

    def test_login_does_not_trust_initial_picture_space_url(self):
        source = Path(WORKER_PATH).read_text(encoding="utf-8")
        login_source = source[source.index("def login"):source.index("def main")]
        self.assertNotIn('"pictureSpace" not in page.url', login_source)
        self.assertIn("qianfan_picture_space_ready(page)", login_source)


if __name__ == "__main__":
    unittest.main()
