import unittest
import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.web_search import DuckDuckGoSearch, SearchResult, _DuckDuckGoParser, _target_url
from recipe_agent.tasks.clean_recipes import clean_recipe_data
from recipe_agent.tasks.recommend_recipe import (
    build_taste_profile,
    recommend_file,
    recommend_recipe,
    render_markdown,
)


class FakeSearch:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        return self.results[:limit]


class CleanRecipesTests(unittest.TestCase):
    def test_drops_only_entries_without_url_ingredients_or_instructions(self) -> None:
        cleaned = clean_recipe_data(
            {
                "recipes": [
                    {"name": "Source only", "url": "https://example.org/source"},
                    {"name": "Ingredients only", "ingredients": "  • flour\nEgg "},
                    {"name": "Instructions only", "instructions": ["1. Mix", "Bake"]},
                    {"name": "Empty", "url": "", "ingredients": "", "instructions": []},
                ]
            }
        )

        self.assertEqual([recipe["name"] for recipe in cleaned["recipes"]], [
            "Source only",
            "Ingredients only",
            "Instructions only",
        ])
        self.assertEqual(cleaned["recipes"][1]["ingredients"], ["flour", "Egg"])
        self.assertEqual(cleaned["recipes"][2]["instructions"], ["Mix", "Bake"])

    def test_preserves_top_level_metadata(self) -> None:
        cleaned = clean_recipe_data(
            {"sourceUrl": "https://example.org", "recipes": [{"name": "Cake", "url": "https://example.org/cake"}]}
        )
        self.assertEqual(cleaned["sourceUrl"], "https://example.org")


