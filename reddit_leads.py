"""
Sitewide Reddit scan for hiring-intent leads — people explicitly looking to pay/hire
someone for tech work of any kind (web dev, apps, automation, AI, chatbots, etc.).

This script searches all of Reddit (Reddit's sitewide search RSS, not a fixed sub list)
for a hiring/outsourcing intent signal and does NOT draft a reply or mention the business
anywhere. It only surfaces raw matching posts to Discord; a human reads them and decides
manually whether/how to respond. No LLM call in this script.

Reddit's unauthenticated .json endpoints return 403 platform-wide — this uses the sitewide
search Atom feed (reddit.com/search.rss) instead, confirmed working via manual curl during
design.

Run: python reddit_leads.py
     python reddit_leads.py --dry-run     (print candidates, skip Discord + seen-set save)
     python reddit_leads.py --fetch-only  (candidates only, same as --dry-run)
"""

import calendar
import itertools
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import feedparser
import requests

from research import HEADERS

from logger import get_logger

log = get_logger("reddit_leads")


# ── Config ──────────────────────────────────────────────────────────────────────

# Templates are split into two groups because they aren't interchangeable with all
# keywords — "need someone to build a developer" or "who can build me a freelancer"
# are grammatically nonsensical and never occur on Reddit (confirmed empirically: a
# rotation batch that happened to cross "build a {x}"-style templates with person
# nouns like developer/programmer/engineer returned zero results across 20 queries).
# PRODUCT_TEMPLATES pair only with PRODUCT_KEYWORDS (things you build); PERSON_TEMPLATES
# pair only with PERSON_KEYWORDS (people you hire).

PRODUCT_TEMPLATES = [
    "need a {x}",
    "need an {x}",
    "who can build me a {x}",
    "need someone to build a {x}",
    "need help building a {x}",
    "looking for someone to build a {x}",
]

PRODUCT_KEYWORDS = [
    "web app",
    "website",
    "automation",
    "chatbot",
    "AI tool",
    "app",
    "web application",
    "mobile app",
]

PERSON_TEMPLATES = [
    "looking to hire a {x}",
    "looking to hire an {x}",
    "looking for a {x}",
    "looking for an {x}",
    "need to hire a {x}",
    "need to hire an {x}",
    "hire a {x}",
    "hire an {x}",
    "budget for a {x}",
]

PERSON_KEYWORDS = [
    "developer",
    "programmer",
    "web developer",
    "app developer",
    "software engineer",
    "freelancer",
    "freelance developer",
    "coder",
]

RECENCY_WINDOW_HOURS = 72
SEEN_WINDOW_DAYS = 14
MIN_LEADS = 10
QUERIES_PER_RUN = 10
# Measured empirically: reddit.com/search.rss rate-limits far more aggressively than a
# per-subreddit new.rss endpoint (which tolerates a 6s pause) would.
# A single request exhausts the budget (x-ratelimit-remaining: 0.0) with ~49s reset; even
# 40s pauses still hit 429 on consecutive queries. Use 55s to reliably stay under the
# bucket refill and fewer queries per run to keep total runtime reasonable (~9 min).
SEARCH_QUERY_PAUSE_SECONDS = 55

_QUERY_STATE_FILE = Path(__file__).parent / "data" / "lead_query_state.json"
_SEEN_LEADS_FILE = Path(__file__).parent / "seen_reddit_leads.json"


# ── Sanitization (untrusted external text) ─────────────────────────────────────

_INJECTION_PREFIXES = re.compile(
    r"^(system:|new task:|new instructions:|your task is now|act as|from now on|"
    r"assistant:|user:|<s>|\[inst\]|</s>|###|---|please (disregard|ignore|forget))",
    re.IGNORECASE,
)

_INJECTION_PATTERN = re.compile(
    r"(?i)(ignore|disregard|forget|override|new instructions)\s.{0,40}"
    r"(above|previous|instruction|prompt|system|task)"
    r"|your (new )?(task|role|purpose) is"
    r"|\[/?INST\]|</s>|<s>",
)

_DELIMITER_PATTERN = re.compile(r"(#{3,}|-{3,}|={3,}|\*{3,}|<[a-zA-Z/]+>)")


