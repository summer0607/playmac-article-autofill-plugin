<?php
/**
 * Plugin Name: PlayMac 文章自动补全
 * Description: 从 Steam 或 Macked 链接生成 PlayMac 游戏、软件文章草稿，并使用已验证的千帆图片外链。
 * Version: 3.1.0
 * Author: PlayMac
 */

defined('ABSPATH') || exit;

final class PlayMac_Article_Importer
{
    private const VERSION = '3.1.0';
    private const AJAX_ACTION = 'playmac_article_import';
    private const AJAX_STATUS_ACTION = 'playmac_article_import_status';
    private const AJAX_QR_START_ACTION = 'playmac_qianfan_qr_start';
    private const AJAX_QR_STATUS_ACTION = 'playmac_qianfan_qr_status';
    private const GITHUB_OWNER = 'summer0607';
    private const GITHUB_REPOSITORY = 'playmac-article-autofill-plugin';
    private const GITHUB_ASSET = 'playmac-article-importer.zip';
    private const UPDATE_CACHE_PREFIX = 'playmac_article_importer_github_release_';
    private const META_SOURCE_URL = '_playmac_import_source_url';
    private const META_SOURCE_KIND = '_playmac_import_source_kind';
    private const META_MISSING = '_playmac_import_missing_fields';
    private const META_JOB_ID = '_playmac_import_job_id';

    public static function boot(): void
    {
        add_action('edit_form_top', array(__CLASS__, 'render_panel'));
        add_action('admin_enqueue_scripts', array(__CLASS__, 'enqueue_assets'));
        add_action('wp_ajax_' . self::AJAX_ACTION, array(__CLASS__, 'ajax_import'));
        add_action('wp_ajax_' . self::AJAX_STATUS_ACTION, array(__CLASS__, 'ajax_import_status'));
        add_action('wp_ajax_' . self::AJAX_QR_START_ACTION, array(__CLASS__, 'ajax_qianfan_qr_start'));
        add_action('wp_ajax_' . self::AJAX_QR_STATUS_ACTION, array(__CLASS__, 'ajax_qianfan_qr_status'));
        add_action('admin_menu', array(__CLASS__, 'register_settings_page'));
        add_action('admin_init', array(__CLASS__, 'register_settings'));
        add_action('admin_notices', array(__CLASS__, 'render_import_notice'));
        add_action('admin_post_playmac_article_importer_initialize', array(__CLASS__, 'initialize_runtime'));
        add_action('admin_post_playmac_article_importer_qianfan_login', array(__CLASS__, 'qianfan_login'));
        add_action('admin_post_playmac_article_importer_qianfan_test', array(__CLASS__, 'qianfan_test'));
        add_action('admin_post_playmac_article_importer_refresh_update', array(__CLASS__, 'refresh_github_update'));
        add_filter('pre_set_site_transient_update_plugins', array(__CLASS__, 'inject_github_update'));
        add_filter('site_transient_update_plugins', array(__CLASS__, 'inject_github_update'));
        add_filter('plugins_api', array(__CLASS__, 'github_plugin_info'), 20, 3);
        add_filter('plugin_action_links_' . plugin_basename(__FILE__), array(__CLASS__, 'add_update_link'));
    }

    public static function activate(): void
    {
        delete_option('playmac_article_importer_helper_url');
        delete_option('playmac_article_importer_helper_token');
    }

