"""
The Tech Tutors — LinkedIn Posting Agent

Commands:
  python run.py plan      — research trending topics and plan this week's 5 posts
  python run.py week      — show this week's schedule and statuses
  python run.py stats     — show engagement stats for this week's posted content
  python run.py           — generate today's post, pick a variant, approve, publish
  python run.py --preview — generate today's post but do not publish
"""

import os
import sys
from datetime import date, datetime

from content_generator import (
    engagement_scorer,
    generate_design_brief,
    generate_text_post_variants,
    plan_weekly_posts,
)
from designer import generate_graphic
from linkedin_poster import get_post_stats, post_first_comment, post_to_linkedin, post_to_linkedin_with_image
from research import fetch_trending_topics
from scheduler import (
    build_week_slots,
    get_recent_topics,
    get_today_slot,
    get_week_overview,
    init_week,
    update_slot,
)


def _timing_note():
    now = datetime.now()
    if now.weekday() < 5 and not (7 <= now.hour <= 11):
        print(f"Note: it's {now.strftime('%H:%M')} — best LinkedIn engagement is 8–10am weekdays.\n")


def cmd_plan():
    print("Fetching trending AI topics from the web...")
    topics = fetch_trending_topics()
    if not topics:
        print("ERROR: No topics fetched. Check your internet connection.")
        return

    recent = get_recent_topics(weeks_back=2)
    if recent:
        print(f"Avoiding {len(recent)} recently covered themes.\n")

    print(f"Found {len(topics)} topics. Asking Claude to score and pick the best 5...\n")
    planned = plan_weekly_posts(topics, recent_titles=recent)

    slots = build_week_slots()
    for p in planned:
        idx = p.get("day_index", 0)
        if 0 <= idx < len(slots):
            slots[idx]["topic"] = {
                "title": p["title"],
                "source_url": p["source_url"],
                "angle": p["angle"],
            }
            slots[idx]["format"] = p["format"]

    init_week(slots)

    print("This week's content plan:\n")
    for slot in slots:
        score = next((p.get("score", "—") for p in planned if p.get("day_index") == slots.index(slot)), "—")
        fmt   = f"[{slot['format']}]" if slot["format"] else "[--]"
        title = slot["topic"]["title"] if slot["topic"] else "— not planned —"
        print(f"  {slot['day']:10}  {slot['date']}  {fmt:8}  score:{score}  {title}")

    print("\nRun 'python run.py' each weekday morning to generate and post.")


def cmd_week():
    slots = get_week_overview()
    if not slots:
        print("No plan for this week. Run: python run.py plan")
        return
    print("This week's schedule:\n")
    for slot in slots:
        status = slot.get("status", "pending")
        fmt    = f"[{slot['format']}]" if slot.get("format") else "[--]"
        title  = slot["topic"]["title"] if slot.get("topic") else "— not planned —"
        print(f"  {slot['day']:10}  {slot['date']}  {fmt:8}  [{status:8}]  {title}")


def cmd_stats():
    slots = get_week_overview()
    if not slots:
        print("No schedule this week.")
        return
    print("This week's post performance:\n")
    any_stats = False
    for slot in slots:
        if slot.get("status") == "posted" and slot.get("post_urn"):
            stats = get_post_stats(slot["post_urn"])
            title = slot["topic"]["title"] if slot.get("topic") else "—"
            likes    = stats.get("likes", "—")
            comments = stats.get("comments", "—")
            print(f"  {slot['day']:10}  {likes} likes  {comments} comments  — {title}")
            any_stats = True
    if not any_stats:
        print("  No posted content with URNs found yet.")


