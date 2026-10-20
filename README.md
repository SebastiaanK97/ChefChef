# Recipe assistant

The assistant is organized as independent tasks so URL extraction, taste
analysis, cleaning, and web discovery can be reused and extended separately.
Recipe discovery makes one DuckDuckGo web search and does not need an API key.

## Tasks

### Clean the recipe collection

Keep recipes that have an HTTP(S) URL. The cleaned records contain only a
display title and URL; ingredients and instructions are fetched from the page
when needed.

```bash
python -m recipe_agent clean
```

### Fetch a recipe URL

Extract Schema.org recipe data from one supplied URL without analyzing taste or
performing a web search:

```bash
python -m recipe_agent fetch --url "https://example.org/recipe"
```

### Analyze taste

Infer broad categories, styles, and flavor preferences using recipe titles and
URLs only:

```bash
python -m recipe_agent analyze-taste
```

### Recommend one new recipe

Analyze the cleaned collection, construct a randomized query from the taste
signals, perform exactly one web search, then try its candidate pages until one
new recipe with ingredients and instructions is found. Existing collection
entries are excluded by URL and approximate title match. The task writes a
one-entry `data/recommended_recipes.json` and `recommended_recipe.md`; both
outputs cite the source URL.

```bash
python -m recipe_agent recommend
```

Pass `--seed <integer>` to reproduce randomized query selection.

### Run the workflow

Clean the original collection and then recommend from the cleaned title/URL
records:

```bash
python -m recipe_agent all
```

Recipe data lives in `data/`. Defaults are `data/recipes.json` for cleaning,
`data/cleaned_recipes.json` for taste analysis and recommendation,
`data/fetched_recipe.json` for standalone URL fetching,
`data/taste_profile.json` for taste analysis,
`recommended_recipe.md`, and `data/recommended_recipes.json`. Use `--input`,
`--cleaned-output`, `--fetched-output`, `--taste-output`, `--markdown-output`,
and `--recommendation-json-output` to override paths.

Extract a public Notion database or a Schema.org recipe page into
`data/recipes.json`:

```bash
python -m utils.extract_recipes "PUBLIC_URL"
```

The extractor accepts `-o`/`--output` to select another output path.

## Extending the agent

- Add an independent task under `recipe_agent/tasks/` and expose it through
  `recipe_agent/__main__.py`.
- `recipe_agent/tasks/recommend_recipe.py` owns title/URL taste analysis.
- `recipe_agent/tasks/fetch_recipe.py` owns extraction from a supplied URL.
- `recipe_agent/tasks/search_recipe.py` owns the single-search recommendation
  workflow and output formatting.
- Replace `RecipeSearchProvider` in `utils/web_search.py` to plug in another
  search service.
