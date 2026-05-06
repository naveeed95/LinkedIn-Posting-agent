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
    DAY_FORMAT,
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


def _timing_note():
    now = datetime.now()
    if not (12 <= now.hour <= 15):
        print(f"Note: it's {now.strftime('%H:%M')} — scheduled posting time is 1pm PKT daily.\n")


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
        print("ERROR: No topics fetched. Check your internet connection.")
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
    _timing_note()
    slot = get_today_slot()

    if not slot:
        today = date.today()
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
    _weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    fmt = DAY_FORMAT.get(_weekdays.index(slot["day"]) if slot["day"] in _weekdays else 0, "text")

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


def cmd_auto():
    """Fully automated run for GitHub Actions: research → generate → Discord approval → post."""
    from analytics_tracker import get_performance_summary, get_topic_history, log_post
    from discord_bot import (
        send_approval_message,
        send_design_approval_message,
        send_posted_confirmation,
        wait_for_approval,
    )

    _timing_note()

    slot = get_today_slot()
    if not slot:
        print("No slot found for today. Run 'python run.py plan' first.")
        return

    if slot["status"] == "posted":
        print(f"Already posted today ({slot['date']}).")
        return

    # Idempotency guard: a prior run may have published successfully but
    # crashed before update_slot persisted status. If post_urn is set we know
    # the post is already live — repair status and exit instead of double-posting.
    if slot.get("post_urn"):
        print(f"Post URN already recorded for today ({slot['post_urn']}). Marking posted and exiting.")
        slot["status"] = "posted"
        update_slot(slot)
        return

    topic = slot["topic"]
    _weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    fmt = DAY_FORMAT.get(_weekdays.index(slot["day"]) if slot["day"] in _weekdays else 0, "text")
    day = slot["day"]

    strategy       = get_strategy()
    focus_keywords = strategy.get("focus_keywords", [])
    domain         = strategy.get("domain", "AI")

    print(f"\nDay:    {day} {slot['date']}")
    print(f"Topic:  {topic['title']}")
    print(f"Angle:  {topic['angle']}")
    print(f"Format: {fmt}")
    print(f"Domain: {domain}\n")

    print("Fetching latest research for today's topic...")
    try:
        fresh = fetch_deep_topic_research(topic["title"], focus_keywords)
        if fresh:
            topic["research_context"] = "\n".join(
                f"- [{r['source']}] {r['title']}: {r.get('description', '')}"
                for r in fresh[:5]
            )
            print(f"  Found {len(fresh)} fresh sources.\n")
    except Exception as e:
        print(f"  Deep research failed: {e}\n")

    past_performance = {}
    try:
        past_performance = get_performance_summary()
    except Exception:
        pass

    top_hashtags: list[str] = []
    try:
        from analytics_tracker import get_top_hashtags
        top_hashtags = get_top_hashtags(n=10)
    except Exception:
        pass

    top_urls = []
    try:
        from analytics_tracker import get_top_post_urls
        top_urls = get_top_post_urls(n=3)
    except Exception as e:
        print(f"  [auto] Could not fetch top post URLs: {e}")

    max_regenerations = 3

    # ── Design post flow ──────────────────────────────────────────────────────
    if fmt == "design":
        hint = ""
        article_text = fetch_article_content(topic.get("source_url", ""))

        for attempt in range(max_regenerations + 1):
            print(f"Generating one carousel per enabled model (attempt {attempt + 1})...")
            variants = generate_carousel_content(
                topic,
                article_text=article_text,
                top_hashtags=top_hashtags or None,
            )

            for i, v in enumerate(variants, 1):
                print(f"  [{i}] {v['display_name']}: hook='{v['content'].get('slide1', {}).get('headline', '')[:60]}...'")

            msg_id = send_design_approval_message(variants, topic, day)
            if not msg_id:
                print("Discord not configured — falling back to interactive mode.")
                cmd_post()
                return

            decision = wait_for_approval(
                msg_id,
                timeout_minutes=120,
                num_variants=len(variants),
            )
            action = decision.get("action")

            if action == "post":
                idx = decision.get("variant_index", 0)
                if idx >= len(variants):
                    idx = 0
                chosen  = variants[idx]
                content = chosen["content"]

                print(f"Building 5-slide carousel PDF from {chosen['display_name']}'s content...")
                pdf_path, _ = generate_carousel_slides(content, slot["date"])

                print("Uploading carousel to LinkedIn...")
                result = post_to_linkedin_with_document(content["caption"], pdf_path)
                slot["status"]       = "posted"
                slot["post_urn"]     = result["urn"]
                slot["design_brief"] = content
                slot["chosen_model"] = chosen["model_key"]
                update_slot(slot)

                try:
                    log_post({
                        "post_urn":       result["urn"],
                        "post_text":      content["caption"],
                        "topic_title":    topic["title"],
                        "day_of_week":    day,
                        "posted_at":      datetime.now().isoformat(),
                        "variant_chosen": idx + 1,
                        "chosen_model":   chosen["model_key"],
                    })
                except Exception as e:
                    print(f"  [auto] Analytics log failed: {e}")

                source_url = topic.get("source_url", "")
                landing = os.environ.get("LANDING_PAGE_URL", "")
                if source_url:
                    comment = f"Source: {source_url}"
                    if landing:
                        comment += f"\n\nLearn more: {landing}"
                    if post_first_comment(result["urn"], comment):
                        print("First comment with source link posted.")

                send_posted_confirmation(result["url"], idx + 1, content["caption"])
                print(f"Live: {result['url']} (model: {chosen['display_name']})")
                return

            elif action == "regenerate":
                hint = decision.get("hint", "")
                print(f"Regenerating carousels with hint: '{hint}'...")
                topic["regen_hint"] = hint
                if attempt >= max_regenerations:
                    print("Max regenerations reached. Skipping today.")
                    slot["status"] = "skipped"
                    update_slot(slot)
                    return
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
                from discord_bot import notify_timeout
                notify_timeout(day, slot["date"])
                return

    # ── Text post flow ────────────────────────────────────────────────────────
    else:
        previous_variants: list[str] = []
        hint = ""

        for attempt in range(max_regenerations + 1):
            print(f"Generating one post per enabled model (attempt {attempt + 1})...")
            variants = generate_text_post_variants(
                topic,
                hint=hint,
                previous=previous_variants or None,
                top_hashtags=top_hashtags or None,
            )
            scores = [engagement_scorer(v["text"], past_performance) for v in variants]

            for v, s in zip(variants, scores):
                print(f"  {v['display_name']}: score {s}/100")

            msg_id = send_approval_message(variants, scores, topic, day)
            if not msg_id:
                print("Discord not configured — falling back to interactive mode.")
                cmd_post()
                return

            decision = wait_for_approval(
                msg_id,
                timeout_minutes=120,
                num_variants=len(variants),
            )
            action = decision.get("action")

            if action == "post":
                idx = decision.get("variant_index", 0)
                if idx >= len(variants):
                    idx = 0
                chosen    = variants[idx]
                post_text = chosen["text"]
                slot["post_text"]    = post_text
                slot["chosen_model"] = chosen["model_key"]

                print(f"Publishing {chosen['display_name']}'s version to LinkedIn...")
                result = post_to_linkedin(post_text)
                slot["status"]   = "posted"
                slot["post_urn"] = result["urn"]
                update_slot(slot)

                try:
                    log_post({
                        "post_urn":       result["urn"],
                        "post_text":      post_text,
                        "topic_title":    topic["title"],
                        "day_of_week":    day,
                        "posted_at":      datetime.now().isoformat(),
                        "variant_chosen": idx + 1,
                        "chosen_model":   chosen["model_key"],
                    })
                except Exception as e:
                    print(f"  [auto] Analytics log failed: {e}")

                source_url = topic.get("source_url", "")
                landing = os.environ.get("LANDING_PAGE_URL", "")
                if source_url:
                    comment = f"Source: {source_url}"
                    if landing:
                        comment += f"\n\nLearn more: {landing}"
                    if post_first_comment(result["urn"], comment):
                        print("First comment with source link posted.")

                send_posted_confirmation(result["url"], idx + 1, post_text)
                print(f"Live: {result['url']} (model: {chosen['display_name']})")
                return

            elif action == "edit":
                post_text = decision["text"]
                slot["post_text"]    = post_text
                slot["chosen_model"] = "human-edit"
                print("Publishing custom text to LinkedIn...")
                result = post_to_linkedin(post_text)
                slot["status"]   = "posted"
                slot["post_urn"] = result["urn"]
                update_slot(slot)
                try:
                    log_post({
                        "post_urn":       result["urn"],
                        "post_text":      post_text,
                        "topic_title":    topic["title"],
                        "day_of_week":    day,
                        "posted_at":      datetime.now().isoformat(),
                        "variant_chosen": 0,
                        "chosen_model":   "human-edit",
                    })
                except Exception:
                    pass
                send_posted_confirmation(result["url"], 0, post_text)
                print(f"Live: {result['url']}")
                return

            elif action == "regenerate":
                hint = decision.get("hint", "")
                previous_variants = [v["text"] for v in variants]
                print(f"Regenerating with hint: '{hint}'...")
                if attempt >= max_regenerations:
                    print("Max regenerations reached. Skipping today.")
                    slot["status"] = "skipped"
                    update_slot(slot)
                    return
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
                from discord_bot import notify_timeout
                notify_timeout(day, slot["date"])
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
