"""Repository paths shared by recipe tasks and command-line entry points."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

RECIPES_PATH = DATA_DIR / "recipes.json"
CLEANED_RECIPES_PATH = DATA_DIR / "cleaned_recipes.json"
RECOMMENDED_RECIPES_PATH = DATA_DIR / "recommended_recipes.json"
RECOMMENDED_RECIPE_MARKDOWN_PATH = PROJECT_ROOT / "recommended_recipe.md"
FETCHED_RECIPE_PATH = DATA_DIR / "fetched_recipe.json"
TASTE_PROFILE_PATH = DATA_DIR / "taste_profile.json"