def _sanitize_thread_text(text: str) -> str:
    text = text[:400]
    if _INJECTION_PREFIXES.match(text.strip()):
        return ""
    text = _INJECTION_PATTERN.sub("", text)
    text = _DELIMITER_PATTERN.sub("", text)
    return text.strip()


# ── Hiring-intent filter — pure regex, no LLM call ─────────────────────────────

# Unambiguous hiring intent — someone explicitly wants to pay/engage a person, not
# just find an existing product. Paired with the broad _TECH_TERM_PATTERN below.
_STRONG_HIRE_PATTERNS = re.compile(
    r"need (to hire|someone) |who can (build|make|do)|budget (is|for|of)|"
    r"willing to pay|hire a |hire an |\[hiring\]|hiring a |"
    r"looking for a (dev|developer|freelancer|programmer|coder)|"
    r"looking to hire",
    re.IGNORECASE,
)

# Ambiguous hiring intent — "need a X" / "looking for a X" / "can someone help me
# make X" also commonly means "I want an existing product", not "I want to hire
# someone" (e.g. "looking for an app that tracks my steps"). Only counts when paired
# with a target noun that clearly means a person/service, not a bare product noun.
#
# The trailing `(a|an)` groups here are mandatory, not optional — an earlier `(a|an)?`
# on "looking for" made the group match zero-width, so the pattern matched bare
# "looking for " with nothing after it, firing on any "looking for feedback/advice/..."
# post regardless of what followed. Confirmed empirically: unrelated posts like
# "Looking for feedback on my new app I built as a self-taught developer" matched.
_WEAK_HIRE_PATTERNS = re.compile(
    r"need (a|an) |looking for (a|an) |"
    r"can (anyone|someone) (help|build|make|recommend|suggest)|"
    r"does anyone know (a|of)|any recommendations? for a|"
    r"where (can|do) i find (a|an)|help me find (a|an)|"
    r"recommend(ations)? for a|suggestions? for a|anyone (know|recommend) (a|an)",
    re.IGNORECASE,
)

_HIRE_TARGET_PATTERN = re.compile(
    r"develop|programm|freelanc|\bcoder\b|engineer|contractor|agency|consultant|"
    r"someone (who can|to) (build|code|develop|make)",
    re.IGNORECASE,
)

# How close a target noun (developer/engineer/etc.) must appear after a weak-hire
# phrase to count. Without this, "looking for a X" anywhere plus "developer"
# anywhere else in a long post body (unrelated to each other) counted as a match.
_PROXIMITY_WINDOW = 60

_FOR_HIRE_PATTERNS = re.compile(
    r"\[for hire\]|available for hire|i'?m a (developer|programmer|freelancer)|"
    r"looking for work|open to work|for hire:|hire me|my (services|portfolio)|"
    r"i (build|develop|code|design) .{0,40}(for clients|for hire)|"
    r"i can (build|connect you|help you|deliver)|dm me|message me (if|for)|"
    r"check out my|i offer|i provide|contact me (for|if)|reach out if you need|"
    r"anyone need a|need a website\?.{0,60}i (can|will)",
    re.IGNORECASE,
)

# Reddit's search endpoint (even phrase-quoted) matches loosely on individual words,
# not the intended phrase — confirmed during testing (a query for "need a developer"
# surfaced completely unrelated posts). Hire-language alone isn't enough either, since
# generic hiring language ("need someone to help with my bathroom") is common outside
# tech contexts. Require a hire-intent phrase AND an actual tech-related term.
_TECH_TERM_PATTERN = re.compile(
    r"develop|programm|\bapp\b|website|web app|automat|chatbot|\bbot\b|\bai\b|"
    r"software|\bcode\b|coding|coder|saas|app builder|no.?code|api\b|script|"
    r"tech stack|freelance|web design|mobile app|backend|frontend|full.?stack",
    re.IGNORECASE,
)


