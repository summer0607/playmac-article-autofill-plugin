<?php
// Pure PHP coverage; the live smoke test also exercises actual WordPress/TinyMCE.
define('ABSPATH', __DIR__);
function add_action(...$args) {}
function add_filter(...$args) {}
function register_activation_hook(...$args) {}
function plugin_basename($file) { return basename($file); }
function wp_slash($text) { return addslashes($text); }
function wp_unslash($text) { return stripslashes($text); }
function wp_kses_post($text) { return $text; }
function get_post_field($field, $id, $context) { return $GLOBALS['sources'][$id] ?? ''; }
class WP_Post { public $ID = 42; public $post_type = 'post'; }
require dirname(__DIR__) . '/playmac-article-importer.php';
function check($condition, $message) {
    if (!$condition) throw new RuntimeException($message);
}
$post = new WP_Post();
$about = '<div class="playmac-steam-about"><p></p><div><h2>A &amp; B</h2><p>Don\'t change</p></div><picture><source srcset="https://example.com/a.webp"><img src="https://example.com/a.avif"></picture><video muted autoplay><source src="https://example.com/v.mp4"></video></div>';
$body = '<!-- wp:html --><p>Before</p>'.$about.'<h2>After</h2><!-- /wp:html -->';
$sources = array(42 => $body);
$protected = PlayMac_Article_Importer::protect_steam_editor($body, 'tinymce');
check(strpos($protected, 'playmac-steam-original-42') !== false, 'Editor marker missing');
check(strpos($protected, 'contenteditable="false"') !== false, 'Editor copy is not read-only');
check(strpos($protected, '<h2>After</h2>') !== false, 'Nested div consumed following content');
$normalized = str_replace(array('<p></p>', '<picture>', '</picture>'), '', $protected);
$normalized = str_replace('Before', 'User changed this', $normalized);
$data = array('post_content'=>wp_slash($normalized), 'post_type'=>'post');
$saved = PlayMac_Article_Importer::restore_steam_editor($data, array('ID'=>42));
check(wp_unslash($saved['post_content']) === str_replace('Before', 'User changed this', $body), 'Source or unrelated edits were changed');
check(PlayMac_Article_Importer::restore_steam_editor($data, array('ID'=>43)) === $data, 'Wrong post source used');
$revision = $data; $revision['post_type'] = 'revision';
$savedRevision = PlayMac_Article_Importer::restore_steam_editor($revision, array('ID'=>99,'post_parent'=>42));
check($savedRevision['post_content'] === $saved['post_content'], 'Autosave source not restored');
check(PlayMac_Article_Importer::protect_steam_editor($body, 'other') === $body, 'Unrelated editor modified');
$ordinary = array('post_content'=>wp_slash('<p>Manual article</p>'),'post_type'=>'post');
check(PlayMac_Article_Importer::restore_steam_editor($ordinary,array('ID'=>42)) === $ordinary, 'Manual removal ignored');
check(PlayMac_Article_Importer::protect_steam_editor('<p>No Steam</p>', 'html') === '<p>No Steam</p>', 'Ordinary article changed');
echo "Editor preservation checks passed.\n";
