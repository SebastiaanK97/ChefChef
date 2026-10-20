"""Run independent recipe-agent tasks from the command line."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from recipe_agent.tasks.clean_recipes import clean_file
from recipe_agent.tasks.fetch_recipe import fetch_file
from recipe_agent.tasks.recommend_recipe import analyze_file
from recipe_agent.tasks.search_recipe import search_file
from recipe_agent.tasks.write_recipe import write_recipe_file
from utils.paths import (
    CLEANED_RECIPES_PATH,
    FETCHED_RECIPE_PATH,
    RECIPES_PATH,
    RECOMMENDED_RECIPE_MARKDOWN_PATH,
    RECOMMENDED_RECIPES_PATH,
    SEARCH_RESULT_PATH,
    TASTE_PROFILE_PATH,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run modular recipe assistant tasks")
    parser.add_argument(
        "task",
        choices=("clean", "fetch", "analyze-taste", "search", "write-recipe", "recommend", "all"),
        help="Task to execute",
    )
    parser.add_argument("--input", type=Path, help="Input recipe JSON")
    parser.add_argument("--url", help="Recipe URL to fetch for the fetch task")
    parser.add_argument("--cleaned-output", type=Path, default=CLEANED_RECIPES_PATH)
    parser.add_argument("--markdown-output", type=Path, default=RECOMMENDED_RECIPE_MARKDOWN_PATH)
    parser.add_argument("--recommendation-json-output", type=Path, default=RECOMMENDED_RECIPES_PATH)
    parser.add_argument("--fetched-output", type=Path, default=FETCHED_RECIPE_PATH)
    parser.add_argument("--taste-output", type=Path, default=TASTE_PROFILE_PATH)
    parser.add_argument("--search-output", type=Path, default=SEARCH_RESULT_PATH)
    parser.add_argument("--seed", type=int, help="Optional seed to reproduce randomized search query selection")
    args = parser.parse_args()

    try:
        if args.task in {"clean", "all"}:
            source_path = args.input or RECIPES_PATH
            source_count, cleaned_count = clean_file(source_path, args.cleaned_output)
            print(f"Cleaned {cleaned_count} of {source_count} recipes into {args.cleaned_output}")
        if args.task == "fetch":
            if not args.url:
                parser.error("--url is required for the fetch task")
            recipes = fetch_file(args.url, args.fetched_output)
            print(f"Fetched {len(recipes)} recipe record(s) into {args.fetched_output}")
        if args.task == "analyze-taste":
            recommendation_input = args.input or CLEANED_RECIPES_PATH
            result = analyze_file(recommendation_input, args.taste_output)
            print(f"Analyzed {result['tasteProfile']['recipeCount']} title/URL records into {args.taste_output}")
        if args.task in {"search", "recommend", "all"}:
            recommendation_input = args.cleaned_output if args.task == "all" else (args.input or CLEANED_RECIPES_PATH)
            search_result = search_file(
                recommendation_input,
                args.search_output,
                rng=random.Random(args.seed) if args.seed is not None else None,
            )
            print(f"Searched for {search_result['searchQuery']}; result saved to {args.search_output}")
        if args.task == "write-recipe":
            search_input = args.input or SEARCH_RESULT_PATH
            written = write_recipe_file(
                search_input,
                args.markdown_output,
                args.recommendation_json_output,
            )
            print(f"Wrote simple recipe {written['recipe']['name']} to {args.markdown_output}")
        if args.task in {"recommend", "all"}:
            written = write_recipe_file(
                args.search_output,
                args.markdown_output,
                args.recommendation_json_output,
            )
            print(
                f"Generated {written['recipe']['name']} "
                f"with {len(written['recipe']['sourceUrls'])} source(s); "
                f"saved to {args.markdown_output} and {args.recommendation_json_output}"
            )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
