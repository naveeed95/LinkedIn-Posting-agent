"""
Smoke test for the multi-provider LLM router.
Run this AFTER you've added OPENROUTER_API_KEY (and optionally CEREBRAS_API_KEY)
to your .env, to verify each provider actually responds.

Usage:
    python test_llm.py

For each model in llm_client.MODELS this will:
  1. Send a tiny prompt
  2. Print the response (or the error)

Run on a Sunday evening — won't touch LinkedIn or Discord.
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from llm_client import MODELS, call_model

PROMPT = "Reply with exactly 5 words about why small businesses need AI."


def main():
    print(f"Testing {len(MODELS)} models...\n")

    successes = 0
    failures  = 0

    for key, cfg in MODELS.items():
        print(f"  → {cfg['display']:25s} ({cfg['provider']}) ... ", end="", flush=True)
        try:
            text = call_model(key, PROMPT, max_tokens=50)
            preview = text.replace("\n", " ")[:80]
            print(f"OK\n      {preview}\n")
            successes += 1
        except Exception as e:
            print(f"FAIL\n      {str(e)[:200]}\n")
            failures += 1

    print(f"\n{'='*60}")
    print(f"  {successes} passed   {failures} failed")
    print(f"{'='*60}\n")

    if failures > 0:
        print("Tips:")
        print("  - 'OPENROUTER_API_KEY not set' → add it to .env")
        print("  - 'model not found' → check the model_id in llm_client.MODELS")
        print("    (OpenRouter occasionally renames :free models; check openrouter.ai/models)")
        print("  - 'rate limit' → wait a minute and retry")
        print("  - 'CEREBRAS_API_KEY not set' is OK if you didn't sign up for Cerebras")


if __name__ == "__main__":
    main()