class RecommendationTests(unittest.TestCase):
    def test_profile_uses_collection_categories_and_ingredients(self) -> None:
        profile = build_taste_profile(
            [
                {"category": ["Desserts"], "tags": ["Egg", "Flour"]},
                {"category": ["Desserts"], "tags": ["Egg", "Butter"]},
            ]
        )
        self.assertEqual(profile["favoriteCategories"][0], "desserts")
        self.assertEqual(profile["favoriteIngredients"][0], "egg")

    def test_returns_one_recommendation_with_up_to_three_sources(self) -> None:
        search = FakeSearch([SearchResult("Berry Custard Tart", "https://example.org/berry-tart")])

        def fetcher(url: str) -> list[dict]:
            self.assertEqual(url, "https://example.org/berry-tart")
            return [
                {
                    "name": "Berry Custard Tart",
                    "category": ["Desserts"],
                    "ingredients": ["Egg", "Butter", "Flour", "Berries"],
                    "instructions": ["Mix the custard", "Bake until set"],
                }
            ]

        result = recommend_recipe(
            {
                "recipes": [
                    {
                        "name": "Forest Pie",
                        "category": ["Desserts"],
                        "tags": ["Butter", "Egg", "Forest Fruit", "Flour"],
                        "ingredients": ["Butter", "Egg", "Forest fruit", "Flour"],
                        "instructions": [],
                        "url": "https://example.org/forest-pie",
                    }
                ]
            },
            search=search,
            fetcher=fetcher,
        )
        recipe = result["recipe"]
        self.assertEqual(recipe["name"], "Berry Custard Tart")
        self.assertEqual(recipe["ingredients"], ["Egg", "Butter", "Flour", "Berries"])
        self.assertEqual(recipe["instructions"], ["Mix the custard", "Bake until set"])
        self.assertEqual(recipe["sourceUrls"], ["https://example.org/berry-tart"])
        self.assertNotEqual(recipe["name"], "Forest Pie")
        self.assertLessEqual(len(recipe["sourceUrls"]), 3)
        self.assertIn("## Ingredients", render_markdown(result))
        self.assertIn("## Instructions", render_markdown(result))
        self.assertTrue(search.queries)
        self.assertIn("dessert", search.queries[0])

    def test_writes_markdown_and_one_entry_recipes_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "recipes.json"
            markdown_path = root / "recommended_recipe.md"
            json_path = root / "recommended_recipes.json"
            input_path.write_text(
                json.dumps(
                    {
                        "sourceUrl": "https://example.org/book",
                        "recipes": [
                            {
                                "name": "Carbonara",
                                "category": ["Desserts"],
                                "tags": ["Egg", "Flour"],
                                "ingredients": "Pasta\nCheese",
                                "instructions": ["Cook pasta"],
                                "url": "https://example.org/carbonara",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            search = FakeSearch([SearchResult("Lemon Tart", "https://example.org/lemon-tart")])
            fetcher = lambda _: [
                {
                    "name": "Lemon Tart",
                    "ingredients": ["Lemon", "Egg", "Flour"],
                    "instructions": ["Bake the tart"],
                }
            ]

            recommend_file(input_path, markdown_path, json_path, search=search, fetcher=fetcher)

            output = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(len(output["recipes"]), 1)
            self.assertEqual(output["recipes"][0]["name"], "Lemon Tart")
            self.assertEqual(output["recipes"][0]["ingredients"], ["Lemon", "Egg", "Flour"])
            self.assertEqual(output["recipes"][0]["url"], "https://example.org/lemon-tart")
            self.assertNotIn("sourceUrls", output["recipes"][0])
            self.assertIn("## Instructions", markdown_path.read_text(encoding="utf-8"))

    def test_rejects_collections_without_complete_recipe_and_source(self) -> None:
        search = FakeSearch([SearchResult("Empty", "https://example.org/empty")])
        with self.assertRaisesRegex(RuntimeError, "no new recipe"):
            recommend_recipe(
                {"recipes": [{"name": "Existing", "tags": ["egg"], "url": "https://example.org/old"}]},
                search=search,
                fetcher=lambda _: [],
            )

    def test_skips_recipes_already_present_in_collection(self) -> None:
        search = FakeSearch(
            [
                SearchResult("Forest Pie", "https://example.org/duplicate"),
                SearchResult("Wild Berry Custard", "https://example.org/new"),
            ]
        )
        fetched = {
            "https://example.org/duplicate": [
                {
                    "name": "Forest Pie",
                    "ingredients": ["Egg", "Flour", "Forest fruit"],
                    "instructions": ["Bake"],
                }
            ],
            "https://example.org/new": [
                {
                    "name": "Wild Berry Custard",
                    "ingredients": ["Egg", "Flour", "Forest fruit"],
                    "instructions": ["Cook"],
                }
            ],
        }
        result = recommend_recipe(
            {
                "recipes": [
                    {
                        "name": "Forest Pie",
                        "ingredients": ["Egg", "Flour", "Forest fruit"],
                        "tags": ["Egg", "Flour", "Forest Fruit"],
                        "url": "https://example.org/existing-pie",
                    }
                ]
            },
            search=search,
            fetcher=lambda url: fetched[url],
        )
        self.assertEqual(result["recipe"]["name"], "Wild Berry Custard")
        self.assertEqual(result["recipe"]["sourceUrls"], ["https://example.org/new"])


class WebSearchTests(unittest.TestCase):
    def test_parses_duckduckgo_results_and_unwraps_target_url(self) -> None:
        parser = _DuckDuckGoParser()
        parser.feed(
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Frecipe">'
            "Berry <b>Custard</b> Tart</a>"
        )
        self.assertEqual(parser.results[0].title, "Berry Custard Tart")
        self.assertEqual(_target_url(parser.results[0].url), "https://example.org/recipe")

    def test_reports_search_engine_challenge(self) -> None:
        with patch("utils.web_search.urlopen", return_value=BytesIO(b"anomaly challenge")):
            with self.assertRaisesRegex(RuntimeError, "blocked automated search"):
                DuckDuckGoSearch().search("dessert recipe")


if __name__ == "__main__":
    unittest.main()
