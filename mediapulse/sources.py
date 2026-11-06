"""Audience presets and the publications behind them."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "audiences.yaml"


@dataclass
class Source:
    name: str
    domain: str
    feed: str | None = None


@dataclass
class Audience:
    key: str
    label: str
    description: str
    keywords: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)


def load_audiences(path: str | Path = DEFAULT_CONFIG) -> dict[str, Audience]:
    """Read audience presets from YAML."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    audiences = {}
    for key, cfg in raw.items():
        audiences[key] = Audience(
            key=key,
            label=cfg.get("label", key),
            description=" ".join(cfg.get("description", "").split()),
            keywords=list(cfg.get("keywords", [])),
            sources=[Source(**s) for s in cfg.get("sources", [])],
        )
    return audiences


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def match_audience(text: str, audiences: dict[str, Audience]) -> Audience:
    """Pick the preset whose description and keywords best overlap free-text input.

    Used when someone describes an audience in their own words instead of naming
    a preset. Ties go to the first preset in the config.
    """
    if not audiences:
        raise ValueError("No audience presets configured.")
    query = _words(text)

    def score(a: Audience) -> int:
        vocab = _words(a.label + " " + a.description + " " + " ".join(a.keywords))
        return len(query & vocab)

    return max(audiences.values(), key=score)
