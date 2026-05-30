"""
The Tech Tutors — LinkedIn Posting Agent

Commands:
  python run.py auto      — research fresh topic, generate, Discord approval, publish (used by Actions)
  python run.py auto --preview — generate and score without publishing or Discord
  python run.py week      — show this week's schedule and statuses
  python run.py stats     — show engagement stats for this week's posted content
  python run.py plan      — (optional) manually pre-plan this week's 7 slots
  python run.py           — interactive: generate today's post, choose variant, publish
  python run.py --preview — generate today's post but do not publish
"""

import os
import sys
from datetime import date, datetime

from content_generator import (
    choose_weekly_strategy,
    engagement_scorer,
    generate_carousel_content,
    generate_text_post_variants,
    plan_weekly_posts,
)
from designer import generate_carousel_slides
from research import fetch_article_content, fetch_deep_topic_research, fetch_trending_topics
from linkedin_poster import get_post_stats, post_first_comment, post_to_linkedin, post_to_linkedin_with_document, post_to_linkedin_with_image
from scheduler import (
    build_week_slots,
    get_recent_topics,
    get_strategy,
    get_today_slot,
    get_week_overview,
    init_week,
    save_strategy,
    update_slot,
)


def _validate_env(*required: str) -> None:
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[startup] ERROR: Required env vars not set: {', '.join(missing)}")
        print("[startup] Set these as GitHub Secrets or in your .env file.")
        sys.exit(1)


def _timing_note():
    now = datetime.now()
    strategy = get_strategy()
    posting_time = strategy.get("posting_time", "1pm PKT") if strategy else "1pm PKT"
    print(f"Note: it's {now.strftime('%H:%M')} — configured posting time is {posting_time} daily.\n")


