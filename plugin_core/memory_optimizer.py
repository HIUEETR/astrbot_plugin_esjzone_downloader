"""内存优化工具模块"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List, TypeVar

from astrbot.api import logger

T = TypeVar('T')


class BatchProcessor:
    """
    批处理器 - 用于大数据量的分批处理

    功能：
    - 大书籍分批处理
    - 内存使用控制
    - 批次间隔控制
    """

    def __init__(
        self,
        batch_size: int = 50,
        batch_delay: float = 0.5,
    ):
        """
        初始化批处理器

        Args:
            batch_size: 每批处理的数量
            batch_delay: 批次之间的延迟（秒）
        """
        self.batch_size = batch_size
        self.batch_delay = batch_delay

    async def process_in_batches(
        self,
        items: List[T],
        processor: Callable[[List[T]], Any],
        on_batch_complete: Callable[[int, int], None] | None = None,
    ) -> List[Any]:
        """
        分批处理数据

        Args:
            items: 待处理的数据列表
            processor: 处理函数（接收一批数据）
            on_batch_complete: 批次完成回调

        Returns:
            所有批次的处理结果
        """
        total_items = len(items)
        total_batches = (total_items + self.batch_size - 1) // self.batch_size
        results = []

        logger.info(
            f"[ESJ] Batch processing: {total_items} items in {total_batches} batches"
        )

        for batch_num in range(total_batches):
            start_idx = batch_num * self.batch_size
            end_idx = min(start_idx + self.batch_size, total_items)
            batch = items[start_idx:end_idx]

            logger.debug(
                f"[ESJ] Processing batch {batch_num + 1}/{total_batches} "
                f"({len(batch)} items)"
            )

            # 处理当前批次
            if asyncio.iscoroutinefunction(processor):
                batch_result = await processor(batch)
            else:
                batch_result = processor(batch)

            results.append(batch_result)

            # 回调通知
            if on_batch_complete:
                on_batch_complete(batch_num + 1, total_batches)

            # 批次间延迟（最后一批不需要）
            if batch_num < total_batches - 1 and self.batch_delay > 0:
                await asyncio.sleep(self.batch_delay)

        logger.info(f"[ESJ] Batch processing completed: {total_batches} batches")
        return results

    def should_use_batch(self, item_count: int, threshold: int = 100) -> bool:
        """
        判断是否需要分批处理

        Args:
            item_count: 数据数量
            threshold: 分批阈值

        Returns:
            是否需要分批
        """
        return item_count > threshold


class MemoryMonitor:
    """
    内存监控器

    功能：
    - 监控内存使用
    - 内存预警
    - 自动触发清理
    """

    def __init__(
        self,
        warning_threshold_mb: float = 500.0,
        critical_threshold_mb: float = 1000.0,
    ):
        """
        初始化内存监控器

        Args:
            warning_threshold_mb: 警告阈值（MB）
            critical_threshold_mb: 严重阈值（MB）
        """
        self.warning_threshold = warning_threshold_mb * 1024 * 1024
        self.critical_threshold = critical_threshold_mb * 1024 * 1024
        self._current_usage = 0
        self._peak_usage = 0

    def track_allocation(self, size_bytes: int) -> None:
        """
        追踪内存分配

        Args:
            size_bytes: 分配的字节数
        """
        self._current_usage += size_bytes
        self._peak_usage = max(self._peak_usage, self._current_usage)

        # 检查阈值
        if self._current_usage >= self.critical_threshold:
            logger.warning(
                f"[ESJ] Memory usage critical: "
                f"{self._current_usage / (1024 * 1024):.2f} MB"
            )
        elif self._current_usage >= self.warning_threshold:
            logger.info(
                f"[ESJ] Memory usage warning: "
                f"{self._current_usage / (1024 * 1024):.2f} MB"
            )

    def track_deallocation(self, size_bytes: int) -> None:
        """
        追踪内存释放

        Args:
            size_bytes: 释放的字节数
        """
        self._current_usage = max(0, self._current_usage - size_bytes)

    def get_usage_mb(self) -> float:
        """获取当前内存使用（MB）"""
        return self._current_usage / (1024 * 1024)

    def get_peak_usage_mb(self) -> float:
        """获取峰值内存使用（MB）"""
        return self._peak_usage / (1024 * 1024)

    def reset(self) -> None:
        """重置统计"""
        self._current_usage = 0
        self._peak_usage = 0

    def is_critical(self) -> bool:
        """判断是否达到严重阈值"""
        return self._current_usage >= self.critical_threshold

    def is_warning(self) -> bool:
        """判断是否达到警告阈值"""
        return self._current_usage >= self.warning_threshold


class StreamingImageDownloader:
    """
    流式图片下载器

    功能：
    - 流式下载图片，不一次性加载到内存
    - 边下载边处理
    - 降低内存峰值
    """

    def __init__(self, chunk_size: int = 8192):
        """
        初始化流式下载器

        Args:
            chunk_size: 每次读取的块大小（字节）
        """
        self.chunk_size = chunk_size

    async def download_streaming(
        self,
        response_stream: Any,
        processor: Callable[[bytes], None] | None = None,
    ) -> bytes:
        """
        流式下载

        Args:
            response_stream: HTTP 响应流
            processor: 数据处理器（可选）

        Returns:
            完整数据
        """
        chunks = []
        total_size = 0

        async for chunk in response_stream.aiter_bytes(chunk_size=self.chunk_size):
            # 处理每个块
            if processor:
                if asyncio.iscoroutinefunction(processor):
                    await processor(chunk)
                else:
                    processor(chunk)

            chunks.append(chunk)
            total_size += len(chunk)

        logger.debug(f"[ESJ] Streaming download completed: {total_size} bytes")
        return b"".join(chunks)


def estimate_chapter_size(
    chapter_count: int,
    avg_chapter_kb: float = 10.0,
) -> float:
    """
    估算章节总大小

    Args:
        chapter_count: 章节数量
        avg_chapter_kb: 平均每章大小（KB）

    Returns:
        估算的总大小（MB）
    """
    return (chapter_count * avg_chapter_kb) / 1024


def estimate_image_size(
    image_count: int,
    avg_image_kb: float = 200.0,
) -> float:
    """
    估算图片总大小

    Args:
        image_count: 图片数量
        avg_image_kb: 平均每张图片大小（KB）

    Returns:
        估算的总大小（MB）
    """
    return (image_count * avg_image_kb) / 1024


def estimate_book_size(
    chapter_count: int,
    image_count: int,
    avg_chapter_kb: float = 10.0,
    avg_image_kb: float = 200.0,
) -> dict[str, float]:
    """
    估算书籍总大小

    Args:
        chapter_count: 章节数量
        image_count: 图片数量
        avg_chapter_kb: 平均每章大小（KB）
        avg_image_kb: 平均每张图片大小（KB）

    Returns:
        估算结果字典
    """
    chapter_size = estimate_chapter_size(chapter_count, avg_chapter_kb)
    image_size = estimate_image_size(image_count, avg_image_kb)
    total_size = chapter_size + image_size

    return {
        "chapter_size_mb": round(chapter_size, 2),
        "image_size_mb": round(image_size, 2),
        "total_size_mb": round(total_size, 2),
        "chapter_count": chapter_count,
        "image_count": image_count,
    }


def format_size_estimate(estimate: dict[str, float]) -> str:
    """
    格式化大小估算结果

    Args:
        estimate: 估算结果字典

    Returns:
        格式化的字符串
    """
    lines = [
        f"预计文件大小：{estimate['total_size_mb']} MB",
        f"  章节内容：{estimate['chapter_size_mb']} MB ({estimate['chapter_count']} 章)",
    ]

    if estimate["image_count"] > 0:
        lines.append(
            f"  图片内容：{estimate['image_size_mb']} MB ({estimate['image_count']} 张)"
        )

    return "\n".join(lines)
