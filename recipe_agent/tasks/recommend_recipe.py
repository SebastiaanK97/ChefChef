"""Recommend a taste-matched recipe from the supplied collection."""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, TypedDict
from urllib.parse import urlparse

from utils.json_io import read_json, write_json
from utils.recipe_fields import text_lines, usable_url
from utils.web_search import DuckDuckGoSearch, RecipeSearchProvider, SearchResult

_STOPWORDS = {
    "and", "the", "with", "from", "for", "recipe", "recipes", "dish", "dishes", "main",
    "fresh", "optional", "total", "time", "mins", "prep", "cook", "servings",
}
MAX_SOURCE_URLS = 3
SEARCH_RESULT_LIMIT = 12
MAX_PAGES_TO_FETCH = 8


class TasteProfile(TypedDict):
    favoriteCategories: list[str]
    favoriteIngredients: list[str]
    categoryIngredients: dict[str, list[str]]


def _items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;\n]", value) if part.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _tokens(value: Any) -> list[str]:
    return [
        token.lower()
        for item in _items(value)
        for token in re.findall(r"[A-Za-zÀ-ÿ]+", item)
        if token.lower() not in _STOPWORDS and len(token) > 2
    ]


def build_taste_profile(recipes: list[dict[str, Any]]) -> TasteProfile:
    categories: Counter[str] = Counter()
    tagged_ingredients: Counter[str] = Counter()
    other_ingredients: Counter[str] = Counter()
    category_ingredients: dict[str, Counter[str]] = {}
    for recipe in recipes:
        recipe_categories = _tokens(recipe.get("category"))
        recipe_tags = _tokens(recipe.get("tags"))
        categories.update(recipe_categories)
        tagged_ingredients.update(recipe_tags)
        other_ingredients.update(_tokens(recipe.get("ingredients")))
        other_ingredients.update(_tokens(recipe.get("name")))
        for category in recipe_categories:
            category_ingredients.setdefault(category, Counter()).update(recipe_tags)
    ranked_ingredients = sorted(
        tagged_ingredients,
        key=lambda term: (
            -(tagged_ingredients[term] * 4 + other_ingredients[term]),
            term,
        ),
    )

    return {
        "favoriteCategories": [term for term, _ in categories.most_common(3)],
        "favoriteIngredients": ranked_ingredients[:6],
        "categoryIngredients": {
            category: [term for term, _ in counts.most_common(6)]
            for category, counts in category_ingredients.items()
        },
    }


def _url(recipe: dict[str, Any]) -> str:
    return usable_url(recipe.get("url"))


def _recipe_terms(recipe: dict[str, Any]) -> set[str]:
    return set(
        _tokens(recipe.get("name"))
        + _tokens(recipe.get("ingredients"))
        + _tokens(recipe.get("tags"))
    )


def _score_recipe(recipe: dict[str, Any], profile: TasteProfile) -> int:
    terms = _recipe_terms(recipe)
    preferred = set(profile["favoriteIngredients"])
    score = 3 * len(terms & preferred)
    categories = set(_tokens(recipe.get("category")) + _tokens(recipe.get("cuisine")))
    score += 5 * len(categories & set(profile["favoriteCategories"]))
    return score


def _display_list(value: Any) -> list[str]:
    return text_lines(value)


def _is_duplicate(candidate: dict[str, Any], existing: list[dict[str, Any]]) -> bool:
    candidate_name = re.sub(r"[^a-z0-9]+", " ", str(candidate.get("name", "")).casefold()).strip()
    candidate_url = _url(candidate).rstrip("/").casefold()
    for recipe in existing:
        existing_name = re.sub(r"[^a-z0-9]+", " ", str(recipe.get("name", "")).casefold()).strip()
        existing_url = _url(recipe).rstrip("/").casefold()
        if candidate_url and existing_url == candidate_url:
            return True
        if candidate_name and existing_name and SequenceMatcher(None, candidate_name, existing_name).ratio() >= 0.82:
            return True
    return False


def _search_queries(profile: TasteProfile) -> list[str]:
    categories = profile["favoriteCategories"]
    ingredients = profile["favoriteIngredients"]
    if not categories and not ingredients:
        raise ValueError("Not enough recipe details to infer taste preferences")
    queries: list[str] = []
    if categories:
        category = categories[0][:-1] if categories[0].endswith("s") else categories[0]
        category_ingredients = profile["categoryIngredients"].get(categories[0], [])
        common = ingredients[:3]
        queries.append(f"{category} recipe {' '.join(common)}".strip())
        distinctive = [term for term in category_ingredients if term not in common]
        if distinctive:
            queries.append(f"{category} recipe {' '.join(common + distinctive[-1:])}".strip())
        if len(categories) > 1:
            alternate = categories[1][:-1] if categories[1].endswith("s") else categories[1]
            queries.append(f"{alternate} recipe {' '.join(common)}".strip())
    else:
        queries.append(f"recipe {' '.join(ingredients[:3])}".strip())
    return queries


