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

WEIGHT_LIKES    = 1
WEIGHT_COMMENTS = 2
WEIGHT_SHARES   = 3


def _engagement_expr(prefix: str = "m") -> str:
    """Returns the SQL engagement score expression for a given table alias."""
    if not prefix.isidentifier():
        raise ValueError(f"Invalid SQL alias: {prefix!r}")
    return f"{prefix}.likes * {WEIGHT_LIKES} + {prefix}.comments * {WEIGHT_COMMENTS} + {prefix}.shares * {WEIGHT_SHARES}"


# ── Database setup ─────────────────────────────────────────────────────────────

_db_initialized = False


def _connect() -> sqlite3.Connection:
    global _db_initialized
    if not _db_initialized:
        _init_db()
        _db_initialized = True
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    # Bootstrap connection — bypass _connect() to avoid recursion through the
    # initialization guard above.
    conn = sqlite3.connect(DB_FILE)
    try:
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
                variant_chosen  INTEGER,
                chosen_model    TEXT
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

            CREATE TABLE IF NOT EXISTS hashtag_metrics (
                id        INTEGER PRIMARY KEY,
                hashtag   TEXT NOT NULL,
                post_id   TEXT NOT NULL,
                likes     INTEGER DEFAULT 0,
                comments  INTEGER DEFAULT 0,
                shares    INTEGER DEFAULT 0,
                polled_at TIMESTAMP,
                UNIQUE(hashtag, post_id)
            );
        """)
        conn.commit()
        # Add indexes for fast lookups (safe to run on existing DBs)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_posts_post_id    ON posts (post_id);
            CREATE INDEX IF NOT EXISTS idx_posts_posted_at  ON posts (posted_at);
            CREATE INDEX IF NOT EXISTS idx_metrics_post_id  ON metrics (post_id);
            CREATE INDEX IF NOT EXISTS idx_hashtag_hashtag  ON hashtag_metrics (hashtag);
            CREATE INDEX IF NOT EXISTS idx_topics_posted_at ON topics_history (posted_at);
        """)
        conn.commit()
        # Migrate existing DBs that pre-date the chosen_model column
        try:
            conn.execute("ALTER TABLE posts ADD COLUMN chosen_model TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    finally:
        conn.close()


# ── LinkedIn API helpers ───────────────────────────────────────────────────────

def _li_headers() -> dict:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }


# ── Public functions ───────────────────────────────────────────────────────────