def cmd_plan():
    recent = get_recent_topics(weeks_back=2)

    performance_data = None
    try:
        from analytics_tracker import get_performance_summary
        performance_data = get_performance_summary()
    except Exception as e:
        print(f"  [plan] Analytics unavailable: {e}")

    if recent:
        print(f"Avoiding {len(recent)} recently covered themes.\n")

    if performance_data and performance_data.get("top_post_topic"):
        print(f"Using past performance data (best hook: {performance_data['best_hook_type']}, best day: {performance_data['best_day']}).\n")

    # Step 1: Quick pre-fetch (RSS + HN) to ground strategy in real trending data
    print("Quick pre-fetch for strategy grounding (RSS + Hacker News)...")
    from research import fetch_rss_feeds, fetch_hacker_news as _fetch_hn
    pre_fetch = fetch_rss_feeds(max_per_feed=5) + _fetch_hn(max_items=10)

    print("AI choosing this week's content domain and posting strategy...")
    try:
        strategy = choose_weekly_strategy(
            performance_data=performance_data,
            recent_titles=recent,
            trending_sample=pre_fetch[:15] if pre_fetch else None,
        )
        save_strategy(strategy)
        print(f"\n{'='*60}")
        print(f"WEEKLY STRATEGY")
        print(f"  Domain:       {strategy['domain']}")
        print(f"  Pillar:       {strategy.get('content_pillar', '—')}")
        print(f"  Keywords:     {', '.join(strategy.get('focus_keywords', []))}")
        print(f"  Posting time: {strategy['posting_time']}")
        print(f"  Rationale:    {strategy['rationale']}")
        print(f"{'='*60}\n")
    except Exception as e:
        print(f"  Strategy selection failed: {e}. Continuing with general topics.\n")
        strategy = {}

    # Step 3: Full research fetch — Tavily now uses domain-aware queries
    print("Fetching trending AI topics from the web...")
    topics = fetch_trending_topics(
        domain=strategy.get("domain", ""),
        focus_keywords=strategy.get("focus_keywords", []),
    )
    if not topics:
        msg = "Weekly plan failed: no topics fetched. Check internet / API keys."
        print(f"[plan] ERROR: {msg}")
        try:
            from discord_bot import notify_workflow_failure
            notify_workflow_failure(msg)
        except Exception:
            pass
        return

    print(f"Found {len(topics)} topics. Asking AI to score and pick the best 7...\n")
    planned = plan_weekly_posts(
        topics,
        recent_titles=recent,
        performance_data=performance_data,
        strategy=strategy,
    )

    # Preserve already-posted or skipped slots — only overwrite pending ones
    existing = {s["day"]: s for s in get_week_overview()} if get_week_overview() else {}
    slots = build_week_slots()
    for p in planned:
        idx = p.get("day_index", 0)
        if 0 <= idx < len(slots):
            day = slots[idx]["day"]
            ex  = existing.get(day, {})
            if ex.get("status") in ("posted", "skipped"):
                slots[idx] = ex  # keep existing posted/skipped slot intact
            else:
                slots[idx]["topic"] = {
                    "title": p["title"],
                    "source_url": p["source_url"],
                    "angle": p["angle"],
                    "why": p.get("why", ""),
                }
                slots[idx]["format"] = p["format"]

    init_week(slots)

    print("This week's content plan:\n")
    score_map: dict[int, int] = {}
    for idx, slot in enumerate(slots):
        score = next((p.get("score", "—") for p in planned if p.get("day_index") == idx), "—")
        why   = next((p.get("why", "") for p in planned if p.get("day_index") == idx), "")
        if isinstance(score, int):
            score_map[idx] = score
        fmt   = f"[{slot['format']}]" if slot["format"] else "[--]"
        title = slot["topic"]["title"] if slot["topic"] else "— not planned —"
        why_str = f"  ({why})" if why else ""
        print(f"  {slot['day']:10}  {slot['date']}  {fmt:8}  score:{score}  {title}{why_str}")

    print("\nRun 'python run.py' each weekday morning to generate and post.")

    # Send full plan summary to Discord (silently no-ops if channel not configured)
    try:
        from discord_bot import send_weekly_plan
        send_weekly_plan(slots, strategy=strategy or None, scores=score_map)
    except Exception as e:
        print(f"  [plan] Discord notification failed: {e}")


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
    _validate_env("DEEPSEEK_API_KEY")
    _timing_note()
    slot = get_today_slot()

    if not slot:
        if not force:
            print("No slot planned for today. Run 'python run.py plan' first, or use --test to force.")
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
    fmt = slot.get("format") or "text"

    print(f"Day:    {slot['day']} {slot['date']}")
    print(f"Topic:  {topic['title']}")
    print(f"Angle:  {topic['angle']}")
    print(f"Format: {fmt}\n")

    if fmt == "text":
        print("Generating one variant per enabled model...\n")
        variants = generate_text_post_variants(topic)

        if not variants:
            print("No variants produced. Skipping.")
            slot["status"] = "skipped"
            update_slot(slot)
            return

        for i, v in enumerate(variants, 1):
            print(f"VARIANT {i} — {v['display_name']}")
            print("=" * 60)
            print(v["text"])
            print("=" * 60)
            print()

        if preview:
            slot["post_text"] = variants[0]["text"]
            slot["chosen_model"] = variants[0]["model_key"]
            update_slot(slot)
            print("Preview mode — not published.")
            return

        valid_choices = [str(i) for i in range(1, len(variants) + 1)]
        prompt_choices = "/".join(valid_choices)
        choice = input(f"\nWhich variant to post? [{prompt_choices}] (or 'n' to skip): ").strip().lower()
        if choice == "n":
            slot["status"] = "skipped"
            update_slot(slot)
            print("Skipped.")
            return

        if choice not in valid_choices:
            choice = "1"
        chosen = variants[int(choice) - 1]
        post_text = chosen["text"]
        slot["post_text"] = post_text
        slot["chosen_model"] = chosen["model_key"]

        answer = input(f"\nPost {chosen['display_name']}'s version to LinkedIn? [Y/n]: ").strip().lower()
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
        print("Fetching full article content...")
        article_text = fetch_article_content(topic.get("source_url", ""))

        print("Generating one carousel per enabled model...\n")
        variants = generate_carousel_content(topic, article_text=article_text)

        if not variants:
            print("No carousel variants produced. Skipping.")
            slot["status"] = "skipped"
            update_slot(slot)
            return

        for i, v in enumerate(variants, 1):
            content = v["content"]
            print(f"VARIANT {i} — {v['display_name']}")
            print("=" * 60)
            print(f"HOOK    : {content.get('slide1', {}).get('headline', '')}")
            print(f"SLIDE 2 : {content.get('slide2', {}).get('section_title', '')} — {len(content.get('slide2', {}).get('stats', []))} stats")
            print(f"SLIDE 3 : {content.get('slide3', {}).get('section_title', '')} — {len(content.get('slide3', {}).get('impacts', []))} impacts")
            print(f"SLIDE 4 : {content.get('slide4', {}).get('section_title', '')} — {len(content.get('slide4', {}).get('steps', []))} steps")
            print(f"SLIDE 5 : {content.get('slide5', {}).get('takeaway', '')[:80]}...")
            print(f"CAPTION : {len(content.get('caption', ''))} chars")
            print("=" * 60)
            print()

        valid_choices = [str(i) for i in range(1, len(variants) + 1)]
        prompt_choices = "/".join(valid_choices)
        choice = input(f"\nWhich carousel to build and post? [{prompt_choices}] (or 'n' to skip): ").strip().lower()
        if choice == "n":
            slot["status"] = "skipped"
            update_slot(slot)
            print("Skipped.")
            return

        if choice not in valid_choices:
            choice = "1"
        chosen = variants[int(choice) - 1]
        content = chosen["content"]
        slot["design_brief"] = content
        slot["chosen_model"] = chosen["model_key"]

        print(f"\nBuilding 5-slide carousel PDF from {chosen['display_name']}'s content...")
        pdf_path, preview_path = generate_carousel_slides(content, slot["date"])
        print(f"PDF:     {pdf_path}")
        print(f"Preview: {preview_path}\n")

        if preview:
            update_slot(slot)
            print("Preview mode — not published.")
            return

        answer = input("Post this carousel to LinkedIn? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            print("Uploading carousel and publishing...")
            result = post_to_linkedin_with_document(content["caption"], pdf_path)
            slot["status"]   = "posted"
            slot["post_urn"] = result["urn"]
            update_slot(slot)
            print(f"Live: {result['url']}")
        else:
            slot["status"] = "skipped"
            update_slot(slot)
            print("Skipped.")


def cmd_auto(target_date: str | None = None, preview: bool = False):
    """Fully automated run for GitHub Actions — researches fresh topic daily, no plan needed."""
    if not preview:
        _validate_env("DEEPSEEK_API_KEY", "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_ORG_URN")
    else:
        _validate_env("DEEPSEEK_API_KEY")
        print("[auto] Preview mode — will generate and score but NOT publish to LinkedIn.\n")
    from agent_runner import run_agent
    run_agent(target_date=target_date, preview=preview)


def main():
    args = sys.argv[1:]
    if "plan" in args:
        cmd_plan()
    elif "week" in args:
        cmd_week()
    elif "stats" in args:
        cmd_stats()
    elif "auto" in args:
        cmd_auto(preview="--preview" in args)
    else:
        cmd_post(preview="--preview" in args, force="--test" in args)


if __name__ == "__main__":
    main()
