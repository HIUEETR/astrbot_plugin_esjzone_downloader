"""下载速率限制器"""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """
    下载速率限制器

    功能：
    - 控制下载速率，防止被服务器限流
    - 基于令牌桶算法
    - 支持突发流量
    """

    def __init__(
        self,
        rate_limit_bytes_per_second: int = 0,
        burst_size: int | None = None,
    ):
        """
        初始化速率限制器

        Args:
            rate_limit_bytes_per_second: 每秒允许的字节数，0 表示不限制
            burst_size: 突发流量大小，默认为 rate_limit 的 2 倍
        """
        self.rate_limit = rate_limit_bytes_per_second
        self.burst_size = burst_size or (rate_limit_bytes_per_second * 2)
        self.tokens = float(self.burst_size)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()
        self.enabled = rate_limit_bytes_per_second > 0

    async def acquire(self, size: int) -> None:
        """
        获取指定大小的令牌

        Args:
            size: 需要的字节数
        """
        if not self.enabled or size <= 0:
            return

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now

            # 补充令牌
            self.tokens = min(
                self.burst_size,
                self.tokens + elapsed * self.rate_limit,
            )

            # 等待足够的令牌
            while self.tokens < size:
                wait_time = (size - self.tokens) / self.rate_limit
                await asyncio.sleep(wait_time)
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(
                    self.burst_size,
                    self.tokens + elapsed * self.rate_limit,
                )

            # 消耗令牌
            self.tokens -= size

    def update_rate(self, rate_limit_bytes_per_second: int) -> None:
        """
        更新速率限制

        Args:
            rate_limit_bytes_per_second: 新的速率限制（字节/秒）
        """
        self.rate_limit = rate_limit_bytes_per_second
        self.burst_size = rate_limit_bytes_per_second * 2
        self.enabled = rate_limit_bytes_per_second > 0
