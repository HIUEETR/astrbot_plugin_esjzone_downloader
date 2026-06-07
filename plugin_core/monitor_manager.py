"""监控管理器 - 增强版"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from astrbot.api import logger


@dataclass
class MonitorEntry:
    """监控条目"""
    book_id: str
    url: str
    title: str
    latest_chapter: str
    latest_index: int
    update_time: str
    unified_msg_origin: str
    created_by: str
    created_at: int
    updated_at: int
    check_count: int = 0  # 检查次数
    fail_count: int = 0  # 连续失败次数
    last_check_at: int = 0  # 上次检查时间


@dataclass
class MonitorHistory:
    """监控历史记录"""
    book_id: str
    check_time: int
    success: bool
    latest_chapter: str
    error_message: Optional[str] = None
    new_chapters: int = 0


class MonitorManager:
    """
    监控管理器

    功能：
    - 智能检查间隔（根据更新频率动态调整）
    - 批量下载优化
    - 失败重试机制
    - 监控历史记录
    """

    def __init__(
        self,
        data_dir: Path,
        base_interval: float = 3600.0,
        max_interval: float = 86400.0,
        min_interval: float = 1800.0,
    ):
        """
        初始化监控管理器

        Args:
            data_dir: 数据目录
            base_interval: 基础检查间隔（秒）
            max_interval: 最大检查间隔（秒）
            min_interval: 最小检查间隔（秒）
        """
        self.data_dir = data_dir
        self.base_interval = base_interval
        self.max_interval = max_interval
        self.min_interval = min_interval

        self.monitor_path = data_dir / "monitor.json"
        self.history_path = data_dir / "monitor_history.json"
        self._lock = asyncio.Lock()

        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

    async def get_smart_interval(self, entry: MonitorEntry) -> float:
        """
        获取智能检查间隔

        根据更新频率动态调整：
        - 频繁更新的书籍缩短间隔
        - 长期未更新的书籍延长间隔

        Args:
            entry: 监控条目

        Returns:
            检查间隔（秒）
        """
        now = int(time.time())

        # 如果从未检查过，使用基础间隔
        if entry.last_check_at == 0:
            return self.base_interval

        # 距离上次更新的时间（小时）
        hours_since_update = (now - entry.updated_at) / 3600

        # 连续失败次数影响
        if entry.fail_count > 0:
            # 失败越多，间隔越长（指数退避）
            backoff = min(2 ** entry.fail_count, 8)
            return min(self.base_interval * backoff, self.max_interval)

        # 根据更新频率调整
        if hours_since_update < 24:
            # 24小时内更新过，缩短间隔
            return max(self.min_interval, self.base_interval * 0.5)
        elif hours_since_update < 72:
            # 3天内更新过，使用基础间隔
            return self.base_interval
        elif hours_since_update < 168:
            # 7天内更新过，略微延长
            return min(self.base_interval * 1.5, self.max_interval)
        else:
            # 长期未更新，大幅延长
            return min(self.base_interval * 3, self.max_interval)

    async def should_check(self, entry: MonitorEntry) -> bool:
        """
        判断是否应该检查

        Args:
            entry: 监控条目

        Returns:
            是否应该检查
        """
        if entry.last_check_at == 0:
            return True

        now = int(time.time())
        interval = await self.get_smart_interval(entry)
        return (now - entry.last_check_at) >= interval

    async def record_check(
        self,
        entry: MonitorEntry,
        success: bool,
        latest_chapter: str = "",
        new_chapters: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """
        记录检查结果

        Args:
            entry: 监控条目
            success: 是否成功
            latest_chapter: 最新章节
            new_chapters: 新章节数
            error_message: 错误消息
        """
        now = int(time.time())
        entry.last_check_at = now
        entry.check_count += 1

        if success:
            entry.fail_count = 0
        else:
            entry.fail_count += 1

        # 记录历史
        history = MonitorHistory(
            book_id=entry.book_id,
            check_time=now,
            success=success,
            latest_chapter=latest_chapter,
            error_message=error_message,
            new_chapters=new_chapters,
        )
        await self._add_history(history)

        logger.debug(
            f"[ESJ] Monitor check recorded: book_id={entry.book_id}, "
            f"success={success}, check_count={entry.check_count}, "
            f"fail_count={entry.fail_count}"
        )

    async def get_batch_to_check(
        self,
        entries: List[MonitorEntry],
        max_batch_size: int = 10,
    ) -> List[MonitorEntry]:
        """
        获取待检查的批次

        优先级：
        1. 从未检查过的
        2. 最近更新过且到达检查间隔的
        3. 长期未检查的

        Args:
            entries: 所有监控条目
            max_batch_size: 最大批次大小

        Returns:
            待检查的条目列表
        """
        to_check: List[tuple[int, MonitorEntry]] = []

        for entry in entries:
            if not await self.should_check(entry):
                continue

            # 计算优先级（越小越优先）
            if entry.last_check_at == 0:
                priority = 0  # 最高优先级：从未检查
            else:
                now = int(time.time())
                hours_since_update = (now - entry.updated_at) / 3600
                hours_since_check = (now - entry.last_check_at) / 3600

                if hours_since_update < 24:
                    priority = 1  # 高优先级：最近更新过
                elif hours_since_check > 24:
                    priority = 2  # 中优先级：长期未检查
                else:
                    priority = 3  # 低优先级：普通检查

            to_check.append((priority, entry))

        # 按优先级排序
        to_check.sort(key=lambda x: (x[0], x[1].last_check_at))

        # 返回前 N 个
        return [entry for _, entry in to_check[:max_batch_size]]

    async def get_history(
        self,
        book_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[MonitorHistory]:
        """
        获取监控历史

        Args:
            book_id: 书籍 ID，None 返回全部
            limit: 限制数量

        Returns:
            历史记录列表
        """
        async with self._lock:
            if not self.history_path.exists():
                return []

            try:
                data = json.loads(self.history_path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    return []

                histories = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    if book_id and item.get("book_id") != book_id:
                        continue

                    history = MonitorHistory(
                        book_id=item.get("book_id", ""),
                        check_time=item.get("check_time", 0),
                        success=item.get("success", False),
                        latest_chapter=item.get("latest_chapter", ""),
                        error_message=item.get("error_message"),
                        new_chapters=item.get("new_chapters", 0),
                    )
                    histories.append(history)

                # 按时间倒序
                histories.sort(key=lambda h: h.check_time, reverse=True)
                return histories[:limit]

            except Exception as exc:
                logger.warning(f"[ESJ] Failed to load monitor history: {exc}")
                return []

    async def cleanup_old_history(self, max_age_days: int = 30) -> int:
        """
        清理旧历史记录

        Args:
            max_age_days: 最大保留天数

        Returns:
            清理的记录数
        """
        async with self._lock:
            if not self.history_path.exists():
                return 0

            try:
                data = json.loads(self.history_path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    return 0

                now = int(time.time())
                cutoff = now - (max_age_days * 86400)

                old_count = len(data)
                data = [
                    item for item in data
                    if isinstance(item, dict) and item.get("check_time", 0) >= cutoff
                ]
                new_count = len(data)

                if new_count < old_count:
                    self._write_json(self.history_path, data)
                    removed = old_count - new_count
                    logger.info(f"[ESJ] Cleaned up {removed} old monitor history records")
                    return removed

                return 0

            except Exception as exc:
                logger.warning(f"[ESJ] Failed to cleanup monitor history: {exc}")
                return 0

    async def _add_history(self, history: MonitorHistory) -> None:
        """添加历史记录"""
        async with self._lock:
            try:
                # 读取现有历史
                if self.history_path.exists():
                    data = json.loads(self.history_path.read_text(encoding="utf-8"))
                    if not isinstance(data, list):
                        data = []
                else:
                    data = []

                # 添加新记录
                data.append({
                    "book_id": history.book_id,
                    "check_time": history.check_time,
                    "success": history.success,
                    "latest_chapter": history.latest_chapter,
                    "error_message": history.error_message,
                    "new_chapters": history.new_chapters,
                })

                # 保留最近 1000 条
                if len(data) > 1000:
                    data = data[-1000:]

                self._write_json(self.history_path, data)

            except Exception as exc:
                logger.warning(f"[ESJ] Failed to add monitor history: {exc}")

    def _write_json(self, path: Path, data: Any) -> None:
        """写入 JSON 文件"""
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def get_statistics(self) -> Dict[str, Any]:
        """
        获取监控统计信息

        Returns:
            统计信息字典
        """
        histories = await self.get_history(limit=1000)

        total_checks = len(histories)
        successful_checks = sum(1 for h in histories if h.success)
        failed_checks = total_checks - successful_checks
        total_new_chapters = sum(h.new_chapters for h in histories)

        # 最近 24 小时的检查
        now = int(time.time())
        recent_checks = [
            h for h in histories
            if (now - h.check_time) < 86400
        ]

        return {
            "total_checks": total_checks,
            "successful_checks": successful_checks,
            "failed_checks": failed_checks,
            "success_rate": successful_checks / total_checks if total_checks > 0 else 0,
            "total_new_chapters": total_new_chapters,
            "recent_24h_checks": len(recent_checks),
        }
