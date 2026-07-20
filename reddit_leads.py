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
import hashlib
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

# Queries are grouped by grammatical shape because templates aren't interchangeable
# with all keywords — "need someone to build a developer" or "who can build me a
# freelancer" are grammatically nonsensical and never occur on Reddit (confirmed
# empirically: a rotation batch crossing "build a {x}" templates with person nouns
# returned zero results across 20 queries). Each template group pairs only with the
# matching keyword group.
#
# The groups target the FULL spectrum of how real people phrase a buying/hiring ask
# — not just the textbook "hire a developer". Observed on Reddit, in rough order of
# how commonly the buyer actually converts:
#   - PRODUCT/PERSON: explicit "need/hire a <thing/person>" (the classic gig post)
#   - COST: price-shopping ("how much to build an app") — already decided to pay
#   - RECOMMEND: referral-seeking ("can anyone recommend a dev/agency")
#   - NEEDED: noun-first gig phrasing ("developer needed", "programmer wanted")
#   - FIXED: colloquial/2026-specific asks (automation, vibe-code rescue, cofounder)
# The FILTER (_is_hiring_lead) is still the gatekeeper — these queries only widen the
# net; each surfaced post must still pass the hire-phrase + tech-target + not-noise
# checks below.

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
    "AI agent",
    "internal tool",
    "landing page",
    "Shopify store",
    "API integration",
    "Discord bot",
    "web scraper",
    "dashboard",
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
    "automation expert",
    "AI developer",
    "no-code developer",
    "full stack developer",
]

# Price-shopping — "how much to build an app" is one of the strongest buying signals
# on Reddit (the poster has already decided to pay, they're just researching cost),
# yet the textbook "hire a X" queries never surface it.
COST_TEMPLATES = [
    "how much to build a {x}",
    "how much does a {x} cost",
    "cost to build a {x}",
    "how much should I pay for a {x}",
]

COST_KEYWORDS = [
    "website",
    "web app",
    "mobile app",
    "app",
    "chatbot",
    "automation",
]

# Referral-seeking — poster has decided to hire, just wants a name.
RECOMMEND_TEMPLATES = [
    "recommend a {x}",
    "can anyone recommend a {x}",
    "where can I find a {x}",
]

RECOMMEND_KEYWORDS = [
    "developer",
    "web developer",
    "app developer",
    "automation expert",
    "development agency",
]

# Noun-first gig phrasing — extremely common on Reddit and missed entirely by the
# verb-first "need a X" templates above.
NEEDED_TEMPLATES = [
    "{x} needed",
    "{x} wanted",
]

NEEDED_KEYWORDS = [
    "developer",
    "web developer",
    "programmer",
    "coder",
    "freelance developer",
]

# Colloquial / 2026-specific asks that don't fit a {template} × {keyword} grid.
# Automation (their sweet spot), vibe-code rescue (built an MVP with an AI/no-code
# tool, hit a wall, now needs a real dev), and non-technical-founder asks.
FIXED_QUERIES = [
    "how do I automate my business",
    "want to automate my workflow",
    "need help automating",
    "vibe coded need a developer",
    "built with lovable need help",
    "no code hit a wall developer",
    "need a technical cofounder",
    "turn my idea into an app",
    "paid gig developer",
    "looking for developers",
    "need developers",
    # Validated against live r/smallbusiness, r/Entrepreneur, r/automation posts —
    # the outsourcing/automation phrasings real non-technical owners actually use.
    "pay someone to build my app",
    "hire someone to build a website",
    "who can build my app",
    "can AI automate my business",
    "looking for someone to build me a website",
    "how do I automate my lead follow up",
    "sick of doing this manually",
    "need an n8n workflow built",
]

RECENCY_WINDOW_HOURS = 72
SEEN_WINDOW_DAYS = 14
MIN_LEADS = 10
# Bumped from 10 → 15 because the query pool roughly doubled (cost/recommend/needed/
# fixed groups added). At 3 runs/day the full rotation still completes in ~4 days,
# comfortably inside the 14-day seen-set window, so no phrasing goes stale-uncovered.
QUERIES_PER_RUN = 15
# Measured empirically: reddit.com/search.rss rate-limits far more aggressively than a
# per-subreddit new.rss endpoint (which tolerates a 6s pause) would.
# A single request exhausts the budget (x-ratelimit-remaining: 0.0) with ~49s reset; even
# 40s pauses still hit 429 on consecutive queries. Use 55s to reliably stay under the
# bucket refill. 15 queries × 55s ≈ 14 min per run.
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

