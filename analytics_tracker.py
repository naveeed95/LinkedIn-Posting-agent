"""
Tracks post performance in SQLite and writes reports to Google Sheets.

Exports:
  log_post(post_data)                    -> None
  poll_metrics(post_id)                  -> dict
  poll_all_recent(days)                  -> None
  get_performance_summary()              -> dict
  get_topic_history(days)                -> list[str]
  write_to_google_sheets(summary, slots) -> str | None
"""

import base64
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

DB_FILE = Path(__file__).parent / "performance.db"
LINKEDIN_STATS_URL = "https://api.linkedin.com/v2/organizationalEntityShareStatistics"


# ── Database setup ─────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                id              INTEGER PRIMARY KEY,
                post_id         TEXT UNIQUE,
                post_text       TEXT,
                topic           TEXT,
                hook_type       TEXT,
                day_of_week     TEXT,
                posted_at       TIMESTAMP,
                char_count      INTEGER,
                hashtags        TEXT,
                variant_chosen  INTEGER
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id               INTEGER PRIMARY KEY,
                post_id          TEXT,
                polled_at        TIMESTAMP,
                hours_since_post REAL,
                likes            INTEGER DEFAULT 0,
                comments         INTEGER DEFAULT 0,
                shares           INTEGER DEFAULT 0,
                impressions      INTEGER DEFAULT 0,
                clicks           INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS topics_history (
                id               INTEGER PRIMARY KEY,
                topic            TEXT,
                posted_at        TIMESTAMP,
                engagement_score REAL DEFAULT 0
            );
        """)


_init_db()


# ── LinkedIn API helpers ───────────────────────────────────────────────────────

def _li_headers() -> dict:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }


# ── Public functions ───────────────────────────────────────────────────────────

def log_post(post_data: dict) -> None:
    post_text = post_data.get("post_text", "")
    hashtags = " ".join(w for w in post_text.split() if w.startswith("#"))
    first_word = post_text.strip().split()[0] if post_text.strip() else ""
    hook_type = "question" if first_word in ("What", "Why", "How", "Is", "Are", "Do", "Can", "Have") else "bold"

    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO posts
               (post_id, post_text, topic, hook_type, day_of_week,
                posted_at, char_count, hashtags, variant_chosen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                post_data.get("post_urn", ""),
                post_text,
                post_data.get("topic_title", ""),
                hook_type,
                post_data.get("day_of_week", ""),
                post_data.get("posted_at", datetime.now().isoformat()),
                len(post_text),
                hashtags,
                post_data.get("variant_chosen", 1),
            ),
        )
        conn.execute(
            "INSERT INTO topics_history (topic, posted_at) VALUES (?, ?)",
            (post_data.get("topic_title", ""), datetime.now().isoformat()),
        )


def poll_metrics(post_id: str) -> dict:
    org_urn = os.environ.get("LINKEDIN_ORG_URN", "")
    if not org_urn or not post_id:
        return {}

    try:
        resp = requests.get(
            LINKEDIN_STATS_URL,
            params={
                "q": "organizationalEntity",
                "organizationalEntity": org_urn,
                "shares[0]": post_id,
            },
            headers=_li_headers(),
            timeout=15,
        )
        if not resp.ok:
            print(f"  [analytics] Poll failed ({resp.status_code}): {resp.text[:200]}")
            return {}

        elements = resp.json().get("elements", [])
        if not elements:
            return {}

        stats = elements[0].get("totalShareStatistics", {})
        data = {
            "likes":       stats.get("likeCount", 0),
            "comments":    stats.get("commentCount", 0),
            "shares":      stats.get("shareCount", 0),
            "impressions": stats.get("impressionCount", 0),
            "clicks":      stats.get("clickCount", 0),
        }

        with _connect() as conn:
            row = conn.execute(
                "SELECT posted_at FROM posts WHERE post_id = ?", (post_id,)
            ).fetchone()
            hours = 0.0
            if row and row["posted_at"]:
                try:
                    posted = datetime.fromisoformat(row["posted_at"])
                    hours = (datetime.now() - posted).total_seconds() / 3600
                except Exception:
                    pass

            conn.execute(
                """INSERT INTO metrics
                   (post_id, polled_at, hours_since_post, likes, comments,
                    shares, impressions, clicks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    post_id,
                    datetime.now().isoformat(),
                    round(hours, 2),
                    data["likes"],
                    data["comments"],
                    data["shares"],
                    data["impressions"],
                    data["clicks"],
                ),
            )
        return data

    except Exception as e:
        print(f"  [analytics] poll_metrics error: {e}")
        return {}


