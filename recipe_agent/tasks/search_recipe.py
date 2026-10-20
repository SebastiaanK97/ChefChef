"""Find one new web recipe with one taste-guided web search."""

from __future__ import annotations

import random
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from recipe_agent.tasks.fetch_recipe import fetch_recipe_url
from recipe_agent.tasks.recommend_recipe import TasteProfile, recommend_recipe
from utils.json_io import read_json, write_json
from utils.recipe_fields import text_lines, usable_url
from utils.web_search import DuckDuckGoSearch, RecipeSearchProvider, SearchResult

MAX_RESULTS_TO_FETCH = 8


def build_search_query(profile: TasteProfile, rng: random.Random | None = None) -> str:
    chooser = rng or random.Random()
    categories = profile["favoriteCategories"]
    styles = profile["favoriteStyles"]
    flavors = profile["favoriteFlavors"]
    options = []
    if categories:
        options.append(("category", chooser.choice(categories)))
    if styles:
        options.append(("style", chooser.choice(styles)))
    if flavors:
        options.append(("flavor", chooser.choice(flavors)))
    category = next((value for kind, value in options if kind == "category"), "")
    remaining = [value for kind, value in options if kind != "category"]
    modifiers = " ".join(remaining)
    suggestion = f"{category} recipe {modifiers}".strip()
    if not category and not modifiers:
        suggestion = "recipe inspired by home cooking"
    return f"new {suggestion}"


def _normalized_name(recipe: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(recipe.get("name", "")).casefold()).strip()


def _is_existing(candidate: dict[str, Any], existing: list[dict[str, Any]]) -> bool:
    candidate_url = usable_url(candidate.get("url")).rstrip("/").casefold()
    candidate_name = _normalized_name(candidate)
    for recipe in existing:
        existing_url = usable_url(recipe.get("url")).rstrip("/").casefold()
        existing_name = _normalized_name(recipe)
        if candidate_url and candidate_url == existing_url:
            return True
        if candidate_name and existing_name and SequenceMatcher(None, candidate_name, existing_name).ratio() >= 0.82:
            return True
    return False


def _usable_recipe(recipe: dict[str, Any]) -> bool:
    return bool(
        isinstance(recipe.get("name"), str)
        and recipe["name"].strip()
        and text_lines(recipe.get("ingredients"))
        and text_lines(recipe.get("instructions"))
    )


def suggest_one_recipe(
    data: dict[str, Any],
    search: RecipeSearchProvider | None = None,
    fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    rows = data.get("recipes")
    if not isinstance(rows, list):
        raise ValueError("Input must contain a recipes list")
    existing = [row for row in rows if isinstance(row, dict)]
    analysis = recommend_recipe({"recipes": existing})
    profile = analysis["tasteProfile"]
    query = build_search_query(profile, rng)
    provider = search or DuckDuckGoSearch()
    fetch = fetcher or fetch_recipe_url

    # Exactly one search call; fetching candidate pages does not trigger new searches.
    results = provider.search(query, limit=MAX_RESULTS_TO_FETCH)
    if not results:
        raise RuntimeError("Web search returned no recipe candidates")

    seen_urls: set[str] = set()
    fetch_failures: list[str] = []
    for result in results[:MAX_RESULTS_TO_FETCH]:
        source_url = result.url.strip()
        if urlparse(source_url).scheme not in {"http", "https"}:
            continue
        normalized_url = source_url.rstrip("/").casefold()
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        if _is_existing({"name": result.title, "url": source_url}, existing):
            continue
        try:
            fetched = fetch(source_url)
        except (RuntimeError, ValueError) as error:
            fetch_failures.append(f"{source_url}: {error}")
            continue
        for recipe in fetched:
            if not isinstance(recipe, dict):
                continue
            candidate = {**recipe, "url": source_url}
            if not candidate.get("name"):
                candidate["name"] = result.title
            if _is_existing(candidate, existing) or not _usable_recipe(candidate):
                continue
            candidate["ingredients"] = text_lines(candidate.get("ingredients"))
            candidate["instructions"] = text_lines(candidate.get("instructions"))
            candidate["sourceUrls"] = [source_url]
            return {
                "recipe": candidate,
                "reason": (
                    f"Found with one web search based on your taste profile "
                    f"({', '.join(profile['favoriteCategories'][:1] + profile['favoriteStyles'][:1] + profile['favoriteFlavors'][:1])})."
                ),
                "tasteProfile": profile,
                "searchQuery": query,
            }
    details = f" Fetch failures: {'; '.join(fetch_failures[:3])}" if fetch_failures else ""
    raise RuntimeError(
        "The single web search did not yield a new recipe with ingredients and instructions."
        + details
    )


def render_markdown(result: dict[str, Any]) -> str:
    recipe = result["recipe"]
    lines = [
        f"# {recipe['name']}",
        "",
        result["reason"],
        "",
        "## Ingredients",
        "",
        *[f"- {item}" for item in recipe["ingredients"]],
        "",
        "## Instructions",
        "",
        *[f"{index}. {step}" for index, step in enumerate(recipe["instructions"], 1)],
        "",
        "## Sources",
        "",
        *[f"- {url}" for url in recipe["sourceUrls"][:3]],
        "",
    ]
    return "\n".join(lines)


def recommend_file(
    input_path: Path,
    markdown_path: Path,
    json_path: Path,
    search: RecipeSearchProvider | None = None,
    fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    data = read_json(input_path)
    if not isinstance(data, dict):
        raise ValueError("Recommendation input must be a JSON object containing recipes")
    result = suggest_one_recipe(data, search=search, fetcher=fetcher, rng=rng)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    json_data = {key: value for key, value in data.items() if key != "recipes"}
    json_data["extractionMethod"] = "single-search-taste-recommendation"
    json_data["recipes"] = [result["recipe"]]
    write_json(json_path, json_data)
    return result
