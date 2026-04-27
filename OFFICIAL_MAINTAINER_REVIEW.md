# AstrBot 官方维护视角审查报告：astrbot_plugin_esjzone_downloader

审查日期：2026-04-28
审查对象：`D:\Work\Code\AstrBot\data\plugins\astrbot_plugin_esjzone_downloader`
审查范围：插件结构、凭据与 Cookie、网络请求、并发下载、数据持久化、文件写入、日志、依赖与运维安全、数据安全保存。
审查方式：静态代码审查；未执行真实 ESJ 网络请求，也未在 QQ/aiocqhttp 环境做端到端验证。

## 总体结论

插件已经具备不少基础安全控制：使用 `get_astrbot_plugin_data_path()` 将运行数据放入 AstrBot 数据目录；下载输出路径使用 `Path.resolve().relative_to()` 做边界检查；ESJ 输入 URL 限定为 HTTPS 和 `www.esjzone.one`；文件名做 Windows 非法字符过滤；监控 JSON 和 Cookie JSON 使用临时文件原子替换；生成 EPUB 前会移除脚本、事件属性、远程图片；图片下载有数量、单图大小、总大小、像素数与最终输出大小限制。

但从官方维护和上架风险角度看，仍有若干需要修复或明确告知的安全与运维问题。优先级最高的是：避免聊天命令承载明文密码、限制 HTTP 重定向的目标、避免在监控锁内执行长时间网络请求、对 Cookie/敏感文件做权限与生命周期治理，以及防止生成阶段在磁盘或内存层面突破资源预算。

## 审查发现与修复建议

| 编号 | 严重度 | 领域          | 结论                                                                                               |
| ---- | ------ | ------------- | -------------------------------------------------------------------------------------------------- |
|      |        |               |                                                                                                    |
| F-02 | 中高   | 网络请求      | `follow_redirects=True` 会先跟随站点重定向，再校验最终 URL，存在外跳访问面                       |
| F-03 | 中高   | 并发/监控     | `_monitor_lock` 覆盖网络请求，监控列表变大或站点卡顿时会阻塞所有监控管理命令                     |
| F-04 | 中     | 数据安全保存  | Cookie 明文 JSON 保存，缺少文件权限收紧、过期清理和域名白名单校验                                  |
| F-05 | 中     | 文件写入/资源 | 输出大小只在生成完成后校验，生成临时 EPUB/TXT 期间仍可能占满磁盘或内存                             |
| F-06 | 中     | 图片处理      | 图片字节预算只覆盖原始下载流，不覆盖 PNG 转码后的膨胀体积；Pillow 全局像素限制会影响同进程其他插件 |
| F-07 | 中     | 日志与隐私    | 日志包含会话来源、书名、URL、输出路径和异常详情，默认运维环境下可能泄露用户阅读偏好和文件布局      |
| F-08 | 中     | 依赖与供应链  | `requirements.txt` 只设置下限，不锁定上限/哈希；Pillow/HTML 解析栈需要更严格版本治理             |
| F-09 | 低中   | 数据持久化    | `monitor.json` 为单文件共享状态，缺少记录数量上限和分片策略，长期运行会变成可用性瓶颈            |
|      |        |               |                                                                                                    |

---

## F-02：重定向目标在请求后才校验

**位置**：`plugin_core/downloader.py:480-499` 创建 `httpx.AsyncClient(follow_redirects=True)`，`_request()` 和 `_download_image()` 在收到响应后调用 `_validate_esj_url(str(response.url))`。**现状**：初始 URL 会校验为 ESJ 官方域名，但 `httpx` 会自动跟随 3xx 跳转；如果 ESJ 页面、图片地址或登录接口返回外部 `Location`，客户端会先向外部地址发起请求，之后才因最终 URL 不合规而抛错。**风险**：这削弱了“只访问 ESJ 官方域名”的承诺；在站点异常、被投毒、被中间页面诱导时，机器人宿主可能对外部域名或内网地址发起请求。**建议修复**：

1. 将客户端改为 `follow_redirects=False`，在 `_request()` / `_download_image()` 内手动处理最多 3-5 次重定向。
2. 每次读取 `Location` 后先用 `urljoin(current_url, location)` 解析，再调用 `_validate_esj_url()`，校验通过才继续请求。
3. 对登录 POST 的重定向单独处理，避免把 POST body 转发到非预期地址。
4. 在日志中只记录已通过校验的规范化 URL。

## F-03：监控锁覆盖长时间网络请求

**位置**：`main.py:524-566` 的 `_check_monitor_updates()`。**现状**：函数在 `async with self._monitor_lock:` 内读取 `monitor.json` 后，继续循环调用 `await self.service.get_book_info(url)`。这意味着整个网络检查过程期间，`m add/list/rm/check` 都需要等待同一把锁。**风险**：当监控条目较多、ESJ 响应慢、网络超时或重试时，用户无法查看或移除监控；自动监控任务也可能和手动检查互相阻塞。**建议修复**：

