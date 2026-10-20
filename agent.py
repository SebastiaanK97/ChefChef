import os

from smolagents import CodeAgent, LiteLLMModel, WebSearchTool

def build_agent() -> CodeAgent:
    model = LiteLLMModel(
        model_id=f"ollama_chat/{os.environ.get('OLLAMA_MODEL', 'llama3.2')}", # nemotron-3.5-bolt | llama3.2
        api_base="http://localhost:11434",
    )
    return CodeAgent(
        tools=[WebSearchTool(max_results=5)],
        model=model,
        instructions=(
            "You are a recipe recommendation assistant. Use the web_search tool to find "
            "a suitable recipe, respect all stated dietary restrictions and allergies, "
            "and output only the recipe name."
        ),
    )


def main() -> None:
    agent = build_agent()
    user_mood_restrictions: list[str] = ["tired and needs a quick meal", "tomato"]
    taste_profile_restrictions: list[str] = ["mediterranean", "spicy"]
    search_query = "recipe ideas"
    if user_mood_restrictions:
        search_query += f" using {', '.join(user_mood_restrictions)}"
    if taste_profile_restrictions:
        search_query += f" {' '.join(taste_profile_restrictions)}"
    task = (
        f"Search the web for a recipe using this search query: {search_query}. "
        f"The today mood and likings of the user is: {', '.join(user_mood_restrictions) or 'none specified'}. "
        f"The general taste profile of the user is: {', '.join(taste_profile_restrictions) or 'none specified'}. "
        "Only output the recipe name."
    )
    result = agent.run(task)
    print(result)


if __name__ == "__main__":
    main()