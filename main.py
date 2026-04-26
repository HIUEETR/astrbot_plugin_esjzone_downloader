from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File, Plain
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
                    "/esj info <小说URL> - 查看书籍与章节信息",
                    "/esj download <小说URL> [epub|txt] [起始章节] [结束章节] - 下载并发送文件",
                    "/esj check <小说URL> - 查看最近更新状态",
                    "/esj login <邮箱> <密码> - 登录并保存 Cookie",
                    "/esj fav [new|favor] [页码] - 查看收藏列表",
                    "示例：/esj download https://www.esjzone.one/detail/123.html epub 1 20",
                ]
            )
        )

    @esj.command("info")
    async def info(self, event: AstrMessageEvent, url: str):
        """查看 ESJ Zone 小说基本信息。"""
        try:
            book = await self.service.get_book_info(url)
            preview = "\n".join(
                f"{chapter.index}. {chapter.title}" for chapter in book.chapters[:10]
            )
            if len(book.chapters) > 10:
                preview += f"\n... 共 {len(book.chapters)} 章"
            yield event.plain_result(
                "\n".join(
                    [
                        f"标题：{book.title}",
                        f"作者：{book.author}",
                        f"最近更新：{book.update_time or '未知'}",
                        f"章节数：{len(book.chapters)}",
                        f"标签：{', '.join(book.tags) if book.tags else '无'}",
                        "",
                        preview or "未解析到章节。",
                    ]
                )
            )
        except Exception as exc:
            logger.warning(f"[ESJ] info failed: {exc}")
            yield event.plain_result(f"获取书籍信息失败：{exc}")

    @esj.command("check")
    async def check(self, event: AstrMessageEvent, url: str):
        """查看 ESJ Zone 小说最近更新状态。"""
        try:
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

        yield event.plain_result("已开始下载，章节较多时可能需要几分钟。")
        async with self._download_lock:
            try:
                result = await self.service.download_book(
                    url=url,
                    fmt=fmt or None,
                    start_chapter=start or None,
                    end_chapter=end or None,
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
            username = await self.service.login(email or None, password or None)
            yield event.plain_result(f"登录成功：{username}")
        except Exception as exc:
            logger.warning(f"[ESJ] login failed: {exc}")
            yield event.plain_result(f"登录失败：{exc}")

    @esj.command("fav")
    async def favorites(
        self,
        event: AstrMessageEvent,
        sort_by: str = "new",
        page: int = 1,
    ):
        """查看 ESJ Zone 收藏列表。"""
        try:
            novels, total_pages = await self.service.get_favorites(page, sort_by)
            if not novels:
                yield event.plain_result("收藏列表为空，或当前登录状态无效。")
                return
            lines = [f"收藏列表 第 {page}/{total_pages} 页："]
            for idx, novel in enumerate(novels[:10], start=1):
                lines.append(
                    f"{idx}. {novel.get('title', '未知标题')}\n"
                    f"   最新：{novel.get('latest_chapter') or '未知'}\n"
                    f"   更新：{novel.get('update_time') or '未知'}\n"
                    f"   {novel.get('url') or ''}"
                )
            yield event.plain_result("\n".join(lines))
        except Exception as exc:
            logger.warning(f"[ESJ] favorites failed: {exc}")
            yield event.plain_result(f"获取收藏列表失败：{exc}")