def log_post(post_data: dict) -> None:
    import re as _re
    post_text = post_data.get("post_text", "")
    hashtags = " ".join(w for w in post_text.split() if w.startswith("#"))
    first_line = post_text.strip().split("\n")[0] if post_text.strip() else ""
    first_word = first_line.split()[0] if first_line.split() else ""
    if first_word in ("What", "Why", "How", "Is", "Are", "Do", "Can", "Have", "Ever", "Would", "Could", "Should") or "?" in first_line:
        hook_type = "question"
    elif _re.match(r'^\d', first_line):
        hook_type = "stat"
    elif _re.match(r'^(Stop|Never|Always|Don\'t|If you)', first_line, _re.I):
        hook_type = "contrarian"
    else:
        hook_type = "bold"

    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO posts
               (post_id, post_text, topic, hook_type, day_of_week,
                posted_at, char_count, hashtags, variant_chosen, chosen_model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                post_data.get("chosen_model", ""),
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

        try:
            resp_json = resp.json()
        except Exception as e:
            print(f"  [analytics] poll_metrics: malformed response from LinkedIn: {e} — body: {resp.text[:200]}")
            return {}
        elements = resp_json.get("elements", [])
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
                except Exception as e:
                    print(f"  [analytics] posted_at parse failed for {post_id}: {e}")

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

            # Update per-hashtag engagement
            post_row = conn.execute(
                "SELECT hashtags FROM posts WHERE post_id = ?", (post_id,)
            ).fetchone()
            if post_row and post_row["hashtags"]:
                now = datetime.now().isoformat()
                for tag in post_row["hashtags"].split():
                    if tag.startswith("#"):
                        conn.execute(
                            """INSERT INTO hashtag_metrics (hashtag, post_id, likes, comments, shares, polled_at)
                               VALUES (?, ?, ?, ?, ?, ?)
                               ON CONFLICT(hashtag, post_id) DO UPDATE SET
                                 likes=excluded.likes, comments=excluded.comments,
                                 shares=excluded.shares, polled_at=excluded.polled_at""",
                            (tag.lower(), post_id, data["likes"], data["comments"], data["shares"], now),
                        )
        return data

    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 401:
            print(f"  [analytics] poll_metrics: LinkedIn token expired (401) — run token_refresher.py")
        elif status == 429:
            print(f"  [analytics] poll_metrics: rate limited (429) — will retry next poll cycle")
        else:
            print(f"  [analytics] poll_metrics error: {type(e).__name__}: {e}")
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
    prune_old_records()


def prune_old_records(keep_days: int = 180) -> None:
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
    with _connect() as conn:
        deleted_m = conn.execute(
            "DELETE FROM metrics WHERE polled_at < ?", (cutoff,)
        ).rowcount
        deleted_t = conn.execute(
            "DELETE FROM topics_history WHERE posted_at < ?", (cutoff,)
        ).rowcount
        if deleted_m or deleted_t:
            print(f"  [analytics] Pruned {deleted_m} metric rows, {deleted_t} topic history rows older than {keep_days}d")


def get_performance_summary() -> dict:
    with _connect() as conn:
        eng = _engagement_expr("m")
        hook_rows = conn.execute(
            f"""SELECT hook_type,
                      AVG({eng}) AS score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               GROUP BY hook_type
               ORDER BY score DESC, hook_type ASC"""
        ).fetchall()

        day_rows = conn.execute(
            f"""SELECT day_of_week,
                      AVG({eng}) AS score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               GROUP BY day_of_week
               ORDER BY score DESC, day_of_week ASC"""
        ).fetchall()

        top_post = conn.execute(
            f"""SELECT p.topic,
                      ({eng}) AS score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               ORDER BY score DESC
               LIMIT 1"""
        ).fetchone()

        recent_avg = conn.execute(
            f"""SELECT AVG({eng}) AS avg_score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               WHERE p.posted_at >= ?""",
            ((datetime.now() - timedelta(days=7)).isoformat(),),
        ).fetchone()

        model_rows = conn.execute(
            f"""SELECT p.chosen_model,
                      COUNT(*) AS wins,
                      AVG({eng}) AS score
               FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               WHERE p.chosen_model IS NOT NULL AND p.chosen_model != ''
               GROUP BY p.chosen_model
               ORDER BY wins DESC"""
        ).fetchall()

    return {
        "best_hook_type":   hook_rows[0]["hook_type"] if hook_rows else "bold",
        "hook_scores":      {r["hook_type"]: round(r["score"] or 0, 1) for r in hook_rows},
        "best_day":         day_rows[0]["day_of_week"] if day_rows else "Tuesday",
        "day_scores":       {r["day_of_week"]: round(r["score"] or 0, 1) for r in day_rows},
        "top_post_topic":   top_post["topic"] if top_post else None,
        "top_post_score":   round(top_post["score"] or 0, 1) if top_post else 0,
        "recent_avg_score": round((recent_avg["avg_score"] or 0), 1) if recent_avg else 0,
        "best_model":       model_rows[0]["chosen_model"] if model_rows else "—",
        "model_wins":       {r["chosen_model"]: r["wins"] for r in model_rows},
        "model_scores":     {r["chosen_model"]: round(r["score"] or 0, 1) for r in model_rows},
    }


def get_topic_history(days: int = 14) -> list[str]:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT topic FROM topics_history WHERE posted_at >= ? ORDER BY posted_at DESC",
            (cutoff,),
        ).fetchall()
    return [r["topic"] for r in rows if r["topic"]]


def get_top_post_urls(n: int = 3) -> list[str]:
    with _connect() as conn:
        eng = _engagement_expr("m")
        rows = conn.execute(
            f"""SELECT p.post_id FROM posts p
               JOIN metrics m ON p.post_id = m.post_id
               ORDER BY ({eng}) DESC
               LIMIT ?""",
            (n,),
        ).fetchall()
    return [
        f"https://www.linkedin.com/feed/update/{r['post_id']}/"
        for r in rows if r["post_id"]
    ]


def get_top_hashtags(n: int = 10) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT hashtag,
                      SUM(likes * {WEIGHT_LIKES} + comments * {WEIGHT_COMMENTS} + shares * {WEIGHT_SHARES}) AS score
               FROM hashtag_metrics
               GROUP BY hashtag
               ORDER BY score DESC
               LIMIT ?""",
            (n,),
        ).fetchall()
    return [r["hashtag"] for r in rows]


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