1. 锁内只做“读取快照”和“写回合并”，不要在锁内做网络请求。
2. 流程改为：锁内读取 entries -> 锁外按限流并发检查 -> 锁内按 `book_id + unified_msg_origin` 合并最新状态并写回。
3. 为监控检查单独设置并发上限和每轮最大处理条数，避免后台任务压垮站点或机器人进程。
4. 对同一 URL 的缓存可保留，但缓存构建应在锁外进行。

## F-04：Cookie 明文保存缺少权限与生命周期治理

**位置**：`plugin_core/downloader.py:512-558`，Cookie 保存到 `data/plugin_data/astrbot_plugin_esjzone_downloader/users/<scope>/cookies.json`。**现状**：Cookie 按用户 scope 隔离，这是正确方向；但文件内容为明文 JSON，写入后未设置更严格的文件权限，也没有保存 `expires`、`secure`、`httponly` 等属性或定期清理策略。加载时也未过滤非 ESJ 域名 Cookie。**风险**：宿主机其他本地用户、备份系统、误上传或插件目录打包都可能暴露登录态；被篡改的 Cookie JSON 也可能污染客户端 CookieJar。**建议修复**：

1. 写入 Cookie 后收紧权限：POSIX 使用 `chmod 600`；Windows 优先继承 AstrBot 数据目录私有 ACL，必要时文档要求独立运行用户。
2. 保存 Cookie 时保留并校验 `domain/path/expires/secure` 等属性；加载时仅接受 `www.esjzone.one` 或 `.esjzone.one` 且 path 合规的 Cookie。
3. 增加 Cookie 过期清理和 `/esj logout all`（管理员）等运维命令。
4. 在 README 明确 `data/plugin_data/.../users` 属敏感目录，备份和迁移时需要按凭据处理。
5. 如 AstrBot 后续提供 secret store，应迁移 Cookie 到统一凭据存储。

## F-05：输出大小在生成完成后才校验

**位置**：`plugin_core/downloader.py:659-670`，`plugin_core/downloader.py:856-859`。**现状**：`_write_output_atomic()` 先完整生成临时文件，再调用 `_ensure_output_size()` 检查最终大小。**风险**：恶意或异常章节内容、图片转码膨胀、章节数上限配置过高时，临时文件可能在被拒绝前已经占用大量磁盘；EPUB 构建过程也可能持有大量图片字节，造成内存压力。**建议修复**：

1. 在 EPUB writer 内实现计量写入，累计 ZIP entry 原始大小和压缩后文件大小，超过 `max_output_bytes` 立即中止。
2. TXT 输出改为流式写入并累计字节数，而不是先拼接大列表再一次性 `write_text()`。
3. 将 `max_chapters_per_download`、`max_images_per_download`、`max_total_image_bytes` 与 `max_output_bytes` 做联动校验，避免配置组合本身不合理。
4. 定期清理失败残留、历史下载文件，或提供管理员清理命令。

## F-06：图片处理预算仍有绕过与进程级副作用

**位置**：`plugin_core/downloader.py:383-414` 下载原始图片，`plugin_core/downloader.py:866-875` `_normalize_image_bytes()`。**现状**：下载阶段限制的是原始响应字节和像素数；非 GIF 会统一转 PNG，转码后的 PNG 可能明显大于原始 WebP/JPEG。函数还会设置 `Image.MAX_IMAGE_PIXELS = max_pixels`，这是 Pillow 的进程级全局变量。**风险**：最终 EPUB 可能因为转码膨胀导致磁盘/内存压力；在 AstrBot 同一进程内，修改 Pillow 全局限制会影响其他插件的图片处理行为。**建议修复**：

1. 对 `_normalize_image_bytes()` 的返回值再次计入预算，超过单图或总输出预算时丢弃图片。
2. 优先保留安全的原始格式（JPEG/PNG/WebP/GIF）并校验 MIME 与实际格式，减少强制 PNG 转码带来的膨胀。
3. 避免在每次调用中修改全局 `Image.MAX_IMAGE_PIXELS`；如必须设置，应在插件初始化时固定一个保守值并记录，或在调用前后恢复旧值。
4. 对 `Image.open()` 增加 `verify()` 或更严格的异常处理，区分格式错误与安全拒绝。

## F-07：日志包含可关联用户阅读行为的信息

