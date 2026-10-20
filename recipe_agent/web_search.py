"""Pluggable public web search for recipe discovery."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str


class RecipeSearchProvider(Protocol):
    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Return public web results matching a search query."""
        ...


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._anchor: dict[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if "result__a" in (attributes.get("class") or "").split() and href:
            self._anchor = {"href": href}
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._anchor is None:
            return
        href = self._anchor.get("href", "")
        title = " ".join("".join(self._text).split())
        self._anchor = None
        if href and title:
            self.results.append(SearchResult(title=title, url=href))


def _target_url(raw_url: str) -> str:
    resolved = urljoin("https://html.duckduckgo.com", raw_url)
    parsed = urlparse(resolved)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return target
    return resolved


class DuckDuckGoSearch:
    """Search DuckDuckGo's public HTML results without an API key."""

    endpoint = "https://html.duckduckgo.com/html/?q="

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        request = Request(
            self.endpoint + quote_plus(query),
            headers={"User-Agent": "Mozilla/5.0 (compatible; RecipeAgent/1.0)", "Accept": "text/html"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                html = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError) as error:
            raise RuntimeError(f"Recipe web search failed: {error}") from error

        parser = _DuckDuckGoParser()
        parser.feed(html)
        if not parser.results and any(marker in html.lower() for marker in ("anomaly", "captcha", "challenge")):
            raise RuntimeError("DuckDuckGo blocked automated search; try again later or add another search provider")

        results = []
        seen: set[str] = set()
        for item in parser.results:
            url = _target_url(item.url)
            if urlparse(url).scheme not in {"http", "https"} or url in seen:
                continue
            seen.add(url)
            results.append(SearchResult(title=item.title, url=url))
            if len(results) >= limit:
                break
        return results