    private static function github_release(): array
    {
        $cached = get_site_transient(self::update_cache_key());
        if (is_array($cached)) {
            return $cached;
        }
        $repository = rawurlencode(self::GITHUB_REPOSITORY);
        $url = 'https://api.github.com/repos/' . self::GITHUB_OWNER . '/' . $repository . '/releases/latest';
        $response = wp_remote_get($url, array(
            'timeout' => 15,
            'headers' => array(
                'Accept' => 'application/vnd.github+json',
                'User-Agent' => 'PlayMac-Article-Importer/' . self::VERSION,
            ),
        ));
        if (is_wp_error($response) || wp_remote_retrieve_response_code($response) !== 200) {
            return array();
        }
        $body = json_decode((string) wp_remote_retrieve_body($response), true);
        if (!is_array($body) || empty($body['tag_name'])) {
            return array();
        }
        $package = '';
        foreach ((array) ($body['assets'] ?? array()) as $asset) {
            if (($asset['name'] ?? '') === self::GITHUB_ASSET) {
                $package = (string) ($asset['browser_download_url'] ?? '');
                break;
            }
        }
        if ($package === '') {
            return array();
        }
        $release = array(
            'version' => ltrim((string) $body['tag_name'], 'vV'),
            'package' => esc_url_raw($package),
            'url' => esc_url_raw((string) ($body['html_url'] ?? '')),
            'notes' => wp_kses_post((string) ($body['body'] ?? '')),
        );
        set_site_transient(self::update_cache_key(), $release, 15 * MINUTE_IN_SECONDS);
        return $release;
    }

    private static function update_cache_key(): string
    {
        return self::UPDATE_CACHE_PREFIX . str_replace('.', '_', self::VERSION);
    }

    public static function inject_github_update($transient)
    {
        if (!is_object($transient) || empty($transient->checked)) {
            return $transient;
        }
        $release = self::github_release();
        $plugin = plugin_basename(__FILE__);
        if (!$release || version_compare($release['version'], self::VERSION, '<=')) {
            if (isset($transient->response[$plugin]) && version_compare((string) $transient->response[$plugin]->new_version, self::VERSION, '<=')) {
                unset($transient->response[$plugin]);
            }
            return $transient;
        }
        $transient->response[$plugin] = (object) array(
            'slug' => 'playmac-article-importer',
            'plugin' => $plugin,
            'new_version' => $release['version'],
            'url' => $release['url'],
            'package' => $release['package'],
        );
        return $transient;
    }

    public static function github_plugin_info($result, $action, $args)
    {
        if ($action !== 'plugin_information' || empty($args->slug) || $args->slug !== 'playmac-article-importer') {
            return $result;
        }
        $release = self::github_release();
        if (!$release) {
            return $result;
        }
        return (object) array(
            'name' => 'PlayMac 文章自动补全',
            'slug' => 'playmac-article-importer',
            'version' => $release['version'],
            'author' => '<a href="https://www.playmac.cc/">PlayMac</a>',
            'homepage' => $release['url'],
            'download_link' => $release['package'],
            'sections' => array(
                'description' => '正式站独立运行的 Steam 和 Macked 文章自动补全插件。',
                'changelog' => $release['notes'] ?: '查看 GitHub Release 了解更新内容。',
            ),
        );
    }

    public static function add_update_link(array $links): array
    {
        $url = wp_nonce_url(
            admin_url('admin-post.php?action=playmac_article_importer_refresh_update'),
            'playmac_article_importer_refresh_update'
        );
        $links[] = '<a href="' . esc_url($url) . '">检查 GitHub 更新</a>';
        return $links;
    }

    public static function refresh_github_update(): void
    {
        if (!current_user_can('update_plugins')) {
            wp_die('你没有更新插件的权限。', 403);
        }
        check_admin_referer('playmac_article_importer_refresh_update');
        delete_site_transient(self::update_cache_key());
        delete_site_transient('update_plugins');
        wp_update_plugins();
        wp_safe_redirect(add_query_arg('playmac_update_checked', '1', self_admin_url('plugins.php')));
        exit;
    }

