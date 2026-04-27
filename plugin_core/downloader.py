from __future__ import annotations

import asyncio
import html
import json
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from astrbot.api import logger

from .epub import build_epub
from .model import Book, Chapter
from .parser import parse_book, parse_chapter, parse_favorites, parse_novel_status

ESJ_BASE_URL = "https://www.esjzone.one"
ALLOWED_ESJ_HOSTS = {"www.esjzone.one"}
DETAIL_PATH_RE = re.compile(r"^/detail/(\d+)\.html$")
MAX_FILENAME_LENGTH = 120
RESERVED_WINDOWS_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(slots=True)
class DownloadResult:
    book: Book
    output_path: Path
    chapter_count: int
    image_count: int


@dataclass(slots=True)
class DownloadBudget:
    max_images: int
    max_image_bytes: int
    max_total_image_bytes: int
    max_image_pixels: int
    image_count: int = 0
    image_bytes: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def reserve_image_slot(self) -> bool:
        async with self._lock:
            if self.image_count >= self.max_images:
                return False
            self.image_count += 1
            return True

    async def add_image_bytes(self, size: int) -> None:
        async with self._lock:
            next_size = self.image_bytes + size
            if next_size > self.max_total_image_bytes:
                raise ValueError("图片总大小超过限制。")
            self.image_bytes = next_size


