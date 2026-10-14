import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock
from test_runtime_worker import WORKER


class QianfanUiTests(unittest.TestCase):
    def page(self, name, link='https://qimg.xiaohongshu.com/arkgoods/test'):
        page = MagicMock()
        response = Mock(status=200)
        response.json.return_value = {'code': 200, 'success': True, 'data': {
            'directoryManageables': [{'name': name, 'additionalData': {'link': link}}]}}
        page.expect_response.return_value.__enter__.return_value.value = response
        return page, response

    def test_exact_name_uses_signed_response_not_truncated_dom(self):
        page, _ = self.page('sha256-' + 'a' * 64)
        self.assertTrue(WORKER.qianfan_find_page_link(page, 'sha256-' + 'a' * 64 + '.jpg'))
        page.get_by_role.assert_not_called()
        page.get_by_text.assert_called_once_with('搜索', exact=True)

    def test_platform_extension_conversion_reuses_same_image(self):
        page, _ = self.page('sha256-abc.jpg')
        self.assertTrue(WORKER.qianfan_find_page_link(page, 'sha256-abc.png'))

    def test_fuzzy_match_never_reuses_other_image(self):
        page, _ = self.page('sha256-abcdef')
        self.assertEqual(WORKER.qianfan_find_page_link(page, 'sha256-abc.jpg'), '')

    def test_invalid_external_host_stops(self):
        page, _ = self.page('sha256-abc', 'https://example.com/image.jpg')
        with self.assertRaises(WORKER.WorkerError):
            WORKER.qianfan_find_page_link(page, 'sha256-abc.jpg')

    def test_failed_business_response_never_becomes_upload_miss(self):
        page, response = self.page('sha256-abc')
        response.json.return_value = {'code': 401, 'success': False}
        with self.assertRaises(WORKER.WorkerError):
            WORKER.qianfan_find_page_link(page, 'sha256-abc.jpg')

    def test_uploader_json_link_supported(self):
        page, response = self.page('sha256-abc')
        response.json.return_value['data']['directoryManageables'][0]['additionalData'] = {
            'uploaderInfoModel': '{"url":"https://qimg.xiaohongshu.com/arkgoods/test"}'}
        self.assertTrue(WORKER.qianfan_find_page_link(page, 'sha256-abc.jpg'))

    def test_no_unsigned_directory_requests(self):
        self.assertNotIn('requests.post(f"{QIANFAN_API}/search_directory_manageable',
                         Path(WORKER.__file__).read_text())
