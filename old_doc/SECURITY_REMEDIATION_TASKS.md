# ESJ Zone Downloader Security Remediation Tasks

Source reviews: `another_review.md` and `SECURITY_REVIEW.md`.

- [x] Restrict all user-controlled URLs to allowed ESJ HTTPS hosts, reject redirects outside the allowlist, and derive `book_id` only from validated numeric detail URLs.
- [x] Ensure download output paths cannot escape the plugin download directory and use safer unique filenames.
- [x] Move login cookies to per-user storage and prevent one chat/user from reusing or overwriting another user's login state.
- [x] Restrict sensitive commands: login/favorites must run in private chat, and global configuration writes must require admin permission.
- [x] Add upper bounds for concurrency, retries, timeout, monitor interval, chapter count, image count, image bytes, and output size.
- [x] Serialize all monitor read-modify-write operations under the same lock.
- [x] Write monitor state and cookie JSON atomically, with corrupt JSON backup on load failure.
- [x] Limit download task creation with bounded batches and enforce image/EPUB resource limits.
- [x] Sanitize chapter and intro HTML before writing EPUB/XHTML.
- [x] Reduce user-facing error detail so internal paths, URLs, and stack details are not exposed in chat.
- [x] Update README and plugin configuration schema with the new security model and limits.
- [x] Run formatting/static checks and record the final verification result.

Verification:

- `ruff format data\plugins\astrbot_plugin_esjzone_downloader`
- `ruff check data\plugins\astrbot_plugin_esjzone_downloader`
- `python -m compileall data\plugins\astrbot_plugin_esjzone_downloader`
- Smoke check for URL rejection and HTML sanitization passed with an `astrbot.api.logger` stub because the local Python environment is missing the AstrBot `deprecated` dependency.
