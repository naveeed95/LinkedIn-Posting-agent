"""
Fetches trending AI topics from multiple free sources:

RSS Feeds (no API key):
  - TLDR AI, Ben's Bites, The Verge AI, VentureBeat AI, TechCrunch AI
  - MIT Technology Review, HuggingFace Blog, arXiv CS.AI

Reddit (no API key):
  - r/artificial, r/MachineLearning, r/LocalLLaMA, r/ChatGPT, r/OpenAI

Other free APIs:
  - HuggingFace trending models API
  - Hacker News Algolia API

Optional (API key required):
  - Tavily semantic search (TAVILY_API_KEY)
  - Exa neural search (EXA_API_KEY)
  - Supadata YouTube transcripts (SUPADATA_API_KEY)

All sources merged and deduplicated before returning.
"""

import os
import re
import time

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

HEADERS = {"User-Agent": "TheTechTutors-PostingAgent/1.0 (LinkedIn AI content research)"}
HN_API  = "https://hn.algolia.com/api/v1/search"

# ── RSS feed registry ──────────────────────────────────────────────────────────
# Each entry: (display_name, url)

RSS_FEEDS = [
    # AI newsletters
    ("TLDR AI",             "https://tldrnewsletter.substack.com/feed"),
    ("Ben's Bites",         "https://www.bensbites.com/feed"),
    # Tech publications — AI sections
    ("The Verge AI",        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("VentureBeat AI",      "https://venturebeat.com/category/ai/feed/"),
    ("TechCrunch AI",       "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("MIT Tech Review",     "https://www.technologyreview.com/feed/"),
    # Lab / company blogs
    ("HuggingFace Blog",    "https://huggingface.co/blog/feed.xml"),
    # Research
    ("arXiv CS.AI",         "https://rss.arxiv.org/rss/cs.AI"),
    ("arXiv CS.LG",         "https://rss.arxiv.org/rss/cs.LG"),
]

# ── Reddit subreddits ──────────────────────────────────────────────────────────

REDDIT_SUBS = [
    "artificial",       # broad AI news & discussion
    "MachineLearning",  # research papers & techniques
    "LocalLLaMA",       # open-source LLM news
    "ChatGPT",          # GPT & OpenAI news — high volume
    "OpenAI",           # official OpenAI news
    "Anthropic",        # Claude & Anthropic news
]

# ── Tavily queries ─────────────────────────────────────────────────────────────

TAVILY_QUERIES = [
    "new AI tools for small business 2026",
    "AI automation productivity tools this week",
    "latest LLM model release business impact",
    "AI cost reduction ROI case study 2026",
    "no-code AI tools launch this week",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _make_topic(title: str, url: str, source: str, description: str = "", points: int = 0, published_date: str = "") -> dict:
    return {"title": title, "url": url, "source": source, "description": description, "points": points, "published_date": published_date}


def _is_ai_relevant(text: str) -> bool:
    keywords = (
        "llm", "gpt", "claude", "gemini", "openai", "anthropic", "mistral",
        "machine learning", "deep learning", "neural network", "automation", "chatbot",
        "language model", "generative", "diffusion", "transformer", "hugging face",
        "llama", "agent", "rag", "fine-tun", "embedding", "inference",
        "artificial intelligence",
    )
    lower = text.lower()
    if any(kw in lower for kw in keywords):
        return True
    # Check "ai" as a whole word only — "aita", "afraid", "said" must not match
    return bool(re.search(r'\bai\b', lower))


# ── RSS fetchers ───────────────────────────────────────────────────────────────

def fetch_rss_feeds(max_per_feed: int = 8) -> list[dict]:
    items = []
    for name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                title = _strip_html(entry.get("title", "")).strip()
                link  = entry.get("link", "")
                summary = _strip_html(entry.get("summary", entry.get("description", "")))[:300]
                if not title or not link:
                    continue
                pub = entry.get("published", "")
                if name in ("arXiv CS.AI", "arXiv CS.LG") or _is_ai_relevant(title + " " + summary):
                    items.append(_make_topic(title, link, name, summary, published_date=pub))
                    count += 1
                    if count >= max_per_feed:
                        break
            print(f"  [research] RSS {name}: {count} items")
        except Exception as e:
            print(f"  [research] RSS {name} failed: {e}")
    return items


# ── Reddit fetcher ─────────────────────────────────────────────────────────────

def fetch_reddit(max_per_sub: int = 10) -> list[dict]:
    items = []
    reddit_headers = {**HEADERS, "Accept": "application/json"}
    for sub in REDDIT_SUBS:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/top.json",
                params={"t": "week", "limit": max_per_sub},
                headers=reddit_headers,
                timeout=10,
            )
            if not resp.ok:
                print(f"  [research] Reddit r/{sub} failed ({resp.status_code})")
                continue
            posts = resp.json().get("data", {}).get("children", [])
            count = 0
            for post in posts:
                d = post.get("data", {})
                title = d.get("title", "").strip()
                url   = d.get("url", "") or f"https://reddit.com{d.get('permalink', '')}"
                score = d.get("score", 0)
                desc  = _strip_html(d.get("selftext", ""))[:200]
                pub = str(d.get("created_utc", ""))
                if title and _is_ai_relevant(title):
                    items.append(_make_topic(title, url, f"Reddit r/{sub}", desc, points=score, published_date=pub))
                    count += 1
            print(f"  [research] Reddit r/{sub}: {count} items")
            time.sleep(0.5)  # be polite to Reddit
        except Exception as e:
            print(f"  [research] Reddit r/{sub} error: {e}")
    return items


# ── HuggingFace trending models ────────────────────────────────────────────────

def fetch_huggingface_trending(limit: int = 10) -> list[dict]:
    try:
        resp = requests.get(
            "https://huggingface.co/api/models",
            params={"sort": "trendingScore", "direction": -1, "limit": limit},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        items = []
        for model in resp.json():
            model_id = model.get("modelId") or model.get("id", "")
            if not model_id:
                continue
            title = f"New trending model: {model_id}"
            url   = f"https://huggingface.co/{model_id}"
            tags  = " ".join(model.get("tags", []))[:200]
            items.append(_make_topic(title, url, "HuggingFace Trending", tags))
        print(f"  [research] HuggingFace trending: {len(items)} models")
        return items
    except Exception as e:
        print(f"  [research] HuggingFace trending failed: {e}")
        return []


# ── Hacker News ────────────────────────────────────────────────────────────────

def fetch_hacker_news(days_back: int = 7, max_items: int = 20) -> list[dict]:
    since = int(time.time()) - days_back * 86400
    # Run multiple short queries — long multi-word queries + date filter return 0 on HN Algolia
    hn_queries = ["AI", "LLM", "automation business", "artificial intelligence",
                  "small business AI", "AI tools productivity"]
    items: list[dict] = []
    seen: set[str] = set()
    per_query = max(4, max_items // len(hn_queries))

    for query in hn_queries:
        try:
            resp = requests.get(
                HN_API,
                params={
                    "query":          query,
                    "tags":           "story",
                    "hitsPerPage":    per_query,
                    "numericFilters": f"created_at_i>{since}",
                },
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            for hit in resp.json().get("hits", []):
                title = hit.get("title", "").strip()
                url   = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
                key   = title.lower()[:50]
                if title and key not in seen and _is_ai_relevant(title):
                    seen.add(key)
                    items.append(_make_topic(title, url, "Hacker News",
                                             points=hit.get("points", 0),
                                             published_date=hit.get("created_at", "")))
        except Exception as e:
            print(f"  [research] Hacker News query '{query}' failed: {e}")

    if len(items) < 3:
        print(f"  [research] WARNING: HN returned only {len(items)} items — Algolia API may be slow or rate-limited")
    else:
        print(f"  [research] Hacker News: {len(items)} items")
    return items


# ── Tavily (optional) ──────────────────────────────────────────────────────────

def fetch_tavily_topics(domain: str = "", keywords: list[str] | None = None) -> list[dict]:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        print("  [research] TAVILY_API_KEY not set — skipping.")
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
    except ImportError:
        print("  [research] tavily-python not installed — skipping.")
        return []

    if domain and keywords:
        queries = [
            f"{domain} small business 2026 news",
            f"{keywords[0]} ROI save time SMB" if keywords else "AI automation ROI 2026",
            f"{keywords[1]} tools small business" if len(keywords) > 1 else "no-code AI tools 2026",
            "AI automation small business cost savings this week",
            "new AI tool launch 2026 SMB productivity",
        ]
    else:
        queries = TAVILY_QUERIES

    items = []
    for query in queries:
        if not query:
            continue
        try:
            results = client.search(query, max_results=5, search_depth="advanced")
            for r in results.get("results", []):
                title = r.get("title", "").strip()
                url   = r.get("url", "")
                if title and url:
                    items.append(_make_topic(title, url, "Tavily", r.get("content", "")[:300]))
        except Exception as e:
            print(f"  [research] Tavily query failed: {e}")
    print(f"  [research] Tavily: {len(items)} items")
    return items


# ── Exa (optional) ─────────────────────────────────────────────────────────────

def fetch_exa_similar(top_post_urls: list[str]) -> list[dict]:
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        print("  [research] EXA_API_KEY not set — skipping.")
        return []
    if not top_post_urls:
        return []
    try:
        from exa_py import Exa
        exa = Exa(api_key=api_key)
    except ImportError:
        print("  [research] exa-py not installed — skipping.")
        return []

    items = []
    for url in top_post_urls[:2]:
        try:
            results = exa.find_similar(url, num_results=5)
            for r in results.results:
                title = getattr(r, "title", "") or ""
                link  = getattr(r, "url", "") or ""
                if title.strip() and link:
                    items.append(_make_topic(title.strip(), link, "Exa Similar"))
        except Exception as e:
            print(f"  [research] Exa find_similar failed: {e}")
    print(f"  [research] Exa: {len(items)} items")
    return items


# ── YouTube broad search (via Tavily, no channel restrictions) ─────────────────
# Searches all of YouTube for AI content relevant to SMB owners.
# Falls back silently if TAVILY_API_KEY not set.

YOUTUBE_AI_QUERIES = [
    "site:youtube.com AI tools small business productivity 2026",
    "site:youtube.com AI automation no-code workflow tutorial",
    "site:youtube.com artificial intelligence business cost savings",
]


def fetch_youtube_search() -> list[dict]:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        print("  [research] TAVILY_API_KEY not set — skipping YouTube search.")
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
    except ImportError:
        print("  [research] tavily-python not installed — skipping YouTube search.")
        return []

    items = []
    for query in YOUTUBE_AI_QUERIES:
        try:
            results = client.search(query, max_results=3, search_depth="basic")
            for r in results.get("results", []):
                url   = r.get("url", "")
                title = r.get("title", "").strip()
                if "youtube.com/watch" in url and title:
                    items.append(_make_topic(title, url, "YouTube", r.get("content", "")[:300]))
        except Exception as e:
            print(f"  [research] YouTube search query failed: {e}")
    print(f"  [research] YouTube search: {len(items)} videos")
    return items


# ── Reddit broad AI search (across all subreddits) ─────────────────────────────
# Complements fetch_reddit() (subreddit-specific) with a wide Reddit search.

REDDIT_AI_SEARCH_QUERIES = [
    "AI tools small business productivity",
    "artificial intelligence automation ROI save time",
    "ChatGPT no-code workflow business",
    "LLM cost efficiency 2026",
]


def fetch_reddit_ai_search(max_per_query: int = 5) -> list[dict]:
    items = []
    reddit_headers = {**HEADERS, "Accept": "application/json"}
    for query in REDDIT_AI_SEARCH_QUERIES:
        try:
            resp = requests.get(
                "https://www.reddit.com/search.json",
                params={"q": query, "sort": "top", "t": "week", "limit": max_per_query},
                headers=reddit_headers,
                timeout=10,
            )
            if not resp.ok:
                continue
            for post in resp.json().get("data", {}).get("children", []):
                d     = post.get("data", {})
                title = d.get("title", "").strip()
                url   = d.get("url", "") or f"https://reddit.com{d.get('permalink', '')}"
                score = d.get("score", 0)
                desc  = _strip_html(d.get("selftext", ""))[:200]
                if title and _is_ai_relevant(title):
                    items.append(_make_topic(title, url, "Reddit Search", desc,
                                             points=score,
                                             published_date=str(d.get("created_utc", ""))))
        except Exception as e:
            print(f"  [research] Reddit AI search '{query}' failed: {e}")
        time.sleep(0.3)
    print(f"  [research] Reddit broad AI search: {len(items)} items")
    return items


# ── Article content fetcher ────────────────────────────────────────────────────

def fetch_article_content(url: str, max_chars: int = 3000) -> str:
    if not url or "ycombinator.com" in url or "reddit.com" in url:
        return ""
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "form", "button"]):
            tag.decompose()
        main = (
            soup.find("article") or
            soup.find("main") or
            soup.find(class_=lambda c: c and any(
                x in str(c).lower() for x in ["article", "post-body", "entry-content", "article-body", "story-body"]
            )) or
            soup.find("body")
        )
        text = (main or soup).get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        print(f"  [research] Article fetched: {len(text)} chars from {url[:60]}")
        return text[:max_chars]
    except Exception as e:
        print(f"  [research] Article fetch failed: {e}")
        return ""


# ── Deep targeted daily research ───────────────────────────────────────────────

def fetch_deep_topic_research(topic_title: str, focus_keywords: list[str]) -> list[dict]:
    items: list[dict] = []

    # Targeted Tavily search
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if api_key:
        try:
            from tavily import TavilyClient
            client  = TavilyClient(api_key=api_key)
            queries = [f"{topic_title} 2026 latest news"] + [
                f"{kw} latest" for kw in focus_keywords[:2]
            ]
            for query in queries[:3]:
                try:
                    results = client.search(query, max_results=5, search_depth="advanced")
                    for r in results.get("results", []):
                        title = r.get("title", "").strip()
                        url   = r.get("url", "")
                        if title and url:
                            items.append(_make_topic(title, url, "Tavily", r.get("content", "")[:400]))
                except Exception as e:
                    print(f"  [research] Deep Tavily query failed: {e}")
        except ImportError:
            pass

    # Targeted HN search
    keywords = " ".join(focus_keywords[:3]) if focus_keywords else topic_title
    try:
        resp = requests.get(
            HN_API,
            params={
                "query":          keywords,
                "tags":           "story",
                "hitsPerPage":    10,
                "numericFilters": f"created_at_i>{int(time.time()) - 7 * 86400}",
            },
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        for hit in resp.json().get("hits", []):
            title = hit.get("title", "").strip()
            url   = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
            if title:
                items.append(_make_topic(title, url, "Hacker News", points=hit.get("points", 0)))
    except Exception as e:
        print(f"  [research] Deep HN search failed: {e}")

    # Targeted Reddit search
    try:
        resp = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": topic_title, "sort": "top", "t": "week", "limit": 5},
            headers={**HEADERS, "Accept": "application/json"},
            timeout=10,
        )
        if resp.ok:
            for post in resp.json().get("data", {}).get("children", []):
                d     = post.get("data", {})
                title = d.get("title", "").strip()
                url   = d.get("url", "") or f"https://reddit.com{d.get('permalink', '')}"
                if title and _is_ai_relevant(title):
                    items.append(_make_topic(title, url, "Reddit Search", points=d.get("score", 0)))
    except Exception as e:
        print(f"  [research] Reddit search failed: {e}")

    # Deduplicate and sort by virality
    seen:   set[str]   = set()
    unique: list[dict] = []
    for t in sorted(items, key=lambda x: x.get("points", 0), reverse=True):
        key = t["title"].lower()[:50]
        if key not in seen:
            seen.add(key)
            unique.append(t)

    print(f"  [research] Deep research: {len(unique)} sources found for '{topic_title}'")
    return unique[:10]


# ── Public entry point ─────────────────────────────────────────────────────────

SMB_BOOST_KEYWORDS = (
    "small business", "smb", "startup", "entrepreneur", "founder",
    "save time", "save money", "automate", "no-code", "low-code",
    "cost", "roi", "per month", "hours per week", "productivity",
)


def fetch_trending_topics(
    top_post_urls: list[str] | None = None,
    domain: str = "",
    focus_keywords: list[str] | None = None,
) -> list[dict]:
    """Fetch, deduplicate, and rank topics from all sources."""
    topics: list[dict] = []

    print("  Fetching RSS feeds (newsletters + tech publications)...")
    topics.extend(fetch_rss_feeds())

    print("  Fetching Reddit communities...")
    topics.extend(fetch_reddit())

    print("  Fetching HuggingFace trending models...")
    topics.extend(fetch_huggingface_trending())

    print("  Fetching Hacker News...")
    topics.extend(fetch_hacker_news())

    print("  Fetching Tavily semantic search...")
    topics.extend(fetch_tavily_topics(domain=domain, keywords=focus_keywords))

    if top_post_urls:
        print("  Fetching Exa similar content...")
        topics.extend(fetch_exa_similar(top_post_urls))

    print("  Fetching YouTube (broad AI search via Tavily)...")
    topics.extend(fetch_youtube_search())

    print("  Fetching Reddit broad AI search (all subreddits)...")
    topics.extend(fetch_reddit_ai_search())

    # Deduplicate: exact prefix match first, then near-duplicate similarity check
    from difflib import SequenceMatcher
    seen:   set[str]   = set()
    unique: list[dict] = []
    for t in topics:
        key = t["title"].lower()[:50]
        if key in seen:
            continue
        if any(SequenceMatcher(None, t["title"].lower(), u["title"].lower()).ratio() > 0.85 for u in unique):
            continue
        seen.add(key)
        unique.append(t)

    # Score each topic. SMB relevance + domain alignment are the PRIMARY signals.
    # Virality is a TIE-BREAKER only — log-scaled so a 20k-upvote meme never
    # beats a 0-upvote Tavily article that directly addresses an SMB pain point.
    import math
    domain_lower = domain.lower()
    kw_list = list(focus_keywords or [])
    for t in unique:
        text = (t["title"] + " " + t.get("description", "")).lower()
        smb_bonus    = 100 if any(kw in text for kw in SMB_BOOST_KEYWORDS) else 0
        domain_bonus = 60  if domain_lower and domain_lower in text else 0
        kw_bonus     = 40  if any(kw.lower() in text for kw in kw_list) else 0
        virality     = int(math.log2(t.get("points", 0) + 1) * 3)  # max ~45 for 20k pts
        t["_score"]  = smb_bonus + domain_bonus + kw_bonus + virality

    unique.sort(key=lambda x: x.get("_score", 0), reverse=True)

    print(f"  Total unique topics found: {len(unique)}")
    return unique