# Hire-phrases whose match text already names a person/tech target (e.g. "looking
# for a developer") — accepted immediately, no proximity check needed, since the
# target IS the match. Covers: singular ("hire a developer"), plural ("looking for
# developers" — a hire verb is required immediately before the plural noun so bare
# "senior engineers" in a career-advice post doesn't match), noun-first gig phrasing
# ("developer needed", "programmer wanted"), and referral-seeking ("recommend a dev
# agency").
_TARGET_INCLUSIVE_HIRE_PATTERNS = re.compile(
    r"(looking for|looking to hire|need|hire|hiring|seeking|want) "
    r"(a |an )?(dev|developer|freelancer|programmer|coder)|"
    r"(looking for|looking to hire|hiring|need|seeking|want) "
    r"(some |a few |multiple |several )?(devs|developers|programmers|coders|freelancers)|"
    r"(dev|developer|web developer|app developer|programmer|coder|"
    r"freelance developer|engineer) (needed|wanted)|"
    r"recommend (a|an|some|any) "
    r"(dev|developer|web developer|app developer|coder|programmer|"
    r"freelancer|agency|dev shop|development agency|software (dev|engineer))|"
    # SMB automation buying question — "can AI handle our invoice processing",
    # "can AI automate my follow-ups". Tech Tutors' exact pitch.
    r"can ai (handle|do|automate|manage|build|run|take over|replace|help with)|"
    # Seeking a service provider in-thread — "any consultants here?", "any agencies
    # around". Scoped to consultant/agency/freelancer/expert (a clear hire signal);
    # deliberately NOT bare "developers here", which is discussion-forum chatter.
    r"any (consultants?|agenc(y|ies)|freelancers?|experts?|"
    r"automation (experts?|consultants?|agenc(y|ies))) (here|around|available)",
    re.IGNORECASE,
)

# Generic hire-phrases that say nothing about WHAT is being hired — "hiring a ",
# "[hiring]", "budget for a ", "who can build/make/do", "need a ", "looking for a "
# match carpet cleaners, video editors, UGC creators, private lenders etc. just as
# readily as developers. Confirmed empirically: "who can (build|make|do)" matched
# "become a good engineer rather than just someone who can build projects" — a
# CS-career-advice post with zero hiring intent — and got cross-posted 9x. These
# only count as a lead when a tech/dev target noun appears shortly AFTER the
# phrase (see _PROXIMITY_WINDOW below), not merely anywhere in the whole post.
_GENERIC_HIRE_PATTERNS = re.compile(
    r"need (to hire|someone) |who can (build|make|do)|budget (is|for|of)|"
    r"willing to pay|hire a |hire an |\[hiring\]|hiring a |hiring an |"
    r"hiring for a |hiring for an |looking to hire|"
    r"need (a|an) |looking for (a|an) |"
    r"can (anyone|someone) (help|build|make|recommend|suggest)|"
    r"does anyone know (a|of)|any recommendations? for a|"
    r"where (can|do) i find (a|an)|help me find (a|an)|"
    r"recommend(ations)? for a|suggestions? for a|anyone (know|recommend) (a|an)|"
    r"paid (gig|project|work|opportunity)|"
    r"need help (building|automating|developing|finishing|fixing|making)|"
    # "<verb> someone to build it" — covers need/pay/hire/looking for/find someone to,
    # the way non-technical owners actually phrase outsourcing (confirmed across
    # r/smallbusiness, r/Entrepreneur). Proximity-gated to a tech target, so "someone
    # to build a deck" still drops out.
    r"someone to (build|make|develop|create|automate|code|design|finish|fix|help|do)|"
    r"(rather|just|willing to|happy to) pay someone|"
    r"pay to (get|have) .{0,25}(built|made|done|developed|created|automated)|"
    # "who should I hire / who do you use" — referral-seeking variant.
    r"who (can i|do i|should i|did you|do you) (hire|pay|use|go to|recommend|trust)|"
    # Automation-intent — "looking to automate my billing", "how do I automate my
    # follow-ups". DIY-noisy on its own, so proximity-gated like everything else:
    # only counts if a concrete tech target (n8n/AI/workflow/etc.) sits right after.
    r"(looking|want|trying|need) to automate|how (do|can|to|should) i ?automate",
    re.IGNORECASE,
)

