"""Alphabetical agent name generator."""

from __future__ import annotations

NAMES: list[str] = [
    "adder",
    "bear",
    "crispy",
    "darling",
    "enkidu",
    "flounder",
    "gecko",
    "hawk",
    "ibis",
    "jackal",
    "kite",
    "lynx",
    "marten",
    "newt",
    "ocelot",
    "puma",
    "quail",
    "raven",
    "shrike",
    "tapir",
    "urchin",
    "viper",
    "wren",
    "xerus",
    "yak",
    "zorilla",
]


def next_name(existing: list[str]) -> str:
    """Return the first unused name from the alphabetical list."""
    used = set(existing)
    for name in NAMES:
        if name not in used:
            return name
    raise RuntimeError(f"All {len(NAMES)} agent names exhausted")


def match_name(prefix: str, existing: list[str]) -> str | None:
    """Match a partial name prefix against existing agent names.

    Returns the first match, or None if no match.
    """
    prefix = prefix.lower()
    for name in existing:
        if name.startswith(prefix):
            return name
    return None
