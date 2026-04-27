# astrbot_plugin_esjzone_downloader 安全与可靠性审查报告

审查日期：2026-04-28
审查范围：`D:\Work\Code\AstrBot\data\plugins\astrbot_plugin_esjzone_downloader`
审查身份：AstrBot 项目所有者视角，重点关注安全隐患、并发问题、数据持久化安全与可维护性改进。

## 总体结论

该插件功能拆分清晰，核心下载逻辑与 AstrBot 命令层已基本分离，数据目录也使用了 AstrBot 插件数据路径。但当前实现仍存在几类需要优先处理的问题：

1. 用户输入 URL 未限制到 ESJ 官方域，存在 SSRF/内网探测风险。
2. 登录态、Cookie、收藏列表、配置均为全局共享，群聊或多用户场景下容易泄露账号权益或互相覆盖状态。
3. `monitor.json` 与 `cookies.json` 使用普通 `write_text` 直接覆盖，且部分读改写没有纳入锁，存在并发丢写和文件损坏风险。
4. 图片下载与 EPUB/TXT 生成缺少资源上限，可能被异常页面或恶意图片造成内存、磁盘和 CPU 消耗。
5. EPUB 内容直接嵌入站点 HTML 与元数据，缺少输出净化，可能生成带脚本/事件属性的主动内容或破坏 XHTML 结构。
6. 命令权限边界不够清晰，任何可触达命令的会话都可以触发登录、收藏读取、全局配置修改或长时间下载。

建议把“域名白名单 + 权限/会话隔离 + 原子持久化 + 资源限额”作为第一阶段修复目标，然后再补充 EPUB 净化、日志脱敏和下载文件生命周期管理。

## 风险清单与解决方法

### 1. URL 规范化允许访问任意外部地址（高优先级）

**位置**：`plugin_core/downloader.py:501-507`、`plugin_core/downloader.py:246`、`plugin_core/downloader.py:272-274`
**现状**：`normalize_url()` 对非纯数字输入直接使用 `urljoin(ESJ_BASE_URL, cleaned)`。当 `cleaned` 是 `http://127.0.0.1:...`、`http://169.254.169.254/...` 或其它绝对 URL 时，`urljoin` 会保留该外部地址。章节内图片 `src` 也通过 `urljoin(chapter.url, src)` 生成，随后直接请求。

**影响**：任何可使用 `/esj i`、`/esj c`、`/esj d`、`/esj m add` 的用户都可能让机器人请求内网、云元数据地址或任意第三方站点，形成 SSRF、内网探测、日志污染和资源消耗风险。

**解决方法**：

- 在 `normalize_url()` 中解析 URL 后强制要求：`scheme == "https"`，`hostname` 必须是 `www.esjzone.one` 或明确允许的 ESJ 域名。
- 对纯数字输入继续转换为 `https://www.esjzone.one/detail/<id>.html`。
- 对相对路径只允许 `/detail/...`、`/forum/...` 等 ESJ 站内路径，转换后再次校验域名。
- 在 `_process_images()` 下载图片前同样调用一个 `validate_esj_asset_url()`；如必须允许 CDN，维护显式 CDN 白名单。
- 对重定向后的最终 URL 也应检查域名，避免站点页面或中间跳转把请求带到内网/第三方地址。

### 2. 登录与 Cookie 全局共享，且可在群聊中触发（高优先级）

**位置**：`main.py:208-217`、`plugin_core/downloader.py:40`、`plugin_core/downloader.py:358-374`
**现状**：`/esj login <邮箱> <密码>` 可直接把 Cookie 保存到插件全局 `cookies.json`，后续 `/esj fav` 和下载都复用同一个 HTTP client 与同一份 Cookie。

**影响**：

- 群聊中输入密码会暴露给群成员、平台消息记录和可能的上游日志。
- 多个 QQ 用户会共享同一个 ESJ 登录态，后登录者覆盖前登录者，收藏列表和受限内容可能被其它会话读取。
- Cookie 明文落盘，一旦 AstrBot 数据目录被其它插件、备份系统或宿主用户读取，就可以复用登录态。

**解决方法**：

