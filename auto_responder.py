"""
Fetches unanswered LinkedIn comments and generates AI reply suggestions.
Sends each to Discord #comments channel for human approval before posting.

Run: python auto_responder.py
"""

import json
import os
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "llama-3.3-70b-versatile"

REPLY_SYSTEM = """You are a community manager for The Tech Tutors LinkedIn page.
Reply to comments in The Tech Tutors brand voice:
- Warm, helpful, conversational — like a knowledgeable friend
- Never salesy or corporate
- Acknowledge the commenter's point specifically
- Add a genuine insight or useful tip
- End with a follow-up question to keep the conversation going
- Keep replies under 300 characters
- Never use: delve, leverage, synergy, game-changer"""


def _li_headers() -> dict:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def fetch_recent_post_urns(days: int = 7) -> list[str]:
    schedule_file = Path(__file__).parent / "weekly_schedule.json"
    if not schedule_file.exists():
        return []

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    urns = []

    with open(schedule_file, encoding="utf-8") as f:
        schedule = json.load(f)

    for week_slots in schedule.values():
        for slot in week_slots:
            if (
                slot.get("status") == "posted"
                and slot.get("post_urn")
                and slot.get("date", "") >= cutoff
            ):
                urns.append(slot["post_urn"])

    return urns


def fetch_comments(post_urn: str) -> list[dict]:
    encoded = urllib.parse.quote(post_urn, safe="")
    try:
        resp = requests.get(
            f"https://api.linkedin.com/v2/socialActions/{encoded}/comments",
            headers=_li_headers(),
            timeout=15,
        )
        if not resp.ok:
            print(f"  [responder] Comments fetch failed ({resp.status_code}): {resp.text[:150]}")
            return []
        return resp.json().get("elements", [])
    except Exception as e:
        print(f"  [responder] fetch_comments error: {e}")
        return []


def _page_has_replied(comment: dict) -> bool:
    org_urn = os.environ.get("LINKEDIN_ORG_URN", "")
    for sub in comment.get("comments", {}).get("elements", []):
        if org_urn and org_urn in sub.get("actor", ""):
            return True
    return False


def fetch_unanswered_comments() -> list[dict]:
    post_urns = fetch_recent_post_urns(days=7)
    if not post_urns:
        print("  [responder] No recent posts found in weekly_schedule.json.")
        return []

    unanswered = []
    for urn in post_urns:
        for comment in fetch_comments(urn):
            if not _page_has_replied(comment):
                message = comment.get("message", {}).get("text", "").strip()
                if message:
                    unanswered.append({
                        "post_urn": urn,
                        "comment_urn": comment.get("$URN", ""),
                        "author": comment.get("actor", "unknown"),
                        "text": message,
                    })

    print(f"  [responder] Found {len(unanswered)} unanswered comments.")
    return unanswered


def generate_reply(comment_text: str, post_context: str = "") -> str:
    context_block = f"\nPost context: {post_context}" if post_context else ""

    prompt = f"""Write a reply to this LinkedIn comment on The Tech Tutors page.{context_block}

Comment: {comment_text}

Requirements:
- Under 300 characters
- Warm, helpful, conversational
- Acknowledge their specific point
- Add one genuine insight
- End with a follow-up question
- No hashtags

Reply:"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": REPLY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  [responder] generate_reply error: {e}")
        return ""


def queue_replies() -> None:
    from discord_bot import send_comment_approval

    comments = fetch_unanswered_comments()
    if not comments:
        print("  [responder] No unanswered comments to process.")
        return

    for comment in comments:
        print(f"  [responder] Generating reply to: {comment['text'][:80]}...")
        suggested = generate_reply(comment["text"], post_context=f"Post URN: {comment['post_urn']}")
        if suggested:
            send_comment_approval(
                comment_author=comment["author"],
                comment_text=comment["text"],
                suggested_reply=suggested,
            )
            print("  [responder] Sent to Discord for approval.")
        else:
            print("  [responder] Could not generate reply — skipping.")


if __name__ == "__main__":
    queue_replies()