    public static function render_panel(WP_Post $post): void
    {
        if ($post->post_type !== 'post' || !current_user_can('edit_post', $post->ID)) {
            return;
        }
        $source_url = (string) get_post_meta($post->ID, self::META_SOURCE_URL, true);
        $missing = get_post_meta($post->ID, self::META_MISSING, true);
        $missing = is_array($missing) ? array_values(array_filter(array_map('strval', $missing))) : array();
        ?>
        <section class="playmac-article-importer" id="playmac-article-importer">
            <div class="playmac-article-importer__heading">
                <div>
                    <h2>文章自动补全</h2>
                    <p>粘贴 Steam 游戏链接或 Macked 软件介绍链接，自动保存标题、正文、分类、标签、高级配置和千帆图片。</p>
                </div>
                <span class="playmac-article-importer__badge">仅保存草稿</span>
            </div>
            <div class="playmac-article-importer__controls">
                <label class="screen-reader-text" for="playmac-import-source-url">Steam 或 Macked 链接</label>
                <input
                    type="url"
                    id="playmac-import-source-url"
                    value="<?php echo esc_attr($source_url); ?>"
                    placeholder="https://store.steampowered.com/app/... 或 https://macked.app/....html"
                    autocomplete="off"
                />
                <button type="button" class="button button-primary" id="playmac-import-start">获取资料并保存草稿</button>
            </div>
            <p class="playmac-article-importer__status" id="playmac-import-status" role="status" aria-live="polite"></p>
            <?php if ($missing): ?>
                <p class="playmac-article-importer__missing">发布前还需填写：<?php echo esc_html(implode('、', $missing)); ?></p>
            <?php endif; ?>
        </section>
        <?php
    }

    public static function enqueue_assets(string $hook): void
    {
        $is_editor = in_array($hook, array('post.php', 'post-new.php'), true);
        $is_settings = $hook === 'settings_page_playmac-article-importer';
        if (!$is_editor && !$is_settings) {
            return;
        }
        if ($is_editor) {
            $screen = get_current_screen();
            if (!$screen || $screen->post_type !== 'post') {
                return;
            }
        }
        $base = plugin_dir_url(__FILE__);
        wp_enqueue_style(
            'playmac-article-importer',
            $base . 'assets/admin.css',
            array(),
            self::VERSION
        );
        wp_enqueue_script(
            'playmac-article-importer',
            $base . 'assets/admin.js',
            array('jquery'),
            self::VERSION,
            true
        );
        wp_localize_script('playmac-article-importer', 'PlayMacArticleImporter', array(
            'ajaxUrl' => admin_url('admin-ajax.php'),
            'action' => self::AJAX_ACTION,
            'statusAction' => self::AJAX_STATUS_ACTION,
            'nonce' => wp_create_nonce(self::AJAX_ACTION),
            'postId' => $is_editor ? get_the_ID() : 0,
            'jobId' => $is_editor ? sanitize_key((string) get_post_meta(get_the_ID(), self::META_JOB_ID, true)) : '',
            'qrStartAction' => self::AJAX_QR_START_ACTION,
            'qrStatusAction' => self::AJAX_QR_STATUS_ACTION,
            'qrNonce' => wp_create_nonce(self::AJAX_QR_START_ACTION),
        ));
    }

    public static function ajax_qianfan_qr_start(): void
    {
        check_ajax_referer(self::AJAX_QR_START_ACTION, 'nonce');
        if (!current_user_can('manage_options')) {
            wp_send_json_error(array('message' => '你没有执行此操作的权限。'), 403);
        }
        try {
            $result = self::runtime_request('POST', '/v1/login/qr/start', array(), 20);
            if (empty($result['success'])) {
                throw new RuntimeException((string) ($result['error'] ?? '千帆登录二维码生成失败。'));
            }
            wp_send_json_success((array) ($result['payload'] ?? array()));
        } catch (Throwable $throwable) {
            wp_send_json_error(array('message' => $throwable->getMessage() ?: '千帆登录二维码生成失败。'), 422);
        }
    }

    public static function ajax_qianfan_qr_status(): void
    {
        check_ajax_referer(self::AJAX_QR_START_ACTION, 'nonce');
        if (!current_user_can('manage_options')) {
            wp_send_json_error(array('message' => '你没有执行此操作的权限。'), 403);
        }
        try {
            $result = self::runtime_request('POST', '/v1/login/qr/status', array(), 15);
            if (empty($result['success'])) {
                throw new RuntimeException((string) ($result['error'] ?? '千帆扫码状态读取失败。'));
            }
            wp_send_json_success((array) ($result['payload'] ?? array()));
        } catch (Throwable $throwable) {
            wp_send_json_error(array('message' => $throwable->getMessage() ?: '千帆扫码状态读取失败。'), 422);
        }
    }