- 默认禁止群聊登录；`/esj login`、`/esj fav` 只允许私聊，或只允许管理员/白名单用户。
- 改为 per-user 登录态：`plugin_data/astrbot_plugin_esjzone_downloader/users/<safe_sender_id>/cookies.json`，服务层按 `event.get_sender_id()` 获取对应 cookie jar。
- 不建议在聊天命令中传明文密码；更安全方案是只支持后台配置、一次性 Cookie 导入，或引导用户私聊机器人后立即删除提示消息（如果平台支持）。
- Cookie 文件应设置最小权限；Windows 可至少避免写到源码目录，Unix 环境可 `chmod 600`。
- 增加 `/esj logout`，清除当前用户 Cookie，并在 README 中说明登录态保存位置和风险。

### 3. 全局配置命令缺少权限控制（高优先级）

**位置**：`main.py:270-320`、`main.py:642-661`
**现状**：`/esj cfg` 可以从聊天修改全局配置，包括并发数、超时、重试、监控开关和监控间隔。未见管理员校验、会话类型校验或配置值上限。

**影响**：普通用户可把 `max_threads`、`retry_attempts`、`retry_delays`、`monitor_interval_hours` 调到极端值，造成请求风暴、长期后台任务、CPU/内存/磁盘消耗，或影响所有其它用户的使用体验。

**解决方法**：

- 修改配置前检查操作者是否为 AstrBot 管理员、插件 owner 白名单或私聊 owner。
- 给数值配置设置上限：例如 `max_threads` 1-10、`timeout_seconds` 5-300、`retry_attempts` 0-5、`monitor_interval_hours` 0.5-168。
- 对普通用户只开放查询当前有效配置，不开放写入。
- 如果确实需要用户级偏好，应写入 per-user 配置文件，而不是改全局 `AstrBotConfig`。

### 4. `monitor.json` 读改写没有统一锁与原子写（中高优先级）

**位置**：`main.py:326-334`、`main.py:379-398`、`main.py:452-494`、`main.py:594-608`
**现状**：后台监控 `_check_monitor_updates()` 使用 `_monitor_lock`，但 `monitor_add()`、`monitor_remove()`、`monitor_list()` 直接读写同一个 `monitor.json`。保存时用 `write_text` 直接覆盖目标文件。

**影响**：当用户添加/删除监控与后台检查同时发生时，可能出现丢写：例如用户刚添加的条目被后台用旧 entries 覆盖。进程崩溃、磁盘满或写入中断时，`monitor.json` 可能只写入半截，下一次加载失败后返回空列表，导致监控状态丢失。

**解决方法**：

- 所有涉及监控状态的读改写都放入同一个 `asyncio.Lock`，包括 add/remove/list/check。
- 保存采用原子写：先写 `monitor.json.tmp`，`flush/fsync` 后用 `Path.replace()` 替换正式文件。
- 保存前做 schema 归一化，只保留必要字段，限制标题长度和 URL 长度。
- 读取失败时不要静默返回空列表；应备份坏文件为 `monitor.json.corrupt.<timestamp>`，并通知管理员或记录 error 级日志。
- 数据量增长后可考虑 per-origin 分文件，减少单文件锁竞争与损坏影响范围。

### 5. `cookies.json` 明文保存且非原子写（中高优先级）

**位置**：`plugin_core/downloader.py:358-374`
**现状**：Cookie 值以 JSON 明文写入 `cookies.json`，保存方式也是直接 `write_text`。

**影响**：Cookie 是登录凭据，泄露后可绕过密码使用账号。直接覆盖也可能因并发登录/校验/退出或进程中断导致文件损坏，进而登录态丢失。

**解决方法**：

- 至少改为 per-user Cookie 文件，并用原子写替代直接覆盖。
- 增加 Cookie 文件权限收紧；如框架支持密钥管理，可用本机密钥或 AstrBot secret store 加密后落盘。
- Cookie 读写加独立锁，避免登录、校验、收藏读取同时修改同一个 cookie jar。
- 日志不要输出 cookie 文件绝对路径；可以只输出相对插件数据目录路径或 cookie 数量。

### 6. 下载任务缺少资源上限，可能导致内存/磁盘/CPU DoS（中高优先级）

**位置**：`main.py:156-203`、`plugin_core/downloader.py:232`、`plugin_core/downloader.py:269`、`plugin_core/downloader.py:552-558`、`plugin_core/downloader.py:602-606`
**现状**：虽然有全局 `_download_lock` 和 `_semaphore`，但 `gather_all()` 会为所有章节/图片一次性创建任务；图片响应完整读入内存后再交给 PIL 转码，没有 `Content-Length`、MIME、像素数、总图片数、总 EPUB 大小或下载章节数限制。

