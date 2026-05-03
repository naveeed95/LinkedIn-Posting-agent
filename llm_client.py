"""
Multi-provider LLM router. Each model is a named entity.

Free-tier providers used:
  - Groq         (Llama 3.3 70B, Llama 3.1 8B)             — already in your stack
  - OpenRouter   (DeepSeek V3, Qwen 2.5 72B, Hermes 3 405B) — set OPENROUTER_API_KEY
  - Cerebras     (Llama 3.3 70B)                            — set CEREBRAS_API_KEY (optional fallback)

Public API:
  call_model(model_key, prompt, system, max_tokens) -> str
      Run a single named model.

  generate_variants(job, prompt, system, max_tokens) -> list[dict]
      Run every model enabled for `job` and return one variant per successful model.
      Each variant is {"model_key", "display_name", "text"}.
      Failed models are skipped (with a printed warning) so the caller still gets
      whatever variants succeeded.

Editing models:
  - Add/remove a model: edit the MODELS dict.
  - Enable/disable a model for a job: edit VARIANT_MODELS.
  - Change utility model: edit UTILITY_MODEL / QUALITY_FIX_MODEL / STRATEGY_MODEL.
"""

import os
import time

from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ── Provider clients ──────────────────────────────────────────────────────────

_groq = Groq(api_key=os.environ["GROQ_API_KEY"])

_openrouter = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY", ""),
)

_cerebras = OpenAI(
    base_url="https://api.cerebras.ai/v1",
    api_key=os.environ.get("CEREBRAS_API_KEY", ""),
)


# ── Model registry ────────────────────────────────────────────────────────────
# Each entry is keyed by short id and describes display name, provider, and
# the model id string used by that provider's API.

MODELS = {
    "deepseek": {
        "display":     "DeepSeek V3",
        "provider":    "openrouter",
        "model_id":    "deepseek/deepseek-chat-v3:free",
        "temperature": 0.85,
    },
    "qwen": {
        "display":     "Qwen 2.5 72B",
        "provider":    "openrouter",
        "model_id":    "qwen/qwen-2.5-72b-instruct:free",
        "temperature": 0.9,
    },
    "hermes": {
        "display":     "Hermes 3 405B",
        "provider":    "openrouter",
        "model_id":    "nousresearch/hermes-3-llama-3.1-405b:free",
        "temperature": 0.95,
    },
    "llama-70b": {
        "display":     "Llama 3.3 70B",
        "provider":    "groq",
        "model_id":    "llama-3.3-70b-versatile",
        "temperature": 0.8,
    },
    "llama-8b": {
        "display":     "Llama 3.1 8B",
        "provider":    "groq",
        "model_id":    "llama-3.1-8b-instant",
        "temperature": 0.3,
    },
    "cerebras-llama": {
        "display":     "Cerebras Llama 3.3",
        "provider":    "cerebras",
        "model_id":    "llama-3.3-70b",
        "temperature": 0.85,
    },
}


# ── Which models to use for each job ──────────────────────────────────────────
# Order = preference for fallback when a provider fails.
# Add/remove model keys here to control how many variants you get per job.

VARIANT_MODELS = {
    "text":     ["deepseek", "qwen", "hermes", "llama-70b"],
    "carousel": ["deepseek", "qwen", "llama-70b"],
    "research": ["deepseek", "llama-70b"],
}

UTILITY_MODEL     = "llama-8b"   # for engagement scoring, classification
QUALITY_FIX_MODEL = "llama-70b"  # for banned-word cleanup
STRATEGY_MODEL    = "deepseek"   # for weekly planning & topic ranking


# ── Public API ────────────────────────────────────────────────────────────────

def call_model(
    model_key: str,
    prompt: str,
    system: str = "",
    max_tokens: int = 2500,
    temperature: float | None = None,
) -> str:
    """Call a single model by its registry key. Returns the text output.

    Raises if the model fails — caller decides how to handle.
    """
    if model_key not in MODELS:
        raise ValueError(
            f"Unknown model: {model_key}. Available: {list(MODELS.keys())}"
        )

    cfg = MODELS[model_key]
    temp = temperature if temperature is not None else cfg["temperature"]
    return _dispatch(
        provider    = cfg["provider"],
        model_id    = cfg["model_id"],
        prompt      = prompt,
        system      = system,
        max_tokens  = max_tokens,
        temperature = temp,
    )


def call_with_fallback(
    model_keys: list[str],
    prompt: str,
    system: str = "",
    max_tokens: int = 2500,
) -> str:
    """Try each model in order. Return the first one that succeeds.

    Used for utility / strategy / quality-fix calls where we only need ONE
    answer and don't care which provider produced it.
    """
    last_error: Exception | None = None
    for model_key in model_keys:
        try:
            return call_model(model_key, prompt, system, max_tokens)
        except Exception as e:
            print(f"  [llm] {model_key} failed: {str(e)[:120]} — trying next")
            last_error = e
            time.sleep(1)
    raise RuntimeError(f"All fallback models exhausted. Last error: {last_error}")


def generate_variants(
    job: str,
    prompt: str,
    system: str = "",
    max_tokens: int = 2500,
) -> list[dict]:
    """Generate one variant per model enabled for `job`.

    Returns a list of {"model_key", "display_name", "text"} — one entry per
    model that succeeded. If a model fails, it's skipped with a warning so the
    caller still gets the variants from the rest.
    """
    if job not in VARIANT_MODELS:
        raise ValueError(
            f"Unknown job: {job}. Use one of: {list(VARIANT_MODELS.keys())}"
        )

    variants: list[dict] = []
    for model_key in VARIANT_MODELS[job]:
        cfg = MODELS[model_key]
        try:
            print(f"  [llm] Generating with {cfg['display']}...")
            text = call_model(model_key, prompt, system, max_tokens)
            variants.append({
                "model_key":    model_key,
                "display_name": cfg["display"],
                "text":         text,
            })
        except Exception as e:
            print(f"  [llm] {cfg['display']} failed: {str(e)[:120]} — skipping this variant")
            continue

    if not variants:
        raise RuntimeError(f"All models failed for job '{job}'")

    return variants


# ── Provider dispatch ─────────────────────────────────────────────────────────

def _dispatch(
    provider: str,
    model_id: str,
    prompt: str,
    system: str,
    max_tokens: int,
    temperature: float,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if provider == "groq":
        client = _groq
    elif provider == "openrouter":
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY not set in environment")
        client = _openrouter
    elif provider == "cerebras":
        if not os.environ.get("CEREBRAS_API_KEY"):
            raise RuntimeError("CEREBRAS_API_KEY not set in environment")
        client = _cerebras
    else:
        raise ValueError(f"Unknown provider: {provider}")

    response = client.chat.completions.create(
        model       = model_id,
        messages    = messages,
        max_tokens  = max_tokens,
        temperature = temperature,
    )
    return response.choices[0].message.content.strip()


# ── Convenience: model display lookup ─────────────────────────────────────────

def display_name(model_key: str) -> str:
    return MODELS.get(model_key, {}).get("display", model_key)
