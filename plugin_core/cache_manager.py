"""缓存管理模块"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional


class CacheManager:
    """
    缓存管理器

    功能：
    - 内存和文件双层缓存
    - 自动过期清理
    - LRU 淘汰策略
    """

    def __init__(
        self,
        cache_dir: Path,
        max_memory_items: int = 100,
        default_ttl: float = 3600.0,
    ):
        """
        初始化缓存管理器

        Args:
            cache_dir: 缓存目录
            max_memory_items: 内存缓存最大条目数
            default_ttl: 默认缓存时间（秒）
        """
        self.cache_dir = cache_dir
        self.max_memory_items = max_memory_items
        self.default_ttl = default_ttl

        # 内存缓存: key -> (value, expires_at)
        self._memory_cache: dict[str, tuple[Any, float]] = {}
        self._access_order: list[str] = []  # LRU 访问顺序
        self._lock = asyncio.Lock()

        # 确保缓存目录存在
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def get(self, key: str) -> Optional[Any]:
        """
        获取缓存

        Args:
            key: 缓存键

        Returns:
            缓存值，如果不存在或过期返回 None
        """
        async with self._lock:
            # 先查内存缓存
            if key in self._memory_cache:
                value, expires_at = self._memory_cache[key]
                if time.time() < expires_at:
                    # 更新访问顺序
                    self._access_order.remove(key)
                    self._access_order.append(key)
                    return value
                else:
                    # 过期，删除
                    del self._memory_cache[key]
                    self._access_order.remove(key)

        # 查文件缓存
        cache_file = self._cache_file_path(key)
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            expires_at = data.get("expires_at", 0)
            if time.time() < expires_at:
                value = data.get("value")
                # 加载到内存缓存
                await self._set_memory(key, value, expires_at)
                return value
            else:
                # 过期，删除文件
                cache_file.unlink()
        except Exception:
            # 文件损坏，删除
            cache_file.unlink()

        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        memory_only: bool = False,
    ) -> None:
        """
        设置缓存

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 使用默认值
            memory_only: 仅存储在内存中
        """
        ttl = ttl if ttl is not None else self.default_ttl
        expires_at = time.time() + ttl

        async with self._lock:
            await self._set_memory(key, value, expires_at)

        if not memory_only:
            # 异步写入文件
            asyncio.create_task(self._write_cache_file(key, value, expires_at))

    async def delete(self, key: str) -> None:
        """
        删除缓存

        Args:
            key: 缓存键
        """
        async with self._lock:
            if key in self._memory_cache:
                del self._memory_cache[key]
                self._access_order.remove(key)

        cache_file = self._cache_file_path(key)
        if cache_file.exists():
            cache_file.unlink()

    async def clear(self) -> None:
        """清空所有缓存"""
        async with self._lock:
            self._memory_cache.clear()
            self._access_order.clear()

        # 删除所有缓存文件
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
            except Exception:
                pass

    async def cleanup_expired(self) -> int:
        """
        清理过期缓存

        Returns:
            清理的缓存数量
        """
        now = time.time()
        count = 0

        # 清理内存缓存
        async with self._lock:
            expired_keys = [
                key for key, (_, expires_at) in self._memory_cache.items()
                if now >= expires_at
            ]
            for key in expired_keys:
                del self._memory_cache[key]
                self._access_order.remove(key)
                count += 1

        # 清理文件缓存
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if now >= data.get("expires_at", 0):
                    cache_file.unlink()
                    count += 1
            except Exception:
                # 文件损坏，删除
                cache_file.unlink()
                count += 1

        return count

    async def _set_memory(self, key: str, value: Any, expires_at: float) -> None:
        """设置内存缓存（需持有锁）"""
        # 如果已存在，更新访问顺序
        if key in self._memory_cache:
            self._access_order.remove(key)

        # 添加到内存缓存
        self._memory_cache[key] = (value, expires_at)
        self._access_order.append(key)

        # LRU 淘汰
        while len(self._memory_cache) > self.max_memory_items:
            oldest_key = self._access_order.pop(0)
            del self._memory_cache[oldest_key]

    async def _write_cache_file(
        self,
        key: str,
        value: Any,
        expires_at: float,
    ) -> None:
        """异步写入缓存文件"""
        cache_file = self._cache_file_path(key)
        try:
            data = {
                "value": value,
                "expires_at": expires_at,
            }
            cache_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass  # 忽略文件写入错误

    def _cache_file_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        # 使用 key 的 hash 作为文件名
        import hashlib
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key_hash}.json"