def cmd_post(preview: bool = False, force: bool = False):
    _timing_note()
    slot = get_today_slot()

    if not slot:
        today = date.today()
        if today.weekday() >= 5 and not force:
            print("Today is a weekend — no post scheduled.")
            print("Tip: use 'python run.py --test' to force-generate from this week's plan.")
            return
        slots = get_week_overview()
        planned = [s for s in slots if s.get("topic") and s.get("status") == "pending"]
        if not planned:
            print("No pending slots found. Run 'python run.py plan' first.")
            return
        slot = planned[-1]
        print(f"Test mode — using slot: {slot['day']} ({slot['date']})\n")

    if slot["status"] == "posted":
        print(f"Already posted today ({slot['date']}). Check weekly_schedule.json for the content.")
        return

    topic = slot["topic"]
    fmt   = slot["format"]

    print(f"Day:    {slot['day']} {slot['date']}")
    print(f"Topic:  {topic['title']}")
    print(f"Angle:  {topic['angle']}")
    print(f"Format: {fmt}\n")

    if fmt == "text":
        print("Generating 2 post variants with Claude...\n")
        variants = generate_text_post_variants(topic, n=2)

        print("VARIANT 1")
        print("=" * 60)
        print(variants[0])
        print("=" * 60)
        print("\nVARIANT 2")
        print("=" * 60)
        print(variants[1])
        print("=" * 60)

        if preview:
            slot["post_text"] = variants[0]
            update_slot(slot)
            print("\nPreview mode — not published.")
            return

        choice = input("\nWhich variant to post? [1/2] (or 'n' to skip): ").strip().lower()
        if choice == "n":
            slot["status"] = "skipped"
            update_slot(slot)
            print("Skipped.")
            return

        post_text = variants[1] if choice == "2" else variants[0]
        slot["post_text"] = post_text

        answer = input("\nPost this to LinkedIn? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            print("Publishing to company page...")
            result = post_to_linkedin(post_text)
            slot["status"]   = "posted"
            slot["post_urn"] = result["urn"]
            update_slot(slot)
            print(f"Live: {result['url']}")
        else:
            slot["status"] = "skipped"
            update_slot(slot)
            print("Skipped.")

    elif fmt == "design":
        print("Generating design brief with Claude...\n")
        brief = generate_design_brief(topic)
        slot["design_brief"] = brief

        print("=" * 60)
        print(f"TEMPLATE      : {brief.get('template', 'list').upper()}")
        print(f"GRAPHIC TITLE : {brief['graphic_title']}")
        print(f"LAYOUT        : {brief['graphic_layout']}")
        print("\nGRAPHIC POINTS:")
        for i, pt in enumerate(brief["graphic_points"], 1):
            print(f"  {i}. {pt}")
        print("\nCAPTION TO POST:")
        print(brief["caption"])
        print("=" * 60)

        print("\nGenerating graphic with Pillow...")
        image_path = generate_graphic(brief, slot["date"])
        print(f"Graphic saved: {image_path}\n")

        if preview:
            update_slot(slot)
            print("Preview mode — not published.")
            return

        answer = input("Post this graphic + caption to LinkedIn? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            print("Uploading image and publishing...")
            result = post_to_linkedin_with_image(brief["caption"], image_path)
            slot["status"]   = "posted"
            slot["post_urn"] = result["urn"]
            update_slot(slot)
            print(f"Live: {result['url']}")
        else:
            slot["status"] = "skipped"
            update_slot(slot)
            print("Skipped.")


def cmd_auto():
    """Fully automated run for GitHub Actions: research → generate → Discord approval → post."""
    from analytics_tracker import get_performance_summary, get_topic_history, log_post
    from discord_bot import (
        send_approval_message,
        send_posted_confirmation,
        wait_for_approval,
    )

    _timing_note()

    # 1. Get today's scheduled slot
    slot = get_today_slot()
    if not slot:
        today = date.today()
        if today.weekday() >= 5:
            print("Today is a weekend — no post scheduled.")
            return
        print("No slot found for today. Run 'python run.py plan' first.")
        return

    if slot["status"] == "posted":
        print(f"Already posted today ({slot['date']}).")
        return

    topic = slot["topic"]
    day = slot["day"]

    print(f"\nDay:   {day} {slot['date']}")
    print(f"Topic: {topic['title']}")
    print(f"Angle: {topic['angle']}\n")

    # 2. Get past performance for scoring
    past_performance = {}
    try:
        past_performance = get_performance_summary()
    except Exception:
        pass

    # 3. Get top post URLs for Exa similar search
    top_urls = []
    try:
        from analytics_tracker import _connect
        with _connect() as conn:
            rows = conn.execute(
                """SELECT p.post_id FROM posts p
                   JOIN metrics m ON p.post_id = m.post_id
                   ORDER BY (m.likes + m.comments * 2 + m.shares * 3) DESC
                   LIMIT 3"""
            ).fetchall()
            top_urls = [
                f"https://www.linkedin.com/feed/update/{r['post_id']}/"
                for r in rows if r["post_id"]
            ]
    except Exception:
        pass

    # 4. Generate 2 variants with regeneration loop
    previous_variants: list[str] = []
    hint = ""
    max_regenerations = 3

    for attempt in range(max_regenerations + 1):
        print(f"Generating post variants (attempt {attempt + 1})...")
        variants = generate_text_post_variants(
            topic, n=2, hint=hint, previous=previous_variants or None
        )
        scores = [engagement_scorer(v, past_performance) for v in variants]

        print(f"Variant 1 score: {scores[0]}/100")
        print(f"Variant 2 score: {scores[1]}/100")

        # 5. Send to Discord for approval
        msg_id = send_approval_message(variants, scores, topic, day)
        if not msg_id:
            print("Discord not configured — falling back to interactive mode.")
            cmd_post()
            return

        # 6. Wait for human decision
        decision = wait_for_approval(msg_id, timeout_minutes=120)
        action = decision.get("action")

        if action == "post":
            variant_num = decision.get("variant", 1)
            post_text = variants[variant_num - 1]
            slot["post_text"] = post_text

            print(f"Publishing variant {variant_num} to LinkedIn...")
            result = post_to_linkedin(post_text)
            slot["status"] = "posted"
            slot["post_urn"] = result["urn"]
            update_slot(slot)

            # Log to analytics DB
            try:
                log_post({
                    "post_urn": result["urn"],
                    "post_text": post_text,
                    "topic_title": topic["title"],
                    "day_of_week": day,
                    "posted_at": datetime.now().isoformat(),
                    "variant_chosen": variant_num,
                })
            except Exception as e:
                print(f"  [auto] Analytics log failed: {e}")

            # Post source URL as first comment
            source_url = topic.get("source_url", "")
            landing = os.environ.get("LANDING_PAGE_URL", "")
            if source_url:
                from linkedin_poster import post_first_comment
                comment = f"Source: {source_url}"
                if landing:
                    comment += f"\n\nLearn more: {landing}"
                if post_first_comment(result["urn"], comment):
                    print("First comment with source link posted.")

            send_posted_confirmation(result["url"], variant_num, post_text)
            print(f"Live: {result['url']}")
            return

        elif action == "edit":
            post_text = decision["text"]
            slot["post_text"] = post_text
            print("Publishing custom text to LinkedIn...")
            result = post_to_linkedin(post_text)
            slot["status"] = "posted"
            slot["post_urn"] = result["urn"]
            update_slot(slot)
            try:
                log_post({
                    "post_urn": result["urn"],
                    "post_text": post_text,
                    "topic_title": topic["title"],
                    "day_of_week": day,
                    "posted_at": datetime.now().isoformat(),
                    "variant_chosen": 0,
                })
            except Exception:
                pass
            send_posted_confirmation(result["url"], 0, post_text)
            print(f"Live: {result['url']}")
            return

        elif action == "regenerate":
            hint = decision.get("hint", "")
            previous_variants = variants
            print(f"Regenerating with hint: '{hint}'...")
            if attempt >= max_regenerations:
                print("Max regenerations reached. Skipping today.")
                slot["status"] = "skipped"
                update_slot(slot)
            continue

        elif action == "skip":
            slot["status"] = "skipped"
            update_slot(slot)
            print("Skipped. Logged in schedule.")
            return

        else:  # timeout
            slot["status"] = "skipped"
            update_slot(slot)
            print("No response within timeout. Logged as missed.")
            from discord_bot import _send_message, _channel
            _send_message(
                _channel("DISCORD_APPROVALS_CHANNEL_ID"),
                f"⚠️ **No approval received** for today's post ({day} {slot['date']}). Logged as missed."
            )
            return


def main():
    args = sys.argv[1:]
    if "plan" in args:
        cmd_plan()
    elif "week" in args:
        cmd_week()
    elif "stats" in args:
        cmd_stats()
    elif "auto" in args:
        cmd_auto()
    else:
        cmd_post(preview="--preview" in args, force="--test" in args)


if __name__ == "__main__":
    main()
