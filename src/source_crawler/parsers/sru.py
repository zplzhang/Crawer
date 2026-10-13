"""解析符合 SRU 2.0 的官方检索响应。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from .api import ApiLink
from ..validators.urls import normalize_url


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(record: ET.Element, name: str) -> str:
    for element in record.iter():
        if _local_name(element.tag) == name and element.text:
            value = element.text.strip()
            if value:
                return value
    return ""


def _record_url(record: ET.Element) -> str:
    for element in record.iter():
        if _local_name(element.tag) == "hasVersion":
            value = element.attrib.get("resourceIdentifier", "").strip()
            if value:
                return normalize_url(value)
    return ""


def discover_sru_links(xml_content: bytes, base_url: str) -> list[ApiLink]:
    """返回 SRU 记录的详情页链接，并使用响应总数生成下一批检索链接。"""
    root = ET.fromstring(xml_content)
    links: dict[str, ApiLink] = {}
    for element in root.iter():
        if _local_name(element.tag) != "record":
            continue
        url = _record_url(element)
        if url:
            links.setdefault(url, ApiLink(
                url=url,
                title=_first_text(element, "title"),
                publication_date=_first_text(element, "available") or _first_text(element, "issued"),
            ))

    total = 0
    for element in root.iter():
        if _local_name(element.tag) == "numberOfRecords" and element.text:
            try:
                total = int(element.text.strip())
            except ValueError:
                pass
            break
    parts = urlsplit(base_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    try:
        start = int(query.get("startRecord", ["1"])[0])
        page_size = int(query.get("maximumRecords", ["10"])[0])
    except ValueError:
        start, page_size = 1, 10
    if total and start + page_size <= total:
        query["startRecord"] = [str(start + page_size)]
        next_url = normalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path,
                                             urlencode(query, doseq=True), "")))
        if next_url:
            links.setdefault(next_url, ApiLink(url=next_url, title="下一页"))
    return sorted(links.values(), key=lambda item: item.url)
