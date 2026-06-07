# ESJ Zone 小说下载器

[![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

AstrBot 插件版 ESJ Zone 小说下载器，支持 EPUB/TXT 格式下载，主要面向 QQ 个人号（aiocqhttp）使用。

## ✨ 特性

- 📚 支持 EPUB 和 TXT 格式下载
- 🚀 异步下载，高性能并发控制
- 📊 实时进度追踪和速率显示
- 🔍 智能更新监控系统
- 💾 双层缓存加速访问
- 🛡️ 完善的错误处理和自动重试
- 📝 详细的下载统计和历史记录
- 🎯 文件大小预估
- ⚡ 内存优化和流式下载

## 📦 版本信息

**当前版本**: v1.3.0 (2026-06-07)

**主要更新**:
- ✨ 新增内存优化器（大书籍分批处理、图片流式下载）
- ✨ 新增并发优化器（自适应并发、分段锁）
- ✨ 新增文件大小预估功能
- 🚀 下载性能优化（速率限制、进度追踪）
- 🚀 监控系统增强（智能间隔、历史记录）
- 📚 完善文档（API 文档、架构文档）

查看完整变更历史：[CHANGELOG.md](CHANGELOG.md)

## 📖 快速开始

### 安装

1. 将插件放置到 AstrBot 的 `data/plugins/` 目录
2. 安装依赖：`pip install -r requirements.txt`
3. 重启 AstrBot

### 基本使用

```bash
# 查看帮助
/esj help

# 下载书籍（最简单）
/esj d 123

# 查看书籍信息
/esj i 123

# 添加更新监控
/esj m add 123
```

详细使用说明请查看：[API_DOCUMENTATION.md](API_DOCUMENTATION.md)

## 📋 命令列表

### 基础命令

- `/esj help` (或 `/esj h`)：查看帮助
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

### 支持的参数格式

`<小说URL或编号>` 可以传：
- 完整 URL：`https://www.esjzone.one/detail/123.html`
- 书籍编号：`123`（自动转换为完整 URL）

### 命令别名

为了快速操作，所有命令都支持简写：
- `help` → `h`
- `info` → `i`
- `download` → `d`
- `check` → `c`
- `fav` → `f`
- `login` → `l`
- `monitor` → `m`
- `config` → `cfg`

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

## ⚙️ 配置说明

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

### 推荐配置

**网络良好时**：
- `max_threads`: 8-10
- `timeout_seconds`: 120
- `download_images`: true

**网络一般时**：
- `max_threads`: 3-5
- `timeout_seconds`: 180
- `retry_attempts`: 3

**大书籍下载**：
- `max_chapters_per_download`: 100（分批下载）
- `download_images`: false（先下载文本）

## 🔒 安全说明

- 只接受 ESJ 官方 HTTPS 详情页 URL 或纯数字书籍编号；外部域名、内网地址、非 HTTPS 地址和路径穿越格式会被拒绝。HTTP 重定向也会逐跳校验，外跳不会继续请求。
- `/esj login`、`/esj fav`、`/esj logout` 只允许私聊使用，Cookie 按平台和发送者隔离保存。
- 私聊登录态失效时，收藏和私聊下载会在检测到登录页后使用插件配置中的 `account.username/password` 自动重新登录并重试一次；群聊下载不会使用或刷新任何用户 Cookie。
- Cookie 文件保存在 AstrBot 插件数据目录的 `users/<用户标识>/cookies.json` 下；文件会尝试收紧为仅运行用户可读写。该目录应按凭据处理，备份、迁移和打包前需要确认不会泄露。
- 下载文件保存在 AstrBot 插件数据目录的 `downloads` 下，文件名会附加随机后缀以避免覆盖旧文件。
- 监控列表保存在插件数据目录的 `monitor.json`，写入时使用临时文件原子替换；损坏的 JSON 会备份为 `*.corrupt.*`。自动检查会按批次和并发上限处理，避免监控文件过大时阻塞管理命令。
- 生成 EPUB 前会移除脚本、事件属性、远程图片和不安全标签；图片下载有单图大小、总大小、数量和像素限制。

## 🔔 更新监控

使用 `/esj m add <小说URL或编号>` 添加当前会话的监控。插件会每隔 `monitor_interval_hours` 小时自动检查一次，默认 12 小时。

发现新章节时，插件会主动向添加监控的会话发送提醒，包含书籍编号、上次记录章节、当前最新章节、新章节页面，以及可直接使用的下载指令，例如：

```text
/esj d 123 21 25
```

发送提醒后，插件会自动把监控记录更新到最新章节，避免重复提醒同一批章节。

下载文件会保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_esjzone_downloader/downloads` 目录，并通过平台文件消息发送。

### 智能监控特性

插件的监控系统具备以下智能特性：

- **动态检查间隔**：根据书籍更新频率自动调整
  - 24 小时内更新：缩短间隔（0.5x）
  - 长期未更新：延长间隔（3x）
- **失败重试**：网络错误时自动重试（指数退避）
- **历史记录**：保存最近 1000 条检查记录
- **批量优化**：优先级队列调度

## 🎯 性能特性

### 下载性能
- ⚡ 异步并发下载（1-10 可配置）
- 🚦 速率限制（防止服务器限流）
- 📊 实时进度追踪
- 💾 双层缓存加速

### 内存优化
- 📦 大书籍自动分批处理（>100 章）
- 🌊 图片流式下载（降低内存峰值）
- 📈 内存监控和预警
- 📏 下载前文件大小估算

### 并发优化
- 🔄 自适应并发（根据错误率调整）
- 🔐 分段锁策略（避免锁竞争）
- 🎯 任务池管理
- ⚖️ 智能批次优化

### 错误处理
- 🏷️ 6 种错误分类
- 🔁 智能自动重试
- 💬 用户友好提示
- 📝 详细错误日志

## 📚 文档

- [API 使用文档](API_DOCUMENTATION.md) - 完整的命令说明和示例
- [架构文档](ARCHITECTURE.md) - 技术架构和模块设计
- [更新日志](CHANGELOG.md) - 版本变更历史
- [完成总结](V1.3.0_COMPLETION_REPORT.md) - v1.3.0 版本完成报告

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

### 开发指南

1. 阅读 [ARCHITECTURE.md](ARCHITECTURE.md) 了解架构
2. 遵循异步编程规范（asyncio）
3. 添加完整的类型注解和 docstring
4. 更新相关文档

## 📄 许可证

MIT License

## 🙏 致谢

- [AstrBot](https://github.com/Soulter/AstrBot) - 优秀的聊天机器人框架
- [esjzone-novel-downloader](https://github.com/HIUEETR/esjzone-novel-downloader) - 原始项目


