"""Normalize recipe data and remove entries with no usable recipe information."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from utils.json_io import read_json, write_json
from utils.recipe_fields import text_lines, usable_url


def _text_lines(value: Any) -> list[str]:
    lines = []
    for candidate in text_lines(value):
        line = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", candidate).strip()
        if line:
            lines.append(line)
    return lines


def clean_recipe(recipe: dict[str, Any]) -> dict[str, Any] | None:
    name = recipe.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    ingredients = _text_lines(recipe.get("ingredients"))
    instructions = _text_lines(recipe.get("instructions"))
    url = usable_url(recipe.get("url"))
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
    data = read_json(input_path)
    if isinstance(data, list):
        source_count = len(data)
    elif isinstance(data, dict) and isinstance(data.get("recipes"), list):
        source_count = len(data["recipes"])
    else:
        source_count = -1
    cleaned = clean_recipe_data(data)
    write_json(output_path, cleaned)
    return source_count, len(cleaned["recipes"])