def _fetch_recipe_page(url: str) -> list[dict[str, Any]]:
    from utils.extract_recipes import extract_jsonld_recipes

    data = extract_jsonld_recipes(url)
    return data["recipes"]


def _find_web_recipe(
    recipes: list[dict[str, Any]],
    profile: TasteProfile,
    search: RecipeSearchProvider,
    fetcher: Callable[[str], list[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    seen_urls = {_url(recipe).rstrip("/").casefold() for recipe in recipes if _url(recipe)}
    results: list[SearchResult] = []
    seen_results: set[str] = set()
    for query in _search_queries(profile):
        for result in search.search(query, limit=SEARCH_RESULT_LIMIT):
            url = result.url.strip()
            parsed_scheme = urlparse(url).scheme.lower()
            normalized_url = url.rstrip("/").casefold()
            if parsed_scheme not in {"http", "https"} or normalized_url in seen_results:
                continue
            if normalized_url in seen_urls:
                continue
            seen_results.add(normalized_url)
            results.append(SearchResult(title=result.title, url=url))

    candidates: list[tuple[int, dict[str, Any], str]] = []
    pages_fetched = 0
    for result in results:
        if pages_fetched >= MAX_PAGES_TO_FETCH:
            break
        pages_fetched += 1
        try:
            page_recipes = fetcher(result.url)
        except (RuntimeError, ValueError):
            continue
        for candidate in page_recipes:
            if not isinstance(candidate, dict):
                continue
            if not str(candidate.get("name", "")).strip():
                candidate = {**candidate, "name": result.title}
            candidate["url"] = result.url
            if _is_duplicate(candidate, recipes):
                continue
            if not _display_list(candidate.get("ingredients")) or not _display_list(candidate.get("instructions")):
                continue
            candidates.append((_score_recipe(candidate, profile), candidate, result.url))

    if not candidates:
        raise RuntimeError(
            "Web search found no new recipe with ingredients and instructions. "
            "Try again later or use another search provider."
        )
    _, selected, source_url = max(candidates, key=lambda item: item[0])
    selected["sourceUrls"] = [source_url]
    return selected, source_url


def _recommended_entry(recipe: dict[str, Any], source_url: str) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": str(recipe["name"]).strip(),
        "ingredients": _display_list(recipe.get("ingredients")),
        "instructions": _display_list(recipe.get("instructions")),
        "url": source_url,
        "sourceUrls": [source_url],
    }
    for key in ("category", "tags", "servings", "prepTime", "cookTime", "totalTime", "cuisine"):
        value = recipe.get(key)
        if value not in (None, "", [], {}):
            entry[key] = value
    return entry


def recommend_recipe(
    data: dict[str, Any],
    search: RecipeSearchProvider | None = None,
    fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    recipes = data.get("recipes")
    if not isinstance(recipes, list) or not recipes:
        raise ValueError("Input contains no recipes to learn taste preferences from")
    valid_recipes = [recipe for recipe in recipes if isinstance(recipe, dict)]
    profile = build_taste_profile(valid_recipes)
    selected, source_url = _find_web_recipe(
        valid_recipes,
        profile,
        search or DuckDuckGoSearch(),
        fetcher or _fetch_recipe_page,
    )
    entry = _recommended_entry(selected, source_url)
    preferences = profile["favoriteCategories"][:1] + profile["favoriteIngredients"][:3]
    reason = "Found a new web recipe matching your recipe collection"
    if preferences:
        reason += " preferences for " + ", ".join(preferences)
    reason += "."
    return {
        "recipe": entry,
        "reason": reason,
        "tasteProfile": profile,
    }


def render_markdown(result: dict[str, Any]) -> str:
    recipe = result["recipe"]
    lines = [
        f"# {recipe['name']}",
        "",
        result["reason"],
        "",
        "## Ingredients",
        "",
        *[f"- {item}" for item in _display_list(recipe.get("ingredients"))],
        "",
        "## Instructions",
        "",
        *[f"{index}. {step}" for index, step in enumerate(recipe["instructions"], start=1)],
        "",
        "## Sources",
        "",
        *[f"- {url}" for url in recipe["sourceUrls"][:MAX_SOURCE_URLS]],
        "",
    ]
    return "\n".join(lines)


def recommend_file(
    input_path: Path,
    markdown_path: Path,
    json_path: Path,
    search: RecipeSearchProvider | None = None,
    fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    data = read_json(input_path)
    if not isinstance(data, dict):
        raise ValueError("Recommendation input must be a JSON object containing recipes")
    result = recommend_recipe(data, search=search, fetcher=fetcher)
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    json_data = {
        key: value
        for key, value in data.items()
        if key != "recipes"
    }
    json_data["extractionMethod"] = "web-search-recommendation"
    json_data["recipes"] = [
        {key: value for key, value in result["recipe"].items() if key != "sourceUrls"}
    ]
    write_json(json_path, json_data)
    return result
