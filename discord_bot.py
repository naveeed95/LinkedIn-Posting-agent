'''
Discord bot for The Tech Tutors posting agent.
Uses Discord HTTP API directly (no gateway/websocket needed for GitHub Actions).

Required env vars:
  DISCORD_BOT_TOKEN
  DISCORD_APPROVALS_CHANNEL_ID
  DISCORD_COMMENTS_CHANNEL_ID
  DISCORD_POSTED_CHANNEL_ID
  DISCORD_ANALYTICS_CHANNEL_ID
  DISCORD_REDDIT_CHANNEL_ID

Exports:
  send_approval_message(variants, scores, topic, day)         -> str | None (message_id)
  wait_for_approval(message_id, timeout_minutes)              -> dict
  send_posted_confirmation(post_url, variant_used, post_text) -> None
  send_reddit_draft(title, body, topic)                       -> None
  send_reddit_leads(posts)                                     -> str | None (message_id)
  send_comment_approval(comment_author, comment_text, suggested_reply) -> None
  send_analytics_report(report_data)                         -> None
  send_rules_update(changes)                                 -> None
'''

import os
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

from logger import get_logger

log = get_logger("discord")


load_dotenv()

DISCORD_API = "https://discord.com/api/v10"
APPROVAL_POLL_INTERVAL = 15  # 15 seconds between checks

_FETCH_ERROR = object()  # sentinel: distinguishes network error from empty message list


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
        log.info(f"Missing token or channel ID — message not sent.")
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
        log.warning(f"Send failed ({resp.status_code}): {resp.text[:200]}")
        return None
    except Exception as e:
        log.warning(f"Send error: {e}")
        return None