# Price-shopping intent — "how much to build an app", "what's a fair rate for a
# website". Strong buying signal (poster's decided to pay, just researching cost),
# but "how much" is noisy on its own, so it's proximity-gated to a tech target the
# same way generic phrases are.
_COST_HIRE_PATTERNS = re.compile(
    r"how much (to |would it |will it |does it )?(cost )?(to )?"
    r"(build|make|develop|create|design|get|hire|pay|charge)|"
    r"how much (does|for|is) (a|an) |"
    r"how much should i (pay|budget|expect|spend)|"
    r"cost (to|of) (build|develop|design|hir|creat|mak)|"
    r"what('?s| is)? (a |the )?(fair|reasonable|typical|average|going|ballpark) "
    r"(rate|price|cost|quote)|"
    r"ballpark (for|cost|price|figure)",
    re.IGNORECASE,
)

# Combined tech/dev target — person nouns (developer, agency, consultant), product
# nouns (app, website, automation, chatbot), and the AI/no-code build tools people
# name when they've hit a wall ("finish my Lovable app", "fix my Webflow site").
# Used as the proximity gate for generic/cost phrases: reddit.com/search.rss matches
# loosely on individual words, not phrases (confirmed during design — a query for
# "need a developer" surfaced completely unrelated posts), so a generic hire-phrase
# must have a tech target close by, not just somewhere in a long post.
_NEAR_TARGET_PATTERN = re.compile(
    r"develop|programm|freelanc|\bcoder\b|engineer|contractor|agency|consultant|"
    r"\bapp\b|website|web app|automat|chatbot|\bbot\b|\bai\b|software|\bcode\b|"
    r"coding|saas|app builder|no.?code|low.?code|\bapi\b|script|tech stack|"
    r"web design|mobile app|backend|frontend|full.?stack|\bmvp\b|"
    r"workflow|integration|crm|dashboard|\bbilling\b|invoic|"
    r"vibe.?cod|lovable|bubble|bolt\.new|cursor|replit|framer|webflow|wix|"
    r"squarespace|wordpress|shopify|zapier|make\.com|\bn8n\b|airtable|"
    r"ghl|gohighlevel|hubspot|salesforce|notion",
    re.IGNORECASE,
)

# How close a tech target must appear after a generic/cost hire-phrase to count.
# Forward-only (not bidirectional): the CS-career post above has "engineer"
# ~40 chars BEFORE "who can build" — a symmetric window would still false-positive
# on it. Real hire posts put the target after the phrase ("hiring a video editor",
# "budget for a chatbot", "how much to build a website").
_PROXIMITY_WINDOW = 70

# Career / jobseeker / learning posts that superficially look like hiring language
# ("hiring managers", "looking for a role", "should I learn X") but where the POSTER
# is the worker, not a buyer. Checked first so it short-circuits everything else.
# The CS-student post that got cross-posted 9x ("Am I focusing on the wrong skills
# as a CS student...") is the canonical case this blocks.
_NOT_A_LEAD_PATTERNS = re.compile(
    r"how (do|can|should) i (become|get into|break into|start (a career|in)|land|learn|study)|"
    r"should i (learn|study|focus on|switch to|pursue)|"
    r"am i (focusing on the wrong|wasting|learning the right|on the right|studying the right)|"
    r"(wrong|right) skills|"
    r"i('?m| am) (a |an )?(new|junior|aspiring|self.?taught|beginner|entry.?level|"
    r"fresh|recent|final.?year|\d(st|nd|rd|th).?.?(year|semester)) "
    r"(grad|graduate|student|dev|developer|programmer|engineer|coder)|"
    r"looking for (a )?(job|internship|employment|full.?time role|entry.?level)|"
    r"seeking (a )?(job|employment|internship|opportunit|position at|role at)|"
    r"(fresh|recent) (grad|graduate)|"
    r"my (resume|cv)\b|"
    r"career (advice|guidance|path|roadmap)|"
    r"roadmap (to|for) (become|becoming|learn|getting)",
    re.IGNORECASE,
)

