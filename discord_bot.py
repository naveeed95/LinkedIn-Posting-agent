"""
Discord bot for The Tech Tutors posting agent.
Uses Discord HTTP API directly (no gateway/websocket needed for GitHub Actions).

Required env vars:
  DISCORD_BOT_TOKEN
  DISCORD_APPROVALS_CHANNEL_ID
  DISCORD_COMMENTS_CHANNEL_ID
  DISCORD_POSTED_CHANNEL_ID
  DISCORD_ANALYTICS_CHANNEL_ID

Exports:
  send_approval_message(variants, scores, topic, day)       -> str | None (message_id)
  wait_for_approval(message_id, timeout_minutes)            -> dict
  send_posted_confirmation(post_url, variant_used, post_text) -> None
  send_comment_approval(comment_author, comment_text, suggested_reply) -> None
  send_analytics_report(report_data)                        -> None
  send_rules_update(changes)                                -> None
"""

import os
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

DISCORD_API = "https://discord.com/api/v10"
APPROVAL_POLL_INTERVAL = 300  # 5 minutes between checks


def _token() -> str:
    return os.environ.get("DISCORD_BOT_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bot {_token()}",
        "Content-Type": "application/json",
    }


def _channel(key: str) -> str:
    return os.environ.get(key, "")


def _send_message(channel_id: str, content: str) -> str | None:
    if not channel_id or not _token():
        print(f"  [discord] Missing token or channel ID — message not sent.")
        return None
    try:
        resp = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            json={"content": content},
            headers=_headers(),
            timeout=15,
        )
        if resp.ok:
            return resp.json().get("id")
        print(f"  [discord] Send failed ({resp.status_code}): {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"  [discord] Send error: {e}")
        return None


def _get_messages_after(channel_id: str, after_id: str) -> list[dict]:
    try:
        resp = requests.get(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            params={"after": after_id, "limit": 10},
            headers=_headers(),
            timeout=15,
        )
        return resp.json() if resp.ok else []
    except Exception as e:
        print(f"  [discord] Fetch messages error: {e}")
        return []


# ── Public functions ───────────────────────────────────────────────────────────

def send_approval_message(
    variants: list[str],
    scores: list[int],
    topic: dict,
    day: str,
) -> str | None:
    date_str = datetime.now().strftime("%A %d %B %Y")
    score1 = scores[0] if scores else 0
    score2 = scores[1] if len(scores) > 1 else 0
    v1 = variants[0] if variants else ""
    v2 = variants[1] if len(variants) > 1 else ""
    divider = "━" * 40

    content = f"""📝 **THE TECH TUTORS — Daily Post** | {day} {date_str}
**Topic:** {topic.get('title', '')}
**Angle:** {topic.get('angle', '')}

{divider}
**VARIANT 1** (Score: {score1}/100) — Question Hook
{v1}
{divider}
**VARIANT 2** (Score: {score2}/100) — Bold Statement
{v2}
{divider}

Reply with:
**1** → post variant 1
**2** → post variant 2
**r [hint]** → regenerate with your instruction (e.g. `r make it funnier`)
**3 edit: [your text]** → post your own version
**skip** → skip today (logged)"""

    channel_id = _channel("DISCORD_APPROVALS_CHANNEL_ID")
    msg_id = _send_message(channel_id, content[:2000])
    if msg_id:
        print(f"  [discord] Approval message sent (id: {msg_id}). Waiting for reply...")
    return msg_id


def wait_for_approval(message_id: str, timeout_minutes: int = 120) -> dict:
    channel_id = _channel("DISCORD_APPROVALS_CHANNEL_ID")
    if not channel_id or not message_id:
        print("  [discord] No channel/message ID — defaulting to timeout.")
        return {"action": "timeout"}

    deadline = time.time() + timeout_minutes * 60
    checks = 0

    while time.time() < deadline:
        if checks > 0:
            mins_left = int((deadline - time.time()) / 60)
            print(f"  [discord] Waiting for approval... ({mins_left}min left)")
            time.sleep(APPROVAL_POLL_INTERVAL)

        checks += 1
        messages = _get_messages_after(channel_id, message_id)

        for msg in reversed(messages):
            if msg.get("author", {}).get("bot"):
                continue

            text = msg.get("content", "").strip()
            text_lower = text.lower()

            if text_lower == "1":
                return {"action": "post", "variant": 1}
            if text_lower == "2":
                return {"action": "post", "variant": 2}
            if text_lower == "skip":
                return {"action": "skip"}
            if text_lower.startswith("r ") and len(text) > 2:
                return {"action": "regenerate", "hint": text[2:].strip()}
            if text_lower.startswith("3 edit:"):
                custom_text = text[7:].strip()
                if custom_text:
                    return {"action": "edit", "text": custom_text}

    print("  [discord] Approval timeout reached.")
    return {"action": "timeout"}


def send_posted_confirmation(post_url: str, variant_used: int, post_text: str) -> None:
    channel_id = _channel("DISCORD_POSTED_CHANNEL_ID")
    preview = post_text[:200] + "..." if len(post_text) > 200 else post_text
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    content = f"""✅ **POSTED SUCCESSFULLY**
{preview}

**Variant used:** {variant_used}
**LinkedIn URL:** {post_url}
**Time:** {timestamp}"""

    _send_message(channel_id, content[:2000])


def send_comment_approval(
    comment_author: str,
    comment_text: str,
    suggested_reply: str,
) -> None:
    channel_id = _channel("DISCORD_COMMENTS_CHANNEL_ID")

    content = f"""💬 **NEW COMMENT** — approval needed
**From:** {comment_author}
**Comment:** {comment_text[:300]}

**Suggested reply:**
{suggested_reply[:500]}

React ✅ to post | ✏️ to edit | ❌ to skip"""

    _send_message(channel_id, content[:2000])


def send_analytics_report(report_data: dict) -> None:
    channel_id = _channel("DISCORD_ANALYTICS_CHANNEL_ID")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    hook_lines = "\n".join(
        f"  • {h}: {s}" for h, s in report_data.get("hook_scores", {}).items()
    )
    day_lines = "\n".join(
        f"  • {d}: {s}" for d, s in report_data.get("day_scores", {}).items()
    )
    sheet_url = report_data.get("sheet_url", "")

    content = f"""📊 **ANALYTICS REPORT** — {timestamp}

**7-day avg engagement score:** {report_data.get('recent_avg_score', 0)}
**Best hook type:** {report_data.get('best_hook_type', '—')}
**Best posting day:** {report_data.get('best_day', '—')}
**Top post this week:** {report_data.get('top_post_topic', '—')}

Hook performance:
{hook_lines or '  No data yet'}

Day performance:
{day_lines or '  No data yet'}"""

    if sheet_url:
        content += f"\n\n📋 **Full report:** {sheet_url}"

    _send_message(channel_id, content[:2000])


def send_rules_update(changes: list[str]) -> None:
    channel_id = _channel("DISCORD_ANALYTICS_CHANNEL_ID")
    if not changes:
        return
    lines = "\n".join(f"  • {c}" for c in changes)
    content = f"""🔔 **LINKEDIN RULES UPDATE DETECTED**

Recent changes found:
{lines}

Rules cache refreshed. Next post will use updated rules."""

    _send_message(channel_id, content[:2000])


# ── CLI entry point (called by GitHub Actions) ─────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    args = sys.argv[1:]
    if "--send-report" in args:
        from analytics_tracker import get_performance_summary, write_to_google_sheets
        from scheduler import get_week_overview
        summary = get_performance_summary()
        slots = get_week_overview()
        sheet_url = write_to_google_sheets(summary, slots)
        if sheet_url:
            summary["sheet_url"] = sheet_url
        send_analytics_report(summary)
        print("Analytics report sent to Discord.")
    elif "--send-weekly-report" in args:
        from analytics_tracker import get_performance_summary, write_to_google_sheets
        from scheduler import get_week_overview
        summary = get_performance_summary()
        slots = get_week_overview()
        sheet_url = write_to_google_sheets(summary, slots)
        if sheet_url:
            summary["sheet_url"] = sheet_url
        send_analytics_report(summary)
        print("Weekly report sent to Discord.")
    elif "--rules-update" in args:
        from linkedin_rules_fetcher import fetch_rules
        data = fetch_rules()
        updates = data.get("recent_updates", [])
        send_rules_update(updates)
        print("Rules update sent to Discord.")
    else:
        print("Usage: python discord_bot.py --send-report | --send-weekly-report | --rules-update")
