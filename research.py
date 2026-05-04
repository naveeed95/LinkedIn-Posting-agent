"""
Fetches trending AI topics from multiple free sources:
  - Hacker News API
  - Tavily semantic search (TAVILY_API_KEY)
  - Exa neural search — finds content similar to top past posts (EXA_API_KEY)
  - Supadata YouTube transcripts from top AI channels (SUPADATA_API_KEY)
  - Playwright scrape of Google Trends for AI searches

All sources are merged and deduplicated before returning.
"""

import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv()

HEADERS = {"User-Agent": "TheTechTutors-PostingAgent/1.0"}
HN_API = "https://hn.algolia.com/api/v1/search"

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

    try:
        from supadata.client import Supadata
    except ImportError:
        print("  [research] supadata SDK not installed — skipping YouTube transcripts.")
        return []

    client = Supadata(api_key=api_key)
    items = []

    for channel_name, channel_id in AI_YOUTUBE_CHANNELS:
        try:
            video_ids_obj = client.youtube.channel.videos(id=channel_id, limit=2)
            ids = (
                video_ids_obj.videoIds
                if hasattr(video_ids_obj, "videoIds")
                else (video_ids_obj if isinstance(video_ids_obj, list) else [])
            )
            for vid in ids[:2]:
                url = f"https://www.youtube.com/watch?v={vid}"
                try:
                    tr = client.transcript(url=url, text=True)
                    excerpt = tr.content[:400] if isinstance(getattr(tr, "content", None), str) else ""
                except Exception:
                    excerpt = ""
                items.append(_make_topic(
                    f"[YouTube/{channel_name}] {vid}",
                    url,
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


# ── Article content fetcher ────────────────────────────────────────────────────

def fetch_article_content(url: str, max_chars: int = 3000) -> str:
    """Scrape and return the main readable text from an article URL."""
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
    """Targeted research on today's specific topic — finds latest and most viral content."""
    items: list[dict] = []

    # Targeted Tavily search
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if api_key:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=api_key)
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

    # Targeted HN search — last 7 days, ranked by points
    keywords = " ".join(focus_keywords[:3]) if focus_keywords else topic_title
    try:
        resp = requests.get(
            HN_API,
            params={
                "query": keywords,
                "tags": "story",
                "hitsPerPage": 10,
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

    # Deduplicate and sort by virality
    seen:   set[str]   = set()
    unique: list[dict] = []
    for t in sorted(items, key=lambda x: x.get("points", 0), reverse=True):
        key = t["title"].lower()[:50]
        if key not in seen:
            seen.add(key)
            unique.append(t)

    print(f"  [research] Deep research: {len(unique)} sources found for '{topic_title}'")
    return unique[:8]


# ── Public entry point ─────────────────────────────────────────────────────────

def fetch_trending_topics(top_post_urls: list[str] | None = None) -> list[dict]:
    """Fetch and deduplicate topics from all sources. Backward compatible."""
    topics: list[dict] = []

    print("  Fetching Hacker News...")
    topics.extend(fetch_hacker_news())

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