def poll_all_recent(days: int = 7) -> None:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT post_id FROM posts WHERE posted_at >= ? AND post_id != ''",
            (cutoff,),
        ).fetchall()
    for row in rows:
        print(f"  [analytics] Polling {row['post_id']}...")
        poll_metrics(row["post_id"])


def get_performance_summary() -> dict:
    with _connect() as conn:
        hook_rows = conn.execute(
            """SELECT hook_type,
                      AVG(m.likes + m.comments * 2 + m.shares * 3) AS score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               GROUP BY hook_type
               ORDER BY score DESC"""
        ).fetchall()

        day_rows = conn.execute(
            """SELECT day_of_week,
                      AVG(m.likes + m.comments * 2 + m.shares * 3) AS score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               GROUP BY day_of_week
               ORDER BY score DESC"""
        ).fetchall()

        top_post = conn.execute(
            """SELECT p.topic,
                      (m.likes + m.comments * 2 + m.shares * 3) AS score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               ORDER BY score DESC
               LIMIT 1"""
        ).fetchone()

        recent_avg = conn.execute(
            """SELECT AVG(m.likes + m.comments * 2 + m.shares * 3) AS avg_score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               WHERE p.posted_at >= ?""",
            ((datetime.now() - timedelta(days=7)).isoformat(),),
        ).fetchone()

    return {
        "best_hook_type":   hook_rows[0]["hook_type"] if hook_rows else "bold",
        "hook_scores":      {r["hook_type"]: round(r["score"] or 0, 1) for r in hook_rows},
        "best_day":         day_rows[0]["day_of_week"] if day_rows else "Tuesday",
        "day_scores":       {r["day_of_week"]: round(r["score"] or 0, 1) for r in day_rows},
        "top_post_topic":   top_post["topic"] if top_post else None,
        "top_post_score":   round(top_post["score"] or 0, 1) if top_post else 0,
        "recent_avg_score": round((recent_avg["avg_score"] or 0), 1) if recent_avg else 0,
    }


def get_topic_history(days: int = 14) -> list[str]:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT topic FROM topics_history WHERE posted_at >= ? ORDER BY posted_at DESC",
            (cutoff,),
        ).fetchall()
    return [r["topic"] for r in rows if r["topic"]]


# ── Google Sheets reporting ────────────────────────────────────────────────────

def _get_sheets_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not raw:
            return None
        sa_info = json.loads(base64.b64decode(raw).decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"  [analytics] Google Sheets service error: {e}")
        return None


def write_to_google_sheets(summary: dict, slots: list[dict]) -> str | None:
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    if not sheet_id:
        return None

    service = _get_sheets_service()
    if not service:
        return None

    try:
        sheets = service.spreadsheets()

        plan_rows = [["Day", "Date", "Topic", "Format", "Status"]]
        for slot in slots:
            topic = slot.get("topic") or {}
            plan_rows.append([
                slot.get("day", ""),
                slot.get("date", ""),
                topic.get("title", ""),
                slot.get("format", ""),
                slot.get("status", "pending"),
            ])
        sheets.values().update(
            spreadsheetId=sheet_id,
            range="Plan!A1",
            valueInputOption="RAW",
            body={"values": plan_rows},
        ).execute()

        perf_rows = [
            ["Metric", "Value"],
            ["Best Hook Type", summary.get("best_hook_type", "—")],
            ["Best Day", summary.get("best_day", "—")],
            ["Recent Avg Score (7d)", summary.get("recent_avg_score", 0)],
            ["Top Post Topic", summary.get("top_post_topic", "—")],
            ["Top Post Score", summary.get("top_post_score", 0)],
        ]
        for hook, score in summary.get("hook_scores", {}).items():
            perf_rows.append([f"Hook — {hook}", score])
        for day, score in summary.get("day_scores", {}).items():
            perf_rows.append([f"Day — {day}", score])

        sheets.values().update(
            spreadsheetId=sheet_id,
            range="Performance!A1",
            valueInputOption="RAW",
            body={"values": perf_rows},
        ).execute()

        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        print(f"  [analytics] Google Sheet updated: {url}")
        return url

    except Exception as e:
        print(f"  [analytics] Google Sheets write error: {e}")
        return None


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--poll" in args:
        print("Polling recent posts...")
        poll_all_recent(days=7)
        print("Done.")
    elif "--weekly-report" in args:
        summary = get_performance_summary()
        print(json.dumps(summary, indent=2))
    else:
        print("Usage: python analytics_tracker.py --poll | --weekly-report")
