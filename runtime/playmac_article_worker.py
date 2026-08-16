#!/usr/bin/env python3
"""Self-contained worker for the PlayMac WordPress article importer."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests


QIANFAN_URL = "https://ark.xiaohongshu.com/app-system/pictureSpace?from=ark-login"
QIANFAN_API = "https://ark.xiaohongshu.com/api/edith/product/material_space"
QIANFAN_USAGE_API = f"{QIANFAN_API}/get_seller_space_usage"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/139 Safari/537.36"
GAME_CATEGORIES = (
    ("模拟经营", ("simulation", "management", "tycoon", "farming", "life sim", "模拟", "经营")),
    ("策略塔防", ("strategy", "tactical", "turn-based", "4x", "策略", "塔防")),
    ("角色扮演", ("rpg", "role-playing", "角色扮演")),
    ("射击游戏", ("shooter", "fps", "射击")),
    ("恐怖悬疑", ("horror", "恐怖")),
    ("末世生存", ("survival", "生存")),
    ("竞技竞速", ("racing", "sports", "竞速", "赛车", "体育")),
    ("益智解谜", ("puzzle", "解谜", "益智")),
    ("音乐节奏", ("music", "rhythm", "音乐", "节奏")),
    ("棋牌桌游", ("board game", "card game", "桌游", "棋牌", "卡牌")),
    ("多人合作", ("co-op", "multiplayer", "合作", "多人")),
    ("休闲娱乐", ("casual", "休闲")),
    ("动作冒险", ("action", "adventure", "rogue", "动作", "冒险", "肉鸽")),
)
SOFTWARE_CATEGORIES = (
    (("video editing", "视频编辑"), "视频剪辑"),
    (("video player", "music player", "视频播放", "音乐播放"), "影音播放"),
    (("screen recording", "screenshot", "屏幕录像", "屏幕截图"), "截图录像"),
    (("audio", "音频编辑"), "音频编辑"),
    (("image", "photo", "graphic", "图像处理", "图片浏览", "图形设计"), "图片处理"),
    (("clean", "optimiz", "系统清理", "系统优化"), "清理优化"),
    (("browser", "network", "网络连接", "浏览器"), "网络连接"),
    (("developer", "coding", "编程"), "编程工具"),
    (("office", "pdf", "办公", "文档"), "办公软件"),
    (("download", "下载"), "下载工具"),
)
GAME_ARTICLE_COMMON_HTML = Path(__file__).with_name("game_article_common.html").read_text(encoding="utf-8").strip()


class WorkerError(RuntimeError):
    pass


def unique(values, limit=8):
    result, seen = [], set()
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" ,，|｜")
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
        if len(result) >= limit:
            break
    return result


def clean_text(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def unique_image_sources(values, limit=8):
    result, seen = [], set()
    for value in values:
        source = str(value or "").strip()
        if not source:
            continue
        parsed = urlparse(source)
        key = (parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, parsed.params)
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
        if len(result) >= limit:
            break
    return result


def image_fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deduplicate_image_files(paths):
    result, seen = [], set()
    for path in paths:
        fingerprint = image_fingerprint(path)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(Path(path))
    return result


def load_qianfan_image_index(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    images = data.get("images") if isinstance(data, dict) else None
    if not isinstance(images, dict):
        return {}
    return {str(key): str(value) for key, value in images.items() if re.fullmatch(r"[a-f0-9]{64}", str(key)) and re.match(r"^https://qimg\.xiaohongshu\.com/", str(value))}


def save_qianfan_image_index(path, images):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps({"version": 1, "images": images}, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(output)


def parse_source(value):
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if host in {"store.steampowered.com", "www.store.steampowered.com"}:
        match = re.search(r"/app/(\d{2,10})(?:/|$)", parsed.path)
        if match:
            return "steam", match.group(1)
    if host in {"macked.app", "www.macked.app"} and parsed.path.lower().endswith(".html"):
        return "macked", parsed.geturl()
    raise WorkerError("仅支持 Steam 游戏商店链接或 Macked 软件介绍链接")


def request(url, *, referer="", timeout=30):
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if referer:
        headers["Referer"] = referer
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


def load_session(path):
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise WorkerError("千帆尚未登录，请在插件设置中完成登录")
    except OSError as exc:
        raise WorkerError("千帆登录状态无法读取，请重新登录") from exc
    try:
        value = json.loads(raw)
        cookie = str(value.get("cookie") or "").strip()
    except json.JSONDecodeError:
        cookie = raw
    if not cookie:
        raise WorkerError("千帆尚未登录，请在插件设置中完成登录")
    return cookie


def qianfan_headers(cookie, content_type=False):
    headers = {
        "User-Agent": USER_AGENT,
        "Cookie": cookie,
        "Origin": "https://ark.xiaohongshu.com",
        "Referer": QIANFAN_URL,
        "Accept": "application/json, text/plain, */*",
    }
    if content_type:
        headers["Content-Type"] = "application/json;charset=UTF-8"
    return headers


def verify_qianfan(cookie):
    response = requests.get(QIANFAN_USAGE_API, headers=qianfan_headers(cookie), timeout=20)
    try:
        data = response.json()
    except ValueError as exc:
        raise WorkerError("千帆登录检查失败，请重新登录") from exc
    if response.status_code != 200 or data.get("code") != 0 or not data.get("success"):
        raise WorkerError("千帆登录已失效，请在插件设置中重新登录")


def playwright_cookies(cookie):
    result = []
    for item in cookie.split(";"):
        if "=" not in item:
            continue
        name, value = item.strip().split("=", 1)
        if name:
            result.append({"name": name, "value": value, "domain": ".xiaohongshu.com", "path": "/", "secure": True})
    return result


def first_visible(locator):
    for index in range(locator.count()):
        candidate = locator.nth(index)
        if candidate.is_visible():
            return candidate
    return None


def submit_qianfan_login_form(page, email, password):
    email_locator = page.locator('input[placeholder*="邮箱"], input[type="email"], input[name*="email" i]')
    email_input = first_visible(email_locator)
    if email_input is None:
        account_login = first_visible(page.get_by_text("账号登录", exact=True))
        if account_login is None:
            raise WorkerError("千帆账号登录入口未找到，请稍后重试")
        account_login.click()
        page.wait_for_timeout(300)
        email_input = first_visible(email_locator)
    password_input = first_visible(page.locator('input[placeholder*="密码"], input[type="password"]'))
    login_button = first_visible(page.get_by_role("button", name=re.compile(r"登\s*[录陸]|登入")))
    if email_input is None or password_input is None or login_button is None:
        raise WorkerError("千帆账号登录表单未加载完成，请稍后重试")
    email_input.fill(email)
    password_input.fill(password)
    agreement = first_visible(page.locator('input[type="checkbox"]'))
    if agreement is not None and not agreement.is_checked():
        agreement.check(force=True)
    login_button.click()


def qianfan_login_error(page):
    try:
        page_text = page.locator("body").inner_text()
    except Exception:
        return ""
    messages = (
        ("邮箱密码不匹配", "千帆邮箱或密码不正确，请确认千帆账号后重试"),
        ("账号或密码错误", "千帆邮箱或密码不正确，请确认千帆账号后重试"),
        ("密码错误", "千帆邮箱或密码不正确，请确认千帆账号后重试"),
        ("安全验证", "千帆要求完成安全验证，账号密码登录暂时无法完成"),
        ("验证码", "千帆要求完成验证码，账号密码登录暂时无法完成"),
    )
    for marker, message in messages:
        if marker in page_text:
            return message
    return ""


def qianfan_login_form_ready(page):
    email = first_visible(page.locator('input[placeholder*="邮箱"], input[type="email"], input[name*="email" i]'))
    account_login = first_visible(page.get_by_text("账号登录", exact=True))
    return email is not None or account_login is not None


def qianfan_picture_space_ready(page):
    return first_visible(page.get_by_text("上传本地图片", exact=True)) is not None


def context_cookie_header(context):
    cookies = context.cookies([
        "https://ark.xiaohongshu.com",
        "https://customer.xiaohongshu.com",
        "https://xiaohongshu.com",
    ])
    return "; ".join(f"{item['name']}={item['value']}" for item in cookies)


def save_qianfan_session(session_path, cookie):
    path = Path(session_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"cookie": cookie, "updated_at": int(time.time())}), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def visible_qr_image(page):
    images = page.locator('img[src^="data:image/png;base64,"]')
    for index in range(images.count()):
        image = images.nth(index)
        if not image.is_visible():
            continue
        dimensions = image.evaluate("element => [element.naturalWidth, element.naturalHeight]")
        if dimensions and min(dimensions) >= 150:
            return str(image.get_attribute("src") or "")
    return ""


def login_with_qr(session_path, update_state, timeout=180):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WorkerError("插件图片组件未初始化，请先初始化") from exc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, user_agent=USER_AGENT)
        page = context.new_page()
        try:
            page.goto(QIANFAN_URL, wait_until="domcontentloaded", timeout=60000)
            for _ in range(60):
                if qianfan_login_form_ready(page):
                    break
                page.wait_for_timeout(250)
            else:
                raise WorkerError("千帆扫码登录入口暂时无法打开")
            switch = first_visible(page.locator(".beer-login-container img"))
            if switch is None:
                raise WorkerError("千帆扫码登录入口未找到")
            switch.click()
            qr_image = ""
            for _ in range(40):
                page.wait_for_timeout(250)
                qr_image = visible_qr_image(page)
                if qr_image:
                    break
            if not qr_image:
                raise WorkerError("千帆登录二维码未生成，请重新获取")
            update_state({"status": "waiting", "message": "请使用小红书 APP 扫码并确认登录", "qr_image": qr_image})
            deadline = time.time() + timeout
            last_cookie = ""
            last_qr_image = qr_image
            while time.time() < deadline:
                page.wait_for_timeout(500)
                cookie = context_cookie_header(context)
                if cookie and cookie != last_cookie:
                    last_cookie = cookie
                    try:
                        verify_qianfan(cookie)
                    except WorkerError:
                        pass
                    else:
                        save_qianfan_session(session_path, cookie)
                        update_state({"status": "success", "message": "千帆扫码登录成功"})
                        return {"message": "千帆扫码登录成功"}
                page_text = page.locator("body").inner_text()
                if "二维码已失效" in page_text or "二维码失效" in page_text:
                    raise WorkerError("千帆登录二维码已失效，请重新获取")
                current_qr_image = visible_qr_image(page)
                if current_qr_image and current_qr_image != last_qr_image:
                    last_qr_image = current_qr_image
                    update_state({"status": "waiting", "message": "二维码已刷新，请使用小红书 APP 扫码", "qr_image": current_qr_image})
            raise WorkerError("千帆扫码登录已超时，请重新获取二维码")
        finally:
            browser.close()


def qianfan_folder(cookie, folder):
    payload = {"filter": {"keyword": "", "statuses": [1], "basicTypes": [1], "fatherDirectoryId": -1}, "pageIndex": 1, "pageSize": 50, "option": {"withDetail": True}}
    response = requests.post(f"{QIANFAN_API}/search_directory_manageable", headers=qianfan_headers(cookie, True), json=payload, timeout=30)
    response.raise_for_status()
    for item in (response.json().get("data") or {}).get("directoryManageables", []):
        if item.get("name") == folder:
            return str(item.get("id"))
    raise WorkerError("千帆中未找到 PlayMac 图片目录")


def qianfan_find_link(cookie, folder_id, filename):
    payload = {"filter": {"keyword": Path(filename).stem, "statuses": [1], "basicTypes": [2], "fatherDirectoryId": folder_id}, "order": {"orderList": [{"field": "createTime", "asc": False}]}, "pageIndex": 1, "pageSize": 100, "option": {"withDetail": True}}
    response = requests.post(f"{QIANFAN_API}/search_directory_manageable", headers=qianfan_headers(cookie, True), json=payload, timeout=30)
    response.raise_for_status()
    for item in (response.json().get("data") or {}).get("directoryManageables", []):
        if item.get("name") not in {filename, Path(filename).stem}:
            continue
        data = item.get("additionalData") or {}
        if data.get("link"):
            return str(data["link"])
        try:
            uploader = data.get("uploaderInfoModel") or {}
            uploader = json.loads(uploader) if isinstance(uploader, str) else uploader
            return str(uploader.get("url") or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return ""


def download_image(url, filename, referer):
    response = request(url, referer=referer, timeout=60)
    content_type = response.headers.get("Content-Type", "").lower()
    if not content_type.startswith("image/") or not response.content:
        raise WorkerError("来源图片不是有效图片")
    suffix = Path(urlparse(url).path).suffix.lower()
    suffix = suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
    output = Path(tempfile.mkdtemp(prefix="playmac-import-")) / f"{filename}{suffix}"
    output.write_bytes(response.content)
    return output


def qianfan_image_available(link):
    if not re.match(r"^https://qimg\.xiaohongshu\.com/", str(link or "")):
        return False
    try:
        check = requests.get(link, headers={"User-Agent": USER_AGENT, "Referer": "https://ark.xiaohongshu.com/"}, timeout=30)
    except requests.RequestException:
        return False
    return check.status_code == 200 and bool(check.content)


def upload_images(session_path, images, folder="PlayMac"):
    cookie = load_session(session_path)
    verify_qianfan(cookie)
    folder_id = qianfan_folder(cookie, folder)
    index_path = Path(session_path).with_name("qianfan-image-index.json")
    image_index = load_qianfan_image_index(index_path)
    image_paths = deduplicate_image_files(images)
    results = [""] * len(image_paths)
    pending = []
    for position, path in enumerate(image_paths):
        fingerprint = image_fingerprint(path)
        filename = f"sha256-{fingerprint}{path.suffix.lower()}"
        link = image_index.get(fingerprint, "")
        if not qianfan_image_available(link):
            image_index.pop(fingerprint, None)
            link = qianfan_find_link(cookie, folder_id, filename)
        if not link and path.name != filename:
            link = qianfan_find_link(cookie, folder_id, path.name)
        if qianfan_image_available(link):
            image_index[fingerprint] = link
            save_qianfan_image_index(index_path, image_index)
            results[position] = link
        else:
            pending.append((position, path, fingerprint, filename))
    if not pending:
        return results
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WorkerError("插件图片组件未初始化，请先在设置中初始化") from exc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
        context.add_cookies(playwright_cookies(cookie))
        page = context.new_page()
        page.goto(QIANFAN_URL, wait_until="domcontentloaded", timeout=60000)
        page.get_by_text("上传本地图片", exact=True).wait_for(state="visible", timeout=30000)
        page.get_by_text(folder, exact=True).first.click()
        page.wait_for_timeout(800)
        for position, path, fingerprint, filename in pending:
            page.get_by_text("上传本地图片", exact=True).click()
            picker = page.locator('input[type="file"]')
            upload_path = path.with_name(filename)
            if upload_path != path:
                shutil.copyfile(path, upload_path)
            picker.set_input_files(str(upload_path))
            page.get_by_text("本次共成功上传1个文件", exact=True).wait_for(state="visible", timeout=60000)
            close = page.get_by_text("关闭", exact=True)
            if close.count():
                close.click()
            link = ""
            for _ in range(12):
                link = qianfan_find_link(cookie, folder_id, filename)
                if link:
                    break
                page.wait_for_timeout(500)
            if not re.match(r"^https://qimg\.xiaohongshu\.com/", link or ""):
                raise WorkerError("千帆图片上传后未返回可用外链")
            if not qianfan_image_available(link):
                raise WorkerError("千帆图片外链校验失败")
            image_index[fingerprint] = link
            save_qianfan_image_index(index_path, image_index)
            results[position] = link
        browser.close()
    return results


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.images, self.text, self.in_title = {}, [], [], False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key.lower()] = values["content"]
        if tag == "img" and values.get("src"):
            self.images.append(values["src"])
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())


def pick_chinese_name(app_id, fallback):
    try:
        data = request(f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=cn&l=schinese").json()
        info = data.get(str(app_id), {}).get("data") or {}
        value = clean_text(info.get("name"))
        return value if re.search(r"[\u4e00-\u9fff]", value) else fallback
    except Exception:
        return fallback


def game_category(genres, description):
    source = " ".join([*genres, description]).lower()
    for name, aliases in GAME_CATEGORIES:
        if any(alias.lower() in source for alias in aliases):
            return name
    return "动作冒险"


def game_body(info, chinese_name, english_name, cover, screenshots):
    description = html.escape(clean_text(info.get("short_description")) or f"{chinese_name} 是一款 Mac 游戏。")
    detailed = str(info.get("detailed_description") or "")[:3000]
    detailed = re.sub(r'<h1\b[^>]*>\s*关于游戏\s*</h1>', "", detailed, count=1, flags=re.I)
    release_date = html.escape(clean_text((info.get("release_date") or {}).get("date")) or "待填写")
    pieces = []
    if cover:
        pieces.extend(["<!-- playmac-game-cover:start -->", f'<p><img decoding="async" src="{cover}" alt="{html.escape(chinese_name, quote=True)}" /></p>', "<!-- playmac-game-cover:end -->"])
    pieces.extend([
        f"<p>{description}</p>",
        f"<p>发行日期：{release_date}</p>",
        "&nbsp;",
        "&nbsp;",
        GAME_ARTICLE_COMMON_HTML,
        '<h2><a id="%E5%85%B3%E4%BA%8E%E6%B8%B8%E6%88%8F" class="anchor" aria-hidden="true"></a>关于游戏</h2>',
        detailed or "<p>Steam 暂未提供更多游戏介绍。</p>",
        '<h2><a id="%E6%B8%B8%E6%88%8F%E6%88%AA%E5%9B%BE" class="anchor" aria-hidden="true"></a>游戏截图</h2>',
    ])
    screenshots = unique_image_sources(screenshots)
    if screenshots:
        pieces.extend(f'<p><img decoding="async" src="{url}" alt="" /></p>' for url in screenshots)
    else:
        pieces.append("<p>Steam 暂未提供游戏截图。</p>")
    return "\n".join(pieces)


def import_steam(app_id, session_path, skip_images=False):
    response = request(f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=cn&l=schinese").json()
    info = response.get(str(app_id), {}).get("data") or {}
    if not info.get("name"):
        raise WorkerError("Steam 没有返回可用的游戏资料")
    english_name = clean_text(info.get("name"))
    chinese_name = pick_chinese_name(app_id, english_name)
    image_urls = unique_image_sources([str(info.get("header_image") or ""), *(str(item.get("path_full") or "") for item in (info.get("screenshots") or [])[:6])], 7)
    if not image_urls:
        raise WorkerError("Steam 没有提供可用图片")
    if skip_images:
        cover, screenshots = image_urls[0], image_urls[1:]
    else:
        staged = [download_image(url, f"steam-{app_id}-{index}", "https://store.steampowered.com/") for index, url in enumerate(image_urls)]
        try:
            uploaded = upload_images(session_path, staged)
        finally:
            for path in staged:
                shutil.rmtree(path.parent, ignore_errors=True)
        cover, screenshots = uploaded[0], uploaded[1:]
    genres = [clean_text(item.get("description")) for item in info.get("genres") or []]
    category = game_category(genres, str(info.get("short_description") or ""))
    languages = clean_text(info.get("supported_languages")) or "待填写"
    mac_raw = clean_text((info.get("mac_requirements") or {}).get("minimum"))
    chip = "✅M系列｜✅Intel" if "Apple Silicon" not in mac_raw else "✅M系列｜❌intel"
    version = "待填写"
    title = f"{chinese_name} Mac版 {english_name} For Mac v{version}|中文原生版"
    return {"kind": "steam", "source_url": f"https://store.steampowered.com/app/{app_id}/", "title": title, "excerpt": clean_text(info.get("short_description")), "content": game_body(info, chinese_name, english_name, cover, screenshots), "categories": ["Mac游戏", category], "tags": unique([*genres, chinese_name, english_name]), "resource_info": [{"title": "资源版本", "desc": version}, {"title": "资源大小", "desc": "待填写"}, {"title": "资源类型", "desc": "原生版"}, {"title": "资源语言", "desc": languages}, {"title": "支持芯片", "desc": chip}, {"title": "系统要求", "desc": mac_raw or "macOS 10.15 及以上"}], "price": None, "seo": {"title": title, "keywords": ",".join(unique([chinese_name, english_name, *genres], 5)), "description": clean_text(info.get("short_description"))[:180]}, "cover_url": cover, "image_urls": [cover, *screenshots], "missing_fields": ["资源版本", "资源大小", "资源价格", "百度网盘", "夸克网盘"], "warnings": []}


def macked_category(source):
    value = source.lower()
    if any(alias in value for alias in ("iina", "播放器", "video player", "music player", "视频播放", "音乐播放")):
        return "影音播放"
    for aliases, category in SOFTWARE_CATEGORIES:
        if any(alias in value for alias in aliases):
            return category
    return "实用工具"


def macked_body(name, info, cover, previews):
    introduction = html.escape(info["description"] or f"{name} 是一款适用于 Mac 的实用软件。")
    pieces = [f'<p class="playmac-software-cover"><img decoding="async" src="{cover}" alt="{html.escape(name, quote=True)}" /></p>', f"<p>{introduction}</p>", "<h2>常见问题</h2>", "<p>安装前请确认系统版本符合要求；如打开受阻，请按 macOS 的安全提示完成允许操作。</p>", "<h2>激活方式</h2>", f"<p>{html.escape(info['activation'] or '免激活，安装后即可使用。')}</p>", "<h2>功能介绍</h2>", f"<p>{introduction}</p>"]
    previews = unique_image_sources(previews, 4)
    if previews:
        pieces.append("<h2>软件截图</h2>")
        pieces.extend(f'<p><img decoding="async" src="{url}" alt="" /></p>' for url in previews)
    return "\n".join(pieces)


def import_macked(source_url, session_path, skip_images=False):
    page = request(source_url, referer="https://macked.app/")
    source = page.text
    if re.search(r"Just a moment|security verification|cf-challenge|checking your browser", source, re.I):
        raise WorkerError("Macked 当前无法提供可靠正文，请稍后重试")
    parser = MetadataParser()
    parser.feed(source)
    raw_title = clean_text(parser.meta.get("og:title") or parser.meta.get("twitter:title") or "")
    raw_title = re.sub(r"\s*[|｜-]\s*Macked.*$", "", raw_title, flags=re.I).strip()
    if not raw_title:
        raw_title = clean_text(" ".join(parser.text[:20]))[:100]
    if not raw_title:
        raise WorkerError("Macked 页面缺少软件名称")
    description = clean_text(parser.meta.get("og:description") or parser.meta.get("description") or "")
    if not description:
        description = clean_text(" ".join(parser.text[20:80]))[:600]
    version_match = re.search(r"(?:version|版本|v)\s*([0-9][0-9A-Za-z._-]{0,30})", f"{raw_title} {description}", re.I)
    if not version_match:
        version_match = re.search(r"\b([0-9]+(?:\.[0-9A-Za-z_-]+){1,5})\b", raw_title)
    version = version_match.group(1) if version_match else "待填写"
    title = re.sub(r"\b" + re.escape(version) + r"\b", "", raw_title) if version != "待填写" else raw_title
    title = re.sub(r"\b(?:For\s+Mac|Mac|开源软件|破解版)\b", "", title, flags=re.I)
    title = re.split(r"\s*[-|｜]\s*", title, maxsplit=1)[0]
    title = re.sub(r"\s+", " ", title).strip(" -|｜")
    if not title:
        title = raw_title
    image_sources = unique_image_sources([parser.meta.get("og:image", ""), *parser.images], 5)
    image_sources = [url for url in image_sources if url.startswith(("http://", "https://"))]
    if not image_sources:
        raise WorkerError("Macked 页面没有可用图片")
    if skip_images:
        cover, previews = image_sources[0], image_sources[1:]
    else:
        staged = [download_image(url, f"macked-{re.sub(r'[^a-z0-9]+', '-', title.lower())[:40]}-{index}", "https://macked.app/") for index, url in enumerate(image_sources)]
        try:
            uploaded = upload_images(session_path, staged)
        finally:
            for path in staged:
                shutil.rmtree(path.parent, ignore_errors=True)
        cover, previews = uploaded[0], uploaded[1:]
    text = " ".join([title, description, *parser.text[:150]])
    size_match = re.search(r"(?:file size|大小|size)\s*[:：]?\s*([0-9.]+\s*(?:KB|MB|GB))", text, re.I)
    language = "中文" if re.search(r"中文|Chinese", text, re.I) else "英文"
    info = {"description": description, "activation": "免激活，安装后即可使用。"}
    article_title = f"{title} For Mac v{version}｜中文破解版｜{description[:28]}".rstrip("｜")
    missing = ["百度网盘", "夸克网盘"]
    if version == "待填写":
        missing.insert(0, "资源版本")
    if not size_match:
        missing.insert(1 if version != "待填写" else 0, "资源大小")
    return {"kind": "macked", "source_url": source_url, "title": article_title, "excerpt": description, "content": macked_body(title, info, cover, previews), "categories": [macked_category(text)], "tags": unique([title, language, macked_category(text)]), "resource_info": [{"title": "资源版本", "desc": version}, {"title": "资源大小", "desc": size_match.group(1) if size_match else "待填写"}, {"title": "资源类型", "desc": "免激活"}, {"title": "资源语言", "desc": language}, {"title": "支持芯片", "desc": "✅M系列｜✅Intel"}, {"title": "系统要求", "desc": "macOS 11 及以上"}], "price": 5, "seo": {"title": article_title, "keywords": ",".join(unique([title, language, macked_category(text)], 5)), "description": description[:180]}, "cover_url": cover, "image_urls": [cover, *previews], "missing_fields": missing, "warnings": []}


def login(session_path, email, password):
    if not email or not password:
        raise WorkerError("请填写千帆账号和密码")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WorkerError("插件图片组件未初始化，请先初始化") from exc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, user_agent=USER_AGENT)
        page = context.new_page()
        page.goto(QIANFAN_URL, wait_until="domcontentloaded", timeout=60000)
        picture_space_ready = False
        login_form_ready = False
        for _ in range(60):
            if qianfan_picture_space_ready(page):
                picture_space_ready = True
                break
            if qianfan_login_form_ready(page):
                login_form_ready = True
                break
            page.wait_for_timeout(250)
        if login_form_ready:
            submit_qianfan_login_form(page, email, password)
            for _ in range(80):
                page.wait_for_timeout(250)
                error = qianfan_login_error(page)
                if error:
                    raise WorkerError(error)
                if qianfan_picture_space_ready(page):
                    picture_space_ready = True
                    break
        if not picture_space_ready:
            raise WorkerError("千帆登录未完成，请检查账号、密码或安全验证")
        cookie = context_cookie_header(context)
        browser.close()
    if not cookie:
        raise WorkerError("千帆登录未完成，请检查账号、密码或安全验证")
    verify_qianfan(cookie)
    save_qianfan_session(session_path, cookie)
    return {"message": "千帆登录成功"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "login", "import"))
    parser.add_argument("--session", required=True)
    parser.add_argument("--source")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--credentials-stdin", action="store_true")
    parser.add_argument("--skip-images", action="store_true")
    args = parser.parse_args()
    if args.command == "check":
        try:
            verify_qianfan(load_session(args.session))
            result = {"success": True, "payload": {"qianfan": "ready"}}
        except WorkerError as exc:
            result = {"success": False, "error": str(exc)}
    elif args.command == "login":
        try:
            if args.credentials_stdin:
                credentials = json.loads(sys.stdin.read() or "{}")
                args.email = str(credentials.get("email") or "")
                args.password = str(credentials.get("password") or "")
            result = {"success": True, "payload": login(args.session, args.email, args.password)}
        except WorkerError as exc:
            result = {"success": False, "error": str(exc)}
    else:
        try:
            kind, value = parse_source(args.source)
            payload = import_steam(value, args.session, args.skip_images) if kind == "steam" else import_macked(value, args.session, args.skip_images)
            result = {"success": True, "payload": payload}
        except (WorkerError, requests.RequestException) as exc:
            result = {"success": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
