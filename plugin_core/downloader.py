from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from astrbot.api import logger

from .epub import build_epub
from .model import Book, Chapter
from .parser import parse_book, parse_chapter, parse_favorites, parse_novel_status

ESJ_BASE_URL = "https://www.esjzone.one"


@dataclass(slots=True)
class DownloadResult:
    book: Book
    output_path: Path
    chapter_count: int
    image_count: int


class EsjzoneDownloadService:
    def __init__(self, config: dict[str, Any], data_dir: Path):
        self.config = config
        self.data_dir = data_dir
        self.downloads_dir = data_dir / "downloads"
        self.cookies_path = data_dir / "cookies.json"
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(self._max_concurrency())

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def validate_cookie(self) -> str | None:
        logger.info("[ESJ] validating saved cookie")
        response = await self._request(f"{ESJ_BASE_URL}/my/profile.html")
        html = response.text
        if "window.location.href='/my/login';" in html:
            client = await self._get_client()
            client.cookies.clear()
            await self._save_cookies()
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

    async def login(self, email: str | None = None, password: str | None = None) -> str:
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
        )

        username = await self.validate_cookie()
        if not username:
            raise ValueError("登录请求完成，但 Cookie 校验失败。")
        await self._save_cookies()
        logger.info(f"[ESJ] login succeeded for user: {username}")
        return username

    async def get_book_info(self, url: str) -> Book:
        normalized_url = self.normalize_url(url)
        logger.info(f"[ESJ] fetching book info: {normalized_url}")
        response = await self._request(normalized_url)
        book = parse_book(response.text, normalized_url)
        logger.info(
            f"[ESJ] parsed book info: {book.title}, chapters={len(book.chapters)}"
        )
        return book

    async def get_novel_status(self, url: str) -> dict[str, str]:
        normalized_url = self.normalize_url(url)
        logger.info(f"[ESJ] checking novel status: {normalized_url}")
        response = await self._request(normalized_url)
        status = parse_novel_status(response.text, normalized_url)
        logger.info(
            f"[ESJ] status parsed: {status.get('title')}, "
            f"latest={status.get('latest_chapter')}"
        )
        return status

    async def get_favorites(
        self, page: int = 1, sort_by: str = "lastest"
    ) -> tuple[list[dict[str, str]], int]:
        page = max(page, 1)
        sort_by = self._normalize_favorite_sort(sort_by)
        logger.info(f"[ESJ] fetching favorites: sort={sort_by}, page={page}")
        client = await self._get_client()
        if sort_by == "lastest":
            client.cookies.set("favorite_sort", "udate", domain="www.esjzone.one")
            url = f"{ESJ_BASE_URL}/my/favorite/udate/{page}"
        else:
            client.cookies.set("favorite_sort", "new", domain="www.esjzone.one")
            url = f"{ESJ_BASE_URL}/my/favorite/{page}"

        response = await self._request(url)
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
        )

        output_path = self._resolve_output_path(book, normalized_url, fmt)
        if fmt == "epub":
            intro_chapter = self._build_intro_chapter(book, selected_chapters)
            build_epub(book, [intro_chapter, *selected_chapters], output_path)
        else:
            self._write_txt(book, selected_chapters, output_path)

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
    ) -> tuple[Book, list[Chapter], int]:
        normalized_url = self.normalize_url(url)
        response = await self._request(normalized_url)
        book = parse_book(response.text, normalized_url)
        selected_chapters = self._select_chapters(book, start_chapter, end_chapter)
        logger.info(
            f"[ESJ] selected chapters: book={book.title}, count={len(selected_chapters)}"
        )

        if download_images and book.cover_url:
            try:
                raw_cover = await self._download_image(book.cover_url)
                book.cover_image = _normalize_image_bytes(raw_cover, "cover.png")
            except Exception as exc:
                logger.warning(f"[ESJ] cover download failed: {exc}")

        image_counter = 0

        async def fetch_chapter(chapter: Chapter) -> None:
            nonlocal image_counter
            async with self._semaphore:
                chapter_response = await self._request(chapter.url)
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
                )
                image_counter += downloaded
            else:
                chapter.content_html = html
            chapter.content_text = _plain_text_from_html(chapter.content_html)

        await gather_all(selected_chapters, fetch_chapter)
        return book, selected_chapters, image_counter

    async def _process_images(
        self,
        html: str,
        chapter: Chapter,
    ) -> tuple[str, int]:
        soup = BeautifulSoup(html, "html.parser")
        image_jobs: list[tuple[Any, str, str]] = []
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src or src.startswith("images/"):
                continue
            image_url = urljoin(chapter.url, src)
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
                    raw = await self._download_image(image_url)
                chapter.images[filename] = _normalize_image_bytes(raw, filename)
                downloaded += 1
            except Exception as exc:
                logger.warning(f"[ESJ] image download failed: {image_url}, {exc}")

        await gather_all(image_jobs, fetch_image)
        return str(soup), downloaded

    async def _download_image(self, url: str) -> bytes:
        response = await self._request(url, timeout=self._timeout())
        return response.content

    async def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        timeout: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        client = await self._get_client()
        retries = self._retry_attempts()
        retry_delays = self._retry_delays()
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                logger.debug(
                    f"[ESJ] request {method} {url}, attempt={attempt + 1}/{retries + 1}"
                )
                response = await client.request(
                    method,
                    url,
                    timeout=timeout or self._timeout(),
                    **kwargs,
                )
                response.raise_for_status()
                return response
            except Exception as exc:
                last_exc = exc
                if attempt >= retries:
                    break
                delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                logger.warning(
                    f"[ESJ] request failed and will retry in {delay}s: "
                    f"{method} {url}, error={exc}"
                )
                await asyncio.sleep(delay)
        assert last_exc is not None
        logger.warning(f"[ESJ] request failed permanently: {method} {url}, {last_exc}")
        raise last_exc

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
            self._client = httpx.AsyncClient(
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
            await self._load_cookies()
            logger.info("[ESJ] HTTP client initialized")
        return self._client

    async def _load_cookies(self) -> None:
        if self._client is None or not self.cookies_path.exists():
            return
        try:
            data = json.loads(self.cookies_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return
            for cookie in data:
                if not isinstance(cookie, dict):
                    continue
                name = str(cookie.get("name", ""))
                value = str(cookie.get("value", ""))
                if not name:
                    continue
                self._client.cookies.set(
                    name,
                    value,
                    domain=cookie.get("domain") or "www.esjzone.one",
                    path=cookie.get("path") or "/",
                )
            logger.info(f"[ESJ] loaded {len(data)} cookies from {self.cookies_path}")
        except Exception as exc:
            logger.warning(f"[ESJ] failed to load cookies: {exc}")

    async def _save_cookies(self) -> None:
        if self._client is None:
            return
        cookies = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            }
            for cookie in self._client.cookies.jar
        ]
        self.cookies_path.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[ESJ] saved {len(cookies)} cookies to {self.cookies_path}")

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
        max_count = self._max_chapters_per_download()
        if max_count > 0 and len(selected) > max_count:
            raise ValueError(
                f"本次将下载 {len(selected)} 章，超过配置限制 {max_count} 章。"
            )
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
                f"<h1>{book.title}</h1>",
                f"<p><strong>作者:</strong> {book.author}</p>",
                f'<p><strong>源网址:</strong> <a href="{book.url}">{book.url}</a></p>',
            ]
        )
        if book.tags:
            intro_content.append(
                f"<p><strong>Tags:</strong> {', '.join(book.tags)}</p>"
            )
        if book.update_time:
            intro_content.append(
                f"<p><strong>最近更新:</strong> {book.update_time}</p>"
            )

        intro_content.append("<h3>简介</h3>")
        for line in book.introduction.splitlines():
            if line.strip():
                intro_content.append(f"<p>{line.strip()}</p>")

        intro_content.append("<h3>目录</h3>")
        intro_content.append("<ul>")
        for chapter in selected_chapters:
            intro_content.append(
                f'<li><a href="chapter_{chapter.index}.xhtml">{chapter.title}</a></li>'
            )
        intro_content.append("</ul>")

        return Chapter(
            url=book.url,
            title="书籍信息",
            index=0,
            content_html="\n".join(intro_content),
            content_text=(
                f"{book.title}\n作者: {book.author}\n"
                f"Tags: {', '.join(book.tags)}\n\n简介:\n{book.introduction}"
            ),
        )

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
        return base_dir / filename

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
        return f"{stem}.{fmt}"

    def normalize_url(self, url: str) -> str:
        cleaned = url.strip()
        if not cleaned:
            raise ValueError("URL 不能为空。")
        if re.fullmatch(r"\d+", cleaned):
            return f"{ESJ_BASE_URL}/detail/{cleaned}.html"
        return urljoin(ESJ_BASE_URL, cleaned)

    def book_id(self, url: str) -> str:
        return self.normalize_url(url).rstrip("/").split("/")[-1].replace(".html", "")

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
        return _safe_float(self._download_config().get("timeout_seconds"), 180.0, 5.0)

    def _retry_attempts(self) -> int:
        return _safe_int(self._download_config().get("retry_attempts"), 2, 0)

    def _retry_delays(self) -> list[float]:
        raw = self._download_config().get("retry_delays")
        if isinstance(raw, list) and raw:
            return [_safe_float(item, 1.0, 0.0) for item in raw]
        return [1.0, 3.0, 5.0]

    def _max_concurrency(self) -> int:
        return _safe_int(self._download_config().get("max_threads"), 5, 1)

    def _max_chapters_per_download(self) -> int:
        return _safe_int(
            self._download_config().get("max_chapters_per_download"),
            120,
            0,
        )

    def _download_images(self) -> bool:
        return _bool(self._download_config().get("download_images"), True)


def _plain_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    return soup.get_text("\n", strip=True)


def _normalize_image_bytes(raw: bytes, filename: str) -> bytes:
    if filename.lower().endswith(".gif"):
        return raw
    with Image.open(BytesIO(raw)) as image:
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def _sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()


def _mask_account(account: str) -> str:
    if "@" in account:
        name, domain = account.split("@", 1)
        return f"{name[:2]}***@{domain}"
    return f"{account[:2]}***"


def _safe_int(value: Any, default: int, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        return max(parsed, minimum)
    return parsed


def _safe_float(value: Any, default: float, minimum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        return max(parsed, minimum)
    return parsed


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "enable", "enabled"}
    if value is None:
        return default
    return bool(value)


async def gather_all(
    items: list[Any],
    func: Callable[[Any], Awaitable[None]],
) -> None:
    await asyncio.gather(*(func(item) for item in items))
