from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chapter:
    url: str
    title: str
    index: int
    section_name: str | None = None
    section_index: int | None = None
    content_html: str | None = None
    content_text: str | None = None
    images: dict[str, bytes] = field(default_factory=dict)


@dataclass
class Book:
    url: str
    title: str
    author: str
    introduction: str
    cover_url: str | None = None
    cover_image: bytes | None = None
    update_time: str | None = None
    tags: list[str] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
