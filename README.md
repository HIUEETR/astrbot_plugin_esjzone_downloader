# ESJ Zone 小说下载器

AstrBot 插件版 ESJ Zone 小说下载器，主要面向 QQ 个人号（aiocqhttp）使用。

## 命令

- `/esj help`：查看帮助
- `/esj i <小说URL或编号>`：用合并转发查看书籍简介、编号和章节数
- `/esj f [lastest|collected] [页码]`：用合并转发查看收藏列表，默认 `lastest`
- `/esj c <小说URL或编号>`：查看最近更新状态
- `/esj d <小说URL或编号> [epub|txt] [起始章节] [结束章节]`：下载并发送文件，未指定格式时默认 EPUB
- `/esj l <邮箱> <密码>`：仅私聊可用，登录并保存当前用户 Cookie
- `/esj logout`：仅私聊可用，清除当前用户 Cookie；管理员可用 `/esj logout all` 清除全部用户 Cookie
- `/esj cfg [配置项] [值]`：查看或修改插件配置，修改配置需要管理员权限
- `/esj m add <小说URL或编号>`：把书籍加入当前会话的更新监控
- `/esj m list`：查看当前会话的监控列表
- `/esj m rm <小说URL或编号|all>`：移除当前会话的监控
- `/esj m check`：立即检查当前会话的监控更新

完整指令仍保留兼容：`info`、`fav`、`check`、`download`、`login`、`config`、`monitor`。

`<小说URL或编号>` 可以传完整 ESJ 详情页 URL，也可以只传书籍编号。例如 `123` 会自动解析为 `https://www.esjzone.one/detail/123.html`。

## 示例

```text
/esj i 123
/esj f
/esj f lastest 2
/esj f collected 1
/esj d 123
/esj d 123 1 20
/esj d 123 txt
/esj d 123 epub 1 20
/esj c 123
/esj cfg file_naming_mode book_id
/esj logout
/esj m add 123
/esj m list
/esj m check
```

## 配置

- `file_naming_mode`：发送文件名，可选 `book_name` 或 `book_id`。
- `use_book_dir`：是否为每本书创建独立目录。
- `download_images`：生成 EPUB 时是否下载封面和插图。
- `max_threads`：并发下载数。
- `timeout_seconds`：请求超时时间。
- `retry_attempts`：失败重试次数。
- `retry_delays`：失败重试等待秒数列表。
- `max_chapters_per_download`：单次下载最大章节数。
- `max_images_per_download`：单次下载最大插图数，不含封面。
- `max_image_bytes`：单张图片最大字节数。
- `max_total_image_bytes`：单次下载图片总字节数。
- `max_image_pixels`：单张图片最大像素数。
- `max_output_bytes`：生成 EPUB/TXT 文件最大字节数。
- `monitor_enabled`：是否启用自动更新监控。
- `monitor_interval_hours`：自动检查间隔，默认 `12` 小时。
- `monitor_max_entries`：全局最大监控条目数。
- `monitor_max_entries_per_origin`：单个会话最大监控条目数。
- `monitor_check_batch_size`：单轮自动检查最大条目数。
- `monitor_check_concurrency`：监控检查并发数。

可以通过 `/esj cfg` 查看当前配置，通过 `/esj cfg <配置项> <值>` 修改常用配置。修改配置需要 AstrBot 管理员权限。布尔值支持 `true/false`，`retry_delays` 使用英文逗号分隔，例如 `/esj cfg retry_delays 1,3,5`。

数值配置会强制限制范围：`max_threads` 为 1-10，`timeout_seconds` 为 5-300，`retry_attempts` 为 0-5，`monitor_interval_hours` 为 0.5-168，`monitor_check_concurrency` 为 1-10。

## 安全说明

- 只接受 ESJ 官方 HTTPS 详情页 URL 或纯数字书籍编号；外部域名、内网地址、非 HTTPS 地址和路径穿越格式会被拒绝。HTTP 重定向也会逐跳校验，外跳不会继续请求。
- `/esj login`、`/esj fav`、`/esj logout` 只允许私聊使用，Cookie 按平台和发送者隔离保存。
- Cookie 文件保存在 AstrBot 插件数据目录的 `users/<用户标识>/cookies.json` 下；文件会尝试收紧为仅运行用户可读写。该目录应按凭据处理，备份、迁移和打包前需要确认不会泄露。
- 下载文件保存在 AstrBot 插件数据目录的 `downloads` 下，文件名会附加随机后缀以避免覆盖旧文件。
- 监控列表保存在插件数据目录的 `monitor.json`，写入时使用临时文件原子替换；损坏的 JSON 会备份为 `*.corrupt.*`。自动检查会按批次和并发上限处理，避免监控文件过大时阻塞管理命令。
- 生成 EPUB 前会移除脚本、事件属性、远程图片和不安全标签；图片下载有单图大小、总大小、数量和像素限制。

## 依赖与运行环境

- 依赖版本范围见 `requirements.txt`，当前约束为 `beautifulsoup4>=4.12,<5`、`httpx>=0.28.1,<0.29`、`pillow>=10,<12`。
- 发布前建议在目标 AstrBot/Python 环境中执行 `ruff check`、`compileall` 和依赖漏洞扫描。

## 更新监控

使用 `/esj m add <小说URL或编号>` 添加当前会话的监控。插件会每隔 `monitor_interval_hours` 小时自动检查一次，默认 12 小时。

发现新章节时，插件会主动向添加监控的会话发送提醒，包含书籍编号、上次记录章节、当前最新章节、新章节页面，以及可直接使用的下载指令，例如：

```text
/esj d 123 21 25
```

发送提醒后，插件会自动把监控记录更新到最新章节，避免重复提醒同一批章节。

下载文件会保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_esjzone_downloader/downloads` 目录，并通过平台文件消息发送。
