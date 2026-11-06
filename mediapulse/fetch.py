"""Pull recent articles from each publication.

Uses the publication's RSS feed when one is configured, and Google News search
(restricted to the publication's domain) otherwise or as a fallback.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

from .sources import Source

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
USER_AGENT = "media-pulse/0.1 (+https://github.com/justfranklin/media-pulse)"


@dataclass
class Article:
    id: str
    title: str
    url: str
    source: str
    published: datetime | None
    summary: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Article":
        pub = d.get("published")
        return cls(
            id=d.get("id") or make_id(d["url"]),
            title=d["title"],
            url=d["url"],
            source=d["source"],
            published=datetime.fromisoformat(pub) if pub else None,
            summary=d.get("summary", ""),
        )


def make_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:10]


def clean_text(raw: str, limit: int = 400) -> str:
    """Strip HTML and whitespace from a feed summary."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = " ".join(html.unescape(text).split())
    return text[:limit].rsplit(" ", 1)[0] + "…" if len(text) > limit else text


def google_news_url(domain: str, days: int, query: str | None = None) -> str:
    q = f"site:{domain} when:{days}d"
    if query:
        q = f"{query} {q}"
    return GOOGLE_NEWS.format(q=quote_plus(q))


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def parse_feed(content: bytes | str, source_name: str, from_google: bool = False) -> list[Article]:
    """Turn RSS/Atom content into Articles."""
    feed = feedparser.parse(content)
    articles = []
    for e in feed.entries:
        title = clean_text(e.get("title", ""), limit=300)
        url = e.get("link", "")
        if not title or not url:
            continue
        if from_google:
            # Google News appends " - Publisher" to titles; its summaries are just links.
            title = re.sub(r"\s+-\s+[^-]+$", "", title)
            summary = ""
        else:
            summary = clean_text(e.get("summary", ""))
        articles.append(Article(make_id(url), title, url, source_name, _published(e), summary))
    return articles


def _get(url: str, timeout: int) -> bytes:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content


def fetch_source(source: Source, days: int, query: str | None = None, timeout: int = 15) -> list[Article]:
    """Fetch one publication, falling back to Google News if its feed fails."""
    if source.feed:
        try:
            items = parse_feed(_get(source.feed, timeout), source.name)
            if items:
                return items
        except requests.RequestException:
            pass
    try:
        content = _get(google_news_url(source.domain, days, query), timeout)
        return parse_feed(content, source.name, from_google=True)
    except requests.RequestException as exc:
        print(f"  ! {source.name}: couldn't fetch ({type(exc).__name__})")
        return []


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def dedupe(articles: list[Article]) -> list[Article]:
    seen, out = set(), []
    for a in articles:
        key = _norm_title(a.title)
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


def fetch_all(sources: list[Source], days: int, query: str | None = None, workers: int = 6) -> list[Article]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda s: fetch_source(s, days, query), sources)
    articles = [a for batch in results for a in batch]
    return dedupe(articles)


def load_fixture(path: str | Path) -> list[Article]:
    """Load saved articles (for demos and tests, no network needed)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Article.from_dict(d) for d in data]
