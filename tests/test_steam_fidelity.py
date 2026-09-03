import unittest
from html.parser import HTMLParser
from test_runtime_worker import WORKER


class SteamFidelityTests(unittest.TestCase):
    def test_animated_picture_keeps_srcset_and_fallback(self):
        source = '<p><picture><source srcset="https://shared.akamai.steamstatic.com/animated.webp?t=123" type="image/webp"><img src="https://shared.akamai.steamstatic.com/poster.avif?t=123" sizes="100vw"></picture></p>'
        self.assertEqual(source, WORKER.steam_about_game({'about_the_game': source}))
        unsafe = '<picture><source srcset="https://example.com/a.webp 1x, javascript:bad() 2x"><img src="https://example.com/fallback.jpg"></picture>'
        self.assertNotIn('srcset', WORKER.steam_about_game({'about_the_game': unsafe}))

    def test_about_is_complete_not_combined_description(self):
        about = '<h2>游戏特色</h2><p>' + '完整段落，保持原文。' * 800 + '</p><h3>次级标题</h3><p>结尾内容</p>'
        body = WORKER.game_body({'about_the_game': about, 'detailed_description': '<h2>评测和广告</h2>'}, '测试', 'Test', '', [])
        self.assertIn(about, body)
        self.assertNotIn('评测和广告', body)
        self.assertTrue(body.startswith('<!-- wp:html -->'))
        self.assertTrue(body.endswith('<!-- /wp:html -->'))

    def test_preserves_paragraph_heading_list_and_break_structure(self):
        about = '<h2 class="bb_tag">第一节</h2><p class="bb_paragraph">A &amp; B</p><h3>小节</h3><ul><li>条目<br><br>续行</li></ul><p></p><h4>细节</h4><p>第二段</p>'
        self.assertEqual(about, WORKER.steam_about_game({'about_the_game': about}))

    def test_media_keeps_original_animated_urls_and_sources(self):
        gif = 'https://shared.akamai.steamstatic.com/extras/intro.gif?t=123&x=1'
        webm = 'https://shared.akamai.steamstatic.com/extras/intro.webm?t=123'
        mp4 = 'https://shared.fastly.steamstatic.com/extras/intro.mp4?t=123'
        about = f'<p><img src="{gif}" /></p><video controls loop poster="https://shared.akamai.steamstatic.com/poster.avif"><source src="{webm}" type="video/webm; codecs=vp9"><source src="{mp4}" type="video/mp4"></video>'
        result = WORKER.steam_about_game({'about_the_game': about})
        tags = []
        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                tags.append((tag, dict(attrs)))
        Parser().feed(result)
        video = next(attrs for tag, attrs in tags if tag == 'video')
        self.assertNotIn('controls', video)
        for attr in ('muted', 'autoplay', 'playsinline', 'loop'):
            self.assertIn(attr, video)
        self.assertEqual([gif, webm, mp4], [attrs['src'] for _, attrs in tags if 'src' in attrs])
        self.assertNotIn('qimg.xiaohongshu.com', result)

    def test_missing_about_fails_without_inventing_or_falling_back(self):
        with self.assertRaises(WORKER.WorkerError):
            WORKER.steam_about_game({'detailed_description': '<p>不是指定区域</p>'})

    def test_removes_active_html_not_safe_content(self):
        source = '<p onclick="alert(1)">保留</p><script>danger()</script><iframe src="https://bad.example"></iframe><video src="javascript:bad()" controls onplay="bad()"></video>'
        result = WORKER.steam_about_game({'about_the_game': source})
        self.assertIn('<p>保留</p>', result)
        for value in ('onclick', 'onplay', 'javascript:', '<script', '<iframe', 'danger()'):
            self.assertNotIn(value, result)