**影响**：恶意页面或异常章节列表可创建大量 task，占用内存；超大图片或压缩炸弹可触发 PIL 高 CPU/高内存；最终 EPUB/TXT 和下载目录可无限增长，拖垮机器人所在主机。

**解决方法**：

- 限制单次下载章节数、图片数、单图字节数、总图片字节数、最终文件大小。
- HTTP 下载使用 streaming，读取时累计字节数，超过上限立即中断。
- 对图片检查 `Content-Type`、`Content-Length`，并设置 `PIL.Image.MAX_IMAGE_PIXELS` 或捕获 `DecompressionBombError`。
- `gather_all()` 改为 worker 队列或分批处理，避免为几千章节一次性创建几千个任务。
- 增加下载目录定期清理、按用户/会话限额、最大保留天数和最大总容量。

### 7. EPUB 生成未净化 HTML，可能嵌入主动内容或破坏 XHTML（中优先级）

**位置**：`plugin_core/downloader.py:401-446`、`plugin_core/epub.py:72-84`
**现状**：章节正文来自站点 `.forum-content`，几乎原样作为 `body_content` 写入 XHTML；简介页中书名、作者、标签、章节标题和简介也直接拼接为 HTML。

**影响**：如果源页面或解析结果包含 `<script>`、事件属性、外链 iframe、异常标签或未转义字符，生成的 EPUB 可能包含主动内容、隐私追踪外链，或产生格式损坏。即使 ESJ 当前页面可信，也不应把远端 HTML 当作安全输出。

**解决方法**：

- 使用 allowlist HTML sanitizer，只保留段落、标题、换行、图片、强调、列表、链接等必要标签。
- 移除 `script/style/iframe/object/embed/form` 和所有 `on*` 事件属性。
- 链接和图片只允许安全协议；EPUB 内图片应全部改为本地 `images/...`。
- 拼接简介页时对书名、作者、标签、简介、章节标题使用 `html.escape()`。
- 写入 XHTML 前可用 XML parser 做一次结构校验，失败则降级为纯文本内容。

### 8. 全局 HTTP client 与 Cookie jar 在并发请求下共享状态（中优先级）

**位置**：`plugin_core/downloader.py:41`、`plugin_core/downloader.py:315-331`、`plugin_core/downloader.py:128-134`
**现状**：插件服务层只有一个 `httpx.AsyncClient`。`get_favorites()` 会修改 `favorite_sort` cookie；登录、校验、下载、监控也共用同一 client 和 cookie jar。

**影响**：并发执行收藏列表、登录、监控或下载时，请求间可能互相影响 cookie 状态；多用户场景下尤其容易把 A 的登录态用于 B 的请求。

**解决方法**：

- 按用户隔离 client/cookie jar，或每次请求构造独立 cookie jar。
- 对会修改 cookie 的操作加锁，或不要通过共享 cookie 设置收藏排序，改为只依赖 URL 路径。
- 后台监控如果不需要登录态，应使用无 cookie client，避免把用户登录态带到自动请求里。

### 9. 下载文件命名和覆盖策略不够稳妥（中优先级）

**位置**：`plugin_core/downloader.py:476-499`
**现状**：同一本书同一格式每次输出到同一路径，下一次下载会覆盖旧文件；标题清理只移除 Windows 禁用字符，没有限制长度、保留名和尾随点/空格。

**影响**：并发或重复下载时可能覆盖正在发送的文件；极长标题在 Windows 下可能触发路径过长；`CON`、`NUL` 等保留名或尾随点可能导致异常。

**解决方法**：

- 文件名增加安全截断、保留名处理、尾随点/空格移除。
- 输出到临时文件，完成后原子替换；发送时使用本次任务唯一文件名或包含时间戳/短 hash。
- 对下载目录做 per-book/per-user 分层，并记录可清理的 manifest。

### 10. 错误信息直接回显给聊天端，可能泄露内部细节（中低优先级）

**位置**：`main.py:133`、`main.py:153`、`main.py:205-216`、`main.py:267`、`main.py:319`、`main.py:350`、`main.py:405`、`main.py:421`
**现状**：多个命令直接 `yield event.plain_result(f"...失败：{exc}")`，异常对象可能包含完整 URL、路径、HTTP 状态、解析细节或内部文件路径。

