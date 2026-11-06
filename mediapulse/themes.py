"""Group articles into themes for the audience.

With an ANTHROPIC_API_KEY set, Claude reads the headlines and summaries and writes
themes, why each matters to the audience, and content angles. Without a key, a
simple keyword-phrase grouping runs offline so the tool always produces a brief.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .fetch import Article
from .sources import Audience

DEFAULT_MODEL = os.environ.get("MEDIA_PULSE_MODEL", "claude-sonnet-5-5")


@dataclass
class Theme:
    name: str
    summary: str
    articles: list[Article]
    why_it_matters: str = ""
    angles: list[str] = field(default_factory=list)


@dataclass
class Brief:
    audience: Audience
    themes: list[Theme]
    headline: str
    method: str  # "claude" or "keyword"
    generated: datetime
    days: int
    topics: list[str] = field(default_factory=list)

    @property
    def article_count(self) -> int:
        return sum(len(t.articles) for t in self.themes)

    @property
    def source_names(self) -> list[str]:
        return sorted({a.source for t in self.themes for a in t.articles})


# --- Claude -----------------------------------------------------------------

PROMPT = """You are a B2B content strategist preparing a media brief.

Audience: {label} — {description}
{topics_line}
Below are recent articles from the publications this audience reads, as JSON.
Group them into {max_themes} or fewer themes that this audience would care about.
Skip articles that are irrelevant to them. Every article you use must appear in
exactly one theme.

Return only JSON, no prose, in this shape:
{{
  "headline": "one sentence on the biggest story for this audience right now",
  "themes": [
    {{
      "name": "short theme name",
      "summary": "two sentences on what is happening, in plain language",
      "why_it_matters": "one sentence on why this audience should care",
      "angles": ["content idea 1", "content idea 2"],
      "article_ids": ["id1", "id2"]
    }}
  ]
}}

Articles:
{articles}
"""


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in model response.")
    return json.loads(text[start : end + 1])


def themes_with_claude(
    articles: list[Article],
    audience: Audience,
    topics: list[str],
    max_themes: int = 5,
    model: str = DEFAULT_MODEL,
    client=None,
) -> tuple[str, list[Theme]]:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    payload = [
        {"id": a.id, "title": a.title, "source": a.source,
         "date": a.published.date().isoformat() if a.published else None,
         "summary": a.summary}
        for a in articles
    ]
    prompt = PROMPT.format(
        label=audience.label,
        description=audience.description,
        topics_line=f"Focus topics: {', '.join(topics)}\n" if topics else "",
        max_themes=max_themes,
        articles=json.dumps(payload, ensure_ascii=False),
    )
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    data = _parse_json(text)

    by_id = {a.id: a for a in articles}
    themes = []
    for t in data.get("themes", []):
        picked = [by_id[i] for i in t.get("article_ids", []) if i in by_id]
        if not picked:
            continue
        themes.append(Theme(
            name=t.get("name", "Untitled"),
            summary=t.get("summary", ""),
            why_it_matters=t.get("why_it_matters", ""),
            angles=list(t.get("angles", [])),
            articles=picked,
        ))
    return data.get("headline", ""), themes


# --- Offline fallback ---------------------------------------------------------

STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before
being below between both but by can could did do does doing down during each few for
from further had has have having he her here hers him his how i if in into is it its
itself just me more most my new no nor not now of off on once only or other our ours
out over own same says said she should so some such than that the their them then there
these they this those through to too under until up very was we were what when where
which while who whom why will with would you your year years week weeks says amid via
how what why get gets got make makes one two first last also us use using report
""".split())


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\.\-]*[a-z0-9]|[a-z0-9]", text.lower())
            if w not in STOPWORDS and not w.isdigit() and len(w) > 2]


def _phrases(article: Article) -> set[str]:
    toks = _tokens(f"{article.title} {article.summary}")
    bigrams = {f"{a} {b}" for a, b in zip(toks, toks[1:])}
    return set(toks) | bigrams


def _display_name(phrase: str, group: list[Article]) -> str:
    """Use the phrase as the articles wrote it ("gTLD round", "UDRP"), not title case."""
    words = phrase.split()
    pattern = r"\b" + r"\W+(?:\w+\W+){0,2}?".join(re.escape(w) for w in words) + r"\b"
    for a in group:
        m = re.search(pattern, f"{a.title} {a.summary}", flags=re.IGNORECASE)
        if m:
            text = m.group(0)
            # Capitalize "phishing" but leave "gTLD" and "eBay" alone.
            if text[0].islower() and (len(text) == 1 or not text[1].isupper()):
                text = text[0].upper() + text[1:]
            return text
    return phrase.capitalize()


def themes_by_keyword(articles: list[Article], max_themes: int = 5) -> tuple[str, list[Theme]]:
    """Greedy grouping on shared phrases. Bigrams are preferred over single words."""
    remaining = list(articles)
    themes: list[Theme] = []
    while remaining and len(themes) < max_themes:
        df = Counter(p for a in remaining for p in _phrases(a))
        # A phrase in most of the articles (a boilerplate tag, the audience's own
        # name) describes the whole set rather than a theme, so skip it.
        ceiling = max(2, int(len(remaining) * 0.6))
        candidates = {p: n * (1.5 if " " in p else 1.0)
                      for p, n in df.items() if 2 <= n <= ceiling}
        if not candidates:
            break
        phrase = max(candidates, key=lambda p: (candidates[p], len(p), p))
        group = [a for a in remaining if phrase in _phrases(a)]
        remaining = [a for a in remaining if a not in group]
        sources = sorted({a.source for a in group})
        name = _display_name(phrase, group)
        themes.append(Theme(
            name=name,
            summary=f"{len(group)} articles mention “{name}” across {', '.join(sources)}.",
            articles=group,
        ))
    if remaining:
        themes.append(Theme(
            name="Other notable coverage",
            summary=f"{len(remaining)} more articles that didn't group with the themes above.",
            articles=remaining,
        ))
    lead = themes[0].name if themes else "No coverage found"
    return f"Most-covered thread: {lead}.", themes


# --- Entry point ------------------------------------------------------------

def build_brief(
    articles: list[Article],
    audience: Audience,
    days: int,
    topics: list[str] | None = None,
    use_claude: bool | None = None,
    max_themes: int = 5,
    client=None,
) -> Brief:
    topics = topics or []
    if use_claude is None:
        use_claude = bool(os.environ.get("ANTHROPIC_API_KEY")) or client is not None

    method = "keyword"
    headline, themes = "", []
    if use_claude and articles:
        try:
            headline, themes = themes_with_claude(articles, audience, topics, max_themes, client=client)
            method = "claude"
        except Exception as exc:  # network, auth or parse failure: fall back, don't crash
            print(f"  ! Claude theme extraction failed ({exc}); using keyword grouping.")
    if not themes:
        headline, themes = themes_by_keyword(articles, max_themes)
        method = "keyword"

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    for t in themes:  # newest first within each theme
        t.articles.sort(key=lambda a: a.published or epoch, reverse=True)

    return Brief(audience, themes, headline, method, datetime.now(timezone.utc), days, topics)
