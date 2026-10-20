"""Fetch a recipe URL without performing search or taste inference."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from utils.extract_recipes import extract_jsonld_recipes
from utils.json_io import write_json
from utils.recipe_fields import usable_url


def fetch_recipe_url(url: str) -> list[dict[str, Any]]:
    source_url = usable_url(url)
    if not source_url or urlparse(source_url).hostname is None:
        raise ValueError("A valid HTTP(S) recipe URL is required")
    result = extract_jsonld_recipes(source_url)
    recipes = result.get("recipes")
    if not isinstance(recipes, list) or not recipes:
        raise RuntimeError(f"No recipe data found at {source_url}")
    return recipes


def fetch_file(url: str, output_path: Path) -> list[dict[str, Any]]:
    recipes = fetch_recipe_url(url)
    write_json(output_path, {"sourceUrl": url, "recipes": recipes})
    return recipes
