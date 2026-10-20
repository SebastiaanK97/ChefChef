#!/usr/bin/env python3
"""Extract recipes from a public Notion database or a Schema.org JSON-LD page.

Usage:
    python -m utils.extract_recipes URL [-o data/recipes.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.json_io import write_json
from utils.paths import RECIPES_PATH


API_LIMIT = 1000
USER_AGENT = "RecipeExtractor/1.0"


class JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_json_ld = False
        self._parts: list[str] = []
        self.documents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attributes = dict(attrs)
        self._in_json_ld = (attributes.get("type") or "").split(";")[0].strip().lower() == "application/ld+json"
        if self._in_json_ld:
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_json_ld:
            self.documents.append("".join(self._parts))
            self._in_json_ld = False
            self._parts = []


def request_bytes(url: str, payload: dict | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except (HTTPError, URLError) as error:
        raise RuntimeError(f"Request failed for {url}: {error}") from error


def request_json(url: str, payload: dict) -> dict:
    try:
        result = json.loads(request_bytes(url, payload))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"API returned invalid JSON for {url}") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"API returned an unexpected response for {url}")
    if result.get("isNotionError"):
        raise RuntimeError(f"Notion API error: {result.get('message', 'unknown error')}")
    return result


def notion_api_url(page_url: str, endpoint: str) -> str:
    parsed = urlparse(page_url)
    return f"{parsed.scheme}://{parsed.netloc}/api/v3/{endpoint}"


def page_id_from_url(page_url: str) -> str:
    match = re.search(r"[0-9a-fA-F]{32}", unquote(urlparse(page_url).path))
    if not match:
        raise ValueError("Could not find a Notion page ID in the URL path")
    compact_id = match.group(0).lower()
    return "-".join((compact_id[:8], compact_id[8:12], compact_id[12:16], compact_id[16:20], compact_id[20:]))


def text_value(raw: object) -> str:
    if not isinstance(raw, list):
        return ""
    parts = []
    for item in raw:
        if isinstance(item, list) and item and isinstance(item[0], str):
            parts.append(item[0])
    return "".join(parts).strip()


def notion_property(raw: object, property_type: str) -> object:
    value = text_value(raw)
    if not value:
        return [] if property_type == "multi_select" else (None if property_type == "number" else "")
    if property_type == "number":
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() else number
    if property_type == "multi_select":
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def block_text(block: dict) -> str:
    value = block.get("value", {}).get("value", {})
    properties = value.get("properties") or {}
    return text_value(properties.get("title"))


def extract_page_instructions(page_url: str, recipe_id: str) -> list[str]:
    response = request_json(
        notion_api_url(page_url, "loadCachedPageChunk"),
        {
            "pageId": recipe_id,
            "limit": 100,
            "cursor": {"stack": []},
            "chunkNumber": 0,
            "verticalColumns": False,
        },
    )
    blocks = response.get("recordMap", {}).get("block", {})
    recipe = blocks.get(recipe_id, {}).get("value", {}).get("value", {})
    instructions: list[str] = []
    visited: set[str] = set()

    def walk(block_ids: list[str]) -> None:
        for block_id in block_ids:
            if block_id in visited:
                continue
            visited.add(block_id)
            block = blocks.get(block_id)
            if not block:
                continue
            value = block.get("value", {}).get("value", {})
            block_type = value.get("type", "")
            text = block_text(block)
            if text and block_type in {"numbered_list", "bulleted_list"}:
                instructions.append(text)
            walk(value.get("content", []))

    walk(recipe.get("content", []))
    return instructions


def extract_notion_recipes(page_url: str) -> dict:
    page_id = page_id_from_url(page_url)
    initial = request_json(
        notion_api_url(page_url, "loadCachedPageChunk"),
        {
            "pageId": page_id,
            "limit": 100,
            "cursor": {"stack": []},
            "chunkNumber": 0,
            "verticalColumns": False,
        },
    )
    records = initial.get("recordMap", {})
    page_record = records.get("block", {}).get(page_id)
    if not page_record:
        raise RuntimeError("Notion did not return the requested public page")
    page = page_record["value"]["value"]
    if page.get("type") != "collection_view_page":
        raise RuntimeError("The Notion URL does not point to a recipe database page")

    collection_id = page.get("collection_id")
    collection = records.get("collection", {}).get(collection_id)
    if not collection:
        raise RuntimeError("The Notion API did not return the database schema")
    collection_record = collection["value"]["value"]
    schema = collection_record.get("schema", {})
    space_id = collection.get("spaceId") or page_record.get("spaceId")
    query = urlparse(page_url).query
    view_id = next((item.split("=", 1)[1] for item in query.split("&") if item.startswith("v=")), None)
    if not view_id:
        view_ids = page.get("view_ids", [])
        if not view_ids:
            raise RuntimeError("The Notion database has no collection view")
        view_id = view_ids[0]

    collection_response = request_json(
        notion_api_url(page_url, "queryCollection"),
        {
            "collection": {"id": collection_id, "spaceId": space_id},
            "collectionView": {"id": view_id, "spaceId": space_id},
            "loader": {
                "type": "reducer",
                "reducers": {"collection_group_results": {"type": "results", "limit": API_LIMIT}},
                "searchQuery": "",
                "userTimeZone": "UTC",
            },
        },
    )
    group_results = (
        collection_response.get("result", {})
        .get("reducerResults", {})
        .get("collection_group_results", {})
    )
    if not isinstance(group_results.get("blockIds"), list):
        raise RuntimeError("Notion API response did not include database recipe rows")
    if group_results.get("hasMore"):
        raise RuntimeError(f"Recipe database exceeds the {API_LIMIT}-record extraction limit")

    field_names = {
        "name": "name",
        "title": "name",
        "ingredients": "ingredients",
        "cooking time": "cookingTime",
        "prep time": "prepTime",
        "total time": "totalTime",
        "servings": "servings",
        "link": "url",
        "url": "url",
        "category": "category",
        "tags": "tags",
        "comment": "comment",
        "description": "description",
        "cuisine": "cuisine",
    }
    rows = collection_response.get("recordMap", {}).get("block", {})
    recipe_ids = group_results.get("blockIds", [])
    recipes = []
    for recipe_id in recipe_ids:
        row = rows.get(recipe_id, {}).get("value", {}).get("value", {})
        properties = row.get("properties") or {}
        recipe = {"id": recipe_id}
        for property_id, definition in schema.items():
            name = field_names.get(definition.get("name", "").strip().lower())
            if name:
                recipe[name] = notion_property(properties.get(property_id), definition.get("type", ""))
        if not recipe.get("name"):
            raise RuntimeError(f"Notion database row {recipe_id} has no recipe name")
        recipes.append(recipe)

    if not recipes:
        raise RuntimeError("No recipes were returned by the Notion database")

    with ThreadPoolExecutor(max_workers=4) as executor:
        instruction_lists = executor.map(
            lambda recipe: extract_page_instructions(page_url, recipe["id"]),
            recipes,
        )
        for recipe, instructions in zip(recipes, instruction_lists):
            if instructions:
                recipe["instructions"] = instructions

    return {"sourceUrl": page_url, "extractionMethod": "notion-public-api", "recipes": recipes}


def recipe_types(value: object) -> bool:
    if isinstance(value, str):
        return value.rsplit("/", 1)[-1].lower() == "recipe"
    if isinstance(value, list):
        return any(recipe_types(item) for item in value)
    return False


def find_jsonld_recipes(value: object) -> list[dict]:
    if isinstance(value, list):
        return [recipe for item in value for recipe in find_jsonld_recipes(item)]
    if not isinstance(value, dict):
        return []
    matches = [value] if recipe_types(value.get("@type")) else []
    return matches + [
        recipe
        for key, nested in value.items()
        if key != "@context"
        for recipe in find_jsonld_recipes(nested)
    ]


def instruction_text(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [line for item in value for line in instruction_text(item)]
    if isinstance(value, dict):
        if value.get("@type") == "HowToSection":
            return instruction_text(value.get("itemListElement", []))
        if value.get("@type") == "HowToStep":
            return instruction_text(value.get("text", value.get("name", "")))
    return []


def as_list(value: object) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def extract_jsonld_recipes(page_url: str) -> dict:
    html = request_bytes(page_url).decode("utf-8", errors="replace")
    parser = JsonLdParser()
    parser.feed(html)
    found = []
    for document in parser.documents:
        try:
            data = json.loads(document)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid JSON-LD on {page_url}: {error}") from error
        found.extend(find_jsonld_recipes(data))
    if not found:
        raise RuntimeError(f"No Schema.org Recipe JSON-LD found at {page_url}")

    recipes = []
    for item in found:
        recipe = {
            "name": item.get("name", ""),
            "ingredients": as_list(item.get("recipeIngredient")),
            "instructions": instruction_text(item.get("recipeInstructions", [])),
            "prepTime": item.get("prepTime", ""),
            "cookTime": item.get("cookTime", ""),
            "totalTime": item.get("totalTime", ""),
            "servings": item.get("recipeYield", ""),
            "category": as_list(item.get("recipeCategory")),
            "cuisine": as_list(item.get("recipeCuisine")),
            "description": item.get("description", ""),
            "url": item.get("url", page_url),
        }
        recipes.append(recipe)
    return {"sourceUrl": page_url, "extractionMethod": "schema-org-json-ld", "recipes": recipes}


def extract_recipes(page_url: str) -> dict:
    parsed = urlparse(page_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Provide an absolute HTTP or HTTPS URL")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ("notion.site", "notion.so", "notion.com")
    ):
        return extract_notion_recipes(page_url)
    return extract_jsonld_recipes(page_url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract recipes from a public Notion database or recipe page")
    parser.add_argument("url", help="Public Notion page or website recipe URL")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=RECIPES_PATH,
        help=f"Output JSON path (default: {RECIPES_PATH})",
    )
    args = parser.parse_args()

    try:
        result = extract_recipes(args.url)
        output_path = Path(args.output)
        write_json(output_path, result)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {len(result['recipes'])} recipes to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
