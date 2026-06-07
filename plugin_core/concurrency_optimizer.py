"""并发优化工具模块"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from astrbot.api import logger

T = TypeVar("T")
R = TypeVar("R")


class AdaptiveSemaphore:
    """
    自适应信号量

    功能：
    - 根据系统负载动态调整并发数
    - 错误率过高时自动降低并发
    - 性能良好时自动提高并发
    """

    def __init__(
        self,
        initial_value: int = 5,
        min_value: int = 1,
        max_value: int = 10,
        error_threshold: float = 0.3,
    ):
        """
        初始化自适应信号量

        Args:
            initial_value: 初始并发数
            min_value: 最小并发数
            max_value: 最大并发数
            error_threshold: 错误率阈值（超过则降低并发）
        """
        self.current_value = initial_value
        self.min_value = min_value
        self.max_value = max_value
        self.error_threshold = error_threshold

        self._semaphore = asyncio.Semaphore(initial_value)
        self._lock = asyncio.Lock()

        # 统计数据
        self.total_tasks = 0
        self.failed_tasks = 0
        self.success_tasks = 0

    async def acquire(self) -> None:
        """获取信号量"""
        await self._semaphore.acquire()

    def release(self) -> None:
        """释放信号量"""
        self._semaphore.release()

    async def __aenter__(self):
        """上下文管理器入口"""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.release()

        # 记录任务结果
        async with self._lock:
            self.total_tasks += 1
            if exc_type is not None:
                self.failed_tasks += 1
            else:
                self.success_tasks += 1

        # 定期调整并发数
        if self.total_tasks % 10 == 0:
            await self._adjust_concurrency()

    async def _adjust_concurrency(self) -> None:
        """根据错误率调整并发数"""
        if self.total_tasks < 10:
            return

        error_rate = self.failed_tasks / self.total_tasks

        async with self._lock:
            old_value = self.current_value

            if error_rate > self.error_threshold:
                # 错误率过高，降低并发
                new_value = max(self.min_value, self.current_value - 1)
            elif error_rate < self.error_threshold / 2 and self.success_tasks > 20:
                # 表现良好，提高并发
                new_value = min(self.max_value, self.current_value + 1)
            else:
                # 保持当前并发
                return

            if new_value != old_value:
                self.current_value = new_value
                # 重新创建信号量
                self._semaphore = asyncio.Semaphore(new_value)

                logger.info(
                    f"[ESJ] Adaptive concurrency adjusted: {old_value} -> {new_value} "
                    f"(error_rate: {error_rate:.2%})"
                )

                # 重置统计（避免历史数据影响）
                self.total_tasks = 0
                self.failed_tasks = 0
                self.success_tasks = 0

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        error_rate = self.failed_tasks / self.total_tasks if self.total_tasks > 0 else 0
        return {
            "current_concurrency": self.current_value,
            "total_tasks": self.total_tasks,
            "success_tasks": self.success_tasks,
            "failed_tasks": self.failed_tasks,
            "error_rate": error_rate,
        }


class LockManager:
    """
    锁管理器

    功能：
    - 避免锁竞争
    - 分段锁策略
    - 锁超时检测
    """

    def __init__(self, num_shards: int = 16):
        """
        初始化锁管理器

        Args:
            num_shards: 分段锁数量
        """
        self.num_shards = num_shards
        self._locks = [asyncio.Lock() for _ in range(num_shards)]

    def _get_shard(self, key: str) -> int:
        """获取 key 对应的分段"""
        return hash(key) % self.num_shards

    def get_lock(self, key: str) -> asyncio.Lock:
        """
        获取 key 对应的锁

        Args:
            key: 锁的键

        Returns:
            对应的锁
        """
        shard = self._get_shard(key)
        return self._locks[shard]

    async def acquire_with_timeout(
        self,
        key: str,
        timeout: float = 30.0,
    ) -> bool:
        """
        带超时的锁获取

        Args:
            key: 锁的键
            timeout: 超时时间（秒）

        Returns:
            是否成功获取锁
        """
        lock = self.get_lock(key)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[ESJ] Lock acquisition timeout: key={key}")
            return False


class TaskPool:
    """
    任务池

    功能：
    - 任务队列管理
    - 工作协程池
    - 任务结果收集
    """

    def __init__(self, max_workers: int = 5):
        """
        初始化任务池

        Args:
            max_workers: 最大工作协程数
        """
        self.max_workers = max_workers
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._result_queue: asyncio.Queue = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        """启动任务池"""
        if self._running:
            return

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self.max_workers)
        ]
        logger.info(f"[ESJ] Task pool started with {self.max_workers} workers")

    async def stop(self) -> None:
        """停止任务池"""
        self._running = False

        # 等待所有工作协程完成
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("[ESJ] Task pool stopped")

    async def submit(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs,
    ) -> None:
        """
        提交任务

        Args:
            func: 任务函数
            args: 位置参数
            kwargs: 关键字参数
        """
        await self._task_queue.put((func, args, kwargs))

    async def get_result(self, timeout: float | None = None) -> Any:
        """
        获取任务结果

        Args:
            timeout: 超时时间（秒）

        Returns:
            任务结果
        """
        if timeout:
            return await asyncio.wait_for(
                self._result_queue.get(),
                timeout=timeout,
            )
        else:
            return await self._result_queue.get()

    async def _worker(self, worker_id: int) -> None:
        """工作协程"""
        logger.debug(f"[ESJ] Task pool worker {worker_id} started")

        while self._running:
            try:
                # 从队列获取任务
                task = await asyncio.wait_for(
                    self._task_queue.get(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue

            func, args, kwargs = task

            try:
                # 执行任务
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # 将结果放入结果队列
                await self._result_queue.put(("success", result))

            except Exception as exc:
                logger.error(f"[ESJ] Task pool worker {worker_id} error: {exc}")
                await self._result_queue.put(("error", exc))

        logger.debug(f"[ESJ] Task pool worker {worker_id} stopped")

    def qsize(self) -> int:
        """获取任务队列大小"""
        return self._task_queue.qsize()

    def result_qsize(self) -> int:
        """获取结果队列大小"""
        return self._result_queue.qsize()


async def gather_with_concurrency(
    tasks: list[Callable[[], Any]],
    max_concurrency: int = 5,
) -> list[Any]:
    """
    限制并发数的 gather

    Args:
        tasks: 任务列表（每个任务是一个无参数的可调用对象）
        max_concurrency: 最大并发数

    Returns:
        任务结果列表
    """
    semaphore = asyncio.Semaphore(max_concurrency)
    results = []

    async def bounded_task(task: Callable[[], Any]) -> Any:
        async with semaphore:
            if asyncio.iscoroutinefunction(task):
                return await task()
            else:
                return task()

    # 创建所有任务
    bounded_tasks = [bounded_task(task) for task in tasks]

    # 并发执行
    results = await asyncio.gather(*bounded_tasks, return_exceptions=True)

    return results


def optimize_batch_size(
    total_items: int,
    max_concurrency: int,
    min_batch_size: int = 1,
    max_batch_size: int = 100,
) -> int:
    """
    优化批次大小

    Args:
        total_items: 总数据量
        max_concurrency: 最大并发数
        min_batch_size: 最小批次大小
        max_batch_size: 最大批次大小

    Returns:
        优化后的批次大小
    """
    # 理想批次大小：让每个工作协程处理一批
    ideal_batch_size = (total_items + max_concurrency - 1) // max_concurrency

    # 限制在合理范围内
    batch_size = max(min_batch_size, min(ideal_batch_size, max_batch_size))

    return batch_size
