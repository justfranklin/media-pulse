"""Write a brief as Markdown (for the repo archive) and HTML (for GitHub Pages)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .themes import Brief

TEMPLATES = Path(__file__).resolve().parent / "templates"


def _longdate(d) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def _date(a) -> str:
    return f"{a.published:%b} {a.published.day}" if a.published else ""


def to_markdown(brief: Brief) -> str:
    lines = [
        f"# Media brief: {brief.audience.label}",
        "",
        f"*{_longdate(brief.generated)} · last {brief.days} days · "
        f"{brief.article_count} articles from {len(brief.source_names)} publications*",
        "",
    ]
    if brief.topics:
        lines += [f"**Focus:** {', '.join(brief.topics)}", ""]
    if brief.headline:
        lines += [f"> {brief.headline}", ""]
    for t in brief.themes:
        lines += [f"## {t.name}", "", t.summary, ""]
        if t.why_it_matters:
            lines += [f"**Why it matters:** {t.why_it_matters}", ""]
        for a in t.articles:
            when = f" ({_date(a)})" if a.published else ""
            lines.append(f"- [{a.title}]({a.url}) — {a.source}{when}")
        lines.append("")
        if t.angles:
            lines += ["**Content angles**", ""] + [f"- {x}" for x in t.angles] + [""]
    method = "Claude" if brief.method == "claude" else "keyword grouping (offline)"
    lines.append(f"---\n*Themes by {method}. Built with [media-pulse](https://github.com/justfranklin/media-pulse).*")
    return "\n".join(lines) + "\n"


def to_html(brief: Brief) -> str:
    return _env().get_template("brief.html.j2").render(brief=brief)


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["shortdate"] = _date
    env.filters["longdate"] = _longdate
    return env


def write_index(briefs: list[Brief], site_dir: Path) -> Path:
    """Landing page linking each audience's brief (used when several run together)."""
    site_dir.mkdir(parents=True, exist_ok=True)
    p = site_dir / "index.html"
    p.write_text(_env().get_template("index.html.j2").render(briefs=briefs), encoding="utf-8")
    return p


def write_brief(brief: Brief, md_dir: Path | None, site_dir: Path | None) -> list[Path]:
    written = []
    stamp = f"{brief.generated:%Y-%m-%d}-{brief.audience.key}"
    if md_dir:
        md_dir.mkdir(parents=True, exist_ok=True)
        p = md_dir / f"{stamp}.md"
        p.write_text(to_markdown(brief), encoding="utf-8")
        written.append(p)
    if site_dir:
        site_dir.mkdir(parents=True, exist_ok=True)
        page = to_html(brief)
        for name in (f"{brief.audience.key}.html", "index.html"):
            p = site_dir / name
            p.write_text(page, encoding="utf-8")
            written.append(p)
    return written
