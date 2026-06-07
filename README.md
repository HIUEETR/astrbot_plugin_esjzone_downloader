# ESJ Zone 小说下载器

AstrBot 插件版 ESJ Zone 小说下载器，支持解析 ESJ Zone 小说信息、下载 EPUB/TXT，并通过 AstrBot 平台发送文件。

## 功能

- 支持 EPUB / TXT 下载
- 支持按章节范围下载
- 支持查看书籍简介、章节数和更新状态
- 支持用户登录、收藏列表和登出
- 支持会话级更新监控和更新提醒
- 支持下载限制、图片限制、重试和并发配置
- 支持 Cookie 多用户隔离

## 安装

1. 将本插件放入 AstrBot 的 `data/plugins/` 目录。
2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 重启 AstrBot。

## 使用

查看帮助：

```text
/esj help
```

常用命令：

```text
/esj i 123                 # 查看书籍信息
/esj d 123                 # 下载 EPUB
/esj d 123 txt             # 下载 TXT
/esj d 123 epub 1 20       # 下载第 1-20 章
/esj c 123                 # 检查最近更新
/esj f                     # 查看收藏列表
/esj l <邮箱> <密码>       # 私聊登录
/esj logout                # 私聊登出
/esj m add 123             # 添加更新监控
/esj m list                # 查看监控列表
/esj m rm 123              # 移除监控
/esj m check               # 立即检查监控更新
/esj cfg                   # 查看配置
```

`<小说URL或编号>` 支持以下格式：

```text
123
https://www.esjzone.one/detail/123.html
```

## 命令列表

| 命令 | 说明 |
| --- | --- |
| `/esj help` 或 `/esj h` | 查看帮助 |
| `/esj i <小说URL或编号>` | 查看书籍简介、编号和章节数 |
| `/esj f [lastest\|collected] [页码]` | 查看收藏列表 |
| `/esj c <小说URL或编号>` | 查看最近更新状态 |
| `/esj d <小说URL或编号> [epub\|txt] [起始章节] [结束章节]` | 下载并发送文件，默认 EPUB |
| `/esj l <邮箱> <密码>` | 私聊登录并保存当前用户 Cookie |
| `/esj logout` | 私聊清除当前用户 Cookie |
| `/esj logout all` | 管理员清除全部用户 Cookie |
| `/esj cfg [配置项] [值]` | 查看或修改插件配置 |
| `/esj m add <小说URL或编号>` | 添加当前会话的更新监控 |
| `/esj m list` | 查看当前会话的监控列表 |
| `/esj m rm <小说URL或编号\|all>` | 移除当前会话的监控 |
| `/esj m check` | 立即检查当前会话的监控更新 |

完整命令名仍兼容：`info`、`fav`、`check`、`download`、`login`、`config`、`monitor`。

## 配置

可通过 `/esj cfg` 查看当前配置，通过 `/esj cfg <配置项> <值>` 修改常用配置。修改配置需要 AstrBot 管理员权限。

常用配置项：

- `file_naming_mode`：发送文件名，可选 `book_name` 或 `book_id`
- `use_book_dir`：是否为每本书创建独立目录
- `download_images`：生成 EPUB 时是否下载封面和插图
- `max_threads`：并发下载数
- `timeout_seconds`：请求超时时间
- `retry_attempts`：失败重试次数
- `retry_delays`：失败重试等待秒数列表，例如 `1,3,5`
- `max_chapters_per_download`：单次下载最大章节数
- `max_images_per_download`：单次下载最大插图数，不含封面
- `max_image_bytes`：单张图片最大字节数
- `max_total_image_bytes`：单次下载图片总字节数
- `max_image_pixels`：单张图片最大像素数
- `max_output_bytes`：生成 EPUB/TXT 文件最大字节数
- `monitor_enabled`：是否启用自动更新监控
- `monitor_interval_hours`：自动检查间隔，默认 `12` 小时
- `monitor_max_entries`：全局最大监控条目数
- `monitor_max_entries_per_origin`：单个会话最大监控条目数
- `monitor_check_batch_size`：单轮自动检查最大条目数
- `monitor_check_concurrency`：监控检查并发数

布尔值支持 `true/false`。

## 更新监控

使用以下命令添加当前会话的监控：

```text
/esj m add 123
```

插件会按配置的 `monitor_interval_hours` 自动检查更新。发现新章节后，会向添加监控的会话发送提醒，并给出可直接使用的下载命令，例如：

```text
/esj d 123 21 25
```

发送提醒后，监控记录会更新到最新章节，避免重复提醒同一批章节。

## 安全说明

- 只接受 ESJ 官方 HTTPS 详情页 URL 或纯数字书籍编号。
- 外部域名、内网地址、非 HTTPS 地址和路径穿越格式会被拒绝。
- 私聊登录、收藏和登出命令仅私聊可用。
- Cookie 按平台和发送者隔离保存。
- 群聊下载不会使用或刷新用户 Cookie。
- 生成 EPUB 前会移除脚本、事件属性、远程图片和不安全标签。
- 图片下载有单图大小、总大小、数量和像素限制。

## 许可证

MIT License

## 致谢

- [AstrBot](https://github.com/Soulter/AstrBot)
- [esjzone-novel-downloader](https://github.com/HIUEETR/esjzone-novel-downloader)