**影响**：普通群成员可能看到宿主路径、内部 URL、错误栈摘要或第三方页面细节，便于进一步探测。

**解决方法**：

- 对用户只返回通用错误和短错误码，例如“下载失败，请稍后重试或联系管理员（ESJ-DL-001）”。
- 详细异常写日志，但对 URL 查询参数、账号、cookie、路径做脱敏。
- 对可预期错误用自定义异常分类，用户侧只显示可操作提示。

### 11. 监控通知目标依赖持久化的 `unified_msg_origin`，缺少有效性校验（中低优先级）

**位置**：`main.py:508-511`、`main.py:594-608`
**现状**：`monitor.json` 中保存的 `unified_msg_origin` 会被后台任务用于 `context.send_message()`。如果文件被误改或损坏，插件会尝试向任意 origin 发送消息。

**影响**：虽然本地文件被篡改通常已是宿主侧风险，但插件不做校验会放大误配置影响，可能向错误会话发送更新提醒。

**解决方法**：

- 保存时记录平台、会话类型、sender/group id 等结构化字段，发送前重新构造并校验。
- 对 origin 做格式校验，只允许当前平台支持的合法 origin。
- 对来源用户不可见的监控条目不允许 list/rm/check。

### 12. README 未充分说明安全边界和数据保存位置（低优先级）

**位置**：`README.md`、`_conf_schema.json`
**现状**：README 说明了命令用法，但没有明确提示 Cookie 明文保存、登录命令应私聊使用、下载文件保留策略、配置命令权限要求和监控数据保存位置。

**影响**：部署者容易在群聊中直接使用登录命令，也不清楚需要保护 `plugin_data` 目录。

**解决方法**：

- README 增加“安全说明”章节，列明 Cookie、下载文件、监控列表的保存位置和清理方式。
- 明确建议只在私聊登录，群聊禁用敏感命令。
- 如果实现权限控制，同步文档中的管理员/白名单配置说明。

## 推荐修复路线

### 第一阶段：阻断高风险入口

1. 为所有用户可控 URL 添加 ESJ 域名白名单和重定向后校验。
2. 禁止群聊使用 `/esj login`、`/esj fav`、`/esj cfg set`，并增加管理员/白名单校验。
3. 为 `max_threads`、`retry_attempts`、`retry_delays`、`monitor_interval_hours` 设置合理上限。
4. 用户侧错误回显改为安全提示，日志做 URL/路径/账号脱敏。

### 第二阶段：修复持久化和并发一致性

1. `monitor.json`、`cookies.json` 改为原子写。
2. 所有监控读改写统一使用 `_monitor_lock`。
3. Cookie/client 改为 per-user 或至少对登录态读写加锁。
4. 读取 JSON 失败时备份坏文件并提示管理员，不要无声清空状态。

### 第三阶段：资源控制和输出净化

1. 下载章节数、图片数、单图大小、总文件大小、下载目录容量加限额。
2. 图片下载改 streaming，验证 MIME 与像素数，防御压缩炸弹。
3. EPUB 生成前净化 HTML，简介页所有插值做 `html.escape()`。
4. 输出文件使用唯一临时路径，发送后按策略清理。

### 第四阶段：文档和运维可见性

1. README 增加安全说明、数据保存路径、清理策略和权限模型。
2. 增加结构化日志字段，但避免敏感信息。
3. 增加最小回归测试：URL 白名单、监控并发写、原子写、HTML 净化、资源限额。

## 建议的验收标准

- 输入 `http://127.0.0.1:6185`、`//127.0.0.1/...`、`https://evil.example/...` 会被拒绝，不产生网络请求。
- 群聊中调用 `/esj login`、`/esj fav`、`/esj cfg max_threads 9999` 被拒绝或要求管理员权限。
- 并发执行 `monitor add/rm/check` 不会丢失已有监控项，进程中断不会留下半截 JSON。
- Cookie 文件按用户隔离，A 用户登录后 B 用户不能读取 A 的收藏列表。
- 超大图片、超多章节、超大 EPUB 会被明确拒绝并留下安全日志。
- 生成的 EPUB 不包含 `<script>`、事件属性或远程主动内容。
