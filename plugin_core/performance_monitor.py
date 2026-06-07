"""性能监控模块 - 下载性能统计和监控"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from astrbot.api import logger


@dataclass
class PerformanceMetrics:
    """性能指标数据类"""
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    total_chapters: int = 0
    completed_chapters: int = 0
    failed_chapters: int = 0
    total_images: int = 0
    completed_images: int = 0
    failed_images: int = 0
    total_bytes: int = 0

    def duration(self) -> float:
        if self.end_time == 0:
            return time.time() - self.start_time
        return self.end_time - self.start_time

    def download_speed(self) -> float:
        duration = self.duration()
        if duration <= 0:
            return 0.0
        return (self.total_bytes / 1024) / duration


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self):
        self.metrics = PerformanceMetrics()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self.metrics.start_time = time.time()
        logger.debug("[ESJ] 性能监控已启动")

    async def stop(self) -> None:
        self.metrics.end_time = time.time()
        logger.debug("[ESJ] 性能监控已停止")

    async def record_chapter(self, success: bool, size_bytes: int = 0) -> None:
        async with self._lock:
            self.metrics.total_chapters += 1
            if success:
                self.metrics.completed_chapters += 1
                self.metrics.total_bytes += size_bytes
            else:
                self.metrics.failed_chapters += 1

    async def record_image(self, success: bool, size_bytes: int = 0) -> None:
        async with self._lock:
            self.metrics.total_images += 1
            if success:
                self.metrics.completed_images += 1
                self.metrics.total_bytes += size_bytes
            else:
                self.metrics.failed_images += 1

    def generate_report(self) -> str:
        m = self.metrics
        return (
            f"下载完成: "
            f"章节 {m.completed_chapters}/{m.total_chapters}, "
            f"图片 {m.completed_images}/{m.total_images}, "
            f"耗时 {m.duration():.1f}s, "
            f"速度 {m.download_speed():.1f} KB/s"
        )

    def log_report(self) -> None:
        logger.info(f"[ESJ] {self.generate_report()}")
