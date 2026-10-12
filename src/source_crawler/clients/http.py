"""限速、重定向和 robots.txt 检查集中在此。"""

from __future__ import annotations

import time
from collections import defaultdict
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from ..config import CrawlConfig
from ..validators.urls import ensure_public_url, is_excluded, normalize_url, within_site_scope


class HttpClient:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": config.user_agent, "Accept-Language": "en,zh-CN;q=0.8,zh;q=0.7"}
        )
        self.last_request_at: dict[str, float] = defaultdict(float)
        self.robot_cache: dict[str, RobotFileParser] = {}

    def close(self) -> None:
        self.session.close()

    def _wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        remaining = self.config.delay - (time.monotonic() - self.last_request_at[host])
        if remaining > 0:
            time.sleep(remaining)
        self.last_request_at[host] = time.monotonic()

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        stream: bool = True,
        site_seed_url: str = "",
        allowed_domains: tuple[str, ...] = (),
    ) -> requests.Response:
        current = url
        for _ in range(6):
            if is_excluded(current, self.config.excluded_domains):
                raise ValueError("目标地址属于排除域名")
            if site_seed_url and not within_site_scope(current, site_seed_url, allowed_domains):
                raise ValueError("目标地址超出该入口的允许域名")
            ensure_public_url(current, resolve_dns=self.config.verify_dns)
            self._wait(current)
            response = self.session.get(
                current,
                headers=headers,
                timeout=self.config.timeout,
                stream=stream,
                allow_redirects=False,
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise requests.RequestException("重定向缺少 Location")
            current = normalize_url(urljoin(current, location))
            if not current:
                raise requests.RequestException("重定向地址无效")
        raise requests.TooManyRedirects("重定向超过 5 次")

    def _robots(self, url: str, site_seed_url: str = "", allowed_domains: tuple[str, ...] = ()) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self.robot_cache:
            return self.robot_cache[origin]
        parser = RobotFileParser()
        robots_url = origin + "/robots.txt"
        parser.set_url(robots_url)
        try:
            response = self.get(robots_url, stream=False, site_seed_url=site_seed_url,
                                allowed_domains=allowed_domains)
            try:
                if response.status_code in {401, 403}:
                    parser.parse(["User-agent: *", "Disallow: /"])
                elif response.status_code < 400:
                    parser.parse(response.text.splitlines())
                elif response.status_code >= 500:
                    raise requests.RequestException(f"robots.txt 返回 HTTP {response.status_code}")
                else:
                    parser.parse([])
            finally:
                response.close()
        except Exception as exc:
            raise requests.RequestException(f"无法核对 robots.txt: {exc}") from exc
        self.robot_cache[origin] = parser
        return parser

    def allowed(self, url: str, site_seed_url: str = "", allowed_domains: tuple[str, ...] = ()) -> bool:
        if not self.config.respect_robots:
            return True
        return self._robots(url, site_seed_url, allowed_domains).can_fetch(self.config.user_agent, url)
