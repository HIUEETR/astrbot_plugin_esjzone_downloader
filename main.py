from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File, Node, Nodes, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .plugin_core.downloader import EsjzoneDownloadService
from .plugin_core.model import Book

PLUGIN_NAME = "astrbot_plugin_esjzone_downloader"

CONFIG_ITEMS = {
    "file_naming_mode": (
        "download",
        "file_naming_mode",
        "choice",
        {"book_name", "book_id"},
    ),
    "use_book_dir": ("download", "use_book_dir", "bool", None),
    "download_images": ("download", "download_images", "bool", None),
    "max_threads": ("download", "max_threads", "int", (1, 10)),
    "timeout_seconds": ("download", "timeout_seconds", "int", (5, 300)),
    "retry_attempts": ("download", "retry_attempts", "int", (0, 5)),
    "retry_delays": ("download", "retry_delays", "float_list", (0.0, 300.0, 5)),
    "max_chapters_per_download": (
        "download",
        "max_chapters_per_download",
        "int",
        (1, 1000),
    ),
    "max_images_per_download": (
        "download",
        "max_images_per_download",
        "int",
        (0, 2000),
    ),
    "max_image_bytes": ("download", "max_image_bytes", "int", (1024, 50 * 1024 * 1024)),
    "max_total_image_bytes": (
        "download",
        "max_total_image_bytes",
        "int",
        (1024, 500 * 1024 * 1024),
    ),
    "max_image_pixels": (
        "download",
        "max_image_pixels",
        "int",
        (1_000_000, 100_000_000),
    ),
    "max_output_bytes": (
        "download",
        "max_output_bytes",
        "int",
        (1024, 1024 * 1024 * 1024),
    ),
    "monitor_enabled": ("monitor", "enabled", "bool", None),
    "monitor_interval_hours": ("monitor", "interval_hours", "float", (0.5, 168.0)),
    "monitor_max_entries": ("monitor", "max_entries", "int", (1, 5000)),
    "monitor_max_entries_per_origin": (
        "monitor",
        "max_entries_per_origin",
        "int",
        (1, 200),
    ),
    "monitor_check_batch_size": (
        "monitor",
        "check_batch_size",
        "int",
        (1, 500),
    ),
    "monitor_check_concurrency": (
        "monitor",
        "check_concurrency",
        "int",
        (1, 10),
    ),
}


