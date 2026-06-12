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
  filter_hard_duplicates(topics, all_titles, recent, similarity_threshold, hard_window_days) -> list[dict]
  is_duplicate_post(post_text, recent_post_texts, similarity_threshold) -> tuple[bool, float]
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


def filter_hard_duplicates(
    topics: list[dict],
    all_titles: set[str],
    recent: list[dict],
    similarity_threshold: float = 0.80,
    hard_window_days: int = 30,
) -> list[dict]:
    """Hard-exclude topics that have already been posted — never let the LLM
    even see them, so a repeat is structurally impossible (not just penalized).

    Two checks, applied to a NEW list (does not mutate `topics`):
    1. Exact title match (normalized) against `all_titles` (all-time, from
       topic_log.get_all_titles()) — excluded regardless of age.
    2. Semantic similarity >= `similarity_threshold` against any topic posted
       within `hard_window_days` (from `recent`, e.g.
       topic_log.get_recent_topic_texts()) — catches "same story, reworded
       headline" within the window.
    """
    if not topics:
        return topics

    kept = [t for t in topics if t["title"].strip().lower() not in all_titles]
    removed_exact = len(topics) - len(kept)

    recent_window = [r for r in recent if r["days_ago"] <= hard_window_days]
    if not recent_window or not kept:
        if removed_exact:
            log.info(f"Hard-filtered {removed_exact} exact-repeat topic(s) of past posts")
        return kept

    try:
        model = _model()
    except Exception as e:
        log.warning(f"Hard dedup filter (semantic) skipped: {e}")
        if removed_exact:
            log.info(f"Hard-filtered {removed_exact} exact-repeat topic(s) of past posts")
        return kept

    try:
        cand_texts = [f"{t['title']} — {t.get('description', '')}" for t in kept]
        recent_texts = [r["text"] for r in recent_window]
        cand_emb = model.encode(cand_texts, normalize_embeddings=True)
        recent_emb = model.encode(recent_texts, normalize_embeddings=True)
        sims = cand_emb @ recent_emb.T
        worst = sims.max(axis=1)
    except Exception as e:
        log.warning(f"Hard dedup filter (semantic) skipped: {e}")
        if removed_exact:
            log.info(f"Hard-filtered {removed_exact} exact-repeat topic(s) of past posts")
        return kept

    final = [t for t, w in zip(kept, worst) if w < similarity_threshold]
    removed_semantic = len(kept) - len(final)
    if removed_exact or removed_semantic:
        log.info(
            f"Hard-filtered {removed_exact} exact-repeat + {removed_semantic} "
            f"near-duplicate topic(s) of posts within {hard_window_days}d"
        )
    return final


def is_duplicate_post(
    post_text: str,
    recent_post_texts: list[str],
    similarity_threshold: float = 0.85,
) -> tuple[bool, float]:
    """Check a freshly-generated post body against the full text of posts
    published in the last N days (e.g. topic_log.get_recent_post_texts(days=7)).

    Catches wording/structure repeats that slip through topic-level dedup —
    e.g. the same hook + CTA reused on a different topic. Returns
    (is_duplicate, best_similarity). Fails open (False, 0.0) if the model or
    embeddings are unavailable.
    """
    if not post_text or not recent_post_texts:
        return False, 0.0

    try:
        model = _model()
        cand_emb = model.encode([post_text], normalize_embeddings=True)
        recent_emb = model.encode(recent_post_texts, normalize_embeddings=True)
        sims = cand_emb @ recent_emb.T
        best = float(sims.max())
    except Exception as e:
        log.warning(f"Post-content dedup check skipped: {e}")
        return False, 0.0

    is_dup = best >= similarity_threshold
    if is_dup:
        log.info(f"Post flagged as near-duplicate of a post from the last week (similarity={best:.2f})")
    return is_dup, best
