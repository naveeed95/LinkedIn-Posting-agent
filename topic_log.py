"""Permanent, git-tracked log of posted topics — the source of truth for
topic-dedup.

`performance.db` (and `cache/*.json`) live in CI cache/artifacts and can be
reset or evicted between runs. `data/posted_topics.json` is committed back to
the repo by the daily_post workflow after every successful publish, so it
survives cache eviction, artifact expiry, and DB resets.

Exports:
  record_posted_topic(title, topic_text, source_url, post_text) -> None
  was_posted_today() -> bool
  get_recent_titles(days)      -> list[str]
  get_recent_topic_texts(days) -> list[dict]  ({"text", "days_ago"})
  get_all_titles()              -> set[str]   (normalized, all-time)
  get_recent_post_texts(days)   -> list[str]  (full published post bodies)
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from logger import get_logger

log = get_logger("topic_log")

_PATH = Path(__file__).parent / "data" / "posted_topics.json"


def _load() -> list[dict]:
    if not _PATH.exists():
        return []
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Could not read {_PATH}: {e}")
        return []


def record_posted_topic(title: str, topic_text: str, source_url: str = "", post_text: str = "") -> None:
    if not title:
        return
    entries = _load()
    entries.append({
        "title": title,
        "topic_text": topic_text or title,
        "source_url": source_url,
        "post_text": post_text,
        "posted_at": datetime.now().isoformat(),
    })
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    log.info(f"Recorded posted topic: {title!r}")


def was_posted_today() -> bool:
    today = datetime.now().date()
    for e in _load():
        try:
            if datetime.fromisoformat(e["posted_at"]).date() == today:
                return True
        except (KeyError, ValueError):
            continue
    return False


def get_recent_titles(days: int = 30) -> list[str]:
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    for e in _load():
        try:
            if datetime.fromisoformat(e["posted_at"]) >= cutoff:
                out.append(e["title"])
        except (KeyError, ValueError):
            continue
    return out


def get_recent_topic_texts(days: int = 30) -> list[dict]:
    """Recent posted topics as {"text": title+angle, "days_ago": float} —
    same shape as analytics_tracker.get_recent_topic_texts(), for
    topic_similarity.apply_dedup_penalty / filter_hard_duplicates."""
    cutoff = datetime.now() - timedelta(days=days)
    now = datetime.now()
    out = []
    for e in _load():
        try:
            posted = datetime.fromisoformat(e["posted_at"])
        except (KeyError, ValueError):
            continue
        if posted < cutoff:
            continue
        text = e.get("topic_text") or e.get("title")
        if not text:
            continue
        days_ago = max(0.0, (now - posted).total_seconds() / 86400)
        out.append({"text": text, "days_ago": days_ago})
    return out


def get_all_titles() -> set[str]:
    """All-time set of normalized (lowercased, stripped) posted titles —
    used to hard-exclude exact-repeat topics regardless of age."""
    return {e["title"].strip().lower() for e in _load() if e.get("title")}


def get_recent_post_texts(days: int = 7) -> list[str]:
    """Full text of posts published in the last `days` days — used to check
    a freshly-generated post for content-level duplication (same wording/
    structure), independent of the topic-level dedup checks above."""
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    for e in _load():
        try:
            if datetime.fromisoformat(e["posted_at"]) < cutoff:
                continue
        except (KeyError, ValueError):
            continue
        text = e.get("post_text")
        if text:
            out.append(text)
    return out
