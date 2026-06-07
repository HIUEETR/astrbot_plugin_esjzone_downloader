"""工具函数模块 - 文本处理和文件名清理"""

from __future__ import annotations

import re
from pathlib import Path


def sanitize_filename(filename: str, max_length: int = 120) -> str:
    """
    清理文件名，移除非法字符

    Args:
        filename: 原始文件名
        max_length: 最大长度

    Returns:
        清理后的文件名
    """
    # Windows 保留文件名
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }

    # 移除非法字符
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", filename)

    # 移除前后空格和点
    cleaned = cleaned.strip(" .")

    # 检查是否为保留名称
    name_without_ext = cleaned.split(".")[0].upper()
    if name_without_ext in reserved_names:
        cleaned = f"_{cleaned}"

    # 截断到最大长度
    if len(cleaned) > max_length:
        name, ext = Path(cleaned).stem, Path(cleaned).suffix
        max_name_len = max_length - len(ext)
        cleaned = name[:max_name_len] + ext

    return cleaned or "untitled"


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    截断文本到指定长度

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后缀

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小

    Args:
        size_bytes: 字节数

    Returns:
        格式化的文件大小字符串
    """
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def split_text_by_length(text: str, max_length: int = 1500) -> list[str]:
    """
    按最大长度分割文本（保留完整行）

    Args:
        text: 原始文本
        max_length: 每段最大长度

    Returns:
        文本段列表
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.splitlines():
        candidate = f"{current}\n{line}".strip() if current else line
        if len(candidate) <= max_length:
            current = candidate
            continue

        if current:
            chunks.append(current)

        # 处理超长单行
        while len(line) > max_length:
            chunks.append(line[:max_length])
            line = line[max_length:]
        current = line

    if current:
        chunks.append(current)

    return chunks


def extract_book_id_from_url(url: str) -> str | None:
    """
    从 URL 中提取书籍 ID

    Args:
        url: ESJ Zone 书籍 URL

    Returns:
        书籍 ID 或 None
    """
    match = re.search(r"/detail/(\d+)\.html", url)
    return match.group(1) if match else None


def format_time_elapsed(seconds: float) -> str:
    """
    格式化时间间隔

    Args:
        seconds: 秒数

    Returns:
        格式化的时间字符串
    """
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}分钟"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}小时"


def normalize_whitespace(text: str) -> str:
    """
    规范化空白字符

    Args:
        text: 原始文本

    Returns:
        规范化后的文本
    """
    # 替换多个空格为单个空格
    text = re.sub(r" +", " ", text)
    # 替换多个换行为双换行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def create_progress_bar(current: int, total: int, width: int = 20) -> str:
    """
    创建简单的进度条文本

    Args:
        current: 当前进度
        total: 总量
        width: 进度条宽度

    Returns:
        进度条字符串
    """
    if total <= 0:
        return "█" * width

    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    percentage = 100 * current / total
    return f"[{bar}] {percentage:.1f}%"
