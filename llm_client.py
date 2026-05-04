"""
Multi-provider LLM router. Each model is a named entity.

Providers used:
  - Groq         (Llama 3.3 70B, Llama 3.1 8B)  — set GROQ_API_KEY
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
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ── Provider clients ──────────────────────────────────────────────────────────

_groq_key = os.environ.get("GROQ_API_KEY", "")
if not _groq_key:
    raise EnvironmentError("GROQ_API_KEY is required but not set")
_groq = Groq(api_key=_groq_key)

# ── Model registry ────────────────────────────────────────────────────────────
# Each entry is keyed by short id and describes display name, provider, and
# the model id string used by that provider's API.

MODELS = {
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
}


# ── Which models to use for each job ──────────────────────────────────────────
# Order = preference for fallback when a provider fails.
# Add/remove model keys here to control how many variants you get per job.

VARIANT_MODELS = {
    "text":     ["llama-70b"],
    "carousel": ["llama-70b"],
    "research": ["llama-70b"],
}

UTILITY_MODEL     = "llama-8b"   # for engagement scoring, classification
QUALITY_FIX_MODEL = "llama-70b"  # for banned-word cleanup
STRATEGY_MODEL    = "llama-70b"  # for weekly planning & topic ranking


# ── Provider availability ─────────────────────────────────────────────────────

def _provider_available(provider: str) -> bool:
    return True  # groq validated at import; only provider now


def _call_with_retry(
    provider: str,
    model_id: str,
    prompt: str,
    system: str,
    max_tokens: int,
    temperature: float,
    max_retries: int = 3,
) -> str:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return _dispatch(provider, model_id, prompt, system, max_tokens, temperature)
        except Exception as e:
            msg = str(e).lower()
            is_retryable = any(code in msg for code in ("429", "500", "502", "503", "rate limit", "rate_limit", "overloaded"))
            if not is_retryable or attempt == max_retries - 1:
                raise
            last_error = e
            delay = min(2 ** attempt + random.uniform(0, 1), 30)
            print(f"  [llm] {provider} transient error (attempt {attempt + 1}/{max_retries}), retry in {delay:.1f}s: {str(e)[:80]}")
            time.sleep(delay)
    raise RuntimeError(f"unreachable — last error: {last_error}")


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
    if not _provider_available(cfg["provider"]):
        raise RuntimeError(f"Provider '{cfg['provider']}' not configured — set the API key env var")
    temp = temperature if temperature is not None else cfg["temperature"]
    return _call_with_retry(
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

    Skips models whose provider API key is not configured.
    Used for utility / strategy / quality-fix calls where we only need ONE
    answer and don't care which provider produced it.
    """
    available = [k for k in model_keys if _provider_available(MODELS[k]["provider"])]
    if not available:
        raise RuntimeError("No providers available — check API key env vars")

    last_error: Exception | None = None
    for model_key in available:
        try:
            return call_model(model_key, prompt, system, max_tokens)
        except Exception as e:
            print(f"  [llm] {model_key} failed: {str(e)[:120]} — trying next")
            last_error = e
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

    model_keys = [
        k for k in VARIANT_MODELS[job]
        if _provider_available(MODELS[k]["provider"])
    ]
    if not model_keys:
        raise RuntimeError(f"No providers available for job '{job}' — check API key env vars")

    order = {k: i for i, k in enumerate(model_keys)}

    def _try_model(model_key: str) -> dict | None:
        cfg = MODELS[model_key]
        try:
            print(f"  [llm] Generating with {cfg['display']}...")
            text = call_model(model_key, prompt, system, max_tokens)
            return {"model_key": model_key, "display_name": cfg["display"], "text": text}
        except Exception as e:
            print(f"  [llm] {cfg['display']} failed: {str(e)[:120]} — skipping this variant")
            return None

    variants: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(4, len(model_keys))) as pool:
        futures = {pool.submit(_try_model, k): k for k in model_keys}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                variants.append(result)

    if not variants:
        raise RuntimeError(f"All models failed for job '{job}'")

    return sorted(variants, key=lambda v: order.get(v["model_key"], 99))


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
    else:
        raise ValueError(f"Unknown provider: {provider}")

    response = client.chat.completions.create(
        model       = model_id,
        messages    = messages,
        max_tokens  = max_tokens,
        temperature = temperature,
        timeout     = 60,
    )
    return response.choices[0].message.content.strip()


# ── Convenience: model display lookup ─────────────────────────────────────────

def display_name(model_key: str) -> str:
    return MODELS.get(model_key, {}).get("display", model_key)
