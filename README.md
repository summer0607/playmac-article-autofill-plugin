# PlayMac 文章自动填充插件

仓库地址使用英文 `playmac-article-autofill-plugin`，以确保 GitHub Release 更新链接稳定；插件名称和说明保持中文。

在 WordPress 文章编辑页顶部粘贴 Steam 商店链接或 Macked 软件介绍链接，插件会在正式网站内生成并保存草稿，不依赖本机电脑、控制台或外部文章助手。耗时处理由服务器常驻组件完成，不占用 WordPress 页面请求。

- Steam：补全游戏标题、正文、分类、标签、资源信息和 SEO；Steam 无法提供成品版本、大小与价格，因此明确列为“待填写”。
- Macked：补全软件标题、正文、分类、标签、版本、大小、系统要求、芯片信息和 SEO。
- 图片：服务器常驻组件的后台任务下载、上传并验证千帆外链，文章只写入 `qimg.xiaohongshu.com` 图片。
- 千帆：在插件设置页获取官方二维码，用小红书 APP 扫码登录；账号密码登录仅作为备用。登录会话保存在独立数据卷中。
- Macked：插件直接读取并解析；无法可靠读取时不会保存草稿，也不会使用旧缓存替代。
- 安全：插件不自动发布，不覆盖已有价格和下载链接。

安装后：

1. 在服务器运行 `docker compose up -d` 启动常驻组件。
2. 打开“设置 → PlayMac 文章自动补全”，点击“测试服务器组件”。
3. 在同一页面获取二维码，并使用小红书 APP 扫码登录千帆图片空间。
4. 新建文章，粘贴 Steam 或 Macked 链接并保存草稿。

## GitHub 更新

插件会读取本仓库的 GitHub Release。发布新版本时推送 `v版本号` 标签，GitHub 会自动生成安装包和 Release；已安装的网站会在 WordPress 插件更新页提示更新，也可以在插件列表点击“检查 GitHub 更新”，立即清除旧缓存并刷新更新状态。

## 服务器常驻组件

常驻组件只监听服务器本机 `127.0.0.1:18990`。千帆会话和未完成任务保存在独立数据卷中，更新 WordPress 插件不会删除。

```bash
docker compose pull
docker compose up -d
```

每次推送版本标签时，GitHub 会同时发布 WordPress 安装包和 `ghcr.io/summer0607/playmac-article-autofill-runtime` 容器镜像。

## 发布新版本

1. 更新插件文件头中的版本号和 `CHANGELOG.md`。
2. 提交并推送代码。
3. 推送同名标签，例如 `v3.1.0`。
4. GitHub 会自动发布 WordPress 安装包和常驻组件镜像。