class EsjzoneDownloadService:
    def __init__(self, config: dict[str, Any], data_dir: Path):
        self.config = config
        self.data_dir = data_dir
        self.downloads_dir = data_dir / "downloads"
        self.users_dir = data_dir / "users"
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._client_init_lock = asyncio.Lock()
        self._cookie_locks: dict[str, asyncio.Lock] = {}
        self._semaphore = asyncio.Semaphore(self._max_concurrency())

    def reload_config(self, config: dict[str, Any]) -> None:
        self.config = config
        self._semaphore = asyncio.Semaphore(self._max_concurrency())
        logger.info("[ESJ] downloader config reloaded")

    async def close(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()

    async def validate_cookie(self, user_key: str | None = None) -> str | None:
        logger.info("[ESJ] validating saved cookie")
        response = await self._request(
            f"{ESJ_BASE_URL}/my/profile.html",
            user_key=user_key,
        )
        html = response.text
        if "window.location.href='/my/login';" in html:
            client = await self._get_client(user_key)
            client.cookies.clear()
            await self._save_cookies(user_key)
            logger.info("[ESJ] saved cookie is invalid and has been cleared")
            return None

        soup = BeautifulSoup(html, "html.parser")
        user_name_tag = soup.find("h6", class_="user-name")
        if user_name_tag:
            username = user_name_tag.get_text(strip=True)
            logger.info(f"[ESJ] cookie validated for user: {username}")
            return username
        logger.info("[ESJ] cookie validation did not find a logged-in user")
        return None

    async def login(
        self,
        email: str | None = None,
        password: str | None = None,
        user_key: str | None = None,
    ) -> str:
        if not user_key:
            raise ValueError("登录需要用户隔离标识。")
        account = self._account_config()
        email = (email or account.get("username") or "").strip()
        password = password or account.get("password") or ""
        if not email or not password:
            raise ValueError("未配置 ESJ Zone 账号或密码。")

        logger.info(f"[ESJ] login started for account: {_mask_account(email)}")
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Origin": ESJ_BASE_URL,
            "Referer": f"{ESJ_BASE_URL}/login",
        }
        payload = {"email": email, "pwd": password, "remember_me": "on"}
        await self._request(
            f"{ESJ_BASE_URL}/inc/mem_login.php",
            method="POST",
            data=payload,
            headers=headers,
            user_key=user_key,
        )

        username = await self.validate_cookie(user_key)
        if not username:
            raise ValueError("登录请求完成，但 Cookie 校验失败。")
        await self._save_cookies(user_key)
        logger.info(f"[ESJ] login succeeded for user: {username}")
        return username

    async def get_book_info(self, url: str, user_key: str | None = None) -> Book:
        normalized_url = self.normalize_url(url)
        logger.info(f"[ESJ] fetching book info: {normalized_url}")
        response = await self._request(normalized_url, user_key=user_key)
        book = parse_book(response.text, normalized_url)
        logger.info(
            f"[ESJ] parsed book info: {book.title}, chapters={len(book.chapters)}"
        )
        return book

    async def get_novel_status(
        self, url: str, user_key: str | None = None
    ) -> dict[str, str]:
        normalized_url = self.normalize_url(url)
        logger.info(f"[ESJ] checking novel status: {normalized_url}")
        response = await self._request(normalized_url, user_key=user_key)
        status = parse_novel_status(response.text, normalized_url)
        logger.info(
            f"[ESJ] status parsed: {status.get('title')}, "
            f"latest={status.get('latest_chapter')}"
        )
        return status

    async def get_favorites(
        self,
        page: int = 1,
        sort_by: str = "lastest",
        user_key: str | None = None,
    ) -> tuple[list[dict[str, str]], int]:
        if not user_key:
            raise ValueError("收藏列表需要用户登录态。")
        page = max(page, 1)
        sort_by = self._normalize_favorite_sort(sort_by)
        logger.info(f"[ESJ] fetching favorites: sort={sort_by}, page={page}")
        if sort_by == "lastest":
            url = f"{ESJ_BASE_URL}/my/favorite/udate/{page}"
        else:
            url = f"{ESJ_BASE_URL}/my/favorite/{page}"

        response = await self._request(url, user_key=user_key)
        novels, total_pages = parse_favorites(response.text)
        logger.info(
            f"[ESJ] favorites parsed: sort={sort_by}, page={page}, "
            f"items={len(novels)}, total_pages={total_pages}"
        )
        return novels, total_pages

    async def download_book(
        self,
        url: str,
        fmt: str | None = None,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        user_key: str | None = None,
    ) -> DownloadResult:
        fmt = (fmt or "epub").lower()
        if fmt not in {"epub", "txt"}:
            raise ValueError("下载格式只支持 epub 或 txt。")

        normalized_url = self.normalize_url(url)
        logger.info(
            f"[ESJ] download started: url={normalized_url}, format={fmt}, "
            f"start={start_chapter or 'first'}, end={end_chapter or 'last'}"
        )
        download_images = fmt == "epub" and self._download_images()
        book, selected_chapters, image_count = await self._fetch_book(
            url=normalized_url,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            download_images=download_images,
            user_key=user_key,
        )

        output_path = self._resolve_output_path(book, normalized_url, fmt)
        if fmt == "epub":
            intro_chapter = self._build_intro_chapter(book, selected_chapters)
            await self._write_output_atomic(
                output_path,
                build_epub,
                book,
                [intro_chapter, *selected_chapters],
            )
        else:
            await self._write_output_atomic(
                output_path,
                self._write_txt,
                book,
                selected_chapters,
            )

        logger.info(
            f"[ESJ] download finished: {book.title}, "
            f"chapters={len(selected_chapters)}, images={image_count}, "
            f"path={output_path}"
        )
        return DownloadResult(
            book=book,
            output_path=output_path,
            chapter_count=len(selected_chapters),
            image_count=image_count,
        )

    async def _fetch_book(
        self,
        url: str,
        start_chapter: int | None,
        end_chapter: int | None,
        download_images: bool,
        user_key: str | None,
    ) -> tuple[Book, list[Chapter], int]:
        normalized_url = self.normalize_url(url)
        response = await self._request(normalized_url, user_key=user_key)
        book = parse_book(response.text, normalized_url)
        selected_chapters = self._select_chapters(book, start_chapter, end_chapter)
        logger.info(
            f"[ESJ] selected chapters: book={book.title}, count={len(selected_chapters)}"
        )

        budget = DownloadBudget(
            max_images=self._max_images_per_download(),
            max_image_bytes=self._max_image_bytes(),
            max_total_image_bytes=self._max_total_image_bytes(),
            max_image_pixels=self._max_image_pixels(),
        )

        if download_images and book.cover_url:
            try:
                raw_cover = await self._download_image(
                    book.cover_url,
                    budget,
                    user_key=user_key,
                )
                book.cover_image = _normalize_image_bytes(
                    raw_cover,
                    "cover.png",
                    budget.max_image_pixels,
                )
            except Exception as exc:
                logger.warning(f"[ESJ] cover download failed: {exc}")

        image_counter = 0

        async def fetch_chapter(chapter: Chapter) -> None:
            nonlocal image_counter
            async with self._semaphore:
                chapter_response = await self._request(chapter.url, user_key=user_key)
            title, html = parse_chapter(
                chapter_response.text,
                chapter.url,
                chapter.title,
            )
            chapter.title = title
            if download_images:
                chapter.content_html, downloaded = await self._process_images(
                    html,
                    chapter,
                    budget,
                    user_key,
                )
                image_counter += downloaded
            else:
                chapter.content_html = _sanitize_html(html)
            chapter.content_text = _plain_text_from_html(chapter.content_html)

        await gather_batched(
            selected_chapters,
            fetch_chapter,
            self._max_concurrency(),
        )
        return book, selected_chapters, image_counter

    async def _process_images(
        self,
        html: str,
        chapter: Chapter,
        budget: DownloadBudget,
        user_key: str | None,
    ) -> tuple[str, int]:
        soup = BeautifulSoup(html, "html.parser")
        image_jobs: list[tuple[Any, str, str]] = []
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src or src.startswith("images/"):
                continue
            image_url = urljoin(chapter.url, src)
            try:
                image_url = self._validate_esj_url(image_url)
            except ValueError:
                img.decompose()
                continue
            if not await budget.reserve_image_slot():
                img.decompose()
                continue
            ext = (
                ".gif"
                if image_url.lower().split("?", 1)[0].endswith(".gif")
                else ".png"
            )
            filename = f"{uuid.uuid4().hex}{ext}"
            img["src"] = f"images/{filename}"
            image_jobs.append((img, image_url, filename))

        downloaded = 0

        async def fetch_image(job: tuple[Any, str, str]) -> None:
            nonlocal downloaded
            _img, image_url, filename = job
            try:
                async with self._semaphore:
                    raw = await self._download_image(
                        image_url,
                        budget,
                        user_key=user_key,
                    )
                chapter.images[filename] = _normalize_image_bytes(
                    raw,
                    filename,
                    budget.max_image_pixels,
                )
                downloaded += 1
            except Exception as exc:
                _img.decompose()
                logger.warning(f"[ESJ] image download failed: {image_url}, {exc}")

        await gather_batched(image_jobs, fetch_image, self._max_concurrency())
        return _sanitize_html(str(soup)), downloaded

    async def _download_image(
        self,
        url: str,
        budget: DownloadBudget,
        user_key: str | None = None,
    ) -> bytes:
        request_url = self._validate_esj_url(url)
        client = await self._get_client(user_key)
        retries = self._retry_attempts()
        retry_delays = self._retry_delays()
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async with client.stream(
                    "GET",
                    request_url,
                    timeout=self._timeout(),
                    headers={"Accept": "image/*,*/*;q=0.8"},
                ) as response:
                    self._validate_esj_url(str(response.url))
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if content_type and not content_type.lower().startswith("image/"):
                        raise ValueError("图片响应类型无效。")
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > budget.max_image_bytes:
                        raise ValueError("图片文件超过单图大小限制。")

                    chunks: list[bytes] = []
                    total_size = 0
                    async for chunk in response.aiter_bytes():
                        total_size += len(chunk)
                        if total_size > budget.max_image_bytes:
                            raise ValueError("图片文件超过单图大小限制。")
                        await budget.add_image_bytes(len(chunk))
                        chunks.append(chunk)
                    return b"".join(chunks)
            except Exception as exc:
                last_exc = exc
                if attempt >= retries:
                    break
                delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                logger.warning(
                    f"[ESJ] image request failed and will retry in {delay}s: "
                    f"{request_url}, error={exc}"
                )
                await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc

    async def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        timeout: float | None = None,
        user_key: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        request_url = self._validate_esj_url(url)
        client = await self._get_client(user_key)
        retries = self._retry_attempts()
        retry_delays = self._retry_delays()
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                logger.debug(
                    f"[ESJ] request {method} {request_url}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                response = await client.request(
                    method,
                    request_url,
                    timeout=timeout or self._timeout(),
                    **kwargs,
                )
                self._validate_esj_url(str(response.url))
                response.raise_for_status()
                return response
            except Exception as exc:
                last_exc = exc
                if attempt >= retries:
                    break
                delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                logger.warning(
                    f"[ESJ] request failed and will retry in {delay}s: "
                    f"{method} {request_url}, error={exc}"
                )
                await asyncio.sleep(delay)
        assert last_exc is not None
        logger.warning(
            f"[ESJ] request failed permanently: {method} {request_url}, {last_exc}"
        )
        raise last_exc

    async def _get_client(self, user_key: str | None = None) -> httpx.AsyncClient:
        scope = self._client_scope(user_key)
        if scope in self._clients:
            return self._clients[scope]
        async with self._client_init_lock:
            if scope in self._clients:
                return self._clients[scope]
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
            client = httpx.AsyncClient(
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
                    ),
                    "Accept": "*/*",
                },
            )
            self._clients[scope] = client
            if user_key:
                await self._load_cookies(scope, client)
            logger.info(f"[ESJ] HTTP client initialized: scope={scope}")
            return client

    async def clear_login(self, user_key: str) -> None:
        scope = self._client_scope(user_key)
        client = self._clients.get(scope)
        if client is not None:
            client.cookies.clear()
        cookies_path = self._cookies_path(scope)
        if cookies_path.exists():
            cookies_path.unlink()
        logger.info(f"[ESJ] cleared cookies for scope={scope}")

    async def _load_cookies(self, scope: str, client: httpx.AsyncClient) -> None:
        cookies_path = self._cookies_path(scope)
        if not cookies_path.exists():
            return
        lock = self._cookie_lock(scope)
        async with lock:
            data = _read_json_with_corrupt_backup(cookies_path)
            if not isinstance(data, list):
                return
            loaded = 0
            for cookie in data:
                if not isinstance(cookie, dict):
                    continue
                name = str(cookie.get("name", ""))
                value = str(cookie.get("value", ""))
                if not name:
                    continue
                client.cookies.set(
                    name,
                    value,
                    domain=cookie.get("domain") or "www.esjzone.one",
                    path=cookie.get("path") or "/",
                )
                loaded += 1
            logger.info(f"[ESJ] loaded {loaded} cookies")

    async def _save_cookies(self, user_key: str | None) -> None:
        if not user_key:
            return
        scope = self._client_scope(user_key)
        client = self._clients.get(scope)
        if client is None:
            return
        cookies_path = self._cookies_path(scope)
        lock = self._cookie_lock(scope)
        async with lock:
            cookies = [
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                }
                for cookie in client.cookies.jar
            ]
            _write_json_atomic(cookies_path, cookies)
            logger.info(f"[ESJ] saved {len(cookies)} cookies")

    def _client_scope(self, user_key: str | None) -> str:
        if not user_key:
            return "anonymous"
        return _safe_state_key(user_key)

    def _cookies_path(self, scope: str) -> Path:
        return self.users_dir / scope / "cookies.json"

    def _cookie_lock(self, scope: str) -> asyncio.Lock:
        lock = self._cookie_locks.get(scope)
        if lock is None:
            lock = asyncio.Lock()
            self._cookie_locks[scope] = lock
        return lock

    def _select_chapters(
        self,
        book: Book,
        start_chapter: int | None,
        end_chapter: int | None,
    ) -> list[Chapter]:
        if not book.chapters:
            raise ValueError("未解析到章节列表。")

        total = len(book.chapters)
        if not start_chapter or start_chapter < 1:
            start_idx = 0
        else:
            start_idx = min(start_chapter - 1, total - 1)

        if not end_chapter or end_chapter < 1:
            end_idx = total - 1
        else:
            end_idx = min(end_chapter - 1, total - 1)

        if end_idx < start_idx:
            raise ValueError("结束章节不能小于起始章节。")

        selected = book.chapters[start_idx : end_idx + 1]
        max_chapters = self._max_chapters_per_download()
        if len(selected) > max_chapters:
            raise ValueError(f"单次下载章节数不能超过 {max_chapters}。")
        return selected

    def _build_intro_chapter(
        self,
        book: Book,
        selected_chapters: list[Chapter],
    ) -> Chapter:
        intro_content = []
        if book.cover_image:
            intro_content.append(
                '<div style="text-align: center;">'
                '<img src="images/cover.png" alt="封面"/>'
                "</div>"
            )
        intro_content.extend(
            [
                f"<h1>{html.escape(book.title)}</h1>",
                f"<p><strong>作者:</strong> {html.escape(book.author)}</p>",
                "<p><strong>源网址:</strong> "
                f'<a href="{html.escape(book.url, quote=True)}">'
                f"{html.escape(book.url)}</a></p>",
            ]
        )
        if book.tags:
            intro_content.append(
                f"<p><strong>Tags:</strong> {html.escape(', '.join(book.tags))}</p>"
            )
        if book.update_time:
            intro_content.append(
                f"<p><strong>最近更新:</strong> {html.escape(book.update_time)}</p>"
            )

        intro_content.append("<h3>简介</h3>")
        for line in book.introduction.splitlines():
            if line.strip():
                intro_content.append(f"<p>{html.escape(line.strip())}</p>")

        intro_content.append("<h3>目录</h3>")
        intro_content.append("<ul>")
        for chapter in selected_chapters:
            intro_content.append(
                f'<li><a href="chapter_{chapter.index}.xhtml">'
                f"{html.escape(chapter.title)}</a></li>"
            )
        intro_content.append("</ul>")

        return Chapter(
            url=book.url,
            title="书籍信息",
            index=0,
            content_html=_sanitize_html("\n".join(intro_content)),
            content_text=(
                f"{book.title}\n作者: {book.author}\n"
                f"Tags: {', '.join(book.tags)}\n\n简介:\n{book.introduction}"
            ),
        )

    async def _write_output_atomic(
        self,
        output_path: Path,
        writer: Callable[..., Any],
        *args: Any,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            await asyncio.to_thread(writer, *args, tmp_path)
            self._ensure_output_size(tmp_path)
            tmp_path.replace(output_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _write_txt(
        self,
        book: Book,
        chapters: list[Chapter],
        output_path: Path,
    ) -> None:
        lines = [
            f"{book.title}\n",
            f"作者: {book.author}\n",
            f"源网址: {book.url}\n\n",
            "简介:\n",
            f"{book.introduction}\n\n",
            "目录:\n",
        ]
        for chapter in chapters:
            lines.append(f"{chapter.title}\n")
        lines.append("\n" + "=" * 20 + "\n\n")
        for chapter in chapters:
            lines.append(f"{chapter.title}\n")
            lines.append("-" * len(chapter.title) + "\n\n")
            lines.append((chapter.content_text or "") + "\n\n")
        output_path.write_text("".join(lines), encoding="utf-8")

    def _resolve_output_path(self, book: Book, url: str, fmt: str) -> Path:
        download_config = self._download_config()
        filename = self._filename_for(book, url, fmt)
        use_book_dir = _bool(download_config.get("use_book_dir"), True)
        if use_book_dir:
            book_id = self.book_id(url)
            base_dir = self.downloads_dir / book_id
        else:
            base_dir = self.downloads_dir
        base_dir.mkdir(parents=True, exist_ok=True)
        output_path = base_dir / filename
        downloads_root = self.downloads_dir.resolve()
        resolved_output = output_path.resolve()
        try:
            resolved_output.relative_to(downloads_root)
        except ValueError as exc:
            raise ValueError("下载输出路径非法。") from exc
        return output_path

    def _filename_for(self, book: Book, url: str, fmt: str) -> str:
        download_config = self._download_config()
        naming_mode = str(
            download_config.get("file_naming_mode")
            or download_config.get("naming_mode")
            or "book_name"
        )
        if naming_mode in {"number", "book_id"}:
            stem = self.book_id(url)
        else:
            stem = _sanitize_filename(book.title) or self.book_id(url)
        return f"{stem}-{uuid.uuid4().hex[:8]}.{fmt}"

    def normalize_url(self, url: str) -> str:
        cleaned = url.strip()
        if not cleaned:
            raise ValueError("URL 不能为空。")
        if re.fullmatch(r"\d+", cleaned):
            return f"{ESJ_BASE_URL}/detail/{cleaned}.html"
        if "\\" in cleaned:
            raise ValueError("只支持 ESJ 小说编号或详情页 URL。")
        normalized = self._validate_esj_url(urljoin(f"{ESJ_BASE_URL}/", cleaned))
        path = urlparse(normalized).path
        if not DETAIL_PATH_RE.fullmatch(path):
            raise ValueError("只支持 ESJ 小说编号或详情页 URL。")
        return normalized

    def book_id(self, url: str) -> str:
        normalized = self.normalize_url(url)
        match = DETAIL_PATH_RE.fullmatch(urlparse(normalized).path)
        if match is None:
            raise ValueError("无法从 URL 解析 ESJ 小说编号。")
        return match.group(1)

    def _validate_esj_url(self, url: str) -> str:
        cleaned = url.strip()
        if not cleaned:
            raise ValueError("URL 不能为空。")
        if "\\" in cleaned or "\\" in unquote(cleaned):
            raise ValueError("URL 包含非法路径字符。")
        if any(ord(ch) < 32 for ch in cleaned):
            raise ValueError("URL 包含非法控制字符。")
        parsed = urlparse(cleaned)
        if parsed.scheme != "https":
            raise ValueError("只允许访问 ESJ HTTPS 地址。")
        hostname = (parsed.hostname or "").lower()
        if hostname not in ALLOWED_ESJ_HOSTS:
            raise ValueError("只允许访问 ESJ 官方域名。")
        if parsed.username or parsed.password:
            raise ValueError("URL 不允许包含用户认证信息。")
        return cleaned

    def _account_config(self) -> dict[str, Any]:
        account = self.config.get("account", {})
        return account if isinstance(account, dict) else {}

    def _download_config(self) -> dict[str, Any]:
        download = self.config.get("download", {})
        return download if isinstance(download, dict) else {}

    def _normalize_favorite_sort(self, sort_by: str) -> str:
        normalized = (sort_by or "lastest").strip().lower()
        if normalized in {"lastest", "latest", "new", "udate", "update"}:
            return "lastest"
        if normalized in {"favor", "favorite", "collect", "collected"}:
            return "collected"
        raise ValueError("收藏排序只支持 lastest 或 collected。")

    def _timeout(self) -> float:
        return _safe_float(
            self._download_config().get("timeout_seconds"),
            180.0,
            5.0,
            300.0,
        )

    def _retry_attempts(self) -> int:
        return _safe_int(self._download_config().get("retry_attempts"), 2, 0, 5)

    def _retry_delays(self) -> list[float]:
        raw = self._download_config().get("retry_delays")
        if isinstance(raw, list) and raw:
            return [_safe_float(item, 1.0, 0.0, 300.0) for item in raw[:5]]
        return [1.0, 3.0, 5.0]

    def _max_concurrency(self) -> int:
        return _safe_int(self._download_config().get("max_threads"), 5, 1, 10)

    def _download_images(self) -> bool:
        return _bool(self._download_config().get("download_images"), True)

    def _max_chapters_per_download(self) -> int:
        return _safe_int(
            self._download_config().get("max_chapters_per_download"),
            300,
            1,
            1000,
        )

    def _max_images_per_download(self) -> int:
        return _safe_int(
            self._download_config().get("max_images_per_download"),
            500,
            0,
            2000,
        )

    def _max_image_bytes(self) -> int:
        return _safe_int(
            self._download_config().get("max_image_bytes"),
            10 * 1024 * 1024,
            1024,
            50 * 1024 * 1024,
        )

    def _max_total_image_bytes(self) -> int:
        return _safe_int(
            self._download_config().get("max_total_image_bytes"),
            100 * 1024 * 1024,
            1024,
            500 * 1024 * 1024,
        )

    def _max_image_pixels(self) -> int:
        return _safe_int(
            self._download_config().get("max_image_pixels"),
            20_000_000,
            1_000_000,
            100_000_000,
        )

    def _max_output_bytes(self) -> int:
        return _safe_int(
            self._download_config().get("max_output_bytes"),
            150 * 1024 * 1024,
            1024,
            1024 * 1024 * 1024,
        )

    def _ensure_output_size(self, output_path: Path) -> None:
        max_output_bytes = self._max_output_bytes()
        if output_path.stat().st_size > max_output_bytes:
            raise ValueError("生成文件超过大小限制。")


def _plain_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    return soup.get_text("\n", strip=True)


def _normalize_image_bytes(raw: bytes, filename: str, max_pixels: int) -> bytes:
    Image.MAX_IMAGE_PIXELS = max_pixels
    with Image.open(BytesIO(raw)) as image:
        width, height = image.size
        if width * height > max_pixels:
            raise ValueError("图片像素数超过限制。")
        if filename.lower().endswith(".gif"):
            return raw
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def _sanitize_html(raw_html: str) -> str:
    allowed_tags = {
        "a",
        "b",
        "blockquote",
        "br",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "rt",
        "ruby",
        "s",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
    allowed_attrs = {
        "a": {"href", "title"},
        "img": {"src", "alt", "title"},
        "td": {"colspan", "rowspan"},
        "th": {"colspan", "rowspan"},
    }
    blocked_tags = {"script", "style", "iframe", "object", "embed", "form"}
    soup = BeautifulSoup(raw_html or "", "html.parser")
    for tag in list(soup.find_all(True)):
        if tag.name in blocked_tags:
            tag.decompose()
            continue
        if tag.name not in allowed_tags:
            tag.unwrap()
            continue
        allowed = allowed_attrs.get(tag.name, set())
        for attr in list(tag.attrs):
            if attr.lower().startswith("on") or attr not in allowed:
                del tag.attrs[attr]
        if tag.name == "a":
            href = str(tag.get("href") or "").strip()
            if not _is_safe_href(href):
                del tag.attrs["href"]
        elif tag.name == "img":
            src = str(tag.get("src") or "").strip()
            if not src.startswith("images/"):
                tag.decompose()
    return str(soup)


def _is_safe_href(href: str) -> bool:
    if not href:
        return False
    parsed = urlparse(href)
    if not parsed.scheme:
        return href.startswith("#") or href.endswith(".xhtml")
    return parsed.scheme in {"https", "http"} and not (
        parsed.username or parsed.password
    )


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "", filename)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return ""
    if cleaned.upper() in RESERVED_WINDOWS_FILENAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:MAX_FILENAME_LENGTH].rstrip(" .")


def _safe_state_key(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", value.strip())
    return safe[:80] or uuid.uuid4().hex


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.replace(path)


def _read_json_with_corrupt_backup(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        backup_path = path.with_name(f"{path.name}.corrupt.{uuid.uuid4().hex[:8]}")
        try:
            path.replace(backup_path)
            logger.warning(f"[ESJ] moved corrupt JSON to {backup_path.name}: {exc}")
        except Exception as backup_exc:
            logger.warning(f"[ESJ] failed to backup corrupt JSON: {backup_exc}")
        return None


def _mask_account(account: str) -> str:
    if "@" in account:
        name, domain = account.split("@", 1)
        return f"{name[:2]}***@{domain}"
    return f"{account[:2]}***"


def _safe_int(
    value: Any,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _safe_float(
    value: Any,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "enable", "enabled"}
    if value is None:
        return default
    return bool(value)


async def gather_batched(
    items: list[Any],
    func: Callable[[Any], Awaitable[None]],
    batch_size: int,
) -> None:
    size = max(int(batch_size or 1), 1)
    for index in range(0, len(items), size):
        await asyncio.gather(*(func(item) for item in items[index : index + size]))