def _is_hiring_lead(post: dict) -> bool:
    if post.get("selftext") in ("[removed]", "[deleted]"):
        return False
    age_hours = (time.time() - post.get("created_utc", 0)) / 3600
    if age_hours > RECENCY_WINDOW_HOURS or age_hours < 0:
        return False
    text = f"{post.get('title', '')} {post.get('selftext', '')}"
    if _FOR_HIRE_PATTERNS.search(text):
        return False
    if not _TECH_TERM_PATTERN.search(text):
        return False
    if _STRONG_HIRE_PATTERNS.search(text):
        return True
    # Weak hire-language ("looking for an app") is common product-shopping phrasing
    # ("looking for an app that tracks macros") that isn't a hiring lead at all —
    # only accept it when a person/service noun (developer, agency, etc.) appears
    # shortly after the hire phrase, not merely anywhere else in the post.
    weak_match = _WEAK_HIRE_PATTERNS.search(text)
    if not weak_match:
        return False
    window = text[weak_match.start():weak_match.end() + _PROXIMITY_WINDOW]
    return bool(_HIRE_TARGET_PATTERN.search(window))


# ── Query rotation (deterministic template x keyword combos, no LLM) ───────────

def _all_queries() -> list[str]:
    product_queries = [t.format(x=k) for t, k in itertools.product(PRODUCT_TEMPLATES, PRODUCT_KEYWORDS)]
    person_queries = [t.format(x=k) for t, k in itertools.product(PERSON_TEMPLATES, PERSON_KEYWORDS)]
    return product_queries + person_queries


