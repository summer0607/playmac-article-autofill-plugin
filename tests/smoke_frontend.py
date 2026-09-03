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
    session = None
    try:
        session = php('''
            $users = get_users(array("role"=>"administrator", "number"=>1));
            if (!$users) throw new RuntimeException("Local admin missing");
            $id = $users[0]->ID;
            $token = WP_Session_Tokens::get_instance($id)->create(time()+600);
            echo json_encode(array("id"=>$id,"token"=>$token,"name"=>LOGGED_IN_COOKIE,
                "cookie"=>wp_generate_auth_cookie($id,time()+600,"logged_in",$token),
                "auth_name"=>AUTH_COOKIE,"auth_cookie"=>wp_generate_auth_cookie($id,time()+600,"auth",$token),"url"=>home_url())) ;
        ''', {})
        reference_common = php('echo json_encode(apply_filters("the_content", $data["body"]));', {"body": WORKER.GAME_ARTICLE_COMMON_HTML})
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.context.add_cookies([
                {"name": session["name"], "value": session["cookie"], "url": session["url"]},
                {"name": session["auth_name"], "value": session["auth_cookie"], "url": session["url"]},
            ])
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
                # A real visual-editor save previously stripped picture/source,
                # empty paragraphs, and other original Steam structure.
                page.goto(f'{session["url"]}/wp-admin/post.php?post={created["id"]}&action=edit')
                page.locator('#content-tmce').click()
                locked = page.frame_locator('#content_ifr').locator('.playmac-steam-about')
                locked.wait_for()
                assert locked.get_attribute('contenteditable') == 'false'
                page.locator('#publish').click()
                page.wait_for_url('**/post.php?post=**&action=edit&message=1')
                saved = php('echo json_encode(get_post_field("post_content", $data["id"]));', {"id": created["id"]})
                assert WORKER.steam_about_game(info) in saved, 'Visual editor changed original Steam HTML'
                assert 'playmac-steam-original-' not in saved, 'Editor-only marker leaked into saved article'
                page.goto(created["url"], wait_until="domcontentloaded")
                page.locator('.playmac-steam-about').wait_for()
                common_format = page.evaluate('''reference => {
                    const expected = document.createElement('template');
                    expected.innerHTML = reference;
                    const headings = Array.from(document.querySelectorAll('h2'));
                    const start = headings.find(e => e.textContent.trim() === '经验建议');
                    const end = headings.find(e => e.textContent.trim() === '关于游戏');
                    const range = document.createRange();
                    range.setStartBefore(start); range.setEndBefore(end);
                    const actual = range.cloneContents();
                    const signature = root => Array.from(root.querySelectorAll('h2,h3,p,li,br,blockquote'))
                        .map(e => [e.tagName, e.textContent.replace(/\\s+/g, ' ').trim()]);
                    return {same: JSON.stringify(signature(actual)) === JSON.stringify(signature(expected.content)),
                        actual: signature(actual), expected: signature(expected.content)};
                }''', reference_common)
                assert common_format['same'], ('Common template formatting changed after editor save', common_format)
                alert = page.locator('.ri-alerts-shortcode .alert').first
                alert_lines = alert.evaluate('''e => {
                    const range = document.createRange();
                    const text = Array.from(e.childNodes).find(n => n.nodeType === Node.TEXT_NODE && n.textContent.includes('1.第一次打开游戏'));
                    range.selectNodeContents(text);
                    return new Set(Array.from(range.getClientRects()).map(r => Math.round(r.top))).size;
                }''')
                assert alert_lines >= 2, 'Attention notes lost their visible line breaks'
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
                print(json.dumps({"app_id": app_id, "source_length": len(about), **result, "editor_roundtrip": True, "playing_videos": videos.count()}, ensure_ascii=False), flush=True)
            browser.close()
    finally:
        if session:
            php('WP_Session_Tokens::get_instance($data["id"])->destroy($data["token"]); echo "true";', session)
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
