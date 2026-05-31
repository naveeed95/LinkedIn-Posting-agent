"""
Fetches latest LinkedIn algorithm rules dynamically via Tavily search.
Caches to cache/linkedin_rules.json for 24 hours.

Exports:
  fetch_rules()             -> dict with rules_text + sources
  build_rules_prompt(data)  -> str to inject into LLM system prompt
"""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from logger import get_logger

load_dotenv()

log = get_logger("rules")

CACHE_FILE = Path(__file__).parent / "cache" / "linkedin_rules.json"
CACHE_TTL_HOURS = 24

_QUERIES = [
    "LinkedIn algorithm rules best practices 2026",
    "LinkedIn post reach engagement tips 2026",
    "LinkedIn algorithm changes latest update 2026",
    "LinkedIn hashtag character limit content format 2026",
    "LinkedIn creator engagement strategy 2026",
]


def _fetch_query(query: str) -> list[dict]:
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY", ""))
        results = client.search(query, max_results=3, search_depth="advanced")
        return results.get("results", [])
    except Exception as e:
        log.warning(f"Tavily query failed ({query[:50]}): {e}")
        return []


def _load_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if datetime.now() - fetched_at < timedelta(hours=CACHE_TTL_HOURS):
            return data
    except Exception as e:
        log.warning(f"Cache load failed ({type(e).__name__}: {e}) — will re-fetch")
    return None


def _save_cache(rules_text: str, sources: list[dict]) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "rules_text": rules_text,
        "sources": sources,
    }
    fd, tmp_path = tempfile.mkstemp(
        prefix=CACHE_FILE.name + ".",
        suffix=".tmp",
        dir=str(CACHE_FILE.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CACHE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def fetch_rules() -> dict:
    cached = _load_cache()
    if cached:
        log.info("Using cached LinkedIn rules (< 24h old).")
        return cached

    if not os.environ.get("TAVILY_API_KEY"):
        log.info("TAVILY_API_KEY not set — skipping rules fetch.")
        return {}

    log.info("Fetching latest LinkedIn algorithm rules via Tavily...")
    all_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_fetch_query, q): q for q in _QUERIES}
        for fut in as_completed(futures):
            all_results.extend(fut.result())

    seen: set[str] = set()
    unique: list[dict] = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen:
            unique.append(r)
            seen.add(url)

    sources = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", "")[:500],
        }
        for r in unique[:12]
    ]
    rules_text = "\n\n".join(
        f"[{r.get('title', '')}]\n{r.get('content', '')[:400]}"
        for r in unique[:10]
    )

    _save_cache(rules_text, sources)
    log.info(f"Fetched {len(unique)} LinkedIn algorithm sources. Cached 24h.")

    return {
        "fetched_at": datetime.now().isoformat(),
        "rules_text": rules_text,
        "sources": sources,
    }


def build_rules_prompt(data: dict, max_chars: int = 2000) -> str:
    rules_text = data.get("rules_text", "")
    sources = data.get("sources", [])
    if not rules_text:
        return ""

    source_titles = ", ".join(s["title"] for s in sources[:5] if s.get("title"))
    lines = [
        "── CURRENT LINKEDIN ALGORITHM RULES (fetched today) ──────────",
        rules_text[:max_chars],
        "──────────────────────────────────────────────────────────────",
    ]
    if source_titles:
        lines.append(f"Sources: {source_titles}")
    return "\n".join(lines)
