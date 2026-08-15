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
        var activeJobId = String(PlayMacArticleImporter.jobId || '');
        if (!$button.length) return;

        function setBusy(busy) {
            $button.prop('disabled', busy);
            $url.prop('disabled', busy);
        }

        function finishWithError(message) {
            activeJobId = '';
            setBusy(false);
            setStatus(message || '文章补全失败，请稍后重试。', 'error');
        }

        function pollJob() {
            $.post(PlayMacArticleImporter.ajaxUrl, {
                action: PlayMacArticleImporter.statusAction,
                nonce: PlayMacArticleImporter.nonce,
                post_id: PlayMacArticleImporter.postId,
                job_id: activeJobId
            }).done(function (response) {
                if (!response || !response.success) {
                    finishWithError((response && response.data && response.data.message) || '文章补全失败。');
                    return;
                }
                var data = response.data || {};
                if (data.status === 'running') {
                    setStatus('服务器正在读取资料、处理图片并上传千帆，可以关闭页面，稍后返回会自动继续…', 'loading');
                    window.setTimeout(pollJob, 2500);
                    return;
                }
                var suffix = data.missing_fields && data.missing_fields.length
                    ? ' 发布前还需填写：' + data.missing_fields.join('、') + '。'
                    : '';
                activeJobId = '';
                setStatus('已保存草稿，共写入 ' + (data.image_count || 0) + ' 张千帆图片。' + suffix, 'success');
                window.setTimeout(function () {
                    window.location.href = data.edit_url || window.location.href;
                }, 900);
            }).fail(function (xhr) {
                var response = xhr.responseJSON || {};
                finishWithError((response.data && response.data.message) || '文章补全失败，请稍后重试。');
            });
        }

        if (activeJobId) {
            setBusy(true);
            setStatus('正在恢复未完成的文章任务…', 'loading');
            pollJob();
        }

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

            setBusy(true);
            setStatus('正在提交文章任务…', 'loading');
            $.post(PlayMacArticleImporter.ajaxUrl, {
                action: PlayMacArticleImporter.action,
                nonce: PlayMacArticleImporter.nonce,
                post_id: PlayMacArticleImporter.postId,
                source_url: sourceUrl
            }).done(function (response) {
                if (!response || !response.success) {
                    finishWithError((response && response.data && response.data.message) || '文章补全失败。');
                    return;
                }
                var data = response.data || {};
                activeJobId = String(data.job_id || '');
                if (!activeJobId) {
                    finishWithError('服务器没有返回文章任务编号。');
                    return;
                }
                setStatus('服务器正在读取资料、处理图片并上传千帆，可以关闭页面，稍后返回会自动继续…', 'loading');
                pollJob();
            }).fail(function (xhr) {
                var response = xhr.responseJSON || {};
                finishWithError((response.data && response.data.message) || '文章补全失败，请稍后重试。');
            });
        });
    });
})(jQuery);
