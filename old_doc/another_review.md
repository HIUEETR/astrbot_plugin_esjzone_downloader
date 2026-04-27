1. P0 任意出网 + Windows 路径穿越写入风险
   data/plugins/astrbot_plugin_esjzone_downloader/plugin_core/downloader.py:501 的 normalize_url() 接受任意绝对 URL，_request
   () 会直接访问；同时 data/plugins/astrbot_plugin_esjzone_downloader/plugin_core/downloader.py:509 的 book_id() 从 URL 最后
   一段直接生成目录名，data/plugins/astrbot_plugin_esjzone_downloader/plugin_core/downloader.py:476 又把它拼到 downloads_dir
   下。Windows 下 ..\..\evil 会被当成父级跳转路径，恶意 URL 加伪造页面可让插件向非 ESJ 域发请求，并把 EPUB/TXT 写出下载目录。
   修复方向：只接受数字 ID 或 https://www.esjzone.one/detail/`<digits>`.html，book_id 只能来自正则捕获的数字；最终输出路径 reso
   lve() 后必须 relative_to(downloads_dir)。
2. P0/P1 登录态全插件共享，任意聊天用户可覆盖或读取同一个 ESJ 账号数据
   插件只创建一个 EsjzoneDownloadService（data/plugins/astrbot_plugin_esjzone_downloader/main.py:53），Cookie 固定保存到同一个
   cookies.json（data/plugins/astrbot_plugin_esjzone_downloader/plugin_core/downloader.py:40）。/esj login 没有限权（data/
   plugins/astrbot_plugin_esjzone_downloader/main.py:208），/esj fav 使用共享 Cookie 读取收藏夹（data/plugins/
   astrbot_plugin_esjzone_downloader/plugin_core/downloader.py:123）。群里任何人都可能覆盖机器人账号，或查看前一个登录者的收藏
   内容。修复方向：登录、收藏、配置类命令加管理员/私聊限制，或者按 unified_msg_origin/用户隔离 Cookie。
3. P1 明文凭据和 Cookie 持久化仍不安全
   配置 schema 仍支持账号密码字段，/esj login <邮箱> <密码> 也会把密码留在聊天平台记录里（data/plugins/
   astrbot_plugin_esjzone_downloader/main.py:209）。Cookie 原样写入 JSON（data/plugins/astrbot_plugin_esjzone_downloader/
   plugin_core/downloader.py:358）。修复方向：不建议保留密码配置；登录仅允许私聊管理员临时输入，或改为后台配置 Cookie；保存
   Cookie 时至少限制文件权限，并提供清除命令。
4. P1 /esj cfg 无权限控制，可被任意用户持久修改插件配置
   data/plugins/astrbot_plugin_esjzone_downloader/main.py:270 暴露配置修改命令，随后直接 save_config()（data/plugins/
   astrbot_plugin_esjzone_downloader/main.py:664）。这允许普通用户调整 max_threads、重试、监控间隔等运行参数。修复方向：配置修
   改必须加 AstrBot 管理员权限过滤；并给 max_threads、章节数、监控数量设置上限。
5. P1 监控数据非原子写入且和后台任务存在丢更新竞态
   monitor add/rm 直接读写 monitor.json（data/plugins/astrbot_plugin_esjzone_downloader/main.py:332、data/plugins/
   astrbot_plugin_esjzone_downloader/main.py:379），后台检查只在 _check_monitor_updates() 内持有锁（data/plugins/
   astrbot_plugin_esjzone_downloader/main.py:457），保存是直接覆盖写入（data/plugins/astrbot_plugin_esjzone_downloader/
   main.py:605）。并发 add/rm/check 时可能互相覆盖。修复方向：所有 monitor 读改写统一走同一把锁，并用临时文件 + Path.replace()
   行。恶意或超大书籍会拖慢整个 Bot。修复方向：限制章节数、图片数、单文件大小、总输出大小；EPUB 构建和图片转码放到线程池。