    public static function ajax_import(): void
    {
        check_ajax_referer(self::AJAX_ACTION, 'nonce');
        $post_id = isset($_POST['post_id']) ? absint($_POST['post_id']) : 0;
        if (!$post_id || !current_user_can('edit_post', $post_id)) {
            wp_send_json_error(array('message' => '你没有编辑这篇文章的权限。'), 403);
        }
        $post = get_post($post_id);
        if (!$post || $post->post_type !== 'post') {
            wp_send_json_error(array('message' => '文章不存在。'), 404);
        }
        $source_url = isset($_POST['source_url']) ? esc_url_raw(wp_unslash($_POST['source_url'])) : '';
        if (!$source_url) {
            wp_send_json_error(array('message' => '请填写 Steam 或 Macked 链接。'), 400);
        }

        $lock_key = 'playmac_article_import_' . get_current_user_id();
        $existing_job = sanitize_key((string) get_post_meta($post_id, self::META_JOB_ID, true));
        if ($existing_job !== '') {
            wp_send_json_success(array('status' => 'running', 'job_id' => $existing_job));
        }
        if (get_transient($lock_key)) {
            wp_send_json_error(array('message' => '已有导入任务正在运行，请稍候。'), 429);
        }
        set_transient($lock_key, 1, 15 * MINUTE_IN_SECONDS);

        try {
            $result = self::runtime_request('POST', '/v1/jobs/import', array('source' => $source_url), 15);
            $job_id = sanitize_key((string) ($result['payload']['job_id'] ?? ''));
            if (empty($result['success']) || strlen($job_id) !== 32) {
                throw new RuntimeException((string) ($result['error'] ?? '服务器组件未返回有效任务。'));
            }
            update_post_meta($post_id, self::META_JOB_ID, $job_id);
            wp_send_json_success(array('status' => 'running', 'job_id' => $job_id));
        } catch (Throwable $throwable) {
            delete_transient($lock_key);
            wp_send_json_error(array('message' => $throwable->getMessage()), 422);
        }
    }

    public static function ajax_import_status(): void
    {
        check_ajax_referer(self::AJAX_ACTION, 'nonce');
        $post_id = isset($_POST['post_id']) ? absint($_POST['post_id']) : 0;
        if (!$post_id || !current_user_can('edit_post', $post_id)) {
            wp_send_json_error(array('message' => '你没有编辑这篇文章的权限。'), 403);
        }
        $job_id = sanitize_key((string) ($_POST['job_id'] ?? get_post_meta($post_id, self::META_JOB_ID, true)));
        if (strlen($job_id) !== 32) {
            wp_send_json_error(array('message' => '没有可恢复的文章任务。'), 404);
        }
        $lock_key = 'playmac_article_import_' . get_current_user_id();
        try {
            $result = self::runtime_request('GET', '/v1/jobs/' . rawurlencode($job_id), null, 15);
            $status = sanitize_key((string) ($result['status'] ?? ''));
            if ($status === 'running') {
                set_transient($lock_key, 1, 15 * MINUTE_IN_SECONDS);
                wp_send_json_success(array('status' => 'running', 'job_id' => $job_id));
            }
            if ($status !== 'complete' || empty($result['success'])) {
                throw new RuntimeException((string) ($result['error'] ?? '文章任务失败。'));
            }
            $payload = $result['payload'] ?? null;
            if (!is_array($payload)) {
                throw new RuntimeException('服务器组件返回的数据不完整。');
            }
            self::validate_payload($payload);
            $saved = self::apply_payload($post_id, $payload);
            delete_post_meta($post_id, self::META_JOB_ID);
            delete_transient($lock_key);
            $saved['status'] = 'complete';
            wp_send_json_success($saved);
        } catch (Throwable $throwable) {
            delete_post_meta($post_id, self::META_JOB_ID);
            delete_transient($lock_key);
            wp_send_json_error(array('message' => $throwable->getMessage()), 422);
        }
    }