**位置**：`main.py` 多处 `logger.info/warning`，`plugin_core/downloader.py` 多处 `logger.info/warning`。**现状**：日志会记录 `event.unified_msg_origin`、输入 URL/规范化 URL、书名、章节数、输出路径、监控来源、异常详情等。未发现密码或 Cookie 直接入日志，这是优点。**风险**：在共享运维、日志集中采集或问题排查导出时，用户的阅读偏好、QQ 会话来源和本地数据目录结构会被暴露。**建议修复**：

1. 默认 INFO 日志只记录匿名 request id、book_id、操作类型和耗时；书名、完整路径、origin 放到 DEBUG。
2. 对 `unified_msg_origin`、sender、scope 做哈希或截断显示。
3. 异常日志避免输出包含完整 URL 的第三方错误对象；统一用脱敏函数处理 URL、路径和账号。
4. 用户可见错误编号已经存在，建议将内部错误详情只保留在 DEBUG 或管理员可见日志。

## F-08：依赖版本治理不足

**位置**：`requirements.txt`。**现状**：依赖为 `beautifulsoup4>=4.12.0`、`httpx>=0.28.1`、`pillow>=10.0.0`，只有下限没有上限、没有锁文件、没有哈希。**风险**：插件部署在不同 AstrBot 实例时会解析到不同依赖版本；Pillow 属于高风险解析库，httpx 行为变化也可能影响重定向、Cookie 或代理处理。**建议修复**：

1. 对插件发布包使用经过验证的兼容范围，例如 `httpx>=0.28,<0.29`、`pillow>=10,<12`，并随 AstrBot 主项目依赖策略调整。
2. 在发布流程中增加 `pip-audit`/`uv audit` 或等价漏洞扫描。
3. 如果 AstrBot 插件市场支持锁定依赖，发布时附带 lock 或哈希。
4. 在 README 标注最低 Python/AstrBot 版本和已验证平台。

## F-09：监控状态单文件共享，缺少规模控制

**位置**：`main.py:665-677` 读写 `monitor.json`，`main.py:401-466` 添加/删除逻辑。**现状**：所有会话的监控条目写入同一个 `monitor.json`，按 `unified_msg_origin + book_id` 去重；单条字段长度有裁剪，但没有总条数、单会话条数或文件大小限制。**风险**：公开群聊中长期使用后，监控文件会增长；每轮自动检查需要读取并遍历全量 entries，最终影响启动、写入和后台检查。**建议修复**：

1. 增加全局最大监控条数、单会话最大条数和单轮检查上限。
2. 将状态按会话或 hash 分片保存，例如 `monitors/<safe_origin>.json`，避免单文件成为热点。
3. 保存前做 schema 校验和去重清理；对长期失败、长期无更新或超过 TTL 的记录自动暂停。
4. 提供管理员命令查看总量、清理过期监控和导出诊断摘要。

## 已做得较好的安全点

- 插件运行数据放在 AstrBot 插件数据目录下，而不是源代码目录。
- URL 输入限定为 ESJ HTTPS 官方详情页或纯数字书籍编号，并拒绝反斜杠、控制字符和 URL 用户认证信息。
- 下载输出路径在 `downloads` 根目录下做解析后边界检查，文件名也过滤 Windows 保留字符和非法字符。
- Cookie 按 `platform:sender_id` 派生 scope，私聊登录态不会直接和群聊下载共享。
- JSON 写入采用临时文件 + `fsync` + replace，损坏 JSON 会备份，降低状态文件损坏后的恢复成本。
- EPUB 内容会清理脚本、事件属性、远程图片和不安全标签，降低生成文件内嵌主动内容风险。
- 图片下载有重试、超时、响应类型、单图大小、总下载大小、数量和像素限制。

## 建议修复顺序

1. **先修 F-02**：这是最直接的凭据与网络边界风险，影响官方插件可信度。
2. **再修 F-03/F-04**：提升长期运行和多用户使用安全性，避免后台任务拖死命令面。
3. **随后修 F-05/F-06/F-09**：完善资源预算和规模控制，防止大书籍/大图片造成磁盘或内存压力。
4. **最后修 F-07/F-08**：完成日志脱敏、依赖治理和发布包整理。

## 推荐验收清

- Cookie 文件仍能按用户隔离生效。
- 构造 ESJ 站内 URL 返回外部 `Location` 时，插件不会向外部地址发起后续请求。
- 监控列表有 100+ 条、ESJ 请求超时时，`/esj m list` 和 `/esj m rm` 不会被长时间阻塞。
- Cookie JSON 文件权限和内容符合预期；篡改为非 ESJ 域名 Cookie 后不会被加载。
- 构造超大 TXT/EPUB、超大图片、转码膨胀图片时，插件能在生成过程中及时中止，并清理临时文件。
- 默认 INFO 日志不出现完整 `unified_msg_origin`、完整本地输出路径、账号、Cookie 或密码。
