import importlib.util
import json
import tempfile
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
    STEAM_LANGUAGE_TABLE = """
    <table class="game_language_options">
      <tr><th></th><th>界面</th><th>完全音频</th><th>字幕</th></tr>
      <tr><td>简体中文</td><td><span>&#10004;</span></td><td></td><td><span>&#10004;</span></td></tr>
      <tr><td>英语</td><td><span>&#10004;</span></td><td><span>&#10004;</span></td><td><span>&#10004;</span></td></tr>
      <tr><td>日语</td><td><span>&#10004;</span></td><td><span>&#10004;</span></td><td></td></tr>
    </table>
    """

    def test_image_sources_ignore_query_duplicates(self):
        sources = WORKER.unique_image_sources([
            "https://cdn.example/image.jpg?t=1",
            "https://cdn.example/image.jpg?t=2",
            "https://cdn.example/other.jpg",
        ])
        self.assertEqual(sources, ["https://cdn.example/image.jpg?t=1", "https://cdn.example/other.jpg"])

    def test_image_fingerprint_index_reuses_existing_qianfan_link(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.jpg"
            second = Path(directory) / "second.png"
            first.write_bytes(b"same-image-content")
            second.write_bytes(b"same-image-content")
            unique_files = WORKER.deduplicate_image_files([first, second])
            self.assertEqual(unique_files, [first])
            fingerprint = WORKER.image_fingerprint(first)
            index_path = Path(directory) / "qianfan-image-index.json"
            link = "https://qimg.xiaohongshu.com/arkgoods/existing"
            WORKER.save_qianfan_image_index(index_path, {fingerprint: link})
            self.assertEqual(WORKER.load_qianfan_image_index(index_path)[fingerprint], link)
            self.assertEqual(index_path.stat().st_mode & 0o777, 0o600)

    def test_upload_images_returns_indexed_link_without_browser_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            session_path = Path(directory) / "qianfan-session.json"
            image_path = Path(directory) / "cover.jpg"
            image_path.write_bytes(b"already-uploaded-image")
            fingerprint = WORKER.image_fingerprint(image_path)
            link = "https://qimg.xiaohongshu.com/arkgoods/existing"
            WORKER.save_qianfan_image_index(session_path.with_name("qianfan-image-index.json"), {fingerprint: link})

            class ImageResponse:
                status_code = 200
                content = b"image"

            original_load_session = WORKER.load_session
            original_verify = WORKER.verify_qianfan
            original_folder = WORKER.qianfan_folder
            original_find_link = WORKER.qianfan_find_link
            original_get = WORKER.requests.get
            WORKER.load_session = lambda _path: "cookie"
            WORKER.verify_qianfan = lambda _cookie: None
            WORKER.qianfan_folder = lambda _cookie, _folder: "folder-id"
            WORKER.qianfan_find_link = lambda *_args: self.fail("已有内容指纹时不应查询或上传千帆图片")
            WORKER.requests.get = lambda *_args, **_kwargs: ImageResponse()
            try:
                self.assertEqual(WORKER.upload_images(session_path, [image_path]), [link])
            finally:
                WORKER.load_session = original_load_session
                WORKER.verify_qianfan = original_verify
                WORKER.qianfan_folder = original_folder
                WORKER.qianfan_find_link = original_find_link
                WORKER.requests.get = original_get

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
            if "/app/620/" in url:
                return Response(text=self.STEAM_LANGUAGE_TABLE)
            return Response({
                "620": {"data": {
                    "name": "Portal 2",
                    "short_description": "一款动作冒险游戏。",
                    "header_image": "https://cdn.example/cover.jpg",
                    "screenshots": [{"path_full": f"https://cdn.example/shot-{index}.jpg"} for index in range(7)],
                    "genres": [{"description": "Action"}],
                    "supported_languages": "English, 简体中文",
                    "release_date": {"date": "2026 年 2 月 27 日"},
                    "mac_requirements": {"minimum": "macOS 10.15"},
                }}
            })

        original = WORKER.request
        original_store_page = WORKER.steam_store_page
        WORKER.request = fake_request
        WORKER.steam_store_page = lambda _app_id: self.STEAM_LANGUAGE_TABLE
        try:
            article = WORKER.import_steam("620", "/tmp/unused", skip_images=True)
        finally:
            WORKER.request = original
            WORKER.steam_store_page = original_store_page
        expected_sections = ["一款动作冒险游戏。", "发行日期：2026 年 2 月 27 日", "经验建议", "注意事项", "安装方法", "常见问题", "关于游戏", "游戏截图"]
        positions = [article["content"].index(section) for section in expected_sections]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Macs Fan Control", article["content"])
        self.assertIn("【其他说明】", article["content"])
        self.assertIn("2025年9月25日后发布的游戏内置了“CE修改器”", article["content"])
        self.assertNotIn("配置要求", article["content"])
        self.assertNotIn("软件介绍", article["content"])
        self.assertEqual(len(article["image_urls"]), 6)
        self.assertEqual(article["content"].count("https://cdn.example/shot-"), 5)
        languages = next(item["desc"] for item in article["resource_info"] if item["title"] == "资源语言")
        self.assertEqual(languages, "简体中文、英语")

    def test_steam_downloads_uploads_and_inserts_five_screenshots(self):
        screenshots = [{"path_full": f"https://cdn.example/shot-{index}.jpg"} for index in range(8)]

        def fake_request(url, **_kwargs):
            if "/app/730/" in url:
                return Response(text=self.STEAM_LANGUAGE_TABLE)
            return Response({"730": {"data": {
                "name": "Test Game",
                "short_description": "简介",
                "header_image": "https://cdn.example/cover.jpg",
                "screenshots": screenshots,
                "genres": [],
                "release_date": {"date": "2026 年 8 月 16 日"},
                "mac_requirements": {"minimum": "macOS 12"},
            }}})

        with tempfile.TemporaryDirectory() as directory:
            staged = []

            def fake_download(url, filename, _referer):
                path = Path(directory) / f"{filename}.jpg"
                path.write_bytes(url.encode("utf-8"))
                staged.append(path)
                return path

            def fake_upload(_session_path, paths):
                self.assertEqual(len(paths), 6)
                return [f"https://qimg.xiaohongshu.com/arkgoods/uploaded-{index}" for index in range(6)]

            original_request = WORKER.request
            original_store_page = WORKER.steam_store_page
            original_download = WORKER.download_image
            original_upload = WORKER.upload_images
            WORKER.request = fake_request
            WORKER.steam_store_page = lambda _app_id: self.STEAM_LANGUAGE_TABLE
            WORKER.download_image = fake_download
            WORKER.upload_images = fake_upload
            try:
                article = WORKER.import_steam("730", "/tmp/session")
            finally:
                WORKER.request = original_request
                WORKER.steam_store_page = original_store_page
                WORKER.download_image = original_download
                WORKER.upload_images = original_upload

        self.assertEqual(len(staged), 6)
        self.assertEqual(len(article["image_urls"]), 6)
        self.assertEqual(article["content"].count("https://qimg.xiaohongshu.com/arkgoods/uploaded-"), 6)
        screenshot_section = article["content"].split("游戏截图</h2>", 1)[1]
        self.assertEqual(screenshot_section.count("<img "), 5)

    def test_steam_about_game_cannot_break_screenshot_section(self):
        content = WORKER.game_body(
            {"short_description": "简介", "detailed_description": "<div>" + ("介绍" * 2000)},
            "测试游戏",
            "Test Game",
            "https://qimg.xiaohongshu.com/cover",
            [f"https://qimg.xiaohongshu.com/shot-{index}" for index in range(5)],
        )
        self.assertEqual(content.split("游戏截图</h2>", 1)[1].count("<img "), 5)
        self.assertNotIn("<div>", content)

    def test_steam_body_keeps_required_sections_without_optional_data(self):
        content = WORKER.game_body({"short_description": "简介"}, "测试游戏", "Test Game", "", [])
        self.assertIn("发行日期：待填写", content)
        self.assertIn("Steam 暂未提供更多游戏介绍。", content)
        self.assertIn("Steam 暂未提供游戏截图。", content)

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
        start = source.index("def login(session_path")
        self.assertLess(source.index("verify_qianfan(cookie)", start), source.index("save_qianfan_session(session_path, cookie)", start))

    def test_login_does_not_trust_initial_picture_space_url(self):
        source = Path(WORKER_PATH).read_text(encoding="utf-8")
        login_source = source[source.index("def login(session_path"):source.index("def main")]
        self.assertNotIn('"pictureSpace" not in page.url', login_source)
        self.assertIn("qianfan_picture_space_ready(page)", login_source)


if __name__ == "__main__":
    unittest.main()