# Content-marketing / SEO articles that agencies farm onto Reddit around the exact
# keyword this scans for — "MVP Development Cost: Complete Breakdown for 2026", "What
# Startups Actually Spend". They trip the cost pattern + a tech target but are not
# buyers, they're vendors. Markers below are things a real one-line buyer question
# ("how much to build my app?") never contains — guide/breakdown framing, "what
# startups spend", authoritative "based on N projects" claims, price-table language.
_CONTENT_GUIDE_PATTERNS = re.compile(
    r"(cost|pricing|price) (breakdown|guide)|complete (guide|breakdown)|"
    r"(ultimate|complete|definitive|full) guide|pricing guide|"
    r": what (startups|founders|businesses|companies|you)|"
    r"(here'?s |this is )?what (startups|founders|businesses) (actually |really )?(spend|pay|cost)|"
    r"(real|actual) (data|numbers|pricing) (from|on)|based on .{0,20}\d+\+? (projects|builds|startups)|"
    r"average .{0,25}(cost|price|rate)|typical(ly)? (falls|ranges|costs|runs)|"
    r"cost (breakdown|guide|in 20\d\d)|complete \d{4} pricing",
    re.IGNORECASE,
)

# Hiring, but for a NON-tech role — UGC creators, video editors, social-media
# managers, VAs, copywriters, appointment setters etc. These flooded the feed
# because the company is often an "AI-powered X app", so a tech target ("app",
# "ai") sits inside the proximity window even though the role being hired has
# nothing to do with dev/automation work (not a service The Tech Tutors offers).
# Anchored to a hire verb / [hiring] tag + up to two filler words before the role,
# so "need a developer for my video-editing app" (a real dev lead) is NOT caught —
# only posts hiring the non-tech role itself.
_NON_TECH_ROLE_PATTERNS = re.compile(
    r"(\[hiring\]|hiring|hire|looking for|looking to hire|need|seeking|want|wanted)"
    r"[:\s]*(a |an |some |a few |\d+\+? )?(\S+[\s-]){0,2}"
    r"(ugc|video editor|content (creator|writer|team|manager)|social media|"
    r"community manager|appointment setter|virtual assistant|\bva\b|copywriter|"
    r"photographer|videographer|voice(-| )?(actor|over)|moderator|"
    r"brand ambassador|campus ambassador|sales (rep|hunter|partner|development)|"
    r"lead.?gen|graphic designer|seamstress|carpet clean|editor for)",
    re.IGNORECASE,
)

_FOR_HIRE_PATTERNS = re.compile(
    r"\[for hire\]|available for hire|"
    # Giveaway/showcase tags — "[FREE] I built a plugin…", "[Open Source] …". The
    # poster is promoting their own creation, not hiring. A buyer never tags a
    # hiring request this way, so it's a zero-false-negative reject. (Caught a live
    # r/WordpressPlugins showcase whose body described the hire-it-yourself scenario
    # it replaces, tripping a hire-phrase + tech target.)
    r"\[free\]|\[open.?source\]|\[oss\]|\[showcase\]|\[release\]|"
    r"i(?:'?m| am) a (?:[a-z]+[\s-]){0,3}(developer|programmer|freelancer|designer|coder|editor)|"
    r"looking for work|open to work|for hire:|hire me|my (services|portfolio)|"
    r"i (build|develop|code|design) .{0,40}(for clients|for hire)|"
    r"i can (build|connect you|help you|deliver)|dm me|message me (if|for)|"
    r"check out my|i offer|i provide|contact me (for|if)|reach out if you need|"
    r"anyone need a|need a website\?.{0,60}i (can|will)|"
    r"currently available for (new )?(projects|clients|work)",
    re.IGNORECASE,
)

# Machine-generated job-board aggregator posts (r/jobhuntify, r/jobboardsearch, and
# similar bot-fed subs) — FTE/contract roles at companies, posted by a bot, not an
# SMB owner looking to outsource work. Detected via the aggregator's consistent
# emoji/field signature rather than subreddit name (bots post to new subs
# constantly, but the template format is stable). Confirmed against live samples:
# "🧑‍💻 Level: ... 📌 Location: ... 💵 Salary: ..." and "Categories: #fulltime ...
# Apply & Description 👉".
_JOB_BOARD_BOT_PATTERN = re.compile(
    r"👉|🧑‍💻\s*level:|📌\s*location:|💵\s*salary:|categories:\s*#",
    re.IGNORECASE,
)


