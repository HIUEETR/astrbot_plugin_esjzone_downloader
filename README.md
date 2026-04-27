# ESJ Zone 小说下载器

AstrBot 插件版 ESJ Zone 小说下载器，主要面向 QQ 个人号（aiocqhttp）使用。

## 命令

- `/esj help`：查看帮助
- `/esj i <小说URL或编号>`：用合并转发查看书籍简介、编号和章节数
- `/esj f [lastest|collected] [页码]`：用合并转发查看收藏列表，默认 `lastest`
- `/esj c <小说URL或编号>`：查看最近更新状态
- `/esj d <小说URL或编号> [epub|txt] [起始章节] [结束章节]`：下载并发送文件，未指定格式时默认 EPUB
- `/esj l <邮箱> <密码>`：登录并保存 Cookie
- `/esj cfg [配置项] [值]`：查看或修改插件配置
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
- `monitor_enabled`：是否启用自动更新监控。
- `monitor_interval_hours`：自动检查间隔，默认 `12` 小时。

可以通过 `/esj cfg` 查看当前配置，通过 `/esj cfg <配置项> <值>` 修改常用配置。布尔值支持 `true/false`，`retry_delays` 使用英文逗号分隔，例如 `/esj cfg retry_delays 1,3,5`。

## 更新监控

使用 `/esj m add <小说URL或编号>` 添加当前会话的监控。插件会每隔 `monitor_interval_hours` 小时自动检查一次，默认 12 小时。

发现新章节时，插件会主动向添加监控的会话发送提醒，包含书籍编号、上次记录章节、当前最新章节、新章节页面，以及可直接使用的下载指令，例如：

```text
/esj d 123 21 25
```

发送提醒后，插件会自动把监控记录更新到最新章节，避免重复提醒同一批章节。

下载文件会保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_esjzone_downloader/downloads` 目录，并通过平台文件消息发送。