    private static function runtime_url(): string
    {
        $url = defined('PLAYMAC_ARTICLE_RUNTIME_URL') ? PLAYMAC_ARTICLE_RUNTIME_URL : 'http://127.0.0.1:18990';
        return untrailingslashit((string) $url);
    }

    private static function runtime_token(): string
    {
        return defined('PLAYMAC_ARTICLE_RUNTIME_TOKEN') ? trim((string) PLAYMAC_ARTICLE_RUNTIME_TOKEN) : '';
    }

    private static function runtime_request(string $method, string $path, ?array $payload, int $timeout): array
    {
        $headers = array('Accept' => 'application/json');
        $token = self::runtime_token();
        if ($token !== '') {
            $headers['Authorization'] = 'Bearer ' . $token;
        }
        $arguments = array(
            'method' => $method,
            'timeout' => $timeout,
            'headers' => $headers,
        );
        if ($payload !== null) {
            $arguments['headers']['Content-Type'] = 'application/json; charset=utf-8';
            $arguments['body'] = wp_json_encode($payload);
        }
        $response = wp_remote_request(self::runtime_url() . $path, $arguments);
        if (is_wp_error($response)) {
            throw new RuntimeException('服务器组件未连接，请确认常驻组件已经启动。');
        }
        $decoded = json_decode((string) wp_remote_retrieve_body($response), true);
        if (!is_array($decoded)) {
            throw new RuntimeException('服务器组件返回格式异常。');
        }
        $code = wp_remote_retrieve_response_code($response);
        if ($code >= 400 && empty($decoded['error'])) {
            throw new RuntimeException('服务器组件请求失败。');
        }
        return $decoded;
    }

    private static function validate_payload(array $payload): void
    {
        foreach (array('kind', 'source_url', 'title', 'content', 'resource_info', 'seo', 'image_urls') as $key) {
            if (!array_key_exists($key, $payload)) {
                throw new RuntimeException('文章资料缺少必要字段：' . $key);
            }
        }
        if (!in_array($payload['kind'], array('steam', 'macked'), true)) {
            throw new RuntimeException('文章来源类型不受支持。');
        }
        if (!is_array($payload['image_urls']) || !$payload['image_urls']) {
            throw new RuntimeException('文章没有可用的千帆图片。');
        }
        foreach ($payload['image_urls'] as $url) {
            $host = strtolower((string) wp_parse_url((string) $url, PHP_URL_HOST));
            if ($host !== 'qimg.xiaohongshu.com') {
                throw new RuntimeException('文章图片尚未全部转为千帆外链。');
            }
        }
    }

