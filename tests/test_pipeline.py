from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json

from mediapulse.fetch import Article, dedupe, google_news_url, load_fixture, parse_feed
from mediapulse.rank import rank, relevance, within_days
from mediapulse.render import to_html, to_markdown, write_brief
from mediapulse.sources import load_audiences, match_audience
from mediapulse.themes import build_brief, themes_by_keyword

FIXTURE = Path(__file__).parent / "fixtures" / "sample_articles.json"
RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>UDRP case &amp; cybersquatting update</title><link>https://example.com/a</link>
<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Body text&lt;/p&gt;</description></item>
<item><title>Story - Publisher Name</title><link>https://news.google.com/x</link>
<pubDate>Tue, 03 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def audiences():
    return load_audiences()


def test_presets_load_with_sources():
    a = audiences()
    assert "ip-brand-protection" in a
    assert all(aud.sources for aud in a.values())


def test_match_audience_from_free_text():
    a = audiences()
    assert match_audience("in-house trademark counsel at global brands", a).key == "ip-brand-protection"
    assert match_audience("CISOs and SOC leads", a).key == "cybersecurity"
    assert match_audience("SEO and AI search visibility", a).key == "search-aeo"


def test_parse_feed_cleans_html_and_dates():
    items = parse_feed(RSS, "Test")
    assert items[0].title == "UDRP case & cybersquatting update"
    assert items[0].summary == "Body text"
    assert items[0].published == datetime(2026, 11, 2, 10, tzinfo=timezone.utc)


def test_google_news_titles_drop_publisher():
    items = parse_feed(RSS, "Test", from_google=True)
    assert items[1].title == "Story"
    assert "site%3Aexample.com" in google_news_url("example.com", 7)


def test_dedupe_and_date_window():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    a = Article("1", "Same Title!", "u1", "A", now - timedelta(days=1))
    b = Article("2", "same title", "u2", "B", now - timedelta(days=2))
    old = Article("3", "Old", "u3", "A", now - timedelta(days=40))
    assert len(dedupe([a, b])) == 1
    assert old not in within_days([a, old], 14, now=now)


def test_rank_prefers_keyword_hits_in_title():
    arts = load_fixture(FIXTURE)
    top = rank(arts, ["UDRP"], limit=2)
    assert all("UDRP" in a.title for a in top)
    assert relevance(top[0], ["UDRP"]) >= 2


def test_keyword_themes_group_related_articles():
    headline, themes = themes_by_keyword(load_fixture(FIXTURE))
    names = [t.name.lower() for t in themes]
    assert any("gtld" in n for n in names)
    assert any("phishing" in n for n in names)
    total = sum(len(t.articles) for t in themes)
    assert total == len(load_fixture(FIXTURE))  # every article lands somewhere once
    assert headline


class FakeClient:
    """Stands in for anthropic.Anthropic so tests need no key or network."""

    def __init__(self, ids):
        body = {"headline": "AI phishing is the story.", "themes": [{
            "name": "AI-driven impersonation", "summary": "S.", "why_it_matters": "W.",
            "angles": ["Checklist post"], "article_ids": ids + ["missing-id"]}]}
        text = "Here you go:\n" + json.dumps(body)
        self.messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)]))


def test_claude_path_maps_ids_and_ignores_unknown():
    arts = load_fixture(FIXTURE)
    aud = audiences()["ip-brand-protection"]
    brief = build_brief(arts, aud, 14, client=FakeClient([arts[3].id, arts[4].id]))
    assert brief.method == "claude"
    assert brief.themes[0].name == "AI-driven impersonation"
    assert len(brief.themes[0].articles) == 2


def test_claude_failure_falls_back_to_keywords():
    class Broken:
        messages = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))

    brief = build_brief(load_fixture(FIXTURE), audiences()["ip-brand-protection"], 14, client=Broken())
    assert brief.method == "keyword" and brief.themes


def test_render_outputs(tmp_path):
    brief = build_brief(load_fixture(FIXTURE), audiences()["ip-brand-protection"], 14,
                        topics=["new gTLDs"], use_claude=False)
    md, page = to_markdown(brief), to_html(brief)
    assert "# Media brief: IP & brand protection" in md
    assert "https://example.com/sample/1" in md and "https://example.com/sample/1" in page
    assert "IP &amp; brand protection" in page  # escaped in HTML
    paths = write_brief(brief, tmp_path / "briefs", tmp_path / "site")
    assert (tmp_path / "site" / "index.html").exists() and len(paths) == 3
