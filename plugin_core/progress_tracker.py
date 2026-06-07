"""下载进度追踪器"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class DownloadProgress:
    """下载进度数据"""
    total_chapters: int = 0
    completed_chapters: int = 0
    failed_chapters: int = 0
    total_images: int = 0
    completed_images: int = 0
    failed_images: int = 0
    bytes_downloaded: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def chapter_progress_percent(self) -> float:
        """章节下载进度百分比"""
        if self.total_chapters == 0:
            return 0.0
        return (self.completed_chapters / self.total_chapters) * 100

    @property
    def image_progress_percent(self) -> float:
        """图片下载进度百分比"""
        if self.total_images == 0:
            return 0.0
        return (self.completed_images / self.total_images) * 100

    @property
    def elapsed_seconds(self) -> float:
        """已用时间（秒）"""
        return time.time() - self.start_time

    @property
    def download_rate_kbps(self) -> float:
        """下载速率（KB/s）"""
        if self.elapsed_seconds <= 0:
            return 0.0
        return (self.bytes_downloaded / 1024) / self.elapsed_seconds

    def format_progress_message(self) -> str:
        """格式化进度消息"""
        lines = []

        if self.total_chapters > 0:
            lines.append(
                f"章节: {self.completed_chapters}/{self.total_chapters} "
                f"({self.chapter_progress_percent:.1f}%)"
            )
            if self.failed_chapters > 0:
                lines.append(f"  失败: {self.failed_chapters}")

        if self.total_images > 0:
            lines.append(
                f"图片: {self.completed_images}/{self.total_images} "
                f"({self.image_progress_percent:.1f}%)"
            )
            if self.failed_images > 0:
                lines.append(f"  失败: {self.failed_images}")

        if self.bytes_downloaded > 0:
            mb_downloaded = self.bytes_downloaded / (1024 * 1024)
            lines.append(
                f"已下载: {mb_downloaded:.2f} MB "
                f"({self.download_rate_kbps:.1f} KB/s)"
            )

        elapsed_min = int(self.elapsed_seconds / 60)
        elapsed_sec = int(self.elapsed_seconds % 60)
        lines.append(f"用时: {elapsed_min}分{elapsed_sec}秒")

        return "\n".join(lines)


class ProgressTracker:
    """
    下载进度追踪器

    功能：
    - 追踪下载进度
    - 定期发送进度消息
    - 估算剩余时间
    """

    def __init__(
        self,
        progress_callback: Optional[Callable[[str], None]] = None,
        update_interval: float = 5.0,
    ):
        """
        初始化进度追踪器

        Args:
            progress_callback: 进度更新回调函数
            update_interval: 更新间隔（秒）
        """
        self.progress = DownloadProgress()
        self.progress_callback = progress_callback
        self.update_interval = update_interval
        self._lock = asyncio.Lock()
        self._last_update = 0.0
        self._update_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self, total_chapters: int, total_images: int = 0) -> None:
        """
        开始追踪

        Args:
            total_chapters: 总章节数
            total_images: 总图片数
        """
        async with self._lock:
            self.progress = DownloadProgress(
                total_chapters=total_chapters,
                total_images=total_images,
            )
            self._stop_event.clear()

        if self.progress_callback:
            self._update_task = asyncio.create_task(self._periodic_update())

    async def stop(self) -> None:
        """停止追踪"""
        self._stop_event.set()
        if self._update_task:
            await self._update_task
            self._update_task = None

    async def update_chapter(self, completed: bool = True) -> None:
        """
        更新章节进度

        Args:
            completed: 是否成功完成
        """
        async with self._lock:
            if completed:
                self.progress.completed_chapters += 1
            else:
                self.progress.failed_chapters += 1

        await self._maybe_send_update()

    async def update_image(self, completed: bool = True) -> None:
        """
        更新图片进度

        Args:
            completed: 是否成功完成
        """
        async with self._lock:
            if completed:
                self.progress.completed_images += 1
            else:
                self.progress.failed_images += 1

        await self._maybe_send_update()

    async def add_bytes(self, size: int) -> None:
        """
        添加已下载字节数

        Args:
            size: 字节数
        """
        async with self._lock:
            self.progress.bytes_downloaded += size

    async def _maybe_send_update(self, force: bool = False) -> None:
        """可能发送进度更新"""
        now = time.time()
        if not force and (now - self._last_update) < self.update_interval:
            return

        self._last_update = now
        if self.progress_callback:
            message = self.progress.format_progress_message()
            try:
                self.progress_callback(message)
            except Exception:
                pass  # 忽略回调错误

    async def _periodic_update(self) -> None:
        """定期更新循环"""
        while not self._stop_event.is_set():
            await asyncio.sleep(self.update_interval)
            await self._maybe_send_update(force=True)

    def get_progress(self) -> DownloadProgress:
        """获取当前进度"""
        return self.progress
