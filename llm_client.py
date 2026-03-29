"""llm_client.py — Provider registry, client construction, unified LLM call."""

import json
import logging
import re


def extract_json_string(text: str) -> str:
    """Extracts the JSON block from text and returns it as a string."""
    try:
        # Regex to find the first '{' and last '}'
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        return match.group(1) if match else text
    except Exception:
        return text


def call_llm(prompt: str, system: str = "", json_mode: bool = False) -> str:
    # ... (Your existing API setup code here) ...

    # Update the return lines at the bottom of the function:
    if is_anthropic:
        # ...
        return extract_json_string(resp.content[0].text)
    else:
        # ...
        return extract_json_string(resp.choices[0].message.content)


# ── Token budgets ────────────────────────────────────────────────────────────
MAX_TOKENS_CHAT = 160
MAX_TOKENS_CLASSIFIER = 180
MAX_TOKENS_SYSTEM = 180

# ── Provider registry — sdk + base_url only ──────────────────────────────────
PROVIDERS = {
    "anthropic": {"name": "Anthropic (Claude)", "base_url": None, "sdk": "anthropic"},
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "sdk": "openai",
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "sdk": "openai",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "sdk": "openai",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "sdk": "openai",
    },
    "ollama": {
        "name": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "sdk": "openai",
    },
}

OLLAMA_URL = "https://ollama.com"

# ── Single source of truth for model names ───────────────────────────────────
MODEL_MAP = {
    "anthropic": {
        "chat": "claude-sonnet-4-20250514",
        "fast": "claude-haiku-4-5-20251001",
    },
    "deepseek": {"chat": "deepseek-chat", "fast": "deepseek-chat"},
    "groq": {"chat": "llama-3.3-70b-versatile", "fast": "llama-3.1-8b-instant"},
    "openai": {"chat": "gpt-4o", "fast": "gpt-4o-mini"},
    "openrouter": {
        "chat": "meta-llama/llama-3.3-70b-instruct",
        "fast": "meta-llama/llama-3.1-8b-instruct",
    },
    "ollama": {"chat": "llama3.2", "fast": "llama3.2"},
}

_current_provider: str = "groq"
_model_override: str = ""


def detect_provider(key: str) -> str:
    k = (key or "").strip()
    if not k or k.lower() in ("ollama", "local", "localhost"):
        return "ollama"
    if k.startswith("ds:"):
        return "deepseek"
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("sk-or-"):
        return "openrouter"
    if k.startswith("sk-"):
        return "openai"
    return "groq"


def build_client(provider: str, key: str):
    p = PROVIDERS[provider]

    clean_key = key
    if clean_key and clean_key.startswith("ds:"):
        clean_key = clean_key[3:]

    if p["sdk"] == "anthropic":
        import anthropic as _ant

        if not clean_key:
            raise ValueError(f"API key required for {p['name']} provider")
        return _ant.Anthropic(api_key=clean_key, timeout=30.0)
    else:
        import openai as _oai

        if not clean_key and provider != "ollama":
            raise ValueError(f"API key required for {p['name']} provider")
        return _oai.OpenAI(
            api_key=clean_key or "", base_url=p["base_url"], timeout=30.0
        )


def call_llm(
    client,
    provider: str,
    model_type: str,
    messages: list,
    max_tokens: int = MAX_TOKENS_CHAT,
    json_mode: bool = False,
) -> str:
    p = PROVIDERS[provider]

    if _model_override and model_type == "chat":
        model = _model_override
    else:
        model = MODEL_MAP.get(provider, {}).get(model_type, "gpt-4o")

    if p["sdk"] == "anthropic":
        sys_msgs = [m["content"] for m in messages if m["role"] == "system"]
        user_msgs = [m for m in messages if m["role"] != "system"]
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=sys_msgs[0] if sys_msgs else "",
            messages=user_msgs,
        )
        return extract_json_string(resp.content[0].text)
    else:
        kwargs: dict = dict(model=model, max_tokens=max_tokens, messages=messages)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        return extract_json_string(resp.choices[0].message.content)
