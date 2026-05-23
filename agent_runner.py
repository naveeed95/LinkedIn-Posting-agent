"""
Direct posting pipeline for LinkedIn (no LLM orchestration).
Workflow: get_slot → analytics → research → generate → score → approve → publish.
Called from run.py cmd_auto().
"""

import os
from datetime import datetime


def _log(level: str, msg: str) -> None:
    print(f"[agent][{level}] {datetime.now().strftime('%H:%M:%S')} {msg}")


def run_agent(target_date: str | None = None, preview: bool = False) -> None:
    """Direct posting pipeline. Called from cmd_auto() in run.py."""

    from scheduler import get_today_slot, get_strategy, update_slot
    from content_generator import engagement_scorer, generate_text_post_variants
    from research import fetch_deep_topic_research
    from linkedin_poster import post_first_comment, post_to_linkedin
    from analytics_tracker import get_performance_summary, get_top_hashtags, log_post
    from discord_bot import (
        notify_auto_post,
        notify_timeout,
        send_approval_message,
        send_posted_confirmation,
        wait_for_approval,
    )

    _WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    state: dict = {
        "slot": None,
        "topic": None,
        "day": None,
        "strategy": {},
        "previous_posts": [],
        "generate_count": 0,
        "done": False,
    }

    # ── Tool implementations ───────────────────────────────────────────────────

    def tool_get_today_slot() -> dict:
        if target_date:
            from scheduler import load_schedule, _week_start
            from datetime import date as _date, timedelta
            d = _date.fromisoformat(target_date)
            week_key = (d - timedelta(days=d.weekday())).isoformat()
            week_slots = load_schedule().get(week_key, [])
            slot = next((s for s in week_slots if s.get("date") == target_date), None)
        else:
            slot = get_today_slot()
        if not slot:
            from scheduler import get_week_overview
            week_slots = get_week_overview()
            pending = [s for s in week_slots if s.get("topic") and s.get("status") == "pending"]
            if pending:
                slot = pending[0]
                print(f"[agent] No slot for today — falling back to pending slot: {slot['day']} ({slot['date']})")
            else:
                try:
                    from discord_bot import notify_workflow_failure
                    notify_workflow_failure(
                        "⚠️ **No content plan for this week** — run `python run.py plan` "
                        "to generate the week's schedule, then re-trigger the daily post."
                    )
                except Exception:
                    pass
                return {"status": "no_slot", "message": "No slot planned for today. Run plan first."}
        if slot.get("status") in ("posted", "skipped"):
            return {"status": "already_posted", "date": slot["date"]}
        if slot.get("post_urn"):
            slot["status"] = "posted"
            try:
                update_slot(slot)
            except Exception as e:
                print(f"[agent] WARNING: failed to persist slot: {e}")
            return {"status": "already_posted", "date": slot["date"]}

        state["slot"] = slot
        state["strategy"] = get_strategy()
        state["topic"] = slot.get("topic") or {}
        state["day"] = slot["day"]

        return {
            "status": "ok",
            "day": slot["day"],
            "date": slot["date"],
            "topic_title": state["topic"].get("title", ""),
            "angle": state["topic"].get("angle", ""),
            "format": slot.get("format") or "text",
            "focus_keywords": state["strategy"].get("focus_keywords", []),
            "domain": state["strategy"].get("domain", "AI"),
        }

    def tool_get_analytics_summary() -> dict:
        try:
            summary = get_performance_summary()
            hashtags = get_top_hashtags(n=10)
            return {**summary, "top_hashtags": hashtags}
        except Exception as e:
            return {"error": str(e), "message": "Analytics unavailable — continue without it"}

    def tool_research_topic(topic_title: str, keywords: list | None = None) -> dict:
        try:
            kws = keywords or state["strategy"].get("focus_keywords", [])
            results = fetch_deep_topic_research(topic_title, kws)
            state["research"] = results or []
            if results:
                state["topic"]["research_context"] = "\n".join(
                    f"- [{r['source']}] {r['title']}: {r.get('description', '')}"
                    for r in results[:5]
                )
            return {
                "sources_found": len(results) if results else 0,
                "top_sources": [
                    {"title": r["title"], "source": r["source"]}
                    for r in (results or [])[:5]
                ],
            }
        except Exception as e:
            return {"error": str(e), "sources_found": 0}

    def tool_generate_post(hint: str = "") -> dict:
        if state["generate_count"] >= 3:
            return {"error": "Max generation attempts (3) reached — must proceed or skip"}
        state["generate_count"] += 1
        try:
            top_hashtags: list = []
            try:
                top_hashtags = get_top_hashtags(n=10)
            except Exception:
                pass

            variants = generate_text_post_variants(
                state["topic"],
                hint=hint,
                previous=state["previous_posts"] or None,
                top_hashtags=top_hashtags or None,
            )
            if not variants:
                return {"error": "Generator returned no variants"}

            v = variants[0]
            state["previous_posts"].append(v["text"])
            return {
                "post_text": v["text"],
                "model_key": v["model_key"],
                "display_name": v["display_name"],
                "char_count": len(v["text"]),
                "attempt": state["generate_count"],
                "attempts_remaining": 3 - state["generate_count"],
            }
        except Exception as e:
            return {"error": str(e)}

    def tool_score_post(post_text: str) -> dict:
        try:
            past = get_performance_summary()
        except Exception:
            past = {}
        result = engagement_scorer(post_text, past)
        score = result["score"]
        advice = result.get("advice", "")
        recent_avg = past.get("recent_avg_score", 0)
        threshold = max(55, min(75, round(recent_avg * 0.9))) if recent_avg > 0 else 62
        return {
            "score": score,
            "threshold": threshold,
            "verdict": "excellent" if score >= threshold else "weak",
            "ready_to_send": score >= threshold,
            "advice": "" if score >= threshold else advice,
        }

    def tool_send_for_approval(post_text: str, score: int = 0) -> dict:
        if preview:
            print("\n" + "=" * 60)
            print(f"[PREVIEW] Score: {score}/100  |  Day: {state['day']}")
            print("=" * 60)
            print(post_text)
            print("=" * 60 + "\n")
            print("[preview] Auto-approving — not sending to Discord.")
            return {"action": "post", "auto": True}

        topic = state["topic"]
        day = state["day"]
        variants = [{"model_key": "deepseek-pro", "display_name": "DeepSeek Chat", "text": post_text}]
        msg_id = send_approval_message(variants, [score], topic, day)

        if not msg_id:
            print("[agent] WARNING: Discord not configured — cannot request approval. Skipping today's post.")
            print("[agent] Set DISCORD_BOT_TOKEN and DISCORD_APPROVALS_CHANNEL_ID to enable approval flow.")
            return {"action": "skip", "reason": "Discord not configured — approval required but unavailable"}

        decision = wait_for_approval(msg_id, timeout_minutes=120, num_variants=1)
        return {
            "action": decision.get("action"),
            "hint": decision.get("hint", ""),
            "custom_text": decision.get("text", ""),
        }

    def tool_publish_post(post_text: str, chosen_model: str = "deepseek-pro") -> dict:
        if not state.get("slot"):
            return {"status": "error", "error": "No slot in state — cannot publish"}
        slot = state["slot"]
        topic = state["topic"]
        day = state["day"]
        if preview:
            print("[preview] Publish skipped — preview mode active.")
            slot["post_text"] = post_text
            slot["chosen_model"] = chosen_model
            state["done"] = True
            return {"status": "preview", "message": "Post generated and scored — not published."}
        try:
            result = post_to_linkedin(post_text)
            slot["status"] = "posted"
            slot["post_urn"] = result["urn"]
            slot["post_text"] = post_text
            slot["chosen_model"] = chosen_model
            try:
                update_slot(slot)
            except Exception as e:
                print(f"[agent] WARNING: failed to persist slot: {e}")

            try:
                log_post({
                    "post_urn": result["urn"],
                    "post_text": post_text,
                    "topic_title": topic.get("title", ""),
                    "day_of_week": day,
                    "posted_at": datetime.now().isoformat(),
                    "variant_chosen": 1,
                    "chosen_model": chosen_model,
                })
            except Exception as e:
                print(f"  [agent] Analytics log failed: {e}")

            source_url = topic.get("source_url", "")
            landing = os.environ.get("LANDING_PAGE_URL", "")
            if source_url:
                comment = f"Source: {source_url}"
                if landing:
                    comment += f"\n\nLearn more: {landing}"
                post_first_comment(result["urn"], comment)

            send_posted_confirmation(result["url"], 1, post_text)
            state["done"] = True
            print(f"[agent] Live: {result['url']}")
            return {"status": "published", "url": result["url"], "urn": result["urn"]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def tool_skip_today(reason: str = "") -> dict:
        slot = state["slot"]
        if slot:
            slot["status"] = "skipped"
            try:
                update_slot(slot)
            except Exception as e:
                print(f"[agent] WARNING: failed to persist slot: {e}")
            try:
                notify_timeout(state["day"], slot.get("date", ""))
            except Exception as e:
                print(f"[agent] notify_timeout failed: {e}")
        state["done"] = True
        print(f"[agent] Skipped: {reason}")
        return {"status": "skipped", "reason": reason}

    # ── Direct pipeline ────────────────────────────────────────────────────────

    _log("INFO", "Starting posting pipeline...")

    # 1. Slot
    slot_result = tool_get_today_slot()
    _log("INFO", f"Slot status: {slot_result['status']}")
    if slot_result["status"] in ("no_slot", "already_posted"):
        return

    # 2. Analytics (for hint context in generation)
    tool_get_analytics_summary()

    # 3. Research
    topic_title = state["topic"].get("title", "")
    keywords = state["strategy"].get("focus_keywords", [])
    research_result = tool_research_topic(topic_title, keywords)
    _log("INFO", f"Research: {research_result.get('sources_found', 0)} sources")

    # 4–5. Generate + score (up to 3 attempts, stop early if score >= 80)
    post_text = ""
    score = 0
    hint = ""
    for attempt in range(3):
        gen = tool_generate_post(hint=hint)
        if "error" in gen:
            _log("ERROR", f"Generation failed: {gen['error']}")
            tool_skip_today(f"Generation failed: {gen['error']}")
            return
        post_text = gen["post_text"]

        scored = tool_score_post(post_text)
        score = scored["score"]
        _log("INFO", f"Attempt {attempt + 1}/3 — score {score}/100")

        if scored["ready_to_send"] or attempt == 2:
            break
        hint = scored.get("advice") or "punchier hook, add a specific stat or number"

    # 6–7. Approval + publish (loop handles regenerate-after-approval)
    while True:
        decision = tool_send_for_approval(post_text, score)
        action = decision.get("action", "skip")

        if action == "post":
            tool_publish_post(post_text)
            return

        elif action == "edit":
            custom = decision.get("custom_text", "").strip()
            tool_publish_post(custom or post_text, chosen_model="human-edit")
            return

        elif action == "regenerate" and state["generate_count"] < 3:
            gen = tool_generate_post(hint=decision.get("hint", ""))
            if "error" in gen:
                _log("ERROR", f"Regeneration failed: {gen['error']}")
                tool_skip_today(f"Regeneration failed: {gen['error']}")
                return
            post_text = gen["post_text"]
            scored = tool_score_post(post_text)
            score = scored["score"]
            _log("INFO", f"Regenerated — score {score}/100")
            # loop back to send_for_approval with new post

        elif action == "timeout":
            _log("INFO", "Approval timeout — auto-publishing variant 1.")
            try:
                notify_auto_post(state["day"], (state["slot"] or {}).get("date", ""))
            except Exception:
                pass
            tool_publish_post(post_text)
            return

        else:
            reason = "max regenerations reached" if action == "regenerate" else action
            tool_skip_today(reason)
            return
