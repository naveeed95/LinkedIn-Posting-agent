"""
Fetches trending AI topics from multiple free sources:
  - Hacker News API
  - RSS feeds (TechCrunch, VentureBeat, The Verge, etc.)
  - Tavily semantic search (TAVILY_API_KEY)
  - Exa neural search — finds content similar to top past posts (EXA_API_KEY)
  - Supadata YouTube transcripts from top AI channels (SUPADATA_API_KEY)
  - Playwright scrape of Google Trends for AI searches

All sources are merged and deduplicated before returning.
"""

import os
import re
import time
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

load_dotenv()

HEADERS = {"User-Agent": "TheTechTutors-PostingAgent/1.0"}
ATOM = "http://www.w3.org/2005/Atom"
HN_API = "https://hn.algolia.com/api/v1/search"

RSS_FEEDS = [
    ("TechCrunch AI",        "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI",       "https://venturebeat.com/category/ai/feed/"),
    ("The Verge AI",         "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Technology Review","https://www.technologyreview.com/feed/"),
    ("Wired AI",             "https://www.wired.com/feed/tag/artificial-intelligence/latest/rss"),
    ("Google AI Blog",       "https://blog.google/technology/ai/rss/"),
    ("Hugging Face Blog",    "https://huggingface.co/blog/feed.xml"),
    ("Reddit r/artificial",  "https://www.reddit.com/r/artificial/.rss"),
    ("Reddit r/ArtificialIntelligence", "https://www.reddit.com/r/ArtificialIntelligence/.rss"),
    ("Reddit r/MachineLearning", "https://www.reddit.com/r/MachineLearning/.rss"),
    ("Product Hunt AI",      "https://www.producthunt.com/feed?category=artificial-intelligence"),
    ("Ars Technica",         "https://feeds.arstechnica.com/arstechnica/technology-lab"),
]

AI_YOUTUBE_CHANNELS = [
    ("Matt Wolfe",        "UCT4KCGtNAGKB5eXqm5k5Spw"),
    ("Two Minute Papers", "UCbfYPyITQ-7l4upoX8nvctg"),
    ("Andrej Karpathy",   "UCH-2wCe5ChpLhP1pAFrp-9g"),
]

