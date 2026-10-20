"""Write a simple recipe document from the final web-search task output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.json_io import read_json, write_json
from utils.recipe_fields import text_lines, usable_url

_RECIPE_SIGNAL_TERMS = {
    "favoriteCategories": {
        "desserts": {"cake", "cookie", "crumble", "dessert", "pastry", "pie", "pudding", "tart"},
        "main dishes": {"carbonara", "meatball", "pasta", "rice", "soup", "stew", "tofu"},
        "drinks": {"coffee", "drink", "espresso", "martini"},
        "breakfast": {"breakfast", "pancake", "waffle"},
    },
    "favoriteStyles": {
        "Italian": {"carbonara", "crostata", "focaccia", "pasta", "ragu"},
        "Mediterranean": {"feta", "greek", "keftedes", "mediterranean"},
        "East Asian": {"asian", "japanese", "rice", "soy", "tofu"},
        "baked": {"bake", "cake", "cookie", "crumble", "pastry", "pie", "tart"},
        "comfort food": {"carbonara", "pancake", "pie", "ragu", "soup", "stew"},
    },
    "favoriteFlavors": {
        "sweet": {"cake", "cookie", "dessert", "jam", "pastry", "pie", "pudding", "syrup", "tart"},
        "fruit-forward": {"apple", "berry", "cherry", "fruit", "lemon", "peach", "strawberry"},
        "savory": {"carbonara", "focaccia", "keftedes", "pasta", "ragu", "rice", "soup", "stew", "tofu"},
        "cheesy": {"burrata", "cheese", "feta", "pecorino"},
        "meaty": {"bacon", "beef", "guanciale", "meat", "mortadella", "pork", "sausage"},
        "coffee-flavored": {"coffee", "espresso", "martini"},
    },
}


def simple_recipe(search_result: dict[str, Any]) -> dict[str, Any]:
    recipe = search_result.get("recipe")
    if not isinstance(recipe, dict):
        raise ValueError("Search result must contain a recipe object")

    name = recipe.get("name")
    ingredients = text_lines(recipe.get("ingredients"))
    instructions = text_lines(recipe.get("instructions"))
    sources = search_result.get("recipe", {}).get("sourceUrls")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Search result recipe must have a title")
    if not ingredients or not instructions:
        raise ValueError("Search result recipe must include ingredients and instructions")
    if not isinstance(sources, list):
        sources = [recipe.get("url")]
    source_urls = list(dict.fromkeys(url for item in sources if (url := usable_url(item))))
    if not source_urls:
        raise ValueError("Search result recipe must include at least one valid source URL")

    url = usable_url(recipe.get("url")) or source_urls[0]
    output_recipe = {
        key: value
        for key, value in recipe.items()
        if key not in {"ingredients", "instructions", "url", "sourceUrls"}
    }
    output_recipe.update(
        {
            "name": name.strip(),
            "ingredients": ingredients,
            "instructions": instructions,
            "url": url,
            "sourceUrls": source_urls[:3],
        }
    )
    profile = search_result.get("tasteProfile")
    recipe_text = " ".join(
        str(recipe.get(key, ""))
        for key in ("name", "url", "category", "cuisine", "description")
    ).casefold()
    taste_signals: list[str] = []
    if isinstance(profile, dict):
        for key, vocabulary in _RECIPE_SIGNAL_TERMS.items():
            values = profile.get(key)
            if isinstance(values, list):
                taste_signals.extend(
                    signal
                    for signal in values
                    if isinstance(signal, str)
                    and signal in vocabulary
                    and recipe_text
                    and any(term in recipe_text for term in vocabulary[signal])
                )
    description = (
        f"Chosen to match your taste for {', '.join(taste_signals)}."
        if taste_signals
        else "Chosen based on your recipe collection's taste profile."
    )
    return {"recipe": output_recipe, "description": description}


def render_markdown(result: dict[str, Any]) -> str:
    recipe = result["recipe"]
    return "\n".join(
        [
            f"# {recipe['name']}",
            "",
            result["description"],
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
            *[f"- {url}" for url in recipe["sourceUrls"]],
            "",
        ]
    )


def write_recipe_file(
    search_output_path: Path,
    markdown_path: Path,
    json_path: Path,
) -> dict[str, Any]:
    search_result = read_json(search_output_path)
    if not isinstance(search_result, dict):
        raise ValueError("Search output must be a JSON object")
    result = simple_recipe(search_result)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    json_data = {
        "extractionMethod": "taste-based-simple-recipe",
        "tasteProfile": search_result.get("tasteProfile", {}),
        "recipes": [result["recipe"]],
    }
    write_json(json_path, json_data)
    return result
