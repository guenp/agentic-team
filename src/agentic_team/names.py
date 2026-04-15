"""Agent name generator — derives short names from task descriptions."""

from __future__ import annotations

import re

# Stop words to skip when building a slug from a task description
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "all", "this", "that", "be",
    "do", "if", "so", "up", "out", "no", "not", "what", "how", "why",
    "when", "where", "which", "who", "can", "will", "should", "would",
    "could", "get", "set", "has", "have", "had", "make", "each", "every",
    "most", "more", "some", "any", "about", "into", "over", "just", "also",
    "than", "then", "them", "their", "there", "these", "those", "very",
})

# Fallback names when no task is provided
_FALLBACK_NAMES = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
    "golf", "hotel", "india", "juliet", "kilo", "lima",
    "mike", "november", "oscar", "papa", "quebec", "romeo",
    "sierra", "tango", "uniform", "victor", "whiskey", "xray",
    "yankee", "zulu",
]


def name_from_task(task: str, existing: list[str]) -> str:
    """Generate a short kebab-case name from a task description.

    Picks the first 2-3 meaningful words from the task, deduplicates
    against existing names by appending a suffix if needed.
    """
    # Extract words, drop stop words and short fragments
    words = re.findall(r"[a-zA-Z]+", task.lower())
    meaningful = [w for w in words if w not in _STOP_WORDS and len(w) > 1]

    if not meaningful:
        return next_fallback(existing)

    slug = "-".join(meaningful[:2])

    # Deduplicate
    if slug not in existing:
        return slug

    for i in range(2, 100):
        candidate = f"{slug}-{i}"
        if candidate not in existing:
            return candidate

    return next_fallback(existing)


def next_fallback(existing: list[str]) -> str:
    """Return the first unused fallback name."""
    used = set(existing)
    for name in _FALLBACK_NAMES:
        if name not in used:
            return name
    raise RuntimeError(f"All {len(_FALLBACK_NAMES)} fallback names exhausted")


def match_name(prefix: str, existing: list[str]) -> str | None:
    """Match a partial name prefix against existing agent names.

    Returns the first match, or None if no match.
    """
    prefix = prefix.lower()
    for name in existing:
        if name.startswith(prefix):
            return name
    return None