@register(
    PLUGIN_NAME,
    "HIUEETR",
    "ESJ Zone 小说下载插件，支持 QQ 平台发送 EPUB/TXT 文件",
    "1.0.0",
)
class EsjzoneDownloaderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config if config is not None else {}
        self.data_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.monitor_path = self.data_dir / "monitor.json"
        self.service = EsjzoneDownloadService(dict(self.config), self.data_dir)
        self._download_lock = asyncio.Lock()
        self._monitor_lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._ensure_monitor_task()

    async def terminate(self):
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._monitor_task
        await self.service.close()

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        self._ensure_monitor_task()

    @filter.command_group("esj")
    def esj(self):
        pass

    @esj.command("help", alias={"h"})
    async def help(self, event: AstrMessageEvent):
        """查看 ESJ Zone 下载插件帮助。"""
        yield event.plain_result(
            "\n".join(
                [
                    "ESJ Zone 小说下载",
                    "/esj i <小说URL或编号> - 合并转发书籍简介、编号和章节数",
                    "/esj f [lastest|collected] [页码] - 合并转发收藏列表，默认 lastest",
                    "/esj c <小说URL或编号> - 查看最近更新状态",
                    "/esj d <小说URL或编号> [epub|txt] [起始章节] [结束章节] - 下载并发送文件",
                    "/esj l <邮箱> <密码> - 私聊登录并保存当前用户 Cookie",
                    "/esj logout - 私聊清除当前用户 Cookie",
                    "/esj cfg [配置项] [值] - 查看或修改插件配置",
                    "/esj m add <小说URL或编号> - 添加当前会话的更新监控",
                    "/esj m list - 查看当前会话的监控列表",
                    "/esj m rm <小说URL或编号|all> - 移除监控",
                    "/esj m check - 立即检查当前会话监控更新",
                    "",
                    "完整指令仍可使用：info/fav/check/download/login/config/monitor。",
                    "下载未指定格式时默认 EPUB；也支持省略格式直接写章节范围。",
                    "示例：/esj d 123",
                    "示例：/esj d 123 1 20",
                    "示例：/esj d 123 txt",
                    "示例：/esj cfg file_naming_mode book_id",
                ]
            )
        )

    @esj.command("info", alias={"i"})
    async def info(self, event: AstrMessageEvent, url: str):
        """查看 ESJ Zone 小说简介。"""
        try:
            book = await self.service.get_book_info(url)
            book_id = self.service.book_id(book.url)
            logger.info(
                f"[ESJ] info command: origin={_hash_for_log(event.unified_msg_origin)}, "
                f"book_id={book_id}"
            )
            nodes = [
                self._node(
                    event,
                    "\n".join(
                        [
                            f"标题：{book.title}",
                            f"编号：{book_id}",
                            f"作者：{book.author}",
                            f"最近更新：{book.update_time or '未知'}",
                            f"章节数：{len(book.chapters)}",
                            f"标签：{', '.join(book.tags) if book.tags else '无'}",
                        ]
                    ),
                )
            ]
            intro = book.introduction.strip() or "暂无简介。"
            for idx, chunk in enumerate(_split_text(intro), start=1):
                title = "简介" if idx == 1 else f"简介（续 {idx}）"
                nodes.append(self._node(event, f"{title}\n\n{chunk}"))
            logger.info(
                f"[ESJ] info command succeeded: book_id={book_id}, "
                f"chapters={len(book.chapters)}"
            )
            yield event.chain_result([Nodes(nodes)])
        except Exception as exc:
            logger.warning(f"[ESJ] info failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("获取书籍信息失败", exc))

    @esj.command("check", alias={"c"})
    async def check(self, event: AstrMessageEvent, url: str):
        """查看 ESJ Zone 小说最近更新状态。"""
        try:
            status = await self.service.get_novel_status(url)
            logger.info(
                f"[ESJ] check command: origin={_hash_for_log(event.unified_msg_origin)}, "
                f"book_id={self._safe_book_id(status.get('url') or url)}"
            )
            yield event.plain_result(
                "\n".join(
                    [
                        f"标题：{status.get('title') or '未知'}",
                        f"最新章节：{status.get('latest_chapter') or '未知'}",
                        f"更新时间：{status.get('update_time') or '未知'}",
                        f"链接：{status.get('url') or url}",
                    ]
                )
            )
        except Exception as exc:
            logger.warning(f"[ESJ] check failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("检查更新失败", exc))

    @esj.command("download", alias={"d"})
    async def download(
        self,
        event: AstrMessageEvent,
        url: str,
        fmt: str = "",
        start: int = 0,
        end: int = 0,
    ):
        """下载 ESJ Zone 小说并发送文件。"""
        if self._download_lock.locked():
            yield event.plain_result("已有下载任务正在执行，请稍后再试。")
            return

        try:
            fmt, start, end = _normalize_download_args(fmt, start, end)
            normalized_url = self.service.normalize_url(url)
            book_id = self.service.book_id(normalized_url)
            logger.info(
                f"[ESJ] download command: "
                f"origin={_hash_for_log(event.unified_msg_origin)}, "
                f"book_id={book_id}, format={fmt}, start={start or 'first'}, "
                f"end={end or 'last'}"
            )
            yield event.plain_result(
                f"已开始下载 {fmt.upper()}，章节较多时可能需要几分钟。"
            )
            async with self._download_lock:
                result = await self.service.download_book(
                    url=url,
                    fmt=fmt,
                    start_chapter=start or None,
                    end_chapter=end or None,
                    user_key=self._private_user_key(event),
                )
                logger.info(
                    f"[ESJ] download command succeeded: book_id={book_id}, "
                    f"file={result.output_path.name}"
                )
                yield event.chain_result(
                    [
                        Plain(
                            "下载完成："
                            f"{result.book.title}\n"
                            f"章节：{result.chapter_count}，图片：{result.image_count}"
                        ),
                        File(
                            file=str(result.output_path), name=result.output_path.name
                        ),
                    ]
                )
        except Exception as exc:
            logger.warning(f"[ESJ] download failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("下载失败", exc))

    @esj.command("login", alias={"l"})
    async def login(self, event: AstrMessageEvent, email: str = "", password: str = ""):
        """登录 ESJ Zone 并保存 Cookie。"""
        try:
            blocked = self._require_private_chat(event, "登录")
            if blocked:
                yield event.plain_result(blocked)
                return
            logger.info(
                f"[ESJ] login command: origin={_hash_for_log(event.unified_msg_origin)}"
            )
            username = await self.service.login(
                email or None,
                password or None,
                user_key=self._user_key(event),
            )
            yield event.plain_result(f"登录成功：{username}")
        except Exception as exc:
            logger.warning(f"[ESJ] login failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("登录失败", exc))

    @esj.command("logout")
    async def logout(self, event: AstrMessageEvent, target: str = ""):
        """清除当前用户 ESJ Zone Cookie。"""
        try:
            if target.strip().lower() == "all":
                if not self._is_admin(event):
                    yield event.plain_result("只有管理员可以清除全部 ESJ 登录态。")
                    return
                deleted = await self.service.clear_all_logins()
                yield event.plain_result(f"已清除 {deleted} 个用户的 ESJ 登录态。")
                return
            blocked = self._require_private_chat(event, "退出登录")
            if blocked:
                yield event.plain_result(blocked)
                return
            await self.service.clear_login(self._user_key(event))
            yield event.plain_result("已清除当前用户的 ESJ 登录态。")
        except Exception as exc:
            logger.warning(f"[ESJ] logout failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("退出登录失败", exc))

    @esj.command("fav", alias={"f"})
    async def favorites(
        self,
        event: AstrMessageEvent,
        sort_by: str = "lastest",
        page: int = 1,
    ):
        """查看 ESJ Zone 收藏列表。"""
        try:
            blocked = self._require_private_chat(event, "收藏列表")
            if blocked:
                yield event.plain_result(blocked)
                return
            if sort_by.isdigit():
                page = int(sort_by)
                sort_by = "lastest"
            logger.info(
                f"[ESJ] favorites command: "
                f"origin={_hash_for_log(event.unified_msg_origin)}, "
                f"sort={sort_by}, page={page}"
            )
            novels, total_pages = await self.service.get_favorites(
                page,
                sort_by,
                user_key=self._user_key(event),
            )
            if not novels:
                yield event.plain_result("收藏列表为空，或当前登录状态无效。")
                return
            nodes = [
                self._node(
                    event,
                    f"收藏列表\n排序：{sort_by}\n页码：{page}/{total_pages}\n数量：{len(novels)}",
                )
            ]
            for idx, novel in enumerate(novels[:10], start=1):
                book_id = self._safe_book_id(novel.get("url") or "")
                nodes.append(
                    self._node(
                        event,
                        "\n".join(
                            [
                                f"{idx}. {novel.get('title', '未知标题')}",
                                f"编号：{book_id}",
                                f"最新：{novel.get('latest_chapter') or '未知'}",
                                f"更新：{novel.get('update_time') or '未知'}",
                                f"上次观看：{novel.get('last_viewed') or '未知'}",
                            ]
                        ),
                    )
                )
            logger.info(
                f"[ESJ] favorites command succeeded: sort={sort_by}, "
                f"page={page}, items={len(novels)}"
            )
            yield event.chain_result([Nodes(nodes)])
        except Exception as exc:
            logger.warning(f"[ESJ] favorites failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("获取收藏列表失败", exc))

    @esj.command("cfg", alias={"config"})
    async def config_command(
        self,
        event: AstrMessageEvent,
        action: str = "",
        key: str = "",
        value: str = "",
    ):
        """查看或修改 ESJ Zone 下载器配置。"""
        try:
            action = action.strip()
            if not action or action == "list":
                yield event.plain_result(self._format_config())
                return

            if action == "get":
                if not key:
                    yield event.plain_result("用法：/esj cfg get <配置项>")
                    return
                yield event.plain_result(self._format_config(key))
                return

            if action == "set":
                target_key = key
                raw_value = value
            else:
                target_key = action
                raw_value = key

            if not target_key or not raw_value:
                yield event.plain_result("用法：/esj cfg <配置项> <值>")
                return

            if not self._is_admin(event):
                yield event.plain_result("只有管理员可以修改 ESJ 全局配置。")
                return

            parsed_value = self._parse_config_value(target_key, raw_value)
            section_name, option_name, _value_type, _extra = CONFIG_ITEMS[target_key]
            section = self.config.setdefault(section_name, {})
            if not isinstance(section, dict):
                section = {}
                self.config[section_name] = section
            section[option_name] = parsed_value
            self._save_plugin_config()
            self.service.reload_config(dict(self.config))
            self._ensure_monitor_task()
            logger.info(
                f"[ESJ] config updated: "
                f"origin={_hash_for_log(event.unified_msg_origin)}, "
                f"{target_key}={parsed_value}"
            )
            yield event.plain_result(f"配置已更新：{target_key} = {parsed_value}")
        except Exception as exc:
            logger.warning(f"[ESJ] config command failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("配置修改失败", exc))

    @esj.group("monitor", alias={"m", "mon"})
    def monitor(self):
        pass

    @monitor.command("add", alias={"a"})
    async def monitor_add(self, event: AstrMessageEvent, url: str):
        """添加当前会话的 ESJ 更新监控。"""
        try:
            book = await self.service.get_book_info(url)
            entry = self._entry_from_book(book, event)
            async with self._monitor_lock:
                entries = self._load_monitor_entries()
                entries = self._upsert_monitor_entry(entries, entry)
                self._save_monitor_entries(entries)
            logger.info(
                f"[ESJ] monitor added: "
                f"origin={_hash_for_log(event.unified_msg_origin)}, "
                f"book_id={entry['book_id']}"
            )
            yield event.plain_result(
                "\n".join(
                    [
                        "已添加更新监控：",
                        f"标题：{entry['title']}",
                        f"编号：{entry['book_id']}",
                        f"当前最新：{entry.get('latest_chapter') or '未知'}",
                    ]
                )
            )
        except Exception as exc:
            logger.warning(f"[ESJ] monitor add failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("添加监控失败", exc))

    @monitor.command("list", alias={"ls"})
    async def monitor_list(self, event: AstrMessageEvent):
        """查看当前会话的 ESJ 更新监控列表。"""
        async with self._monitor_lock:
            entries = [
                entry
                for entry in self._load_monitor_entries()
                if entry.get("unified_msg_origin") == event.unified_msg_origin
            ]
        if not entries:
            yield event.plain_result("当前会话没有监控书籍。")
            return
        lines = [f"当前会话监控列表：{len(entries)} 本"]
        for idx, entry in enumerate(entries[:20], start=1):
            lines.append(
                f"{idx}. {entry.get('title') or '未知标题'} "
                f"({entry.get('book_id') or '未知编号'}) - "
                f"{entry.get('latest_chapter') or '未知章节'}"
            )
        if len(entries) > 20:
            lines.append(f"还有 {len(entries) - 20} 本未显示。")
        yield event.plain_result("\n".join(lines))

    @monitor.command("rm", alias={"remove", "del", "r"})
    async def monitor_remove(self, event: AstrMessageEvent, url: str):
        """移除当前会话的 ESJ 更新监控。"""
        try:
            target_book_id = "all"
            async with self._monitor_lock:
                entries = self._load_monitor_entries()
                before_count = len(entries)
                if url.lower() == "all":
                    entries = [
                        entry
                        for entry in entries
                        if entry.get("unified_msg_origin") != event.unified_msg_origin
                    ]
                else:
                    book_id = self.service.book_id(url)
                    target_book_id = book_id
                    entries = [
                        entry
                        for entry in entries
                        if not (
                            entry.get("unified_msg_origin") == event.unified_msg_origin
                            and entry.get("book_id") == book_id
                        )
                    ]
                removed_count = before_count - len(entries)
                self._save_monitor_entries(entries)
            logger.info(
                f"[ESJ] monitor removed: "
                f"origin={_hash_for_log(event.unified_msg_origin)}, "
                f"book_id={target_book_id}, removed={removed_count}"
            )
            yield event.plain_result(f"已移除 {removed_count} 条监控。")
        except Exception as exc:
            logger.warning(f"[ESJ] monitor remove failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("移除监控失败", exc))

    @monitor.command("check", alias={"c"})
    async def monitor_check(self, event: AstrMessageEvent):
        """立即检查当前会话的 ESJ 监控更新。"""
        try:
            updates = await self._check_monitor_updates(
                origin=event.unified_msg_origin,
                send_notifications=False,
            )
            if not updates:
                yield event.plain_result("当前会话监控列表没有发现新章节。")
                return
            yield event.plain_result("\n\n".join(update["text"] for update in updates))
        except Exception as exc:
            logger.warning(f"[ESJ] monitor check failed: {_safe_exception(exc)}")
            yield event.plain_result(self._format_user_error("检查监控失败", exc))

    def _ensure_monitor_task(self) -> None:
        if not self._monitor_enabled():
            return
        if self._monitor_task is not None and not self._monitor_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("[ESJ] monitor task start delayed: no running event loop")
            return
        self._monitor_task = loop.create_task(
            self._monitor_loop(),
            name=f"{PLUGIN_NAME}_monitor",
        )
        logger.info("[ESJ] monitor task started")

    async def _monitor_loop(self) -> None:
        await asyncio.sleep(min(30.0, self._monitor_interval_seconds()))
        while True:
            try:
                if self._monitor_enabled():
                    await self._check_monitor_updates(send_notifications=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[ESJ] monitor loop failed: {_safe_exception(exc)}")
            await asyncio.sleep(self._monitor_interval_seconds())

    async def _check_monitor_updates(
        self,
        origin: str | None = None,
        send_notifications: bool = True,
    ) -> list[dict[str, str]]:
        async with self._monitor_lock:
            entries = self._load_monitor_entries()
            if origin and not any(
                entry.get("unified_msg_origin") == origin for entry in entries
            ):
                return []
            target_entries = [
                dict(entry)
                for entry in entries
                if (not origin or entry.get("unified_msg_origin") == origin)
                and entry.get("url")
            ][: self._monitor_check_batch_size()]

        logger.info(
            f"[ESJ] monitor check started: total={len(target_entries)}, "
            f"origin={_hash_for_log(origin) if origin else '*'}"
        )
        book_cache = await self._fetch_monitor_books(target_entries)

        updates: list[dict[str, str]] = []
        changed = False
        target_keys = {_monitor_entry_key(entry) for entry in target_entries}
        now = int(time.time())
        async with self._monitor_lock:
            entries = self._load_monitor_entries()
            for entry in entries:
                if _monitor_entry_key(entry) not in target_keys:
                    continue
                url = str(entry.get("url") or "")
                book = book_cache.get(url)
                if book is None:
                    continue
                update = self._refresh_monitor_entry(entry, book, now)
                changed = True
                if update:
                    updates.append(update)

            if changed:
                self._save_monitor_entries(entries)

        if send_notifications:
            for update in updates:
                await self._send_monitor_notification(update)
        logger.info(f"[ESJ] monitor check finished: updates={len(updates)}")
        return updates

    async def _fetch_monitor_books(
        self,
        entries: list[dict[str, Any]],
    ) -> dict[str, Book]:
        urls = list(dict.fromkeys(str(entry.get("url") or "") for entry in entries))
        urls = [url for url in urls if url]
        semaphore = asyncio.Semaphore(self._monitor_check_concurrency())
        results: dict[str, Book] = {}

        async def fetch(url: str) -> None:
            async with semaphore:
                try:
                    results[url] = await self.service.get_book_info(url)
                except Exception as exc:
                    logger.warning(
                        "[ESJ] monitor check failed for "
                        f"{self._safe_book_id(url)}: {_safe_exception(exc)}"
                    )

        await asyncio.gather(*(fetch(url) for url in urls))
        return results

    async def _send_monitor_notification(self, update: dict[str, str]) -> None:
        origin = update.get("origin")
        text = update.get("text") or ""
        if not origin or not text:
            return
        try:
            await self.context.send_message(origin, MessageChain(chain=[Plain(text)]))
            logger.info(
                f"[ESJ] monitor notification sent: origin={_hash_for_log(origin)}"
            )
        except Exception as exc:
            logger.warning(
                "[ESJ] monitor notification failed: "
                f"origin={_hash_for_log(origin)}, error={_safe_exception(exc)}"
            )

    def _refresh_monitor_entry(
        self,
        entry: dict[str, Any],
        book: Book,
        now: int,
    ) -> dict[str, str] | None:
        book_id = self.service.book_id(book.url)
        latest_chapter = book.chapters[-1].title if book.chapters else ""
        latest_url = book.chapters[-1].url if book.chapters else book.url
        latest_index = len(book.chapters)
        old_chapter = str(entry.get("latest_chapter") or "")
        old_index = _safe_int(entry.get("latest_index"), 0, 0)
        start_index = self._new_chapter_start_index(book, old_chapter, old_index)

        entry.update(
            {
                "book_id": book_id,
                "url": book.url,
                "title": book.title,
                "latest_chapter": latest_chapter,
                "latest_index": latest_index,
                "update_time": book.update_time or "",
                "updated_at": now,
            }
        )

        if not old_chapter or not latest_chapter or latest_chapter == old_chapter:
            return None
        if start_index < 1 or start_index > latest_index:
            return None

        text = "\n".join(
            [
                "ESJ 更新提醒",
                f"标题：{book.title}",
                f"编号：{book_id}",
                f"上次记录：{old_chapter or '未知'}",
                f"当前最新：{latest_chapter}",
                f"更新时间：{book.update_time or '未知'}",
                f"新章节页面：{latest_url}",
                f"下载指令：/esj d {book_id} {start_index} {latest_index}",
            ]
        )
        return {"origin": str(entry.get("unified_msg_origin") or ""), "text": text}

    def _new_chapter_start_index(
        self,
        book: Book,
        old_chapter: str,
        old_index: int,
    ) -> int:
        latest_index = len(book.chapters)
        if old_index > 0 and latest_index > old_index:
            return old_index + 1
        if old_chapter:
            for idx, chapter in enumerate(book.chapters, start=1):
                if chapter.title == old_chapter and latest_index > idx:
                    return idx + 1
        if old_chapter and latest_index > 0:
            return latest_index
        return 0

    def _entry_from_book(
        self,
        book: Book,
        event: AstrMessageEvent,
    ) -> dict[str, Any]:
        now = int(time.time())
        return {
            "book_id": self.service.book_id(book.url),
            "url": book.url,
            "title": book.title,
            "latest_chapter": book.chapters[-1].title if book.chapters else "",
            "latest_index": len(book.chapters),
            "update_time": book.update_time or "",
            "unified_msg_origin": event.unified_msg_origin,
            "created_by": event.get_sender_id() or "",
            "created_at": now,
            "updated_at": now,
        }

    def _load_monitor_entries(self) -> list[dict[str, Any]]:
        if not self.monitor_path.exists():
            return []
        data = _read_json_with_corrupt_backup(self.monitor_path)
        if isinstance(data, list):
            return _dedupe_monitor_entries(
                [item for item in data if isinstance(item, dict)]
            )
        return []

    def _save_monitor_entries(self, entries: list[dict[str, Any]]) -> None:
        _write_json_atomic(
            self.monitor_path, [_normalize_monitor_entry(e) for e in entries]
        )

    def _upsert_monitor_entry(
        self,
        entries: list[dict[str, Any]],
        entry: dict[str, Any],
    ) -> list[dict[str, Any]]:
        entries = _dedupe_monitor_entries(entries)
        for idx, old_entry in enumerate(entries):
            if (
                old_entry.get("unified_msg_origin") == entry["unified_msg_origin"]
                and old_entry.get("book_id") == entry["book_id"]
            ):
                entries[idx] = entry
                return entries
        origin_count = sum(
            1
            for old_entry in entries
            if old_entry.get("unified_msg_origin") == entry["unified_msg_origin"]
        )
        if len(entries) >= self._monitor_max_entries():
            raise ValueError(f"监控总数不能超过 {self._monitor_max_entries()}。")
        if origin_count >= self._monitor_max_entries_per_origin():
            raise ValueError(
                f"当前会话监控数量不能超过 {self._monitor_max_entries_per_origin()}。"
            )
        entries.append(entry)
        return entries

    def _format_config(self, only_key: str | None = None) -> str:
        keys = [only_key] if only_key else CONFIG_ITEMS.keys()
        lines = ["ESJ 当前配置："]
        for key in keys:
            if key not in CONFIG_ITEMS:
                raise ValueError(f"未知配置项：{key}")
            section_name, option_name, _value_type, _extra = CONFIG_ITEMS[key]
            section = self.config.get(section_name, {})
            value = section.get(option_name) if isinstance(section, dict) else None
            lines.append(f"{key} = {value}")
        if not only_key:
            lines.append("")
            lines.append("用法：/esj cfg <配置项> <值>")
            lines.append("布尔值支持 true/false，retry_delays 使用逗号分隔。")
        return "\n".join(lines)

    def _parse_config_value(self, key: str, raw_value: str) -> Any:
        if key not in CONFIG_ITEMS:
            raise ValueError(f"未知配置项：{key}")
        _section_name, _option_name, value_type, extra = CONFIG_ITEMS[key]
        if value_type == "choice":
            value = raw_value.strip()
            if value not in extra:
                raise ValueError(f"{key} 只支持：{', '.join(sorted(extra))}")
            return value
        if value_type == "bool":
            return _parse_bool_strict(raw_value)
        if value_type == "int":
            minimum, maximum = _bounds(extra, 0, None)
            parsed = int(raw_value)
            if parsed < minimum or (maximum is not None and parsed > maximum):
                max_text = f" 到 {maximum}" if maximum is not None else " 以上"
                raise ValueError(f"{key} 范围：{minimum}{max_text}。")
            return parsed
        if value_type == "float":
            minimum, maximum = _bounds(extra, 0.0, None)
            parsed = float(raw_value)
            if parsed < minimum or (maximum is not None and parsed > maximum):
                max_text = f" 到 {maximum}" if maximum is not None else " 以上"
                raise ValueError(f"{key} 范围：{minimum}{max_text}。")
            return parsed
        if value_type == "float_list":
            values = [item.strip() for item in raw_value.split(",") if item.strip()]
            if not values:
                raise ValueError("retry_delays 不能为空。")
            minimum, maximum, max_items = _list_bounds(extra, 0.0, 300.0, 5)
            if len(values) > max_items:
                raise ValueError(f"retry_delays 最多 {max_items} 项。")
            parsed_values = [float(item) for item in values]
            for parsed in parsed_values:
                if parsed < minimum or parsed > maximum:
                    raise ValueError(f"retry_delays 每项范围：{minimum} 到 {maximum}。")
            return parsed_values
        raise ValueError(f"不支持的配置类型：{value_type}")

    def _save_plugin_config(self) -> None:
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            save_config()
        else:
            logger.warning("[ESJ] config object does not support save_config")

    def _monitor_config(self) -> dict[str, Any]:
        monitor = self.config.get("monitor", {})
        return monitor if isinstance(monitor, dict) else {}

    def _monitor_enabled(self) -> bool:
        return _parse_bool(self._monitor_config().get("enabled", True))

    def _monitor_interval_seconds(self) -> float:
        try:
            interval_hours = float(self._monitor_config().get("interval_hours", 12))
        except (TypeError, ValueError):
            interval_hours = 12
        return min(max(interval_hours, 0.5), 168.0) * 3600

    def _monitor_max_entries(self) -> int:
        return _safe_int(self._monitor_config().get("max_entries"), 1000, 1, 5000)

    def _monitor_max_entries_per_origin(self) -> int:
        return _safe_int(
            self._monitor_config().get("max_entries_per_origin"),
            50,
            1,
            200,
        )

    def _monitor_check_batch_size(self) -> int:
        return _safe_int(
            self._monitor_config().get("check_batch_size"),
            100,
            1,
            500,
        )

    def _monitor_check_concurrency(self) -> int:
        return _safe_int(
            self._monitor_config().get("check_concurrency"),
            3,
            1,
            10,
        )

    def _node(self, event: AstrMessageEvent, text: str) -> Node:
        return Node(
            uin=event.get_self_id() or event.get_sender_id() or "0",
            name="ESJ Zone",
            content=[Plain(text)],
        )

    def _is_private_chat(self, event: AstrMessageEvent) -> bool:
        is_private = getattr(event, "is_private_chat", None)
        if callable(is_private):
            return bool(is_private())
        return not bool(event.get_group_id())

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        is_admin = getattr(event, "is_admin", None)
        if callable(is_admin):
            return bool(is_admin())
        return getattr(event, "role", "") == "admin"

    def _require_private_chat(
        self,
        event: AstrMessageEvent,
        action_name: str,
    ) -> str | None:
        if self._is_private_chat(event):
            return None
        return f"{action_name}涉及账号登录态，只允许在私聊中使用。"

    def _user_key(self, event: AstrMessageEvent) -> str:
        platform = str(event.get_platform_name() or "unknown").strip() or "unknown"
        sender_id = str(event.get_sender_id() or "").strip()
        if not sender_id:
            sender_id = str(event.unified_msg_origin or "unknown").strip()
        return f"{platform}:{sender_id}"

    def _private_user_key(self, event: AstrMessageEvent) -> str | None:
        if not self._is_private_chat(event):
            return None
        return self._user_key(event)

    def _format_user_error(self, message: str, exc: Exception) -> str:
        if isinstance(exc, ValueError):
            return f"{message}：{exc}"
        error_id = uuid.uuid4().hex[:8]
        logger.warning(f"[ESJ] user-facing error id={error_id}: {_safe_exception(exc)}")
        logger.debug(f"[ESJ] user-facing error detail id={error_id}: {exc}")
        return f"{message}，请稍后重试或联系管理员。错误编号：ESJ-{error_id}"

    def _safe_book_id(self, url: str) -> str:
        try:
            return self.service.book_id(url)
        except Exception:
            return "未知"


def _normalize_download_args(fmt: str, start: int, end: int) -> tuple[str, int, int]:
    fmt = (fmt or "").strip().lower()
    if not fmt:
        return "epub", start, end
    if fmt in {"epub", "txt"}:
        return fmt, start, end
    if fmt.isdigit():
        return "epub", int(fmt), start
    raise ValueError("下载格式只支持 epub 或 txt。")


def _split_text(text: str, limit: int = 1500) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        candidate = f"{current}\n{line}".strip() if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks


def _monitor_entry_key(entry: dict[str, Any]) -> tuple[str, str]:
    origin = str(entry.get("unified_msg_origin") or "")
    book_id = str(entry.get("book_id") or entry.get("url") or "")
    return origin, book_id


def _dedupe_monitor_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        key = _monitor_entry_key(entry)
        if not key[0] or not key[1]:
            continue
        deduped[key] = entry
    return list(deduped.values())


def _normalize_monitor_entry(entry: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "book_id": 32,
        "url": 500,
        "title": 200,
        "latest_chapter": 300,
        "update_time": 100,
        "unified_msg_origin": 300,
        "created_by": 100,
    }
    normalized: dict[str, Any] = {}
    for key, max_len in fields.items():
        value = entry.get(key, "")
        normalized[key] = str(value or "")[:max_len]
    for key in ("latest_index", "created_at", "updated_at"):
        normalized[key] = _safe_int(entry.get(key), 0, 0)
    return normalized


def _hash_for_log(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return "none"
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=6).hexdigest()
    return digest


def _safe_exception(exc: Exception) -> str:
    return exc.__class__.__name__


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.replace(path)


def _read_json_with_corrupt_backup(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        backup_path = path.with_name(f"{path.name}.corrupt.{uuid.uuid4().hex[:8]}")
        try:
            path.replace(backup_path)
            logger.warning(
                f"[ESJ] moved corrupt JSON to {backup_path.name}: "
                f"{_safe_exception(exc)}"
            )
        except Exception as backup_exc:
            logger.warning(
                f"[ESJ] failed to backup corrupt JSON: {_safe_exception(backup_exc)}"
            )
        return None


def _bounds(
    extra: Any,
    default_minimum: int | float,
    default_maximum: int | float | None,
) -> tuple[Any, Any]:
    if isinstance(extra, tuple):
        if len(extra) >= 2:
            return extra[0], extra[1]
        if len(extra) == 1:
            return extra[0], default_maximum
    if extra is not None:
        return extra, default_maximum
    return default_minimum, default_maximum


def _list_bounds(
    extra: Any,
    default_minimum: float,
    default_maximum: float,
    default_max_items: int,
) -> tuple[float, float, int]:
    if isinstance(extra, tuple) and len(extra) >= 3:
        return float(extra[0]), float(extra[1]), int(extra[2])
    return default_minimum, default_maximum, default_max_items


def _safe_int(
    value: Any,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disable", "disabled"}:
            return False
    return bool(value)


def _parse_bool_strict(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enable", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    raise ValueError("布尔配置只支持 true/false。")
