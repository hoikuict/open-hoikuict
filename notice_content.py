from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import UploadFile


NOTICE_UPLOAD_ROOT = Path("storage") / "notice_attachments"
NOTICE_MAX_FILE_SIZE = 10 * 1024 * 1024
NOTICE_MAX_ATTACHMENTS = 5
NOTICE_IMAGE_SIZES = {"small", "medium", "large", "full"}

_VOID_TAGS = {"br"}
_ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "div",
    "em",
    "font",
    "h2",
    "h3",
    "li",
    "ol",
    "p",
    "span",
    "strong",
    "u",
    "ul",
}
_SUPPRESSED_TAGS = {"script", "style"}
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")
_RGB_PATTERN = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})"
    r"(?:\s*,\s*(?:0(?:\.\d+)?|1(?:\.0+)?))?\s*\)$"
)


class NoticeContentError(ValueError):
    pass


@dataclass(slots=True)
class StoredNoticeAttachment:
    original_filename: str
    storage_path: str
    content_type: str
    file_size: int
    is_image: bool


def normalize_image_size(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in NOTICE_IMAGE_SIZES else "medium"


def _safe_color(value: str) -> str | None:
    normalized = value.strip()
    if _COLOR_PATTERN.fullmatch(normalized):
        return normalized.lower()
    match = _RGB_PATTERN.fullmatch(normalized)
    if match and all(0 <= int(component) <= 255 for component in match.groups()[:3]):
        return normalized
    return None


def _safe_href(value: str) -> str | None:
    normalized = value.strip()
    if normalized.startswith("/") and not normalized.startswith("//"):
        return normalized
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() in {"http", "https", "mailto"}:
        return normalized
    return None


def _safe_style(value: str) -> str | None:
    allowed: list[str] = []
    for declaration in value.split(";"):
        if ":" not in declaration:
            continue
        property_name, property_value = declaration.split(":", 1)
        property_name = property_name.strip().lower()
        property_value = property_value.strip()
        if property_name in {"color", "background-color"}:
            color = _safe_color(property_value)
            if color:
                allowed.append(f"{property_name}: {color}")
        elif property_name == "font-size" and property_value in {
            "0.875rem",
            "1rem",
            "1.25rem",
            "1.5rem",
            "2rem",
        }:
            allowed.append(f"font-size: {property_value}")
    return "; ".join(allowed) or None


class _NoticeHtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.stack: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SUPPRESSED_TAGS:
            self.suppressed_depth += 1
            return
        if self.suppressed_depth or tag not in _ALLOWED_TAGS:
            return

        safe_attrs: list[tuple[str, str]] = []
        for name, raw_value in attrs:
            if raw_value is None:
                continue
            name = name.lower()
            if tag == "a" and name == "href":
                href = _safe_href(raw_value)
                if href:
                    safe_attrs.append(("href", href))
            elif tag in {"span", "div", "p"} and name == "style":
                style = _safe_style(raw_value)
                if style:
                    safe_attrs.append(("style", style))
            elif tag == "font" and name == "color":
                color = _safe_color(raw_value)
                if color:
                    safe_attrs.append(("color", color))
            elif tag == "font" and name == "size" and raw_value in {"1", "2", "3", "4", "5", "6", "7"}:
                safe_attrs.append(("size", raw_value))

        serialized_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in safe_attrs
        )
        self.output.append(f"<{tag}{serialized_attrs}>")
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SUPPRESSED_TAGS:
            if self.suppressed_depth:
                self.suppressed_depth -= 1
            return
        if self.suppressed_depth or tag not in self.stack:
            return
        while self.stack:
            open_tag = self.stack.pop()
            self.output.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth:
            self.output.append(html.escape(data))

    def close(self) -> None:
        super().close()
        while self.stack:
            self.output.append(f"</{self.stack.pop()}>")


class _NoticeTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _SUPPRESSED_TAGS:
            self.suppressed_depth += 1
        elif not self.suppressed_depth and tag.lower() in {"br", "div", "h2", "h3", "li", "p"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SUPPRESSED_TAGS:
            if self.suppressed_depth:
                self.suppressed_depth -= 1
        elif not self.suppressed_depth and tag.lower() in {"blockquote", "div", "h2", "h3", "li", "p"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(data)


def sanitize_notice_html(raw_html: str | None) -> str:
    parser = _NoticeHtmlSanitizer()
    parser.feed(raw_html or "")
    parser.close()
    return "".join(parser.output).strip()


def notice_plain_text(raw_html: str | None) -> str:
    parser = _NoticeTextExtractor()
    parser.feed(raw_html or "")
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def legacy_notice_body_html(body: str | None) -> str:
    escaped = html.escape((body or "").strip())
    return f"<p>{escaped.replace(chr(10), '<br>')}</p>" if escaped else ""


def render_notice_body_html(body: str | None, body_html: str | None) -> str:
    if body_html:
        sanitized = sanitize_notice_html(body_html)
        if sanitized:
            return sanitized
    return legacy_notice_body_html(body)


def _detected_file_type(content: bytes) -> tuple[str, str, bool] | None:
    if content.startswith(b"%PDF-"):
        return ".pdf", "application/pdf", False
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png", True
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg", True
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp", "image/webp", True
    return None


def _safe_original_filename(filename: str) -> str:
    base_name = Path(filename or "attachment").name.strip() or "attachment"
    cleaned = "".join(character for character in base_name if ord(character) >= 32)
    return cleaned[:120] or "attachment"


def store_notice_uploads(
    uploads: list[UploadFile],
    *,
    existing_count: int = 0,
) -> list[StoredNoticeAttachment]:
    named_uploads = [upload for upload in uploads if (upload.filename or "").strip()]
    if existing_count + len(named_uploads) > NOTICE_MAX_ATTACHMENTS:
        raise NoticeContentError(f"添付ファイルは最大{NOTICE_MAX_ATTACHMENTS}件です。")

    NOTICE_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    stored: list[StoredNoticeAttachment] = []
    try:
        for upload in named_uploads:
            content = upload.file.read(NOTICE_MAX_FILE_SIZE + 1)
            if not content:
                raise NoticeContentError("空のファイルは添付できません。")
            if len(content) > NOTICE_MAX_FILE_SIZE:
                raise NoticeContentError("添付ファイルは1件10MB以下にしてください。")
            detected = _detected_file_type(content)
            if detected is None:
                raise NoticeContentError("PDF・JPEG・PNG・WebP画像のみ添付できます。")
            extension, content_type, is_image = detected
            storage_name = f"{uuid4().hex}{extension}"
            (NOTICE_UPLOAD_ROOT / storage_name).write_bytes(content)
            stored.append(
                StoredNoticeAttachment(
                    original_filename=_safe_original_filename(upload.filename or "attachment"),
                    storage_path=storage_name,
                    content_type=content_type,
                    file_size=len(content),
                    is_image=is_image,
                )
            )
    except Exception:
        cleanup_notice_uploads(item.storage_path for item in stored)
        raise
    return stored


def notice_attachment_path(storage_path: str) -> Path | None:
    root = NOTICE_UPLOAD_ROOT.resolve()
    candidate = (NOTICE_UPLOAD_ROOT / storage_path).resolve()
    if candidate.parent != root:
        return None
    return candidate


def cleanup_notice_uploads(storage_paths) -> None:
    for storage_path in storage_paths:
        path = notice_attachment_path(str(storage_path))
        if path is not None:
            path.unlink(missing_ok=True)
