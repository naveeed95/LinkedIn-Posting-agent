"""
Semantic-similarity dedup penalty for topic selection.

Catches "same underlying story, different headline" — e.g. six straight days
of Anthropic-valuation posts that each scored highest individually but were
the same story reworded. Title-string / LLM-judgment dedup misses this; cosine
similarity on sentence embeddings does not.

Uses a local MiniLM model (sentence-transformers/all-MiniLM-L6-v2) — no API
calls, no extra provider, fully free. Model weights cache to ./.st_cache so
nothing touches the system/user profile directories.

Exports:
  apply_dedup_penalty(topics, recent, max_penalty, window_days) -> None  (mutates topics in place)
"""

import os
from pathlib import Path

from logger import get_logger

log = get_logger("similarity")

_CACHE_DIR = Path(__file__).parent / ".st_cache"
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(_CACHE_DIR))
os.environ.setdefault("HF_HOME", str(_CACHE_DIR))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import logging as _logging  # noqa: E402

for _noisy in ("httpx", "huggingface_hub", "sentence_transformers", "transformers"):
    _logging.getLogger(_noisy).setLevel(_logging.WARNING)

_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer("all-MiniLM-L6-v2", cache_folder=str(_CACHE_DIR))
    return _MODEL


def apply_dedup_penalty(
    topics: list[dict],
    recent: list[dict],
    max_penalty: float = 60.0,
    window_days: int = 10,
) -> None:
    """Subtract a decaying semantic-similarity penalty from each topic's `_score`.

    `recent` = [{"text": "<title> — <angle>", "days_ago": float}, ...] from
    analytics_tracker.get_recent_topic_texts(). Penalty for a candidate is
    `-max_penalty * best_similarity * decay`, where `decay` falls linearly
    from 1.0 (posted today) to 0.0 (posted `window_days` ago) — so a
    dominant story can resurface after the cooldown window instead of being
    permanently blacklisted.
    """
    if not recent or not topics:
        return
    try:
        import numpy as np
    except ImportError:
        log.error("numpy not installed — dedup similarity penalty permanently disabled. Run: pip install -r requirements.txt")
        return

    try:
        model = _model()
    except ImportError:
        log.error("sentence-transformers not installed — dedup similarity penalty permanently disabled. Run: pip install -r requirements.txt")
        return
    except Exception as e:
        log.warning(f"Dedup similarity check skipped (model load failed): {e}")
        return

    try:
        cand_texts = [f"{t['title']} — {t.get('description', '')}" for t in topics]
        recent_texts = [r["text"] for r in recent]
        cand_emb = model.encode(cand_texts, normalize_embeddings=True)
        recent_emb = model.encode(recent_texts, normalize_embeddings=True)
    except Exception as e:
        log.warning(f"Dedup similarity check skipped (embedding failed): {e}")
        return

    decays = np.array([max(0.0, 1 - r["days_ago"] / window_days) for r in recent])
    sims = cand_emb @ recent_emb.T          # [n_candidates, n_recent] cosine similarity
    weighted = sims * decays                 # decay each recent topic's pull over time
    worst = weighted.max(axis=1)

    flagged = 0
    for t, w in zip(topics, worst):
        if w > 0:
            penalty = -max_penalty * float(w)
            t["_score"] = t.get("_score", 0) + penalty
            t["_dedup_penalty"] = round(penalty, 1)
            if w > 0.6:
                flagged += 1

    if flagged:
        log.info(f"Dedup penalty flagged {flagged} near-duplicate topic(s) of recent posts")
