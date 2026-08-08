"""Thin wrapper over the OpenRouter client already used by main.py.

Every call is temperature 0 and cached on disk, so re-running the same fixtures
gives the same answers and costs nothing after the first run.
"""

import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

MODEL_CLASSIFY = os.getenv("MODEL_CLASSIFY", "openai/gpt-4o-mini")
MODEL_EXTRACT = os.getenv("MODEL_EXTRACT", "openai/gpt-4o-mini")

CACHE_PATH = Path("runs/llm_cache.json")
_cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}


def _complete(model: str, system_prompt: str, user_content: str, json_mode: bool) -> str:
    """One completion, cached. Same inputs always give the same string back."""
    key = hashlib.sha256(
        f"{model}|{json_mode}|{system_prompt}|{user_content}".encode()
    ).hexdigest()
    if key in _cache:
        return _cache[key]

    json_option = {"response_format": {"type": "json_object"}} if json_mode else {}
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
        **json_option,
    )
    answer = completion.choices[0].message.content

    _cache[key] = answer
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(_cache, indent=2))
    return answer


def ask_text(model: str, system_prompt: str, user_content: str) -> str:
    """One completion, plain text back."""
    return _complete(model, system_prompt, user_content, json_mode=False)


def ask_json(model: str, system_prompt: str, user_content: str) -> dict:
    """One completion, parsed JSON back."""
    return json.loads(_complete(model, system_prompt, user_content, json_mode=True))
