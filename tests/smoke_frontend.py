#!/usr/bin/env python3
"""Optional live Steam -> local WordPress -> Chromium smoke test. No uploads.

Run with the existing local site/container running. All temporary posts are
deleted in finally; refuses to write to any non-loopback WordPress installation.
Requires the project's existing requests and Playwright test environment.
"""
import importlib.util
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("worker", ROOT / "runtime/playmac_article_worker.py")
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)
DOCKER = "/Applications/Docker.app/Contents/Resources/bin/docker"
PHP_BOOT = '''
define("WP_USE_THEMES", false);
require "/var/www/html/wp-load.php";
if (!in_array(parse_url(home_url(), PHP_URL_HOST), array("localhost", "127.0.0.1"), true)) {
    fwrite(STDERR, "Local site only"); exit(1);
}
$data = json_decode(stream_get_contents(STDIN), true);
'''


def php(code, data):
    result = subprocess.run(
        [DOCKER, "exec", "-i", "playmac-local-php81", "php", "-r", PHP_BOOT + code],
        input=json.dumps(data), text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def main():
    ids = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            # Keep analytics and unrelated theme services out of this local test.
            page.route("**/*", lambda route: route.continue_() if (
                (urlparse(route.request.url).hostname or "") in {"localhost", "127.0.0.1"}
                or (urlparse(route.request.url).hostname or "").endswith(".steamstatic.com")
            ) else route.abort())
            for app_id in ("1145350", "367520", "413150"):
                info = WORKER.request(f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=cn&l=schinese").json()[app_id]["data"]
                about = info["about_the_game"]
                body = WORKER.game_body(info, info["name"], info["name"], "", [])
                created = php('''
                    $id = wp_insert_post(wp_slash(array(
                        "post_title" => "PlayMac Steam local smoke test",
                        "post_content" => $data["body"], "post_status" => "publish"
                    )), true);
                    if (is_wp_error($id)) { fwrite(STDERR, $id->get_error_message()); exit(1); }
                    echo json_encode(array("id" => $id, "url" => get_permalink($id)));
                ''', {"body": body})
                ids.append(created["id"])
                page.goto(created["url"], wait_until="domcontentloaded")
                page.locator('.playmac-steam-about').wait_for()
                result = page.evaluate('''(source) => {
                    const template = document.createElement('template');
                    template.innerHTML = source;
                    const actual = document.querySelector('.playmac-steam-about');
                    const blocks = root => Array.from(root.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,br')).map(e => [e.tagName, e.textContent]);
                    const media = root => Array.from(root.querySelectorAll('picture,img,video,source')).map(e => [e.tagName, e.getAttribute('src'), e.getAttribute('srcset'), e.getAttribute('sizes'), e.getAttribute('poster'), e.getAttribute('type')]);
                    return {
                        text: template.content.textContent === actual.textContent,
                        blocks: JSON.stringify(blocks(template.content)) === JSON.stringify(blocks(actual)),
                        media: JSON.stringify(media(template.content)) === JSON.stringify(media(actual)),
                        stylesheet: !!document.querySelector('#playmac-steam-media-css'),
                        script: !!document.querySelector('#playmac-steam-media-js')
                    };
                }''', about)
                assert all(result.values()), (app_id, result)
                videos = page.locator('.playmac-steam-about video')
                for index in range(videos.count()):
                    video = videos.nth(index)
                    video.scroll_into_view_if_needed()
                    page.wait_for_function('''index => {
                        const v = document.querySelectorAll('.playmac-steam-about video')[index];
                        return !v.paused && v.currentTime > 0 && v.readyState >= 2;
                    }''', arg=index, timeout=45000)
                    state = video.evaluate('''v => ({muted:v.muted, volume:v.volume, autoplay:v.autoplay,
                        controls:v.controls, inline:v.playsInline, rightClickBlocked:!v.dispatchEvent(new MouseEvent('contextmenu', {bubbles:true,cancelable:true}))})''')
                    assert state == {"muted": True, "volume": 0, "autoplay": True, "controls": False, "inline": True, "rightClickBlocked": True}, state
                    if index == 0:
                        video.screenshot(path="/tmp/playmac-steam-video-verified.png")
                print(json.dumps({"app_id": app_id, "source_length": len(about), **result, "playing_videos": videos.count()}, ensure_ascii=False), flush=True)
            browser.close()
    finally:
        if ids:
            cleaned = php('''
                $removed = array();
                foreach ($data["ids"] as $id) {
                    if (get_the_title($id) === "PlayMac Steam local smoke test" && wp_delete_post($id, true)) $removed[] = $id;
                }
                echo json_encode($removed);
            ''', {"ids": ids})
            assert cleaned == ids, "Test post cleanup incomplete"
            print(f"Removed {len(cleaned)} temporary local test posts.", flush=True)


if __name__ == "__main__":
    main()
