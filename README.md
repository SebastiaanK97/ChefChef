# Recipe assistant

The assistant exposes independent tasks so new recipe workflows can be added
without coupling them to cleaning or recommendation logic. Recipe search uses
public DuckDuckGo results and does not need a search API key.

## Run tasks

Recipe JSON data lives in `data/`. Clean `data/recipes.json` into
`data/cleaned_recipes.json`. A recipe is kept when it has a valid HTTP(S) URL,
at least one ingredient, or at least one instruction:

```bash
python -m recipe_agent clean
```

Search the web for a new recipe matching the cleaned collection's categories
and ingredients, fetch its structured recipe data, and write a Markdown recipe
and one-entry `data/recommended_recipes.json`. Existing recipe names and URLs
are excluded:

```bash
python -m recipe_agent recommend
```

Run both tasks in sequence:

```bash
python -m recipe_agent all
```

Defaults are `data/recipes.json` for cleaning, `data/cleaned_recipes.json` for
recommendation input, `recommended_recipe.md`, and
`data/recommended_recipes.json`. Override them with `--input`,
`--cleaned-output`, `--markdown-output`, and `--recommendation-json-output`.

Extract recipes from a public Notion database or Schema.org recipe page into
`data/recipes.json`:

```bash
python -m utils.extract_recipes "PUBLIC_URL"
```

The extractor accepts `-o`/`--output` to select a different output path.

## Extending the agent

- Add a task in `recipe_agent/tasks/` and wire its command in
  `recipe_agent/__main__.py`.
- Replace `RecipeSearchProvider` in `utils/web_search.py` to plug in a
  different search service.
- Recommendation selection and output formatting are isolated in
  `recipe_agent/tasks/recommend_recipe.py` and can later be replaced or
  enhanced with a model-backed implementation.

Recommendation ranks new fetched candidates based on the available recipe
categories, tags, ingredients, and names. The generated recipe must include
ingredients and instructions and cites its source URL (up to three sources).
It does not claim to represent explicit likes or ratings, which are not
present in the current data.
