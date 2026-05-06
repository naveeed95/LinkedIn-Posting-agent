"""
Fetches latest LinkedIn algorithm rules from free public sources.
Caches to cache/linkedin_rules.json for 7 days.

Exports:
  fetch_rules()             -> dict of current rules + recent updates
  build_rules_prompt(data)  -> str to inject into LLM system prompt
"""

import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

CACHE_FILE = Path(__file__).parent / "cache" / "linkedin_rules.json"
CACHE_TTL_DAYS = 7
HEADERS = {"User-Agent": "TheTechTutors-PostingAgent/1.0"}
ATOM = "http://www.w3.org/2005/Atom"

RULES_RSS_FEEDS = [
    ("SocialMediaExaminer", "https://www.socialmediaexaminer.com/tag/linkedin/feed/"),
    ("Buffer Blog",         "https://buffer.com/resources/feed/"),
    ("Search Engine Journal","https://www.searchenginejournal.com/feed/"),
    ("Later Blog",          "https://later.com/blog/feed/"),
]

REDDIT_URL = "https://www.reddit.com/r/linkedin/top.json?t=week&limit=20"

# Only pass through Reddit posts about algorithm/posting strategy — not user complaints
_REDDIT_SIGNAL_KEYWORDS = (
    "algorithm", "reach", "impression", "engagement", "post", "content",
    "visibility", "viral", "follower", "hashtag", "feed", "newsletter",
    "creator", "growth", "analytics", "strategy", "tip", "hack", "update",
    "change", "ban", "penali", "boost", "suppress", "organic",
)

BASELINE_RULES = {
    "character_limit": 3000,
    "optimal_post_length": "1200-1800 chars",
    "link_in_body": False,
    "hashtag_limit": 5,
    "optimal_hashtags": "3-5 placed at end",
    "automated_comments": "banned as of April 2026",
    "line_breaks": "one idea per line",
    "ai_citation_active": True,
    "best_post_times": "Tue-Thu 8-10am local time",
    "image_posts": "1.91:1 ratio or 1:1 square performs best",
    "first_comment_links": "post source URLs in first comment, never in body",
    "engagement_window": "first 60-90 minutes determine reach",
    "poll_reach": "polls get 3-5x more impressions than text",
    "carousel_reach": "PDF carousels get highest dwell time",
}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _fetch_rss_updates(name: str, url: str, max_items: int = 3) -> list[str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"  [rules] {name} feed failed: {e}")
        return []

    entries = list(root.iter("item")) or list(root.iter(f"{{{ATOM}}}entry"))
    updates = []
    for entry in entries[:max_items]:
        title = _strip_html(
            entry.findtext("title") or entry.findtext(f"{{{ATOM}}}title") or ""
        )
        if title and "linkedin" in title.lower():
            updates.append(f"[{name}] {title}")
    return updates


def _fetch_reddit_updates(max_items: int = 5) -> list[str]:
    try:
        resp = requests.get(
            REDDIT_URL,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])
    except Exception as e:
        print(f"  [rules] Reddit r/linkedin failed: {e}")
        return []

    updates = []
    for post in posts[:max_items]:
        title = post.get("data", {}).get("title", "").strip()
        score = post.get("data", {}).get("score", 0)
        title_lower = title.lower()
        is_signal = any(kw in title_lower for kw in _REDDIT_SIGNAL_KEYWORDS)
        if title and score > 5 and is_signal:
            updates.append(f"[Reddit r/linkedin] {title}")
    return updates


def _load_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if datetime.now() - fetched_at < timedelta(days=CACHE_TTL_DAYS):
            return data
    except Exception:
        pass
    return None


def _save_cache(rules: dict, updates: list[str]) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "rules": rules,
        "recent_updates": updates,
    }
    # Atomic write — see scheduler.save_schedule for rationale.
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
        print("  [rules] Using cached LinkedIn rules (< 7 days old).")
        return cached

    print("  [rules] Fetching latest LinkedIn algorithm updates...")
    updates: list[str] = []

    for name, url in RULES_RSS_FEEDS:
        updates.extend(_fetch_rss_updates(name, url))

    updates.extend(_fetch_reddit_updates())

    rules = dict(BASELINE_RULES)
    _save_cache(rules, updates)
    print(f"  [rules] Fetched {len(updates)} recent LinkedIn updates. Cached.")

    return {
        "fetched_at": datetime.now().isoformat(),
        "rules": rules,
        "recent_updates": updates,
    }


def build_rules_prompt(data: dict) -> str:
    rules = data.get("rules", BASELINE_RULES)
    updates = data.get("recent_updates", [])

    lines = [
        "── CURRENT LINKEDIN ALGORITHM RULES ──────────────────────",
        f"• Character limit: {rules['character_limit']} (optimal: {rules['optimal_post_length']})",
        f"• Links in post body: {'ALLOWED' if rules['link_in_body'] else 'PENALISED — put source URL in first comment only'}",
        f"• First comment: {rules.get('first_comment_links', 'post source URLs in first comment, never in body')}",
        f"• Hashtags: {rules['optimal_hashtags']} (max {rules['hashtag_limit']})",
        f"• Automated comments: {rules['automated_comments']}",
        f"• Line breaks: {rules['line_breaks']}",
        f"• Best posting times: {rules['best_post_times']}",
        f"• Engagement window: {rules['engagement_window']}",
        f"• Poll reach: {rules.get('poll_reach', 'polls get 3-5x more impressions than text')}",
        f"• Carousel reach: {rules.get('carousel_reach', 'PDF carousels get highest dwell time')}",
        f"• AI citations: {'LinkedIn content now indexed by ChatGPT — write with authority' if rules.get('ai_citation_active') else 'standard'}",
        "──────────────────────────────────────────────────────────",
    ]

    if updates:
        lines.append("\nRecent LinkedIn algorithm news (factor into your post strategy):")
        for u in updates[:5]:
            lines.append(f"  • {u}")
        lines.append("")

    return "\n".join(lines)
