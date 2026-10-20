"""Keep only recipes with source URLs and normalize their display titles."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from utils.json_io import read_json, write_json
from utils.recipe_fields import usable_url


def _title_from_url(url: str) -> str:
    path = unquote(urlparse(url).path.rstrip("/"))
    slug = path.rsplit("/", 1)[-1] or urlparse(url).hostname or "Recipe"
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


def clean_recipe(recipe: dict[str, Any]) -> dict[str, Any] | None:
    url = usable_url(recipe.get("url"))
    if not url:
        return None

    title = recipe.get("name")
    if not isinstance(title, str) or not title.strip():
        title = _title_from_url(url)
    return {"name": title.strip(), "url": url}


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
