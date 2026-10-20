"""Normalize recipe data and remove entries with no usable recipe information."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _text_lines(value: Any) -> list[str]:
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

    lines = []
    for candidate in candidates:
        line = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", candidate).strip()
        if line:
            lines.append(line)
    return lines


def _usable_url(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if not isinstance(value, str):
        return ""
    url = value.strip()
    return url if url.startswith(("https://", "http://")) else ""


def clean_recipe(recipe: dict[str, Any]) -> dict[str, Any] | None:
    name = recipe.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    ingredients = _text_lines(recipe.get("ingredients"))
    instructions = _text_lines(recipe.get("instructions"))
    url = _usable_url(recipe.get("url"))
    if not (url or ingredients or instructions):
        return None

    cleaned: dict[str, Any] = {
        "name": name.strip(),
        "ingredients": ingredients,
        "instructions": instructions,
    }
    if url:
        cleaned["url"] = url
    for key, value in recipe.items():
        if key in {"name", "ingredients", "instructions", "url"}:
            continue
        if value not in (None, "", [], {}):
            cleaned[key] = value
    return cleaned


def clean_recipe_data(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        metadata: dict[str, Any] = {}
        recipe_rows = data
    elif isinstance(data, dict) and isinstance(data.get("recipes"), list):
        metadata = {key: value for key, value in data.items() if key != "recipes"}
        recipe_rows = data["recipes"]
    else:
        raise ValueError("Input JSON must be a recipe list or an object containing a recipes list")

    cleaned = []
    for index, recipe in enumerate(recipe_rows):
        if not isinstance(recipe, dict):
            raise ValueError(f"Recipe entry at index {index} must be an object")
        result = clean_recipe(recipe)
        if result is not None:
            cleaned.append(result)
    return {**metadata, "recipes": cleaned}


def clean_file(input_path: Path, output_path: Path) -> tuple[int, int]:
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {input_path}: {error}") from error
    if isinstance(data, list):
        source_count = len(data)
    elif isinstance(data, dict) and isinstance(data.get("recipes"), list):
        source_count = len(data["recipes"])
    else:
        source_count = -1
    cleaned = clean_recipe_data(data)
    output_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return source_count, len(cleaned["recipes"])