    private static function apply_payload(int $post_id, array $payload): array
    {
        global $wpdb;
        $current_post = get_post($post_id);
        if (!$current_post instanceof WP_Post) {
            throw new RuntimeException('文章不存在，未保存草稿。');
        }
        $category_result = self::resolve_categories((array) ($payload['categories'] ?? array()), $payload['kind']);
        $resource_info = array();
        foreach ((array) $payload['resource_info'] as $item) {
            if (!is_array($item)) {
                continue;
            }
            $title = sanitize_text_field((string) ($item['title'] ?? ''));
            $desc = sanitize_text_field((string) ($item['desc'] ?? ''));
            if ($title !== '') {
                $resource_info[] = array('title' => $title, 'desc' => $desc);
            }
        }
        if (!$resource_info) {
            throw new RuntimeException('文章高级配置为空，未保存草稿。');
        }

        $wpdb->query('START TRANSACTION');
        try {
            $post_update = array(
                'ID' => $post_id,
                'post_title' => sanitize_text_field((string) $payload['title']),
                'post_excerpt' => sanitize_textarea_field((string) ($payload['excerpt'] ?? '')),
                'post_content' => (string) $payload['content'],
            );
            if ($current_post->post_status === 'auto-draft') {
                $post_update['post_status'] = 'draft';
            }
            $updated = wp_update_post(wp_slash($post_update), true);
            if (is_wp_error($updated)) {
                throw new RuntimeException($updated->get_error_message());
            }
            if ($category_result['ids']) {
                wp_set_post_categories($post_id, $category_result['ids'], false);
            }
            $tags = array_values(array_filter(array_map('sanitize_text_field', (array) ($payload['tags'] ?? array()))));
            wp_set_post_tags($post_id, $tags, false);

            update_post_meta($post_id, 'cao_info', $resource_info);
            update_post_meta($post_id, 'cao_status', '1');
            update_post_meta($post_id, 'cao_swit', '1');
            if ($payload['price'] !== null && get_post_meta($post_id, 'cao_price', true) === '') {
                update_post_meta($post_id, 'cao_price', (string) absint($payload['price']));
                update_post_meta($post_id, 'cao_vip_rate', '0');
            }

            $seo = is_array($payload['seo']) ? $payload['seo'] : array();
            $seo_title = sanitize_text_field((string) ($seo['title'] ?? ''));
            $seo_keywords = sanitize_text_field((string) ($seo['keywords'] ?? ''));
            $seo_description = sanitize_textarea_field((string) ($seo['description'] ?? ''));
            update_post_meta($post_id, 'post_titie', $seo_title);
            update_post_meta($post_id, 'keywords', $seo_keywords);
            update_post_meta($post_id, 'description', $seo_description);
            update_post_meta($post_id, 'rank_math_title', $seo_title);
            update_post_meta($post_id, 'rank_math_focus_keyword', $seo_keywords);
            update_post_meta($post_id, 'rank_math_description', $seo_description);
            update_post_meta($post_id, self::META_SOURCE_URL, esc_url_raw((string) $payload['source_url']));
            update_post_meta($post_id, self::META_SOURCE_KIND, sanitize_key((string) $payload['kind']));
            $missing = array_values(array_filter(array_map('sanitize_text_field', (array) ($payload['missing_fields'] ?? array()))));
            update_post_meta($post_id, self::META_MISSING, $missing);
            update_post_meta($post_id, '_playmac_import_cover_url', esc_url_raw((string) ($payload['cover_url'] ?? '')));
            $wpdb->query('COMMIT');
        } catch (Throwable $throwable) {
            $wpdb->query('ROLLBACK');
            clean_post_cache($post_id);
            throw $throwable;
        }

        $warnings = array_values(array_filter(array_map('sanitize_text_field', (array) ($payload['warnings'] ?? array()))));
        if ($category_result['missing']) {
            $warnings[] = '未找到分类：' . implode('、', $category_result['missing']);
        }
        set_transient('playmac_article_import_notice_' . get_current_user_id(), array(
            'post_id' => $post_id,
            'missing' => $missing,
            'warnings' => $warnings,
        ), 2 * MINUTE_IN_SECONDS);

        return array(
            'message' => '文章草稿已补全并保存。',
            'post_id' => $post_id,
            'edit_url' => get_edit_post_link($post_id, 'raw'),
            'missing_fields' => $missing,
            'warnings' => $warnings,
            'image_count' => count((array) $payload['image_urls']),
        );
    }

    private static function resolve_categories(array $names, string $kind): array
    {
        $categories = get_categories(array('hide_empty' => false));
        $ids = array();
        $missing = array();
        foreach ($names as $name) {
            $target = self::normalize_category_name((string) $name);
            if ($target === '') {
                continue;
            }
            $matched = 0;
            foreach ($categories as $category) {
                $candidate = self::normalize_category_name($category->name);
                if ($candidate === $target) {
                    $matched = (int) $category->term_id;
                    break;
                }
            }
            if ($matched) {
                $ids[] = $matched;
            } else {
                $missing[] = sanitize_text_field((string) $name);
            }
        }
        if (!$ids) {
            $fallback = $kind === 'steam' ? 'Mac游戏' : 'Mac软件';
            foreach ($categories as $category) {
                if (self::normalize_category_name($category->name) === self::normalize_category_name($fallback)) {
                    $ids[] = (int) $category->term_id;
                    break;
                }
            }
        }
        return array('ids' => array_values(array_unique($ids)), 'missing' => $missing);
    }

