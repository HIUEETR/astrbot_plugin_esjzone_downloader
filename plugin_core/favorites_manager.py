"""收藏夹管理器 - 缓存和并发获取"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger


class FavoritesManager:
    """
    收藏夹管理器

    功能：
    - 本地 JSON 缓存
    - 会话内仅更新一次
    - 异步并发获取分页
    - 线程安全
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.cache_file = data_dir / "favorites_cache.json"

        # 缓存数据
        self.cache: dict[str, list[dict[str, str]]] = {
            "lastest": [],  # 最近更新
            "collected": [],  # 最近收藏
        }

        # 更新标志（会话内仅更新一次）
        self._updated_flags: dict[str, bool] = {
            "lastest": False,
            "collected": False,
        }

        # 锁
        self._lock = asyncio.Lock()

        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 加载缓存
        asyncio.create_task(self._load_cache())

    async def _load_cache(self) -> None:
        """从文件加载缓存数据"""
        async with self._lock:
            if not self.cache_file.exists():
                return

            try:
                data = await asyncio.to_thread(
                    lambda: json.loads(self.cache_file.read_text(encoding="utf-8"))
                )
                if isinstance(data, dict):
                    for key in ["lastest", "collected"]:
                        if key in data and isinstance(data[key], list):
                            self.cache[key] = data[key]
                    logger.info(
                        f"[ESJ] 收藏缓存已加载: "
                        f"lastest={len(self.cache['lastest'])}, "
                        f"collected={len(self.cache['collected'])}"
                    )
            except Exception as exc:
                logger.warning(f"[ESJ] 加载收藏缓存失败: {exc}")

    async def _save_cache(self) -> None:
        """保存缓存到文件"""
        async with self._lock:
            try:
                await asyncio.to_thread(
                    lambda: self.cache_file.write_text(
                        json.dumps(self.cache, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                )
                logger.debug("[ESJ] 收藏缓存已保存")
            except Exception as exc:
                logger.error(f"[ESJ] 保存收藏缓存失败: {exc}")

    def get_novels(self, sort_by: str) -> list[dict[str, str]]:
        """获取指定排序的收藏列表（同步接口）"""
        return self.cache.get(sort_by, [])

    async def get_novels_async(self, sort_by: str) -> list[dict[str, str]]:
        """获取指定排序的收藏列表（异步接口）"""
        async with self._lock:
            return list(self.cache.get(sort_by, []))

    def is_updated(self, sort_by: str) -> bool:
        """检查是否已更新"""
        return self._updated_flags.get(sort_by, False)

    async def ensure_updated(
        self, sort_by: str, fetch_callback: Any, force: bool = False
    ) -> None:
        """
        确保数据已更新（会话内仅更新一次，除非 force=True）

        Args:
            sort_by: 排序方式
            fetch_callback: 获取收藏的回调函数 (page, sort_by) -> (novels, total_pages)
            force: 强制更新
        """
        if not force and self._updated_flags.get(sort_by):
            return

        logger.info(f"[ESJ] 正在更新收藏列表 ({sort_by})...")
        start_time = time.time()

        try:
            await self._update_favorites(sort_by, fetch_callback)
            self._updated_flags[sort_by] = True
            elapsed = time.time() - start_time
            logger.info(
                f"[ESJ] 收藏列表更新完成，"
                f"共 {len(self.cache[sort_by])} 本，"
                f"耗时 {elapsed:.1f}秒"
            )
        except Exception as exc:
            logger.error(f"[ESJ] 更新收藏列表失败: {exc}")
            raise

    async def _update_favorites(self, sort_by: str, fetch_callback: Any) -> None:
        """执行更新逻辑（异步并发获取）"""
        # 获取第一页以确定总页数
        novels_p1, total_pages = await fetch_callback(1, sort_by)
        results: dict[int, list[dict[str, str]]] = {1: novels_p1}

        if total_pages > 1:
            # 并发获取剩余页
            pages_to_fetch = list(range(2, total_pages + 1))

            # 使用信号量限制并发数
            semaphore = asyncio.Semaphore(5)

            async def fetch_page(page: int) -> tuple[int, list[dict[str, str]]]:
                async with semaphore:
                    try:
                        novels, _ = await fetch_callback(page, sort_by)
                        return page, novels
                    except Exception as exc:
                        logger.warning(f"[ESJ] 获取第 {page} 页失败: {exc}")
                        return page, []

            # 并发获取
            page_results = await asyncio.gather(
                *(fetch_page(p) for p in pages_to_fetch), return_exceptions=True
            )

            for result in page_results:
                if isinstance(result, tuple):
                    page, novels = result
                    results[page] = novels

        # 按页码顺序合并
        final_list = []
        for page in sorted(results.keys()):
            final_list.extend(results[page])

        async with self._lock:
            self.cache[sort_by] = final_list
            await self._save_cache()

    def clear_cache(self, sort_by: str | None = None) -> None:
        """清除缓存"""
        if sort_by:
            self.cache[sort_by] = []
            self._updated_flags[sort_by] = False
        else:
            self.cache = {"lastest": [], "collected": []}
            self._updated_flags = {"lastest": False, "collected": False}
        logger.info(f"[ESJ] 收藏缓存已清除: {sort_by or '全部'}")

    async def invalidate_and_update(self, sort_by: str, fetch_callback: Any) -> None:
        """使缓存失效并重新更新"""
        self._updated_flags[sort_by] = False
        await self.ensure_updated(sort_by, fetch_callback, force=True)
