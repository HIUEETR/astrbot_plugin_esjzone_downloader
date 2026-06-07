"""异步下载管理器 - 从线程池版本迁移到 asyncio"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from astrbot.api import logger


@dataclass
class Task:
    """基础任务类"""

    url: str
    retry_count: int = 0
    callback: Callable | None = None
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)


@dataclass
class ChapterTask(Task):
    """章节下载任务"""

    chapter_obj: Any = None


@dataclass
class ImageTask(Task):
    """图片下载任务"""

    chapter_obj: Any = None
    image_filename: str = ""


class AsyncDownloadManager:
    """
    异步下载管理器

    功能：
    - 章节和图片分离队列
    - 并发控制和进度跟踪
    - 自动重试机制
    - 速率统计
    - 错误降级（降为单并发）
    """

    def __init__(self, config: dict[str, Any]):
        # 队列
        self.chapter_queue: asyncio.Queue[ChapterTask] = asyncio.Queue()
        self.image_queue: asyncio.Queue[ImageTask] = asyncio.Queue()

        # 控制标志
        self._stop_event = asyncio.Event()
        self._workers: list[asyncio.Task] = []
        self._monitor_task: asyncio.Task | None = None

        # 统计数据
        self._lock = asyncio.Lock()
        self.active_workers = 0
        self.pending_retries = 0

        self.total_chapters = 0
        self.completed_chapters = 0
        self.total_images = 0
        self.completed_images = 0
        self.failed_tasks = 0

        self.bytes_downloaded = 0
        self.start_time = time.time()

        self.consecutive_errors = 0
        self.is_downgraded = False

        # 配置
        dl_config = config.get("download", {})
        self.max_concurrency = dl_config.get("max_threads", 5)
        self.timeout = dl_config.get("timeout_seconds", 180)
        self.max_retries = dl_config.get("retry_attempts", 2)
        self.retry_delays = dl_config.get("retry_delays", [10, 15, 30])

        # 回调
        self.on_progress: Callable[[str, int, int], None] | None = None
        self.on_rate_update: Callable[[str, int], None] | None = None

        self._prefer_image = False

    async def add_chapter_task(self, task: ChapterTask) -> None:
        """添加章节任务"""
        await self.chapter_queue.put(task)
        async with self._lock:
            self.total_chapters += 1
            if self.on_progress:
                self.on_progress(
                    "chapter", self.completed_chapters, self.total_chapters
                )

    async def add_image_task(self, task: ImageTask) -> None:
        """添加单个图片任务"""
        await self.add_image_tasks([task])

    async def add_image_tasks(self, tasks: list[ImageTask]) -> None:
        """批量添加图片任务"""
        if not tasks:
            return
        async with self._lock:
            self.total_images += len(tasks)
            if self.on_progress:
                self.on_progress("image", self.completed_images, self.total_images)
        for task in tasks:
            await self.image_queue.put(task)

    async def start(self) -> None:
        """启动下载管理器"""
        logger.info(f"[ESJ] 启动异步下载管理器，并发数：{self.max_concurrency}")
        self._stop_event.clear()
        self.start_time = time.time()

        # 创建工作协程
        self._workers = [
            asyncio.create_task(self._worker_loop(i), name=f"ESJ-Worker-{i}")
            for i in range(self.max_concurrency)
        ]

        # 创建监控协程
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(), name="ESJ-Monitor"
        )

    async def stop(self) -> None:
        """停止下载管理器"""
        self._stop_event.set()
        for worker in self._workers:
            worker.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()
        tasks_to_cancel = [*self._workers]
        if self._monitor_task is not None:
            tasks_to_cancel.append(self._monitor_task)
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    async def wait_until_complete(self) -> None:
        """等待所有任务完成"""
        while not self._stop_event.is_set():
            if (
                self.chapter_queue.empty()
                and self.image_queue.empty()
                and self.active_workers == 0
                and self.pending_retries == 0
            ):
                break
            await asyncio.sleep(0.5)

    async def _worker_loop(self, worker_id: int) -> None:
        """工作协程循环"""
        while not self._stop_event.is_set():
            task: Task | None = None
            task_type: str | None = None

            # 降级模式：只允许 worker-0 运行
            if self.is_downgraded and worker_id != 0:
                await asyncio.sleep(1)
                continue

            try:
                task, task_type = await self._dequeue_task()
                if task is None or task_type is None:
                    await asyncio.sleep(0.05)
                    continue

                async with self._lock:
                    self.active_workers += 1

                await self._process_task(task, task_type)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[ESJ] 工作协程错误: {exc}")
            finally:
                if task:
                    async with self._lock:
                        self.active_workers -= 1

    async def _process_task(self, task: Task, task_type: str) -> None:
        """处理单个任务"""
        try:
            if task.callback:
                if asyncio.iscoroutinefunction(task.callback):
                    await task.callback(*task.args, **task.kwargs)
                else:
                    task.callback(*task.args, **task.kwargs)

            async with self._lock:
                self.consecutive_errors = 0
                if self.is_downgraded:
                    logger.info("[ESJ] 网络已恢复，恢复并发下载")
                    self.is_downgraded = False

                if task_type == "chapter":
                    self.completed_chapters += 1
                else:
                    self.completed_images += 1

                if self.on_progress:
                    self.on_progress(
                        task_type,
                        self.completed_chapters
                        if task_type == "chapter"
                        else self.completed_images,
                        self.total_chapters
                        if task_type == "chapter"
                        else self.total_images,
                    )

        except Exception as exc:
            logger.error(f"[ESJ] 任务失败: {task.url}, 错误: {exc}")
            await self._handle_failure(task, task_type, exc)

    async def _dequeue_task(self) -> tuple[Task | None, str | None]:
        """从队列取出任务（章节和图片交替）"""
        if self.chapter_queue.empty() and self.image_queue.empty():
            return None, None

        # 两个队列都有任务时交替获取
        if not self.chapter_queue.empty() and not self.image_queue.empty():
            if self._prefer_image:
                try:
                    task = self.image_queue.get_nowait()
                    self._prefer_image = False
                    return task, "image"
                except asyncio.QueueEmpty:
                    pass
            try:
                task = self.chapter_queue.get_nowait()
                self._prefer_image = True
                return task, "chapter"
            except asyncio.QueueEmpty:
                pass
            try:
                task = self.image_queue.get_nowait()
                self._prefer_image = False
                return task, "image"
            except asyncio.QueueEmpty:
                pass
            return None, None

        # 只有章节队列有任务
        if not self.chapter_queue.empty():
            try:
                task = self.chapter_queue.get_nowait()
                self._prefer_image = True
                return task, "chapter"
            except asyncio.QueueEmpty:
                return None, None

        # 只有图片队列有任务
        try:
            task = self.image_queue.get_nowait()
            self._prefer_image = False
            return task, "image"
        except asyncio.QueueEmpty:
            return None, None

    async def _handle_failure(
        self, task: Task, task_type: str, error: Exception
    ) -> None:
        """处理任务失败"""
        async with self._lock:
            self.consecutive_errors += 1
            if self.consecutive_errors > 5 and not self.is_downgraded:
                logger.warning("[ESJ] 连续错误过多，降级为单并发下载")
                self.is_downgraded = True

        if task.retry_count < self.max_retries:
            delay = self.retry_delays[min(task.retry_count, len(self.retry_delays) - 1)]
            logger.info(
                f"[ESJ] 将在 {delay}秒后重试任务 {task.url} "
                f"(尝试 {task.retry_count + 1}/{self.max_retries})"
            )

            async with self._lock:
                self.pending_retries += 1

            # 异步延迟后重新入队
            asyncio.create_task(self._requeue_task(task, task_type, delay))
        else:
            logger.error(f"[ESJ] 任务永久失败: {task.url}")
            async with self._lock:
                self.failed_tasks += 1
                if task_type == "chapter":
                    self.completed_chapters += 1
                else:
                    self.completed_images += 1

                if self.on_progress:
                    self.on_progress(
                        task_type,
                        self.completed_chapters
                        if task_type == "chapter"
                        else self.completed_images,
                        self.total_chapters
                        if task_type == "chapter"
                        else self.total_images,
                    )

    async def _requeue_task(self, task: Task, task_type: str, delay: float) -> None:
        """延迟后重新入队任务"""
        await asyncio.sleep(delay)
        task.retry_count += 1
        if task_type == "chapter":
            await self.chapter_queue.put(cast(ChapterTask, task))
        else:
            await self.image_queue.put(cast(ImageTask, task))

        async with self._lock:
            self.pending_retries -= 1

    async def _monitor_loop(self) -> None:
        """监控循环：统计速率和活跃工作者"""
        while not self._stop_event.is_set():
            await asyncio.sleep(1)
            rate = self.get_rate()
            if self.on_rate_update:
                self.on_rate_update(rate, self.active_workers)

    def report_bytes(self, count: int) -> None:
        """报告已下载字节数（用于速率计算）"""
        self.bytes_downloaded += count

    def get_rate(self) -> str:
        """获取当前下载速率"""
        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return "0 KB/s"
        rate = (self.bytes_downloaded / 1024) / elapsed
        return f"{rate:.1f} KB/s"
