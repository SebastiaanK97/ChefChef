"""Infer taste signals using only recipe titles and source URLs."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import unquote, urlparse

from utils.json_io import read_json, write_json
from utils.recipe_fields import usable_url


class TasteProfile(TypedDict):
    favoriteCategories: list[str]
    favoriteStyles: list[str]
    favoriteFlavors: list[str]
    recipeCount: int


_CATEGORY_TERMS = {
    "desserts": {"cake", "cookie", "crostata", "crumble", "dessert", "frolla", "pancake", "pastry", "pie", "pudding", "syrniki", "tart"},
    "main dishes": {"carbonara", "focaccia", "fried", "keftedes", "meatball", "pasta", "ragu", "rice", "soup", "stew", "tofu", "yakimeshi"},
    "drinks": {"coffee", "drink", "espresso", "martini"},
    "breakfast": {"breakfast", "pancake", "pannenkoek", "syrniki"},
}

_STYLE_TERMS = {
    "Italian": {"carbonara", "crostata", "focaccia", "frolla", "italian", "pasta", "ragu"},
    "Mediterranean": {"feta", "greek", "keftedes", "mediterranean", "tzatziki"},
    "East Asian": {"asian", "fried", "japanese", "rice", "soy", "tofu", "yakimeshi"},
    "baked": {"cake", "cookie", "crumble", "focaccia", "pastry", "pie", "tart"},
    "comfort food": {"carbonara", "pancake", "pie", "ragu", "soup", "stew"},
}

_FLAVOR_TERMS = {
    "sweet": {"cake", "cookie", "crostata", "crumble", "dessert", "jam", "pancake", "pastry", "pie", "pudding", "syrniki", "syrup", "tart"},
    "fruit-forward": {"apple", "berry", "cherry", "fruit", "lemon", "peach", "strawberry"},
    "savory": {"carbonara", "focaccia", "keftedes", "meatball", "pasta", "ragu", "rice", "soup", "stew", "tofu"},
    "cheesy": {"burrata", "cheese", "feta", "pecorino"},
    "meaty": {"bacon", "beef", "guanciale", "meat", "mortadella", "pork", "ragu", "sausage"},
    "coffee-flavored": {"coffee", "espresso", "martini"},
}


def _source_tokens(recipe: dict[str, Any]) -> set[str]:
    title = recipe.get("name")
    url = recipe.get("url")
    text = " ".join(value for value in (title, url) if isinstance(value, str))
    path = unquote(urlparse(url).path) if isinstance(url, str) else ""
    text = f"{text} {path}"
    return {token.casefold() for token in re.findall(r"[a-zA-ZÀ-ÿ]+", text)}


def _matched_signals(
    recipes: list[dict[str, Any]],
    vocabulary: dict[str, set[str]],
) -> list[str]:
    counts: Counter[str] = Counter()
    for recipe in recipes:
        tokens = _source_tokens(recipe)
        counts.update(
            signal
            for signal, terms in vocabulary.items()
            if tokens & {term.casefold() for term in terms}
        )
    return [signal for signal, _ in counts.most_common()]


def build_taste_profile(recipes: list[dict[str, Any]]) -> TasteProfile:
    usable = [
        recipe
        for recipe in recipes
        if isinstance(recipe.get("name"), str)
        and recipe["name"].strip()
        and usable_url(recipe.get("url"))
    ]
    if not usable:
        raise ValueError("Taste analysis requires recipes with titles and URLs")
    return {
        "favoriteCategories": _matched_signals(usable, _CATEGORY_TERMS),
        "favoriteStyles": _matched_signals(usable, _STYLE_TERMS),
        "favoriteFlavors": _matched_signals(usable, _FLAVOR_TERMS),
        "recipeCount": len(usable),
    }


def recommend_recipe(data: dict[str, Any]) -> dict[str, Any]:
    """Return a taste profile inferred from recipe title and URL fields only."""
    recipes = data.get("recipes")
    if not isinstance(recipes, list):
        raise ValueError("Input must contain a recipes list")
    title_url_recipes = [
        {"name": recipe.get("name"), "url": recipe.get("url")}
        for recipe in recipes
        if isinstance(recipe, dict)
    ]
    profile = build_taste_profile(title_url_recipes)
    return {"tasteProfile": profile, "analyzedRecipes": title_url_recipes}


def analyze_file(input_path: Path, output_path: Path) -> dict[str, Any]:
    data = read_json(input_path)
    if not isinstance(data, dict):
        raise ValueError("Taste analysis input must be a JSON object containing recipes")
    result = recommend_recipe(data)
    write_json(output_path, result)
    return result
