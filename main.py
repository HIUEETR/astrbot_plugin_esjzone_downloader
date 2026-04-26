from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File, Node, Nodes, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .plugin_core.downloader import EsjzoneDownloadService

PLUGIN_NAME = "astrbot_plugin_esjzone_downloader"


@register(
    PLUGIN_NAME,
    "HIUEETR",
    "ESJ Zone 小说下载插件，支持 QQ 平台发送 EPUB/TXT 文件",
    "1.0.0",
)
class EsjzoneDownloaderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.service = EsjzoneDownloadService(dict(self.config), self.data_dir)
        self._download_lock = asyncio.Lock()

    async def terminate(self):
        await self.service.close()

    @filter.command_group("esj")
    def esj(self):
        pass

    @esj.command("help")
    async def help(self, event: AstrMessageEvent):
        """查看 ESJ Zone 下载插件帮助。"""
        yield event.plain_result(
            "\n".join(
                [
                    "ESJ Zone 小说下载",
                    "/esj info <小说URL或编号> - 合并转发书籍简介、编号和章节数",
                    "/esj fav [lastest|collected] [页码] - 合并转发收藏列表，默认 lastest",
                    "/esj check <小说URL或编号> - 查看最近更新状态",
                    "/esj download <小说URL或编号> [epub|txt] [起始章节] [结束章节] - 下载并发送文件",
                    "/esj login <邮箱> <密码> - 登录并保存 Cookie",
                    "",
                    "下载未指定格式时默认 EPUB；也支持省略格式直接写章节范围。",
                    "示例：/esj download 123",
                    "示例：/esj download 123 1 20",
                    "示例：/esj download 123 txt",
                    "",
                    "配置项 file_naming_mode 可控制发送文件名：book_name 或 book_id。",
                ]
            )
        )

    @esj.command("info")
    async def info(self, event: AstrMessageEvent, url: str):
        """查看 ESJ Zone 小说简介。"""
        try:
            logger.info(f"[ESJ] info command from {event.unified_msg_origin}: {url}")
            book = await self.service.get_book_info(url)
            book_id = self.service.book_id(book.url)
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
                f"[ESJ] info command succeeded: {book.title}, chapters={len(book.chapters)}"
            )
            yield event.chain_result([Nodes(nodes)])
        except Exception as exc:
            logger.warning(f"[ESJ] info failed: {exc}")
            yield event.plain_result(f"获取书籍信息失败：{exc}")

    @esj.command("check")
    async def check(self, event: AstrMessageEvent, url: str):
        """查看 ESJ Zone 小说最近更新状态。"""
        try:
            logger.info(f"[ESJ] check command from {event.unified_msg_origin}: {url}")
            status = await self.service.get_novel_status(url)
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
            logger.warning(f"[ESJ] check failed: {exc}")
            yield event.plain_result(f"检查更新失败：{exc}")

    @esj.command("download")
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
            logger.info(
                f"[ESJ] download command from {event.unified_msg_origin}: "
                f"url={normalized_url}, format={fmt}, start={start or 'first'}, "
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
                )
                logger.info(
                    f"[ESJ] download command succeeded: {result.book.title}, "
                    f"path={result.output_path}"
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
            logger.warning(f"[ESJ] download failed: {exc}")
            yield event.plain_result(f"下载失败：{exc}")

    @esj.command("login")
    async def login(self, event: AstrMessageEvent, email: str = "", password: str = ""):
        """登录 ESJ Zone 并保存 Cookie。"""
        try:
            logger.info(f"[ESJ] login command from {event.unified_msg_origin}")
            username = await self.service.login(email or None, password or None)
            yield event.plain_result(f"登录成功：{username}")
        except Exception as exc:
            logger.warning(f"[ESJ] login failed: {exc}")
            yield event.plain_result(f"登录失败：{exc}")

    @esj.command("fav")
    async def favorites(
        self,
        event: AstrMessageEvent,
        sort_by: str = "lastest",
        page: int = 1,
    ):
        """查看 ESJ Zone 收藏列表。"""
        try:
            if sort_by.isdigit():
                page = int(sort_by)
                sort_by = "lastest"
            logger.info(
                f"[ESJ] favorites command from {event.unified_msg_origin}: "
                f"sort={sort_by}, page={page}"
            )
            novels, total_pages = await self.service.get_favorites(page, sort_by)
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
            logger.warning(f"[ESJ] favorites failed: {exc}")
            yield event.plain_result(f"获取收藏列表失败：{exc}")

    def _node(self, event: AstrMessageEvent, text: str) -> Node:
        return Node(
            uin=event.get_self_id() or event.get_sender_id() or "0",
            name="ESJ Zone",
            content=[Plain(text)],
        )

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
