(function ($) {
    'use strict';

    function currentContent() {
        if (window.tinymce) {
            var editor = window.tinymce.get('content');
            if (editor && !editor.isHidden()) {
                return String(editor.getContent() || '');
            }
        }
        return String($('#content').val() || '');
    }

    function setStatus(message, state) {
        $('#playmac-import-status')
            .removeClass('is-loading is-error is-success')
            .addClass(state ? 'is-' + state : '')
            .text(message || '');
    }

    $(function () {
        var $button = $('#playmac-import-start');
        var $url = $('#playmac-import-source-url');
        if (!$button.length) return;

        $button.on('click', function () {
            var sourceUrl = $.trim($url.val() || '');
            if (!sourceUrl) {
                setStatus('请先粘贴 Steam 或 Macked 链接。', 'error');
                $url.trigger('focus');
                return;
            }
            if (($.trim($('#title').val() || '') || $.trim(currentContent()))
                && !window.confirm('当前文章已有内容。继续会用来源资料更新标题和正文，但会保留已有价格与下载链接。是否继续？')) {
                return;
            }

            $button.prop('disabled', true);
            $url.prop('disabled', true);
            setStatus('正在读取资料、处理图片并上传千帆，请不要关闭页面…', 'loading');
            $.post(PlayMacArticleImporter.ajaxUrl, {
                action: PlayMacArticleImporter.action,
                nonce: PlayMacArticleImporter.nonce,
                post_id: PlayMacArticleImporter.postId,
                source_url: sourceUrl
            }).done(function (response) {
                if (!response || !response.success) {
                    setStatus((response && response.data && response.data.message) || '文章补全失败。', 'error');
                    return;
                }
                var data = response.data || {};
                var suffix = data.missing_fields && data.missing_fields.length
                    ? ' 发布前还需填写：' + data.missing_fields.join('、') + '。'
                    : '';
                setStatus('已保存草稿，共写入 ' + (data.image_count || 0) + ' 张千帆图片。' + suffix, 'success');
                window.setTimeout(function () {
                    window.location.href = data.edit_url || window.location.href;
                }, 900);
            }).fail(function (xhr) {
                var response = xhr.responseJSON || {};
                setStatus((response.data && response.data.message) || '文章补全失败，请稍后重试。', 'error');
            }).always(function () {
                $button.prop('disabled', false);
                $url.prop('disabled', false);
            });
        });
    });
})(jQuery);
