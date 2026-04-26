# ESJ Zone 小说下载器

AstrBot 插件版 ESJ Zone 小说下载器，主要面向 QQ 个人号（aiocqhttp）使用。

## 命令

- `/esj help`：查看帮助
- `/esj info <小说URL>`：查看书籍与章节信息
- `/esj check <小说URL>`：查看最近更新状态
- `/esj download <小说URL> [epub|txt] [起始章节] [结束章节]`：下载并发送文件
- `/esj login <邮箱> <密码>`：登录并保存 Cookie
- `/esj fav [new|favor] [页码]`：查看收藏列表

## 示例

```text
/esj info https://www.esjzone.one/detail/123.html
/esj download https://www.esjzone.one/detail/123.html epub 1 20
/esj download https://www.esjzone.one/detail/123.html txt
```

下载文件会保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_esjzone_downloader/downloads` 目录，并通过平台文件消息发送。
