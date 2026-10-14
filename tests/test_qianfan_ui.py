import unittest
from pathlib import Path
from unittest.mock import Mock
from test_runtime_worker import WORKER


class QianfanUiTests(unittest.TestCase):
    def page(self, name, link='https://qimg.xiaohongshu.com/arkgoods/test'):
        page = Mock()
        row = Mock()
        row.inner_text.return_value = name + '\n复制链接'
        page.get_by_role.return_value.count.return_value = 2
        page.get_by_role.return_value.nth.return_value = row
        page.evaluate.side_effect = [None, link]
        return page, row

    def test_exact_name_copies_verified_host(self):
        page, row = self.page('sha256-abc')
        self.assertEqual(WORKER.qianfan_find_page_link(page, 'sha256-abc.jpg'),
                         'https://qimg.xiaohongshu.com/arkgoods/test')
        row.get_by_text.assert_called_once_with('复制链接', exact=True)

    def test_fuzzy_match_never_reuses_other_image(self):
        page, row = self.page('sha256-abcdef')
        self.assertEqual(WORKER.qianfan_find_page_link(page, 'sha256-abc.jpg'), '')
        row.get_by_text.assert_not_called()

    def test_invalid_clipboard_link_stops(self):
        page, _ = self.page('sha256-abc', 'https://example.com/image.jpg')
        with self.assertRaises(WORKER.WorkerError):
            WORKER.qianfan_find_page_link(page, 'sha256-abc.jpg')

    def test_directory_search_endpoint_removed(self):
        self.assertNotIn('search_directory_manageable', Path(WORKER.__file__).read_text())
