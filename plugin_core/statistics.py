"""统计模块 - 下载历史和数据分析"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from astrbot.api import logger


@dataclass
class DownloadRecord:
    """下载记录"""
    book_id: str
    book_title: str
    format: str  # epub or txt
    chapters: int
    success: bool
    timestamp: float
    duration: float  # 秒
    size_bytes: int
    user_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DownloadRecord:
        return cls(**data)


class StatisticsManager:
    """
    统计管理器

    功能：
    - 下载历史记录
    - 统计数据分析
    - 存储空间统计
    - 用户活跃度分析
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.history_file = data_dir / "download_history.json"
        self.stats_file = data_dir / "statistics.json"

        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 加载历史记录
        self.records: list[DownloadRecord] = []
        self._load_history()

    def _load_history(self) -> None:
        """加载下载历史"""
        if not self.history_file.exists():
            return

        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.records = [
                    DownloadRecord.from_dict(record)
                    for record in data
                ]
            logger.debug(f"[ESJ] 加载了 {len(self.records)} 条下载历史")
        except Exception as exc:
            logger.warning(f"[ESJ] 加载下载历史失败: {exc}")

    def _save_history(self) -> None:
        """保存下载历史"""
        try:
            data = [record.to_dict() for record in self.records]
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"[ESJ] 保存了 {len(self.records)} 条下载历史")
        except Exception as exc:
            logger.error(f"[ESJ] 保存下载历史失败: {exc}")

    def add_record(self, record: DownloadRecord) -> None:
        """添加下载记录"""
        self.records.append(record)
        self._save_history()

    def get_records(
        self,
        user_key: str | None = None,
        limit: int = 50
    ) -> list[DownloadRecord]:
        """获取下载记录"""
        filtered = self.records
        if user_key:
            filtered = [r for r in filtered if r.user_key == user_key]
        # 按时间倒序
        filtered = sorted(filtered, key=lambda r: r.timestamp, reverse=True)
        return filtered[:limit]

    def get_statistics(self, user_key: str | None = None) -> dict[str, Any]:
        """获取统计信息"""
        records = self.records if not user_key else [
            r for r in self.records if r.user_key == user_key
        ]

        if not records:
            return {
                'total_downloads': 0,
                'success_count': 0,
                'failed_count': 0,
                'success_rate': 0.0,
                'total_chapters': 0,
                'total_size_mb': 0.0,
                'total_duration_hours': 0.0,
                'avg_duration_minutes': 0.0,
                'format_stats': {},
            }

        total = len(records)
        success = len([r for r in records if r.success])
        failed = total - success
        total_chapters = sum(r.chapters for r in records)
        total_bytes = sum(r.size_bytes for r in records if r.success)
        total_duration = sum(r.duration for r in records if r.success)

        # 格式统计
        format_count: dict[str, int] = {}
        for record in records:
            fmt = record.format
            format_count[fmt] = format_count.get(fmt, 0) + 1

        return {
            'total_downloads': total,
            'success_count': success,
            'failed_count': failed,
            'success_rate': (success / total * 100) if total > 0 else 0.0,
            'total_chapters': total_chapters,
            'total_size_mb': total_bytes / (1024 * 1024),
            'total_duration_hours': total_duration / 3600,
            'avg_duration_minutes': (total_duration / success / 60) if success > 0 else 0.0,
            'format_stats': format_count,
        }

    def get_recent_books(self, user_key: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """获取最近下载的书籍"""
        records = self.get_records(user_key, limit)
        return [
            {
                'title': r.book_title,
                'format': r.format,
                'chapters': r.chapters,
                'time': time.strftime('%Y-%m-%d %H:%M', time.localtime(r.timestamp)),
                'success': r.success,
            }
            for r in records
        ]

    def clear_history(self, user_key: str | None = None) -> int:
        """清除历史记录"""
        if user_key:
            count = len([r for r in self.records if r.user_key == user_key])
            self.records = [r for r in self.records if r.user_key != user_key]
        else:
            count = len(self.records)
            self.records = []

        self._save_history()
        logger.info(f"[ESJ] 清除了 {count} 条下载历史")
        return count

    def format_statistics_report(self, user_key: str | None = None) -> str:
        """生成统计报告"""
        stats = self.get_statistics(user_key)

        lines = [
            "📊 下载统计",
            "=" * 40,
            f"总下载: {stats['total_downloads']} 本",
            f"成功: {stats['success_count']} 本",
            f"失败: {stats['failed_count']} 本",
            f"成功率: {stats['success_rate']:.1f}%",
            "",
            f"总章节: {stats['total_chapters']} 章",
            f"总流量: {stats['total_size_mb']:.1f} MB",
            f"总耗时: {stats['total_duration_hours']:.2f} 小时",
            f"平均耗时: {stats['avg_duration_minutes']:.1f} 分钟/本",
            "",
            "格式统计:",
        ]

        for fmt, count in stats['format_stats'].items():
            lines.append(f"  {fmt.upper()}: {count} 本")

        lines.append("=" * 40)
        return "\n".join(lines)


# 简化的记录器（无持久化）
class SimpleStatisticsRecorder:
    """简化的统计记录器"""

    def __init__(self):
        self.total_downloads = 0
        self.success_count = 0

    def record_download(self, success: bool) -> None:
        self.total_downloads += 1
        if success:
            self.success_count += 1

    def get_success_rate(self) -> float:
        if self.total_downloads == 0:
            return 0.0
        return (self.success_count / self.total_downloads) * 100

    def get_summary(self) -> str:
        return (
            f"下载统计: "
            f"总计 {self.total_downloads} 本, "
            f"成功 {self.success_count} 本, "
            f"成功率 {self.get_success_rate():.1f}%"
        )