    private static function normalize_category_name(string $value): string
    {
        $value = preg_replace('/[^\p{L}\p{N}]+/u', '', $value);
        return function_exists('mb_strtolower') ? mb_strtolower((string) $value, 'UTF-8') : strtolower((string) $value);
    }

    public static function register_settings_page(): void
    {
        add_options_page(
            'PlayMac 文章自动补全',
            'PlayMac 文章自动补全',
            'manage_options',
            'playmac-article-importer',
            array(__CLASS__, 'render_settings_page')
        );
    }

    public static function register_settings(): void
    {
    }

    public static function render_settings_page(): void
    {
        if (!current_user_can('manage_options')) {
            return;
        }
        ?>
        <div class="wrap">
            <h1>PlayMac 文章自动补全</h1>
            <p>所有资料读取和图片处理均由网站服务器内的常驻组件完成，不连接本机电脑或外部控制台。</p>
            <?php self::render_settings_notice(); ?>
            <h2>第一步：检查服务器组件</h2>
            <p>常驻组件独立运行，插件更新不会删除它，也不需要 PHP 启动或安装 Python。</p>
            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
                <input type="hidden" name="action" value="playmac_article_importer_initialize" />
                <?php wp_nonce_field('playmac_article_importer_initialize'); ?>
                <?php submit_button('测试服务器组件', 'secondary', 'submit', false); ?>
            </form>
            <hr />
            <h2>第二步：扫码登录千帆图片空间</h2>
            <p>点击后会显示千帆官方登录二维码。请使用小红书 APP 扫码并确认，插件不会读取或保存账号密码。</p>
            <button type="button" class="button button-primary" id="playmac-qianfan-qr-start">获取千帆登录二维码</button>
            <div class="playmac-qianfan-qr" id="playmac-qianfan-qr" hidden>
                <img id="playmac-qianfan-qr-image" alt="千帆登录二维码" />
                <p id="playmac-qianfan-qr-status" role="status" aria-live="polite"></p>
            </div>
            <details class="playmac-qianfan-password-login">
                <summary>账号密码登录（备用）</summary>
                <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
                    <input type="hidden" name="action" value="playmac_article_importer_qianfan_login" />
                    <?php wp_nonce_field('playmac_article_importer_qianfan_login'); ?>
                    <table class="form-table" role="presentation">
                        <tr>
                            <th scope="row"><label for="playmac-qianfan-email">千帆账号</label></th>
                            <td><input class="regular-text" required type="text" id="playmac-qianfan-email" name="email" autocomplete="username" /></td>
                        </tr>
                        <tr>
                            <th scope="row"><label for="playmac-qianfan-password">千帆密码</label></th>
                            <td><input class="regular-text" required type="password" id="playmac-qianfan-password" name="password" autocomplete="current-password" /></td>
                        </tr>
                    </table>
                    <?php submit_button('使用账号密码登录', 'secondary', 'submit', false); ?>
                </form>
            </details>
            <hr />
            <h2>第三步：测试千帆连接</h2>
            <p>登录后可随时测试当前会话是否仍然有效，不会修改文章或图片。</p>
            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
                <input type="hidden" name="action" value="playmac_article_importer_qianfan_test" />
                <?php wp_nonce_field('playmac_article_importer_qianfan_test'); ?>
                <?php submit_button('测试千帆连接', 'secondary', 'submit', false); ?>
            </form>
        </div>
        <?php
    }

