"""Load the locally stored OpenAI API key."""

from pathlib import Path


def load_local_api_key() -> str:
    key_file = Path(__file__).resolve().parents[1] / "keys.py"
    if not key_file.is_file():
        raise RuntimeError(
            f"OpenAI API key not found. Set OPENAI_API_KEY or add it to {key_file}."
        )
    for line in key_file.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() == "OPENAI_API_KEY":
            key = value.strip().strip("\"'")
            if key:
                return key
    raise RuntimeError(
        f"OPENAI_API_KEY is missing or empty. Set it in the environment or add it to {key_file}."
    )