def _load_query_state() -> dict:
    if not _QUERY_STATE_FILE.exists():
        return {"cursor": 0}
    try:
        with open(_QUERY_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Failed to load {_QUERY_STATE_FILE.name}: {e} — restarting rotation.")
        return {"cursor": 0}


def _save_query_state(state: dict) -> None:
    try:
        _QUERY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_QUERY_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.warning(f"Failed to save {_QUERY_STATE_FILE.name}: {e}")


def next_query_batch(n: int = QUERIES_PER_RUN) -> list[str]:
    """Rotates through the full template x keyword combo list so every phrasing
    gets queried roughly evenly over time, instead of always hitting the same
    first N combos (which would waste rate-limited requests on repeats)."""
    all_queries = _all_queries()
    state = _load_query_state()
    cursor = state.get("cursor", 0) % len(all_queries)

    batch = []
    for i in range(n):
        batch.append(all_queries[(cursor + i) % len(all_queries)])
    state["cursor"] = (cursor + n) % len(all_queries)
    _save_query_state(state)
    return batch


# ── Seen-set dedup ──────────────────────────────────────────────────────────────

def _load_seen_leads() -> set[str]:
    if not _SEEN_LEADS_FILE.exists():
        return set()
    try:
        with open(_SEEN_LEADS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        cutoff = (date.today() - timedelta(days=SEEN_WINDOW_DAYS)).isoformat()
        return {fullname for fullname, ts in data.items() if ts >= cutoff}
    except Exception as e:
        log.warning(f"Failed to load seen leads: {e}")
        return set()


def _save_seen_leads(fullnames: set[str]) -> None:
    now = datetime.now().isoformat()
    try:
        existing: dict = {}
        if _SEEN_LEADS_FILE.exists():
            with open(_SEEN_LEADS_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        cutoff = (date.today() - timedelta(days=SEEN_WINDOW_DAYS)).isoformat()
        existing = {u: ts for u, ts in existing.items() if ts >= cutoff}
        for fullname in fullnames:
            existing[fullname] = now
        with open(_SEEN_LEADS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        log.warning(f"Failed to save seen leads: {e}")


# ── Fetch — Reddit sitewide search RSS ─────────────────────────────────────────

_SELFTEXT_MARKER = "<!-- SC_OFF -->"
_FOOTER_PATTERN = re.compile(r"\s*submitted by\s*/u/\S+.*$", re.IGNORECASE | re.DOTALL)


def _parse_entry(entry) -> dict:
    raw_html = ""
    if entry.get("content"):
        raw_html = entry["content"][0].get("value", "")
    elif entry.get("summary"):
        raw_html = entry.get("summary", "")

    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = _FOOTER_PATTERN.sub("", text).strip()

    created_utc = 0
    if entry.get("published_parsed"):
        created_utc = calendar.timegm(entry["published_parsed"])

    subreddit = ""
    for tag in entry.get("tags", []):
        term = tag.get("term", "")
        if term:
            subreddit = term
            break

    return {
        "name": entry.get("id", ""),
        "title": entry.get("title", ""),
        "selftext": text,
        "subreddit": subreddit,
        "created_utc": created_utc,
        "url": entry.get("link", ""),
    }


def fetch_search_new(query: str, limit: int = 25) -> list[dict]:
    for attempt, backoff in enumerate((30, 60)):
        try:
            resp = requests.get(
                "https://www.reddit.com/search.rss",
                params={"q": query, "sort": "new", "limit": limit},
                headers=HEADERS,
                timeout=10,
            )
            if resp.status_code == 429:
                log.info(f"Reddit search '{query}' rate-limited — waiting {backoff}s before retry.")
                time.sleep(backoff)
                continue
            if not resp.ok:
                log.warning(f"Reddit search '{query}' failed ({resp.status_code})")
                return []
            feed = feedparser.parse(resp.content)
            return [_parse_entry(e) for e in feed.entries]
        except Exception as e:
            log.warning(f"Reddit search '{query}' error: {e}")
            return []
    log.warning(f"Reddit search '{query}' still rate-limited after retries — skipping.")
    return []


def fetch_lead_candidates() -> list[dict]:
    queries = next_query_batch()
    seen = _load_seen_leads()

    candidates: dict[str, dict] = {}
    for query in queries:
        for post in fetch_search_new(query):
            if not _is_hiring_lead(post):
                continue
            fullname = post.get("name", "")
            if not fullname or fullname in seen or fullname in candidates:
                continue
            candidates[fullname] = {
                "fullname": fullname,
                "subreddit": post.get("subreddit", ""),
                "title": _sanitize_thread_text(post.get("title", "")),
                "selftext": _sanitize_thread_text(post.get("selftext", "")),
                "url": post.get("url", ""),
                "created_utc": post.get("created_utc", 0),
            }
        time.sleep(SEARCH_QUERY_PAUSE_SECONDS)

    results = list(candidates.values())
    results.sort(key=lambda c: c["created_utc"], reverse=True)
    log.info(f"Found {len(results)} eligible hiring-intent lead(s) across {len(queries)} quer(ies).")
    return results


# ── Entry point ─────────────────────────────────────────────────────────────────

def _age_str(created_utc: float) -> str:
    hours = (time.time() - created_utc) / 3600
    if hours < 1:
        return f"{int(hours * 60)}m ago"
    if hours < 24:
        return f"{int(hours)}h ago"
    return f"{int(hours / 24)}d ago"


def queue_leads(dry_run: bool = False) -> None:
    from discord_bot import send_reddit_leads

    candidates = fetch_lead_candidates()
    if not candidates:
        log.info("No new hiring-intent leads found.")
        return

    if len(candidates) < MIN_LEADS:
        log.info(
            f"Only {len(candidates)} lead(s) found this run (floor is {MIN_LEADS}) — "
            f"sending what's available rather than reaching further back in time."
        )
    leads = candidates[:max(MIN_LEADS, len(candidates))]

    # Every fetched candidate is marked seen here, not just the ones sent — a
    # candidate that showed up this run but wasn't posted (over the floor) would
    # otherwise stay unseen and could be re-surfaced identically next run since
    # it's still within the recency window.
    new_seen = {c["fullname"] for c in candidates}

    if dry_run:
        for c in leads:
            print(f"\nr/{c['subreddit']} — {_age_str(c['created_utc'])}\n{c['title']}\n{c['url']}\n{'-' * 40}")
        log.info(f"[dry-run] {len(leads)} lead(s) found, not sent to Discord, seen-set not saved.")
        return

    for c in leads:
        c["age"] = _age_str(c["created_utc"])
    send_reddit_leads(leads)
    _save_seen_leads(new_seen)
    log.info(f"Sent {len(leads)} hiring-intent lead(s) to Discord.")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--fetch-only" in args:
        for c in fetch_lead_candidates()[:20]:
            print(f"r/{c['subreddit']}: {c['title']} — {c['url']}")
    else:
        queue_leads(dry_run="--dry-run" in args)