    public static function initialize_runtime(): void
    {
        if (!current_user_can('manage_options')) {
            wp_die('你没有执行此操作的权限。', 403);
        }
        check_admin_referer('playmac_article_importer_initialize');
        try {
            $result = self::runtime_request('GET', '/health', null, 10);
            if (empty($result['success']) || ($result['payload']['status'] ?? '') !== 'ready') {
                self::redirect_settings('error', (string) ($result['error'] ?? '服务器组件尚未就绪。'));
            }
            $version = sanitize_text_field((string) ($result['payload']['version'] ?? ''));
            self::redirect_settings('success', '服务器组件连接正常' . ($version !== '' ? '，版本：' . $version : '') . '。');
        } catch (Throwable $throwable) {
            self::redirect_settings('error', $throwable->getMessage() ?: '服务器组件连接失败。');
        }
    }

    public static function qianfan_login(): void
    {
        if (!current_user_can('manage_options')) {
            wp_die('你没有执行此操作的权限。', 403);
        }
        check_admin_referer('playmac_article_importer_qianfan_login');
        @set_time_limit(180);
        $email = sanitize_text_field((string) ($_POST['email'] ?? ''));
        $password = (string) ($_POST['password'] ?? '');
        if ($email === '' || $password === '') {
            self::redirect_settings('error', '请填写千帆账号和密码。');
        }
        try {
            $result = self::runtime_request('POST', '/v1/login', array('email' => $email, 'password' => $password), 120);
            if (empty($result['success'])) {
                self::redirect_settings('error', (string) ($result['error'] ?? '千帆登录失败。'));
            }
            self::redirect_settings('success', '千帆登录成功，插件已可上传图片。');
        } catch (Throwable $throwable) {
            self::redirect_settings('error', $throwable->getMessage() ?: '千帆登录暂时无法完成，请稍后重试。');
        } finally {
            unset($password);
        }
    }

    public static function qianfan_test(): void
    {
        if (!current_user_can('manage_options')) {
            wp_die('你没有执行此操作的权限。', 403);
        }
        check_admin_referer('playmac_article_importer_qianfan_test');
        try {
            $result = self::runtime_request('POST', '/v1/check', array(), 30);
            if (empty($result['success'])) {
                self::redirect_settings('error', (string) ($result['error'] ?? '千帆连接测试失败。'));
            }
            self::redirect_settings('success', '千帆连接正常，当前登录仍然有效。');
        } catch (Throwable $throwable) {
            self::redirect_settings('error', $throwable->getMessage() ?: '千帆连接测试暂时无法完成。');
        }
    }

    private static function redirect_settings(string $type, string $message): void
    {
        wp_safe_redirect(add_query_arg(array(
            'page' => 'playmac-article-importer',
            'playmac_importer_notice' => $type,
            'playmac_importer_message' => $message,
        ), admin_url('options-general.php')));
        exit;
    }

    private static function render_settings_notice(): void
    {
        $type = sanitize_key((string) ($_GET['playmac_importer_notice'] ?? ''));
        $message = sanitize_text_field(wp_unslash((string) ($_GET['playmac_importer_message'] ?? '')));
        if (!in_array($type, array('success', 'error'), true) || $message === '') {
            return;
        }
        printf('<div class="notice notice-%1$s"><p>%2$s</p></div>', esc_attr($type === 'success' ? 'success' : 'error'), esc_html($message));
    }

    public static function render_import_notice(): void
    {
        $key = 'playmac_article_import_notice_' . get_current_user_id();
        $notice = get_transient($key);
        if (!is_array($notice)) {
            return;
        }
        delete_transient($key);
        $message = '文章资料和千帆图片已补全，草稿已保存。';
        if (!empty($notice['missing'])) {
            $message .= ' 发布前还需填写：' . implode('、', array_map('strval', $notice['missing'])) . '。';
        }
        if (!empty($notice['warnings'])) {
            $message .= ' 提醒：' . implode('；', array_map('strval', $notice['warnings'])) . '。';
        }
        echo '<div class="notice notice-success is-dismissible"><p>' . esc_html($message) . '</p></div>';
    }
}

register_activation_hook(__FILE__, array('PlayMac_Article_Importer', 'activate'));
PlayMac_Article_Importer::boot();