TAVILY_QUERIES = [
    "trending AI tools for small business this week",
    "AI automation business productivity 2026",
    "new AI model release business impact",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _text(el, *tags: str) -> str:
    for tag in tags:
        val = el.findtext(tag, "")
        if val:
            return val.strip()
    return ""


def _make_topic(title: str, url: str, source: str, description: str = "", points: int = 0) -> dict:
    return {"title": title, "url": url, "source": source, "description": description, "points": points}


# ── Source fetchers ────────────────────────────────────────────────────────────

def fetch_hacker_news(days_back: int = 7, max_items: int = 15) -> list[dict]:
    since = int(time.time()) - days_back * 86400
    try:
        resp = requests.get(
            HN_API,
            params={
                "query": "AI LLM machine learning automation",
                "tags": "story",
                "hitsPerPage": max_items,
                "numericFilters": f"created_at_i>{since}",
            },
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  [research] Hacker News failed: {e}")
        return []

    items = []
    for hit in resp.json().get("hits", []):
        title = hit.get("title", "").strip()
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        if title:
            items.append(_make_topic(title, url, "Hacker News", points=hit.get("points", 0)))
    return items


def fetch_rss(name: str, url: str, max_items: int = 6) -> list[dict]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"  [research] Failed ({name}): {e}")
        return []

    entries = list(root.iter("item")) or list(root.iter(f"{{{ATOM}}}entry"))
    items = []
    for entry in entries:
        title = _strip_html(_text(entry, "title", f"{{{ATOM}}}title"))
        link = _text(entry, "link", f"{{{ATOM}}}link").strip()
        if not link:
            link_el = entry.find(f"{{{ATOM}}}link")
            if link_el is not None:
                link = link_el.get("href", "")
        description = _strip_html(
            _text(entry, "description", f"{{{ATOM}}}summary", f"{{{ATOM}}}content")
        )[:300]
        if title and link:
            items.append(_make_topic(title, link, name, description))
        if len(items) >= max_items:
            break
    return items


def fetch_tavily_topics() -> list[dict]:
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

    items = []
    for query in TAVILY_QUERIES:
        try:
            results = client.search(query, max_results=5, search_depth="advanced")
            for r in results.get("results", []):
                title = r.get("title", "").strip()
                url = r.get("url", "")
                if title and url:
                    items.append(_make_topic(title, url, "Tavily", r.get("content", "")[:300]))
        except Exception as e:
            print(f"  [research] Tavily query failed: {e}")
    return items


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
                link = getattr(r, "url", "") or ""
                if title.strip() and link:
                    items.append(_make_topic(title.strip(), link, "Exa Similar"))
        except Exception as e:
            print(f"  [research] Exa find_similar failed: {e}")
    return items


def fetch_youtube_transcripts() -> list[dict]:
    api_key = os.environ.get("SUPADATA_API_KEY", "")
    if not api_key:
        print("  [research] SUPADATA_API_KEY not set — skipping YouTube transcripts.")
        return []

    items = []
    for channel_name, channel_id in AI_YOUTUBE_CHANNELS:
        try:
            resp = requests.get(
                "https://api.supadata.ai/v1/youtube/channel/videos",
                params={"channelId": channel_id, "limit": 2},
                headers={"x-api-key": api_key},
                timeout=15,
            )
            if not resp.ok:
                print(f"  [research] Supadata {channel_name} failed ({resp.status_code})")
                continue
            for video in resp.json().get("videos", []):
                video_id = video.get("videoId", "")
                title = video.get("title", "").strip()
                if not video_id or not title:
                    continue
                tr = requests.get(
                    "https://api.supadata.ai/v1/youtube/transcript",
                    params={"videoId": video_id, "format": "text"},
                    headers={"x-api-key": api_key},
                    timeout=20,
                )
                excerpt = tr.json().get("content", "")[:400] if tr.ok else ""
                items.append(_make_topic(
                    f"[YouTube] {title}",
                    f"https://www.youtube.com/watch?v={video_id}",
                    f"YouTube/{channel_name}",
                    description=f"Transcript: {excerpt}",
                ))
        except Exception as e:
            print(f"  [research] Supadata {channel_name} error: {e}")
    return items


def fetch_google_trends() -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [research] playwright not installed — skipping Google Trends.")
        return []

    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(
                "https://trends.google.com/trends/trendingsearches/daily?geo=US",
                timeout=20000,
            )
            page.wait_for_timeout(3000)
            trends = page.query_selector_all("div.feed-item-header")
            ai_keywords = ("ai", "gpt", "llm", "claude", "gemini", "openai", "machine", "automation", "chatbot")
            for trend in trends[:20]:
                text = trend.inner_text().strip()
                if text and any(kw in text.lower() for kw in ai_keywords):
                    items.append(_make_topic(
                        text,
                        "https://trends.google.com/trends/trendingsearches/daily?geo=US",
                        "Google Trends",
                    ))
            browser.close()
    except Exception as e:
        print(f"  [research] Google Trends failed: {e}")
    return items


# ── Public entry point ─────────────────────────────────────────────────────────

def fetch_trending_topics(top_post_urls: list[str] | None = None) -> list[dict]:
    """Fetch and deduplicate topics from all sources. Backward compatible."""
    topics: list[dict] = []

    print("  Fetching Hacker News...")
    topics.extend(fetch_hacker_news())

    for name, url in RSS_FEEDS:
        print(f"  Fetching {name}...")
        topics.extend(fetch_rss(name, url))

    print("  Fetching Tavily semantic search...")
    topics.extend(fetch_tavily_topics())

    if top_post_urls:
        print("  Fetching Exa similar content...")
        topics.extend(fetch_exa_similar(top_post_urls))

    print("  Fetching YouTube transcripts via Supadata...")
    topics.extend(fetch_youtube_transcripts())

    print("  Fetching Google Trends...")
    topics.extend(fetch_google_trends())

    seen: set[str] = set()
    unique: list[dict] = []
    for t in topics:
        key = t["title"].lower()[:50]
        if key not in seen:
            seen.add(key)
            unique.append(t)

    print(f"  Total unique topics found: {len(unique)}")
    return unique
