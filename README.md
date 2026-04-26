# ESJ Zone 小说下载器

AstrBot 插件版 ESJ Zone 小说下载器，主要面向 QQ 个人号（aiocqhttp）使用。

## 命令

- `/esj help`：查看帮助
- `/esj info <小说URL或编号>`：用合并转发查看书籍简介、编号和章节数
- `/esj fav [lastest|collected] [页码]`：用合并转发查看收藏列表，默认 `lastest`
- `/esj check <小说URL或编号>`：查看最近更新状态
- `/esj download <小说URL或编号> [epub|txt] [起始章节] [结束章节]`：下载并发送文件，未指定格式时默认 EPUB
- `/esj login <邮箱> <密码>`：登录并保存 Cookie

`<小说URL或编号>` 可以传完整 ESJ 详情页 URL，也可以只传书籍编号。例如 `123` 会自动解析为 `https://www.esjzone.one/detail/123.html`。

## 示例

```text
/esj info 123
/esj fav
/esj fav lastest 2
/esj fav collected 1
/esj download 123
/esj download 123 1 20
/esj download 123 txt
/esj download 123 epub 1 20
/esj check 123
```

## 配置

- `file_naming_mode`：发送文件名，可选 `book_name` 或 `book_id`。
- `use_book_dir`：是否为每本书创建独立目录。
- `download_images`：生成 EPUB 时是否下载封面和插图。
- `max_threads`：并发下载数。
- `max_chapters_per_download`：单次最多下载章节数，设为 `0` 表示不限制。

下载文件会保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_esjzone_downloader/downloads` 目录，并通过平台文件消息发送。