def _send_long_message(channel_id: str, content: str) -> str | None:
    """Discord caps each message at 2000 chars. Split long content across messages.
    Returns the ID of the FIRST message (the one we'll watch for replies)."""
    if not channel_id or not _token():
        log.info(f"Missing token or channel ID — message not sent.")
        return None

    if len(content) <= 1990:
        return _send_message(channel_id, content)

    # Leave headroom for the "_(part i/n)_\n" prefix added below (worst case
    # double-digit/double-digit ~= 16 chars) so no chunk can cross Discord's
    # hard 2000-char cap after the prefix is added.
    MAX_CHUNK = 1970

    chunks: list[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= MAX_CHUNK:
            chunks.append(remaining)
            break
        # Prefer to break at a divider line if possible
        cut = remaining.rfind("━━━", 0, MAX_CHUNK)
        if cut <= 100:
            cut = remaining.rfind("\n", 0, MAX_CHUNK)
        if cut <= 100:
            cut = MAX_CHUNK
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    first_id: str | None = None
    for i, chunk in enumerate(chunks):
        prefix = f"_(part {i+1}/{len(chunks)})_\n" if len(chunks) > 1 else ""
        msg_id = _send_message(channel_id, prefix + chunk)
        if i == 0:
            first_id = msg_id
            if first_id is None:
                log.warning("First chunk failed to send — aborting long message")
                return None
        time.sleep(0.5)
    return first_id


def _get_messages_after(channel_id: str, after_id: str) -> "list[dict] | object":
    """Returns a list of message dicts, an empty list (no new messages), or _FETCH_ERROR on network/API error."""
    try:
        resp = requests.get(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            params={"after": after_id, "limit": 10},
            headers=_headers(),
            timeout=15,
        )
        if not resp.ok:
            log.warning(f"Fetch messages failed ({resp.status_code}): {resp.text[:200]}")
            return _FETCH_ERROR
        try:
            data = resp.json()
            if isinstance(data, list):
                return data
            log.info(f"Unexpected response shape: {str(data)[:200]}")
            return _FETCH_ERROR
        except Exception as e:
            log.warning(f"Response decode error: {e}")
            return _FETCH_ERROR
    except Exception as e:
        log.warning(f"Fetch messages error: {e}")
        return _FETCH_ERROR


# ── Public functions ───────────────────────────────────────────────────────────

def send_approval_message(
    variants: list[dict],
    scores: list[int],
    topic: dict,
    day: str,
) -> str | None:
    """Send an approval message showing one variant per model.

    `variants` is a list of {"model_key", "display_name", "text"} dicts produced
    by content_generator.generate_text_post_variants().
    `scores[i]` is the engagement score for `variants[i]`.
    """
    date_str = datetime.now().strftime("%A %d %B %Y")
    divider  = "━" * 40

    if not variants:
        _send_message(
            _channel("DISCORD_APPROVALS_CHANNEL_ID"),
            f"⚠️ No variants generated for {day} {date_str}. Logging as missed.",
        )
        return None

    single = len(variants) == 1
    sections: list[str] = []
    for i, v in enumerate(variants, 1):
        score = scores[i - 1] if i - 1 < len(scores) else 0
        label = "" if single else f"[{i}] "
        sections.append(
            f"{divider}\n"
            f"**{label}{v['display_name']}** — score {score}/100\n"
            f"{v['text']}"
        )

    if single:
        instructions = (
            "**Reply with:**\n"
            "✅ `yes` — approve and post this\n"
            "🔄 `r [hint]` — regenerate (e.g. `r make it punchier`)\n"
            "🆕 `new topic [hint]` — scrap this topic, pick a different one (e.g. `new topic: focus on automation`)\n"
            "✏️ `edit: [your text]` — post your own version instead\n"
            "❌ `skip` — skip today (logged as missed)"
        )
    else:
        instructions = "**Reply with:**\n"
        for i, v in enumerate(variants, 1):
            instructions += f"✅ `{i}` — post {v['display_name']}'s version\n"
        instructions += (
            "🔄 `r [hint]` — regenerate all (e.g. `r make them punchier`)\n"
            "🆕 `new topic [hint]` — scrap this topic, pick a different one\n"
            "✏️ `edit: [your text]` — post your own version instead\n"
            "❌ `skip` — skip today (logged as missed)"
        )

    header = (
        f"📝 **THE TECH TUTORS — Daily Post** | {day} {date_str}\n"
        f"**Topic:** {topic.get('title', '')}\n"
        f"**Angle:** {topic.get('angle', '')}\n"
    )

    content = header + "\n" + "\n\n".join(sections) + f"\n\n{divider}\n\n" + instructions

    channel_id = _channel("DISCORD_APPROVALS_CHANNEL_ID")
    msg_id = _send_long_message(channel_id, content)
    if msg_id:
        log.info(f"Approval sent with {len(variants)} variants (id: {msg_id}). Waiting for reply...")
    return msg_id


def wait_for_approval(
    message_id: str,
    timeout_minutes: int = 120,
    num_variants: int = 4,
) -> dict:
    """Poll Discord for the user's reply.

    Returns one of:
      {"action": "post",       "variant_index": int}    # 0-based
      {"action": "edit",       "text": str}
      {"action": "regenerate", "hint": str}
      {"action": "new_topic",  "hint": str}
      {"action": "skip"}
      {"action": "timeout"}
    """
    if timeout_minutes <= 0:
        return {"action": "timeout"}

    channel_id = _channel("DISCORD_APPROVALS_CHANNEL_ID")
    if not channel_id or not message_id:
        log.warning("No channel/message ID — defaulting to timeout.")
        return {"action": "timeout"}

    valid_picks = {str(i) for i in range(1, num_variants + 1)}
    # Natural language aliases for approving (always maps to variant 0 / the only variant)
    approve_words = {"yes", "approve", "post", "ok", "okay", "send", "publish"}
    deadline = time.time() + timeout_minutes * 60
    checks = 0

    while time.time() < deadline:
        if checks > 0:
            time.sleep(APPROVAL_POLL_INTERVAL)

        checks += 1
        messages = _get_messages_after(channel_id, message_id)

        if messages is _FETCH_ERROR:
            continue

        for msg in reversed(messages):
            if msg.get("author", {}).get("bot"):
                continue

            text = msg.get("content", "").strip()
            text_lower = text.lower()

            # Natural approval: yes / approve / post / ok / send / publish
            if text_lower in approve_words:
                return {"action": "post", "variant_index": 0}

            # Numbered selection: 1, 2, 3...
            if text_lower in valid_picks:
                return {"action": "post", "variant_index": int(text_lower) - 1}

            if text_lower == "skip":
                return {"action": "skip"}

            if text_lower.startswith("r ") and len(text) > 2:
                return {"action": "regenerate", "hint": text[2:].strip()}

            if text_lower.startswith("new topic"):
                hint = text[len("new topic"):].strip().lstrip(":").strip()
                return {"action": "new_topic", "hint": hint}

            if text_lower.startswith("edit:"):
                custom_text = text[5:].strip()
                if custom_text:
                    if len(custom_text) > 3000:
                        custom_text = custom_text[:3000]
                    return {"action": "edit", "text": custom_text}

        # Print status every minute (every 4 checks at 15s interval)
        if checks % 4 == 0:
            mins_left = int((deadline - time.time()) / 60)
            log.info(f"Waiting for approval... ({mins_left}min left)")

    log.warning("Approval timeout reached.")
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


def send_reddit_draft(title: str, body: str, topic: dict) -> None:
    """Send today's Reddit-adapted draft to Discord for the human to copy-paste and post manually.

    Reddit closed self-service API app creation (Responsible Builder Policy, Nov 2025) — no OAuth
    app can be created for this account, so this is a fire-and-forget draft, not an approval flow.
    """
    date_str = datetime.now().strftime("%A %d %B %Y")
    divider = "━" * 40

    content = (
        f"🔶 **REDDIT DRAFT (post manually)** | {date_str}\n"
        f"**Topic:** {topic.get('title', '')}\n\n"
        f"{divider}\n"
        f"**Title:** {title}\n\n"
        f"{body}\n"
        f"{divider}"
    )

    channel_id = _channel("DISCORD_REDDIT_CHANNEL_ID")
    _send_long_message(channel_id, content)


def send_reddit_leads(posts: list[dict]) -> str | None:
    """Batch-push N raw hiring-intent posts to Discord — discovery only, no drafted
    reply, no self-promo. Each post dict: subreddit, title, url, selftext, age.
    """
    channel_id = _channel("DISCORD_REDDIT_LEADS_CHANNEL_ID")
    date_str = datetime.now().strftime("%A %d %B %Y")
    divider = "━" * 40

    header = f"💼 **HIRING LEADS — {len(posts)} post(s), newest first** | {date_str}\n"
    sections = []
    for p in posts:
        snippet = p.get("selftext", "")[:200]
        sections.append(
            f"{divider}\n**r/{p['subreddit']}** — {p['title']} _({p.get('age', '')})_\n"
            f"🔗 {p['url']}\n\n{snippet}"
        )
    content = header + "\n" + "\n\n".join(sections) + f"\n\n{divider}"
    return _send_long_message(channel_id, content)


def send_comment_approval(
    comment_author: str,
    comment_text: str,
    suggested_reply: str,
) -> str | None:
    channel_id = _channel("DISCORD_COMMENTS_CHANNEL_ID")

    content = f"""💬 **NEW COMMENT** — approval needed
**From:** {comment_author}
**Comment:** {comment_text[:300]}

**Suggested reply:**
{suggested_reply[:500]}

Reply `post` to send · `edit: [new text]` to customise · `skip` to ignore"""

    return _send_message(channel_id, content[:2000])


def wait_for_comment_approval(
    message_id: str,
    suggested_reply: str,
    timeout_minutes: int = 25,
) -> dict:
    channel_id = _channel("DISCORD_COMMENTS_CHANNEL_ID")
    if not channel_id or not message_id:
        return {"action": "timeout"}

    deadline = time.time() + timeout_minutes * 60
    checks   = 0

    while time.time() < deadline:
        if checks > 0:
            time.sleep(APPROVAL_POLL_INTERVAL)
        checks += 1

        messages = _get_messages_after(channel_id, message_id)
        if messages is _FETCH_ERROR:
            continue
        for msg in reversed(messages):
            if msg.get("author", {}).get("bot"):
                continue
            text       = msg.get("content", "").strip()
            text_lower = text.lower()

            if text_lower == "post":
                return {"action": "post", "text": suggested_reply}
            if text_lower == "skip":
                return {"action": "skip"}
            if text_lower.startswith("edit:"):
                custom = text[5:].strip()
                if custom:
                    return {"action": "post", "text": custom[:1250]}

    return {"action": "timeout"}


def send_analytics_report(report_data: dict) -> None:
    channel_id = _channel("DISCORD_ANALYTICS_CHANNEL_ID")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    hook_lines = "\n".join(
        f"  • {h}: {s}" for h, s in report_data.get("hook_scores", {}).items()
    )
    day_lines = "\n".join(
        f"  • {d}: {s}" for d, s in report_data.get("day_scores", {}).items()
    )
    model_wins   = report_data.get("model_wins", {})
    model_scores = report_data.get("model_scores", {})
    total_wins   = sum(model_wins.values()) or 1
    win_lines = "\n".join(
        f"  • {m}: {w} wins ({round(100 * w / total_wins)}%)"
        for m, w in model_wins.items()
    )
    score_lines = "\n".join(
        f"  • {m}: {s}" for m, s in model_scores.items()
    )

    sheet_url = report_data.get("sheet_url", "")

    content = f"""📊 **ANALYTICS REPORT** — {timestamp}

**7-day avg engagement score:** {report_data.get('recent_avg_score', 0)}
**Best hook type:** {report_data.get('best_hook_type', '—')}
**Best posting day:** {report_data.get('best_day', '—')}
**Best model:** {report_data.get('best_model', '—')}
**Top post this week:** {report_data.get('top_post_topic', '—')}

Hook performance:
{hook_lines or '  No data yet'}

Day performance:
{day_lines or '  No data yet'}

Model win rates (which model you picked):
{win_lines or '  No data yet'}

Model engagement (which model audience prefers):
{score_lines or '  No data yet'}"""

    if sheet_url:
        content += f"\n\n📋 **Full report:** {sheet_url}"

    _send_long_message(channel_id, content)


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


def notify_timeout(day: str, date_str: str) -> None:
    _send_message(
        _channel("DISCORD_APPROVALS_CHANNEL_ID"),
        f"⚠️ **No approval received** for today's post ({day} {date_str}). Logged as missed.",
    )


def notify_auto_post(day: str, date_str: str) -> None:
    _send_message(
        _channel("DISCORD_APPROVALS_CHANNEL_ID"),
        f"⏱️ **No response after 2 hours** ({day} {date_str}) — auto-posting variant 1 now.",
    )


def notify_workflow_failure(message: str) -> None:
    _send_message(_channel("DISCORD_ANALYTICS_CHANNEL_ID"), message)


# ── CLI entry point (called by GitHub Actions) ─────────────────────────────────

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--send-report" in args:
        from analytics_tracker import get_performance_summary, write_to_google_sheets
        summary = get_performance_summary()
        sheet_url = write_to_google_sheets(summary)
        if sheet_url:
            summary["sheet_url"] = sheet_url
        send_analytics_report(summary)
        print("Analytics report sent to Discord.")
    elif "--send-weekly-report" in args:
        from analytics_tracker import get_performance_summary, write_to_google_sheets
        summary = get_performance_summary()
        sheet_url = write_to_google_sheets(summary)
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
