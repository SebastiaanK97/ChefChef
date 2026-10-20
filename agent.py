import os

from smolagents import CodeAgent, LiteLLMModel

def build_agent() -> CodeAgent:
    model = LiteLLMModel(
        model_id=f"ollama_chat/{os.environ.get('OLLAMA_MODEL', 'llama3.2')}", # nemotron-3.5-bolt | llama3.2
        api_base="http://localhost:11434",
        instructions="You are a recommendation system that recommends recipes. You only output the name of the recipe, nothing else.",
    )
    return CodeAgent(tools=[], model=model)


def main() -> None:
    agent = build_agent()
    result = agent.run("Recommend a recipe.")
    print(result)


if __name__ == "__main__":
    main()