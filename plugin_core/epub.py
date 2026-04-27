from __future__ import annotations

import datetime as _dt
import uuid
import zipfile
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

from PIL import Image

from .model import Book, Chapter


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_epub(
    book: Book,
    chapters: Iterable[Chapter],
    output_path: str | Path,
    max_output_bytes: int | None = None,
) -> None:
    output_path = Path(output_path)
    chapters = list(chapters)
    book_id = str(uuid.uuid4())
    written_source_bytes = 0

    def writestr_limited(
        zf: zipfile.ZipFile,
        filename: str,
        content: str | bytes,
        *,
        compress_type: int | None = None,
    ) -> None:
        nonlocal written_source_bytes
        size = len(content.encode("utf-8") if isinstance(content, str) else content)
        if (
            max_output_bytes is not None
            and written_source_bytes + size > max_output_bytes
        ):
            raise ValueError("生成文件超过大小限制。")
        kwargs = {}
        if compress_type is not None:
            kwargs["compress_type"] = compress_type
        zf.writestr(filename, content, **kwargs)
        written_source_bytes += size
        if (
            max_output_bytes is not None
            and output_path.exists()
            and output_path.stat().st_size > max_output_bytes
        ):
            raise ValueError("生成文件超过大小限制。")

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        writestr_limited(
            zf,
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )

        container_xml = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
        writestr_limited(zf, "META-INF/container.xml", container_xml)

        spine_items: list[str] = []
        manifest_items: list[str] = []

        # Collect images once to avoid duplicate ZIP entries.
        all_images: dict[str, tuple[bytes, str]] = {}

        for ch in chapters:
            if hasattr(ch, "images") and ch.images:
                for filename, content in ch.images.items():
                    if filename not in all_images:
                        ext = Path(filename).suffix.lower()
                        if ext == ".png":
                            mimetype = "image/png"
                        elif ext == ".gif":
                            mimetype = "image/gif"
                        elif ext == ".webp":
                            mimetype = "image/webp"
                        else:
                            mimetype = "image/jpeg"
                        all_images[filename] = (content, mimetype)

            chapter_filename = f"OEBPS/chapter_{ch.index}.xhtml"
            spine_items.append(f'<itemref idref="chap{ch.index}"/>')
            manifest_items.append(
                f'<item id="chap{ch.index}" href="chapter_{ch.index}.xhtml" '
                f'media-type="application/xhtml+xml"/>'
            )
            body_title = ch.title or f"第 {ch.index} 章"
            body_content = ch.content_html or "<p></p>"
            chapter_xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>{escape_xml(body_title)}</title>
    <meta charset="utf-8" />
  </head>
  <body>
    <h1>{escape_xml(body_title)}</h1>
    {body_content}
  </body>
</html>
"""
            writestr_limited(zf, chapter_filename, chapter_xhtml)

        # Write image resources.
        cover_id = None
        cover_ext = ".png"

        if book.cover_image:
            cover_mime = "image/png"
            try:
                with Image.open(BytesIO(book.cover_image)) as img:
                    if img.format == "JPEG":
                        cover_ext = ".jpg"
                        cover_mime = "image/jpeg"
                    elif img.format == "GIF":
                        cover_ext = ".gif"
                        cover_mime = "image/gif"
            except Exception:
                pass

            writestr_limited(zf, f"OEBPS/images/cover{cover_ext}", book.cover_image)
            cover_id = "cover_img"

            manifest_items.append(
                f'<item id="{cover_id}" href="images/cover{cover_ext}" media-type="{cover_mime}" properties="cover-image"/>'
            )

        for filename, (content, mimetype) in all_images.items():
            writestr_limited(zf, f"OEBPS/images/{filename}", content)
            manifest_items.append(
                f'<item id="img_{filename.replace(".", "_")}" href="images/{filename}" media-type="{mimetype}"/>'
            )

        # Build toc.ncx for EPUB readers that still prefer NCX navigation.
        ncx_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{book_id}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>{escape_xml(book.title)}</text>
  </docTitle>
  <navMap>
"""
        for i, ch in enumerate(chapters):
            ncx_content += f"""    <navPoint id="navPoint-{i + 1}" playOrder="{i + 1}">
      <navLabel>
        <text>{escape_xml(ch.title)}</text>
      </navLabel>
      <content src="chapter_{ch.index}.xhtml"/>
    </navPoint>
"""
        ncx_content += """  </navMap>
</ncx>
"""
        writestr_limited(zf, "OEBPS/toc.ncx", ncx_content)
        manifest_items.append(
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        )

        manifest = "\n    ".join(manifest_items)
        spine = "\n    ".join(spine_items)
        now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        tags_xml = "\n    ".join(
            [f"<dc:subject>{escape_xml(tag)}</dc:subject>" for tag in book.tags]
        )

        description_xml = (
            f"<dc:description>{escape_xml(book.introduction)}</dc:description>"
            if book.introduction
            else ""
        )

        cover_meta = f'<meta name="cover" content="{cover_id}" />' if cover_id else ""

        content_opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{escape_xml(book.title)}</dc:title>
    <dc:creator>{escape_xml(book.author)}</dc:creator>
    <dc:language>zh</dc:language>
    <meta property="dcterms:modified">{now}</meta>
    {tags_xml}
    {description_xml}
    {cover_meta}
  </metadata>
  <manifest>
    {manifest}
  </manifest>
  <spine toc="ncx">
    {spine}
  </spine>
</package>
"""
        writestr_limited(zf, "OEBPS/content.opf", content_opf)
