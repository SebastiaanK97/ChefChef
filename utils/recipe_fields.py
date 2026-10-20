"""Shared normalization for recipe text fields and URLs."""

from __future__ import annotations

from typing import Any


def text_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = value.splitlines()
    elif isinstance(value, list):
        candidates = []
        for item in value:
            if isinstance(item, str):
                candidates.extend(item.splitlines())
            elif isinstance(item, dict):
                text = item.get("text") or item.get("name")
                if isinstance(text, str):
                    candidates.extend(text.splitlines())
    else:
        return []
    return [candidate.strip() for candidate in candidates if candidate.strip()]


def usable_url(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if not isinstance(value, str):
        return ""
    url = value.strip()
    return url if url.startswith(("https://", "http://")) else ""
