"""Run independent recipe-agent tasks from the command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils.paths import (
    CLEANED_RECIPES_PATH,
    RECIPES_PATH,
    RECOMMENDED_RECIPE_MARKDOWN_PATH,
    RECOMMENDED_RECIPES_PATH,
)
from recipe_agent.tasks.clean_recipes import clean_file
from recipe_agent.tasks.recommend_recipe import recommend_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Run modular recipe assistant tasks")
    parser.add_argument("task", choices=("clean", "recommend", "all"), help="Task to execute")
    parser.add_argument("--input", type=Path, help="Input recipe JSON")
    parser.add_argument("--cleaned-output", type=Path, default=CLEANED_RECIPES_PATH)
    parser.add_argument("--markdown-output", type=Path, default=RECOMMENDED_RECIPE_MARKDOWN_PATH)
    parser.add_argument("--recommendation-json-output", type=Path, default=RECOMMENDED_RECIPES_PATH)
    args = parser.parse_args()

    try:
        if args.task in {"clean", "all"}:
            source_path = args.input or RECIPES_PATH
            source_count, cleaned_count = clean_file(source_path, args.cleaned_output)
            print(f"Cleaned {cleaned_count} of {source_count} recipes into {args.cleaned_output}")
        if args.task in {"recommend", "all"}:
            recommendation_input = args.cleaned_output if args.task == "all" else (args.input or CLEANED_RECIPES_PATH)
            result = recommend_file(
                recommendation_input,
                args.markdown_output,
                args.recommendation_json_output,
            )
            print(
                f"Generated {result['recipe']['name']} "
                f"with {len(result['recipe']['sourceUrls'])} source(s); "
                f"saved to {args.markdown_output} and {args.recommendation_json_output}"
            )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
