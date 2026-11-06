"""Command line: media-pulse --audience "in-house trademark counsel" --days 14"""

from __future__ import annotations

import argparse
from pathlib import Path

from .fetch import fetch_all, load_fixture
from .rank import rank, within_days
from .render import write_brief, write_index
from .sources import DEFAULT_CONFIG, load_audiences, match_audience
from .themes import build_brief


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="media-pulse",
        description="Pull recent coverage from the publications your audience reads "
                    "and turn it into a themed brief with links.",
    )
    who = p.add_mutually_exclusive_group()
    who.add_argument("--preset", help="Audience preset key(s) from the config, comma-separated (see --list).")
    who.add_argument("--audience", help="Describe the audience in your own words; the closest preset is used.")
    p.add_argument("--topics", default="", help="Comma-separated focus topics, e.g. 'new gTLDs, AI infringement'.")
    p.add_argument("--days", type=int, default=14, help="How far back to look (default 14).")
    p.add_argument("--max-articles", type=int, default=40, help="Articles to keep after ranking (default 40).")
    p.add_argument("--max-themes", type=int, default=5)
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to audiences YAML.")
    p.add_argument("--out", default="briefs", help="Folder for the Markdown brief ('' to skip).")
    p.add_argument("--site", default="site", help="Folder for the HTML brief ('' to skip).")
    p.add_argument("--no-claude", action="store_true", help="Skip Claude and use offline keyword grouping.")
    p.add_argument("--fixture", help="Load articles from a JSON file instead of the web (demo/testing).")
    p.add_argument("--list", action="store_true", help="List audience presets and exit.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    audiences = load_audiences(args.config)

    if args.list:
        for key, a in audiences.items():
            names = ", ".join(s.name for s in a.sources)
            print(f"{key:22} {a.label}\n{'':22} {names}\n")
        return 0

    if args.preset:
        keys = [k.strip() for k in args.preset.split(",") if k.strip()]
        unknown = [k for k in keys if k not in audiences]
        if unknown:
            print(f"Unknown preset(s) {', '.join(unknown)}. Options: {', '.join(audiences)}")
            return 2
        targets = [audiences[k] for k in keys]
    elif args.audience:
        match = match_audience(args.audience, audiences)
        print(f"Closest preset for “{args.audience}”: {match.label}")
        targets = [match]
    else:
        targets = [next(iter(audiences.values()))]

    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    site = Path(args.site) if args.site else None
    briefs = [run_one(a, topics, args) for a in targets]
    if site and len(briefs) > 1:
        print(f"  wrote {write_index(briefs, site)}")
    return 0


def run_one(audience, topics: list[str], args):
    keywords = audience.keywords + topics
    if args.fixture:
        articles = load_fixture(args.fixture)
        print(f"Loaded {len(articles)} articles from {args.fixture}")
    else:
        print(f"Fetching {len(audience.sources)} publications for {audience.label}…")
        articles = fetch_all(audience.sources, args.days)
        print(f"  {len(articles)} articles found")
        articles = within_days(articles, args.days)  # saved fixtures keep their own dates

    articles = rank(articles, keywords, args.max_articles)
    print(f"  {len(articles)} kept after date filter and ranking")

    brief = build_brief(
        articles, audience, args.days, topics,
        use_claude=False if args.no_claude else None,
        max_themes=args.max_themes,
    )
    paths = write_brief(
        brief,
        Path(args.out) if args.out else None,
        Path(args.site) if args.site else None,
    )
    print(f"  {len(brief.themes)} themes ({brief.method})")
    for path in paths:
        print(f"  wrote {path}")
    return brief
