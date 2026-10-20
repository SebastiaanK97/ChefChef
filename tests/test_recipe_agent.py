import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import random

from recipe_agent.tasks.clean_recipes import clean_recipe_data
from recipe_agent.tasks.fetch_recipe import fetch_recipe_url
from recipe_agent.tasks.recommend_recipe import build_taste_profile, recommend_recipe
from recipe_agent.tasks.search_recipe import (
    build_search_query,
    recommend_file,
    render_markdown,
    suggest_one_recipe,
)
from utils.web_search import DuckDuckGoSearch, SearchResult, _DuckDuckGoParser, _target_url


class FakeSearch:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        return self.results[:limit]


class CleanRecipesTests(unittest.TestCase):
    def test_keeps_only_http_recipe_urls_and_only_title_url_fields(self) -> None:
        cleaned = clean_recipe_data(
            {
                "recipes": [
                    {
                        "name": "Source recipe",
                        "url": "https://example.org/source",
                        "ingredients": ["flour"],
                        "instructions": ["Bake"],
                    },
                    {"name": "Ingredients only", "ingredients": ["flour"]},
                    {"name": "Bad URL", "url": "ftp://example.org/recipe"},
                ]
            }
        )
        self.assertEqual(
            cleaned["recipes"],
            [{"name": "Source recipe", "url": "https://example.org/source"}],
        )

    def test_derives_title_from_url_and_preserves_metadata(self) -> None:
        cleaned = clean_recipe_data(
            {
                "sourceUrl": "https://example.org",
                "recipes": [{"url": "https://example.org/lemon-tart/"}],
            }
        )
        self.assertEqual(cleaned["sourceUrl"], "https://example.org")
        self.assertEqual(cleaned["recipes"][0]["name"], "Lemon Tart")


class TasteAnalysisTests(unittest.TestCase):
    def test_profile_uses_title_and_url_only(self) -> None:
        profile = build_taste_profile(
            [
                {
                    "name": "Ragu Porco y Porcini",
                    "url": "https://example.org/italian-pasta",
                    "ingredients": ["ignored"],
                },
                {"name": "Keftedes spinach feta", "url": "https://example.org/greek"},
            ]
        )
        self.assertEqual(profile["recipeCount"], 2)
        self.assertIn("main dishes", profile["favoriteCategories"])
        self.assertIn("Italian", profile["favoriteStyles"])
        self.assertIn("savory", profile["favoriteFlavors"])
        self.assertNotIn("favoriteIngredients", profile)

    def test_recommend_recipe_returns_only_taste_analysis(self) -> None:
        result = recommend_recipe(
            {"recipes": [{"name": "Espresso Martini", "url": "https://example.org/espresso-martini"}]}
        )
        self.assertIn("tasteProfile", result)
        self.assertNotIn("recipe", result)
        self.assertEqual(result["analyzedRecipes"], [
            {"name": "Espresso Martini", "url": "https://example.org/espresso-martini"}
        ])

    def test_randomized_query_is_repeatable_with_seed(self) -> None:
        profile = build_taste_profile(
            [{"name": "Ragu Porco", "url": "https://example.org/italian-pasta"}]
        )
        self.assertEqual(
            build_search_query(profile, random.Random(7)),
            build_search_query(profile, random.Random(7)),
        )
        self.assertIn("recipe", build_search_query(profile, random.Random(7)))


class FetchRecipeTests(unittest.TestCase):
    @patch("recipe_agent.tasks.fetch_recipe.extract_jsonld_recipes")
    def test_fetches_only_the_supplied_url(self, extract: object) -> None:
        extract.return_value = {"recipes": [{"name": "Soup", "ingredients": ["water"]}]}  # type: ignore[attr-defined]
        self.assertEqual(fetch_recipe_url("https://example.org/soup"), [
            {"name": "Soup", "ingredients": ["water"]}
        ])
        extract.assert_called_once_with("https://example.org/soup")  # type: ignore[attr-defined]

    def test_rejects_non_http_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid HTTP"):
            fetch_recipe_url("file:///tmp/recipe")


class SearchRecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.collection = {
            "recipes": [
                {"name": "Forest Pie", "url": "https://example.org/forest-pie"},
                {"name": "Ragu Porco", "url": "https://example.org/ragu"},
            ]
        }

    def test_one_search_and_returns_new_complete_recipe(self) -> None:
        search = FakeSearch(
            [
                SearchResult("Forest Pie", "https://example.org/forest-pie"),
                SearchResult("Berry Tart", "https://example.org/berry-tart"),
            ]
        )
        fetched_urls: list[str] = []

        def fetcher(url: str) -> list[dict]:
            fetched_urls.append(url)
            return [
                {
                    "name": "Berry Tart",
                    "ingredients": ["berries", "flour"],
                    "instructions": ["Mix", "Bake"],
                }
            ]

        result = suggest_one_recipe(
            self.collection, search=search, fetcher=fetcher, rng=random.Random(3)
        )
        self.assertEqual(len(search.queries), 1)
        self.assertEqual(fetched_urls, ["https://example.org/berry-tart"])
        self.assertEqual(result["recipe"]["name"], "Berry Tart")
        self.assertEqual(result["recipe"]["sourceUrls"], ["https://example.org/berry-tart"])
        self.assertEqual(len(result["recipe"]["sourceUrls"]), 1)
        self.assertIn("## Ingredients", render_markdown(result))
        self.assertIn("## Instructions", render_markdown(result))
        self.assertIn("## Sources", render_markdown(result))

    def test_tries_alternatives_after_unusable_candidate_without_searching_again(self) -> None:
        search = FakeSearch(
            [
                SearchResult("No data", "https://example.org/no-data"),
                SearchResult("New soup", "https://example.org/new-soup"),
            ]
        )
        fetched = {
            "https://example.org/no-data": [],
            "https://example.org/new-soup": [
                {
                    "name": "New soup",
                    "ingredients": ["beans"],
                    "instructions": ["Simmer"],
                }
            ],
        }
        result = suggest_one_recipe(
            self.collection,
            search=search,
            fetcher=lambda url: fetched[url],
            rng=random.Random(1),
        )
        self.assertEqual(len(search.queries), 1)
        self.assertEqual(result["recipe"]["name"], "New soup")

    def test_writes_markdown_and_single_recipe_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "recipes.json"
            markdown_path = root / "nested" / "recommended_recipe.md"
            json_path = root / "data" / "recommended_recipes.json"
            input_path.write_text(json.dumps(self.collection), encoding="utf-8")
            search = FakeSearch([SearchResult("New tart", "https://example.org/new-tart")])
            fetcher = lambda _: [
                {"name": "New tart", "ingredients": ["fruit"], "instructions": ["Bake"]}
            ]

            recommend_file(
                input_path,
                markdown_path,
                json_path,
                search=search,
                fetcher=fetcher,
                rng=random.Random(2),
            )
            output = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(len(output["recipes"]), 1)
            self.assertEqual(output["recipes"][0]["url"], "https://example.org/new-tart")
            self.assertEqual(output["recipes"][0]["sourceUrls"], ["https://example.org/new-tart"])
            self.assertTrue(markdown_path.exists())
            self.assertEqual(len(search.queries), 1)

    def test_raises_when_one_search_has_no_complete_new_recipe(self) -> None:
        search = FakeSearch([SearchResult("Incomplete", "https://example.org/incomplete")])
        with self.assertRaisesRegex(RuntimeError, "single web search"):
            suggest_one_recipe(
                self.collection,
                search=search,
                fetcher=lambda _: [],
                rng=random.Random(0),
            )
        self.assertEqual(len(search.queries), 1)


class WebSearchTests(unittest.TestCase):
    def test_parses_results_and_unwraps_target_url(self) -> None:
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
