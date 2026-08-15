<?php
/**
 * Plugin Name: PlayMac 文章自动补全
 * Description: 从 Steam 或 Macked 链接生成 PlayMac 游戏、软件文章草稿，并使用已验证的千帆图片外链。
 * Version: 2.0.2
 * Author: PlayMac
 */

defined('ABSPATH') || exit;

final class PlayMac_Article_Importer
{
    private const VERSION = '2.0.2';
    private const AJAX_ACTION = 'playmac_article_import';
    private const GITHUB_OWNER = 'summer0607';
    private const GITHUB_REPOSITORY = 'playmac-article-autofill-plugin';
    private const GITHUB_ASSET = 'playmac-article-importer.zip';
    private const UPDATE_CACHE_KEY = 'playmac_article_importer_github_release_v2';
    private const META_SOURCE_URL = '_playmac_import_source_url';
    private const META_SOURCE_KIND = '_playmac_import_source_kind';
    private const META_MISSING = '_playmac_import_missing_fields';

    public static function boot(): void
    {
        add_action('edit_form_top', array(__CLASS__, 'render_panel'));
        add_action('admin_enqueue_scripts', array(__CLASS__, 'enqueue_assets'));
        add_action('wp_ajax_' . self::AJAX_ACTION, array(__CLASS__, 'ajax_import'));
        add_action('admin_menu', array(__CLASS__, 'register_settings_page'));
        add_action('admin_init', array(__CLASS__, 'register_settings'));
        add_action('admin_notices', array(__CLASS__, 'render_import_notice'));
        add_action('admin_post_playmac_article_importer_initialize', array(__CLASS__, 'initialize_runtime'));
        add_action('admin_post_playmac_article_importer_qianfan_login', array(__CLASS__, 'qianfan_login'));
        add_action('admin_post_playmac_article_importer_qianfan_test', array(__CLASS__, 'qianfan_test'));
        add_filter('pre_set_site_transient_update_plugins', array(__CLASS__, 'inject_github_update'));
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
        $cached = get_site_transient(self::UPDATE_CACHE_KEY);
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
        set_site_transient(self::UPDATE_CACHE_KEY, $release, 15 * MINUTE_IN_SECONDS);
        return $release;
    }

    public static function inject_github_update($transient)
    {
        if (!is_object($transient) || empty($transient->checked)) {
            return $transient;
        }
        $release = self::github_release();
        if (!$release || version_compare($release['version'], self::VERSION, '<=')) {
            return $transient;
        }
        $plugin = plugin_basename(__FILE__);
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
        $links[] = '<a href="' . esc_url(admin_url('update-core.php?force-check=1')) . '">检查 GitHub 更新</a>';
        return $links;
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
        if (!in_array($hook, array('post.php', 'post-new.php'), true)) {
            return;
        }
        $screen = get_current_screen();
        if (!$screen || $screen->post_type !== 'post') {
            return;
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
            'nonce' => wp_create_nonce(self::AJAX_ACTION),
            'postId' => get_the_ID(),
        ));
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
        if (get_transient($lock_key)) {
            wp_send_json_error(array('message' => '已有导入任务正在运行，请稍候。'), 429);
        }
        set_transient($lock_key, 1, 5 * MINUTE_IN_SECONDS);

