# Official Maintainer Remediation Tasks

Source review: `OFFICIAL_MAINTAINER_REVIEW.md`.

- [x] F-02: Disable automatic redirects and manually validate every ESJ redirect target before following it.
- [x] F-03: Keep monitor state locks around local read/write only, and move network checks outside the lock with per-round limits.
- [x] F-04: Harden Cookie persistence with domain/path/expires validation, permission tightening, expiry cleanup, and admin logout-all support.
- [x] F-05: Enforce output byte budgets during TXT/EPUB generation instead of only after full temporary file creation.
- [x] F-06: Count normalized image bytes against budgets and avoid permanent Pillow global pixel-limit side effects.
- [x] F-07: Reduce INFO logs to operation/book IDs and anonymized origins; keep sensitive details out of default logs.
- [x] F-08: Narrow dependency version ranges and document verified runtime expectations.
- [x] F-09: Add monitor scale limits, duplicate cleanup, and bounded automatic check batches.
- [x] Run formatting/static checks and record verification results.

Verification:

- `ruff format data\plugins\astrbot_plugin_esjzone_downloader`
- `ruff check data\plugins\astrbot_plugin_esjzone_downloader`
- `python -m compileall data\plugins\astrbot_plugin_esjzone_downloader`
- `python -m json.tool data\plugins\astrbot_plugin_esjzone_downloader\_conf_schema.json`
- Stubbed smoke check passed for ESJ URL rejection, safe redirect handling, HTML sanitization, and EPUB output budget enforcement.
