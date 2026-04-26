# ESJ Zone 小说下载器

AstrBot 插件版 ESJ Zone 小说下载器，主要面向 QQ 个人号（aiocqhttp）使用。

## 命令

- `/esj help`：查看帮助
- `/esj info <小说URL或编号>`：用合并转发查看书籍简介和章节数
- `/esj check <小说URL或编号>`：查看最近更新状态
- `/esj download <小说URL或编号> [epub|txt] [起始章节] [结束章节]`：下载并发送文件，未指定格式时默认 EPUB
- `/esj login <邮箱> <密码>`：登录并保存 Cookie
- `/esj fav [lastest|collected] [页码]`：用合并转发查看收藏列表，默认 `lastest`

## 示例

```text
/esj info 123
/esj fav
/esj download 123
/esj download 123 1 20
/esj download 123 txt
```

下载文件会保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_esjzone_downloader/downloads` 目录，并通过平台文件消息发送。
可在插件配置中将发送文件名设置为书籍名或 ESJ 书籍编号。