        try {
            $payload = self::request_worker($source_url);
            $result = self::apply_payload($post_id, $payload);
            delete_transient($lock_key);
            wp_send_json_success($result);
        } catch (Throwable $throwable) {
            delete_transient($lock_key);
            wp_send_json_error(array('message' => $throwable->getMessage()), 422);
        }
    }

    private static function request_worker(string $source_url): array
    {
        $decoded = self::run_worker(array('import', '--source', $source_url), 300);
        if (empty($decoded['success'])) {
            throw new RuntimeException((string) ($decoded['error'] ?? '文章资料生成失败。'));
        }
        $payload = $decoded['payload'] ?? null;
        if (!is_array($payload)) {
            throw new RuntimeException('本机文章助手返回的数据不完整。');
        }
        self::validate_payload($payload);
        return $payload;
    }

    private static function runtime_dir(): string
    {
        return plugin_dir_path(__FILE__) . 'runtime';
    }

    private static function runtime_python(): string
    {
        return self::runtime_dir() . '/.venv/bin/python';
    }

    private static function session_file(): string
    {
        $directory = trailingslashit(get_temp_dir()) . 'playmac-article-importer-' . substr(hash_hmac('sha256', site_url(), wp_salt('auth')), 0, 24);
        if (!is_dir($directory)) {
            wp_mkdir_p($directory);
            @chmod($directory, 0700);
        }
        return trailingslashit($directory) . 'qianfan-session.json';
    }

    private static function run_worker(array $arguments, int $timeout, string $input = ''): array
    {
        $process_error = self::worker_process_error();
        if ($process_error !== '') {
            throw new RuntimeException($process_error);
        }
        $python = self::runtime_python();
        $worker = self::runtime_dir() . '/playmac_article_worker.py';
        if (!is_file($python) || !is_file($worker)) {
            throw new RuntimeException('插件运行环境尚未初始化，请先到设置页完成初始化。');
        }
        $command = array_merge(array($python, $worker), $arguments, array('--session', self::session_file()));
        $pipes = array();
        $process = proc_open($command, array(
            0 => array('pipe', 'r'),
            1 => array('pipe', 'w'),
            2 => array('pipe', 'w'),
        ), $pipes, self::runtime_dir());
        if (!is_resource($process)) {
            throw new RuntimeException('无法启动插件文章处理器。');
        }
        if ($input !== '') {
            fwrite($pipes[0], $input);
        }
        fclose($pipes[0]);
        stream_set_blocking($pipes[1], false);
        stream_set_blocking($pipes[2], false);
        $stdout = '';
        $stderr = '';
        $started = time();
        do {
            $stdout .= stream_get_contents($pipes[1]);
            $stderr .= stream_get_contents($pipes[2]);
            $state = proc_get_status($process);
            if (!$state['running']) {
                break;
            }
            if (time() - $started > $timeout) {
                proc_terminate($process, 9);
                throw new RuntimeException('文章处理超时，请稍后重试。');
            }
            usleep(100000);
        } while (true);
        $stdout .= stream_get_contents($pipes[1]);
        $stderr .= stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $exit_code = proc_close($process);
        $decoded = json_decode(trim($stdout), true);
        if (!is_array($decoded)) {
            $detail = trim($stderr);
            throw new RuntimeException($detail ?: ($exit_code === 0 ? '文章处理器返回异常。' : '文章处理器运行失败。'));
        }
        return $decoded;
    }

    private static function worker_process_error(): string
    {
        $required = array('proc_open', 'proc_get_status', 'proc_close', 'proc_terminate');
        $disabled = array();
        foreach ($required as $function) {
            if (!function_exists($function)) {
                $disabled[] = $function;
            }
        }
        if (!$disabled) {
            return '';
        }
        return '服务器未开启插件所需的进程权限，暂时不能登录千帆或生成文章。请在宝塔 PHP 设置的“禁用函数”中移除：' . implode('、', $disabled) . '。';
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
            <p>所有资料读取和图片处理均由本插件在网站服务器内完成，不连接本机电脑或外部控制台。</p>
            <?php self::render_settings_notice(); ?>
            <h2>第一步：初始化</h2>
            <p>首次安装时，插件会安装自己的图片处理组件。完成后不需要保持其他程序运行。</p>
            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
                <input type="hidden" name="action" value="playmac_article_importer_initialize" />
                <?php wp_nonce_field('playmac_article_importer_initialize'); ?>
                <?php submit_button(is_file(self::runtime_python()) ? '重新检查组件' : '初始化插件组件', 'secondary', 'submit', false); ?>
            </form>
            <hr />
            <h2>第二步：登录千帆图片空间</h2>
            <p>登录仅由插件用于上传图片，账号密码不会保存；登录会话保存在网站私有目录中。</p>
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
                <?php submit_button('登录并保存插件会话', 'primary', 'submit', false); ?>
            </form>
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
        @set_time_limit(300);
        $process_error = self::worker_process_error();
        if ($process_error !== '') {
            self::redirect_settings('error', $process_error);
        }
        $script = self::runtime_dir() . '/install-runtime.sh';
        if (!is_file($script)) {
            self::redirect_settings('error', '插件初始化文件缺失，请重新安装插件。');
        }
        $pipes = array();
        $process = proc_open(array('/bin/bash', $script), array(1 => array('pipe', 'w'), 2 => array('pipe', 'w')), $pipes, self::runtime_dir());
        if (!is_resource($process)) {
            self::redirect_settings('error', '无法启动插件初始化。');
        }
        $stdout = stream_get_contents($pipes[1]);
        $stderr = stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $status = proc_close($process);
        if ($status !== 0 || !is_file(self::runtime_python())) {
            self::redirect_settings('error', trim($stderr) ?: '插件组件初始化失败。');
        }
        self::redirect_settings('success', '插件组件已准备完成。');
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
            $result = self::run_worker(
                array('login', '--credentials-stdin'),
                120,
                wp_json_encode(array('email' => $email, 'password' => $password))
            );
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
        @set_time_limit(60);
        try {
            $result = self::run_worker(array('check'), 45);
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
