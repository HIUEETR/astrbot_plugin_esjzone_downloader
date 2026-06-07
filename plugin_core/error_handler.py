"""错误处理和分类模块"""

from __future__ import annotations

from enum import Enum


class ErrorCategory(Enum):
    """错误分类"""

    NETWORK = "network"  # 网络错误（超时、连接失败）
    PERMISSION = "permission"  # 权限错误（需要登录、VIP 章节）
    RESOURCE = "resource"  # 资源错误（书籍不存在、章节404）
    LIMIT = "limit"  # 限制错误（下载限额、验证码）
    PARSING = "parsing"  # 解析错误
    FILESYSTEM = "filesystem"  # 文件系统错误
    UNKNOWN = "unknown"  # 未知错误


class ESJError(Exception):
    """ESJ 插件基础异常"""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        original: Exception | None = None,
        user_message: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.original = original
        self.user_message = user_message or message


class NetworkError(ESJError):
    """网络相关错误"""

    def __init__(self, message: str, original: Exception | None = None):
        super().__init__(
            message,
            category=ErrorCategory.NETWORK,
            original=original,
            user_message="网络连接失败，请检查网络后重试",
        )


class PermissionError(ESJError):
    """权限相关错误"""

    def __init__(self, message: str, original: Exception | None = None):
        super().__init__(
            message,
            category=ErrorCategory.PERMISSION,
            original=original,
            user_message="需要登录或权限不足，请在私聊使用 /esj l 登录",
        )


class ResourceNotFoundError(ESJError):
    """资源不存在错误"""

    def __init__(self, message: str, original: Exception | None = None):
        super().__init__(
            message,
            category=ErrorCategory.RESOURCE,
            original=original,
            user_message="请求的资源不存在，请检查书籍编号或 URL",
        )


class LimitExceededError(ESJError):
    """限制超出错误"""

    def __init__(self, message: str, original: Exception | None = None):
        super().__init__(
            message,
            category=ErrorCategory.LIMIT,
            original=original,
            user_message="下载限额或服务器限流，请稍后重试",
        )


class ParsingError(ESJError):
    """解析错误"""

    def __init__(self, message: str, original: Exception | None = None):
        super().__init__(
            message,
            category=ErrorCategory.PARSING,
            original=original,
            user_message="页面解析失败，可能是网站结构变化",
        )


def classify_error(exc: Exception) -> ErrorCategory:
    """
    分类异常

    Args:
        exc: 异常对象

    Returns:
        错误分类
    """
    if isinstance(exc, ESJError):
        return exc.category

    exc_name = exc.__class__.__name__.lower()
    exc_message = str(exc).lower()

    # 网络错误
    if any(
        keyword in exc_name for keyword in ["timeout", "connect", "network", "httpx"]
    ):
        return ErrorCategory.NETWORK
    if any(keyword in exc_message for keyword in ["timeout", "连接", "network"]):
        return ErrorCategory.NETWORK

    # 权限错误
    if any(
        keyword in exc_message for keyword in ["登录", "login", "权限", "permission"]
    ):
        return ErrorCategory.PERMISSION
    if "401" in exc_message or "403" in exc_message:
        return ErrorCategory.PERMISSION

    # 资源错误
    if "404" in exc_message or "not found" in exc_message:
        return ErrorCategory.RESOURCE
    if any(keyword in exc_message for keyword in ["不存在", "未找到"]):
        return ErrorCategory.RESOURCE

    # 限制错误
    if any(keyword in exc_message for keyword in ["限额", "限流", "rate limit", "429"]):
        return ErrorCategory.LIMIT
    if "验证码" in exc_message or "captcha" in exc_message:
        return ErrorCategory.LIMIT

    # 解析错误
    if any(keyword in exc_name for keyword in ["parse", "value"]):
        return ErrorCategory.PARSING
    if any(keyword in exc_message for keyword in ["解析", "parse"]):
        return ErrorCategory.PARSING

    return ErrorCategory.UNKNOWN


def get_user_friendly_message(exc: Exception) -> str:
    """
    获取用户友好的错误提示

    Args:
        exc: 异常对象

    Returns:
        用户友好的错误消息
    """
    if isinstance(exc, ESJError) and exc.user_message:
        return exc.user_message

    category = classify_error(exc)

    messages = {
        ErrorCategory.NETWORK: "网络连接失败，请检查网络后重试",
        ErrorCategory.PERMISSION: "需要登录或权限不足，请在私聊使用 /esj l 登录",
        ErrorCategory.RESOURCE: "请求的资源不存在，请检查书籍编号或 URL",
        ErrorCategory.LIMIT: "下载限额或服务器限流，请稍后重试",
        ErrorCategory.PARSING: "页面解析失败，可能是网站结构变化",
        ErrorCategory.FILESYSTEM: "文件操作失败，请检查磁盘空间和权限",
        ErrorCategory.UNKNOWN: "操作失败，请稍后重试",
    }

    return messages.get(category, "操作失败，请稍后重试")


def should_retry(exc: Exception) -> bool:
    """
    判断是否应该重试

    Args:
        exc: 异常对象

    Returns:
        是否应该重试
    """
    category = classify_error(exc)

    # 网络错误和限制错误可以重试
    if category in {ErrorCategory.NETWORK, ErrorCategory.LIMIT}:
        return True

    # 权限错误、资源错误、解析错误不应重试
    if category in {
        ErrorCategory.PERMISSION,
        ErrorCategory.RESOURCE,
        ErrorCategory.PARSING,
    }:
        return False

    # 未知错误默认重试
    return True
