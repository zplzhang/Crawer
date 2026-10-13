"""从公开 JSON 检索接口中发现可继续处理的资料链接。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from ..validators.urls import normalize_url


@dataclass(frozen=True)
class ApiLink:
    url: str
    title: str = ""
    publication_date: str = ""


_URL_KEYS = {"url", "urlalias", "uri", "downloadurl", "download_url", "fileurl", "file_url"}
_TITLE_KEYS = ("title", "name", "label")
_DATE_KEYS = ("created", "publication_date", "publicationdate", "date", "published")


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_value(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _string_value(item.get(key))
        if value:
            return value
    return ""


def _next_page_url(payload: object, base_url: str) -> str:
    """支持返回 ``pager.nextPage`` 的公开检索接口（页码从 0 或 1 均可）。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("pager"), dict):
        return ""
    next_page = payload["pager"].get("nextPage")
    if isinstance(next_page, bool) or not isinstance(next_page, int) or next_page < 0:
        return ""
    parts = urlsplit(base_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    current_page = query.get("page", [])
    if current_page and current_page[0] == str(next_page):
        return ""
    query["page"] = [str(next_page)]
    return normalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path,
                                    urlencode(query, doseq=True), "")))


def discover_json_links(payload: object, base_url: str) -> list[ApiLink]:
    """提取常见 API 资料字段和分页地址，保留结果标题与发布日期。"""
    found: dict[str, ApiLink] = {}

    def visit(value: object, context: dict[str, Any] | None = None) -> None:
        if isinstance(value, list):
            for element in value:
                visit(element, context)
            return
        if not isinstance(value, dict):
            return
        title = _first_value(value, _TITLE_KEYS) or _first_value(context or {}, _TITLE_KEYS)
        published = _first_value(value, _DATE_KEYS) or _first_value(context or {}, _DATE_KEYS)
        for key, child in value.items():
            if key.casefold() in _URL_KEYS:
                raw_url = _string_value(child)
                url = normalize_url(urljoin(base_url, raw_url)) if raw_url else ""
                if url and url != normalize_url(base_url):
                    found.setdefault(url, ApiLink(url=url, title=title, publication_date=published))
            elif isinstance(child, (dict, list)):
                visit(child, value)

    visit(payload)
    next_page = _next_page_url(payload, base_url)
    if next_page:
        found.setdefault(next_page, ApiLink(url=next_page, title="下一页"))
    return sorted(found.values(), key=lambda item: item.url)
