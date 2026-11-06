"""Keep the articles that matter to this audience."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .fetch import Article


def within_days(articles: list[Article], days: int, now: datetime | None = None) -> list[Article]:
    """Drop articles older than the window. Undated articles are kept."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    return [a for a in articles if a.published is None or a.published >= cutoff]


def relevance(article: Article, keywords: list[str]) -> int:
    """Keyword hits, with title mentions counting double."""
    title, summary = article.title.lower(), article.summary.lower()
    score = 0
    for kw in keywords:
        k = kw.lower()
        score += 2 * (k in title) + (k in summary)
    return score


def rank(articles: list[Article], keywords: list[str], limit: int) -> list[Article]:
    """Sort by relevance, then recency, and keep the top `limit`."""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def key(a: Article):
        return (relevance(a, keywords), a.published or epoch)

    return sorted(articles, key=key, reverse=True)[:limit]