def _is_hiring_lead(post: dict) -> bool:
    if post.get("selftext") in ("[removed]", "[deleted]"):
        return False
    age_hours = (time.time() - post.get("created_utc", 0)) / 3600
    if age_hours > RECENCY_WINDOW_HOURS or age_hours < 0:
        return False
    text = f"{post.get('title', '')} {post.get('selftext', '')}"
    if _NOT_A_LEAD_PATTERNS.search(text):
        return False
    if _CONTENT_GUIDE_PATTERNS.search(text):
        return False
    if _FOR_HIRE_PATTERNS.search(text):
        return False
    if _JOB_BOARD_BOT_PATTERN.search(text):
        return False
    # An explicitly-named dev target ("need a developer") accepts before the
    # non-tech-role reject runs, so a real dev lead that merely mentions a non-tech
    # role in passing ("need a developer, social media is handled separately") isn't
    # killed. Only posts that never name a dev target fall through to the reject.
    if _TARGET_INCLUSIVE_HIRE_PATTERNS.search(text):
        return True
    if _NON_TECH_ROLE_PATTERNS.search(text):
        return False
    # Generic and cost phrases only count when a tech target appears just after the
    # phrase — the phrase alone matches far too much unrelated Reddit chatter.
    for pattern in (_GENERIC_HIRE_PATTERNS, _COST_HIRE_PATTERNS):
        match = pattern.search(text)
        if match:
            window = text[match.end():match.end() + _PROXIMITY_WINDOW]
            if _NEAR_TARGET_PATTERN.search(window):
                return True
    return False


# ── Query rotation (deterministic template x keyword combos, no LLM) ───────────

def _all_queries() -> list[str]:
    groups = [
        (PRODUCT_TEMPLATES, PRODUCT_KEYWORDS),
        (PERSON_TEMPLATES, PERSON_KEYWORDS),
        (COST_TEMPLATES, COST_KEYWORDS),
        (RECOMMEND_TEMPLATES, RECOMMEND_KEYWORDS),
        (NEEDED_TEMPLATES, NEEDED_KEYWORDS),
    ]
    queries: list[str] = []
    for templates, keywords in groups:
        queries.extend(t.format(x=k) for t, k in itertools.product(templates, keywords))
    queries.extend(FIXED_QUERIES)
    return queries


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


# ── Seen-set dedup — keys are either a Reddit fullname (t3_xxx) or a "ct:<hash>"
# content-key (see _content_key), sharing one file/TTL since both are just
# opaque dedup keys ──────────────────────────────────────────────────────────────

def _load_seen_leads() -> set[str]:
    if not _SEEN_LEADS_FILE.exists():
        return set()
    try:
        with open(_SEEN_LEADS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        cutoff = (date.today() - timedelta(days=SEEN_WINDOW_DAYS)).isoformat()
        return {key for key, ts in data.items() if ts >= cutoff}
    except Exception as e:
        log.warning(f"Failed to load seen leads: {e}")
        return set()


def _save_seen_leads(keys: set[str]) -> None:
    now = datetime.now().isoformat()
    try:
        existing: dict = {}
        if _SEEN_LEADS_FILE.exists():
            with open(_SEEN_LEADS_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        cutoff = (date.today() - timedelta(days=SEEN_WINDOW_DAYS)).isoformat()
        existing = {u: ts for u, ts in existing.items() if ts >= cutoff}
        for key in keys:
            existing[key] = now
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


def _content_key(title: str, selftext: str) -> str:
    """Same post crossposted to N subreddits gets a distinct Reddit fullname per
    sub — confirmed live: a single spam post ("[HIRING] Long-Term YouTube/TikTok
    Editor...") appeared 8x under 8 different fullnames and filled an entire
    lead batch by itself. Normalize title + a leading slice of selftext so all
    crossposts of the same content collapse to one dedup key regardless of which
    subreddit or post ID they landed under."""
    basis = re.sub(r"[^a-z0-9]+", "", (title + selftext[:150]).lower())
    return "ct:" + hashlib.md5(basis.encode("utf-8")).hexdigest()


def fetch_lead_candidates() -> list[dict]:
    queries = next_query_batch()
    seen = _load_seen_leads()

    candidates: dict[str, dict] = {}
    content_keys_this_run: set[str] = set()
    for query in queries:
        for post in fetch_search_new(query):
            if not _is_hiring_lead(post):
                continue
            fullname = post.get("name", "")
            if not fullname or fullname in seen or fullname in candidates:
                continue
            content_key = _content_key(post.get("title", ""), post.get("selftext", ""))
            if content_key in seen or content_key in content_keys_this_run:
                continue
            content_keys_this_run.add(content_key)
            candidates[fullname] = {
                "fullname": fullname,
                "content_key": content_key,
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
    # it's still within the recency window. Both the fullname AND the content_key
    # are recorded so a later crosspost of the same content (different fullname,
    # different subreddit) is caught by the content-key half of the seen-set.
    new_seen = {c["fullname"] for c in candidates} | {c["content_key"] for c in candidates}

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
