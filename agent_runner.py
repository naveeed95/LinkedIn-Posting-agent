"""
Direct posting pipeline for LinkedIn — no weekly plan required.
Workflow: research → pick topic → deep research → generate → score → approve → publish.
Called from run.py cmd_auto().
"""

import os
from datetime import datetime, date

from logger import get_logger

log_agent = get_logger("agent")
log_preview = get_logger("preview")


def _log(level: str, msg: str) -> None:
    fn = log_agent.warning if level.upper() in ("WARNING", "ERROR") else log_agent.info
    fn(msg)


def run_agent(target_date: str | None = None, preview: bool = False) -> None:
    """Direct posting pipeline. Called from cmd_auto() in run.py."""

    from content_generator import engagement_scorer, generate_text_post_variants, pick_daily_topic
    from research import fetch_trending_topics, fetch_deep_topic_research
    from linkedin_poster import post_first_comment, post_to_linkedin
    from analytics_tracker import (
        get_performance_summary,
        get_recent_topic_texts,
        get_top_hashtags,
        get_topic_history,
        log_post,
    )
    from discord_bot import (
        notify_auto_post,
        notify_timeout,
        send_approval_message,
        send_posted_confirmation,
        wait_for_approval,
    )

    today = date.fromisoformat(target_date) if target_date else date.today()

    MAX_TOPIC_SWITCHES = 1  # how many times "new topic" can be requested per run

    state: dict = {
        "topic": None,
        "topic_pool": [],
        "recent_titles": [],
        "tried_titles": set(),
        "topic_switches": 0,
        "day": today.strftime("%A"),
        "date": today.isoformat(),
        "previous_posts": [],
        "generate_count": 0,
        "done": False,
    }

    # ── Tool implementations ───────────────────────────────────────────────────

    def tool_pick_daily_topic() -> dict:
        """Research trending topics and pick the best one for today."""
        # Dedup: skip if already posted today (checked via analytics DB)
        try:
            today_topics = get_topic_history(days=1)
            if today_topics:
                return {"status": "already_posted", "date": state["date"]}
        except Exception as e:
            _log("WARNING", f"Dedup check failed: {e}")

        # Recent topics for repetition avoidance (last 30 days, LLM avoid-list)
        recent_titles: list[str] = []
        try:
            recent_titles = get_topic_history(days=30)
        except Exception as e:
            _log("WARNING", f"Could not fetch recent topics: {e}")

        # Recent topic texts for semantic-similarity dedup penalty (last 10 days,
        # decaying — catches "same story, reworded headline" that title-matching misses)
        recent_topic_texts: list[dict] = []
        try:
            recent_topic_texts = get_recent_topic_texts(days=10)
        except Exception as e:
            _log("WARNING", f"Could not fetch recent topic texts for dedup scoring: {e}")

        _log("INFO", "Fetching trending topics from all sources...")
        try:
            from analytics_tracker import get_top_post_urls

            top_urls = get_top_post_urls(n=3)
        except Exception:
            top_urls = []

        topics = fetch_trending_topics(top_post_urls=top_urls or None, recent_topics=recent_topic_texts or None)
        if not topics:
            return {"status": "no_topics", "message": "No topics found from research sources"}

        _log("INFO", f"Found {len(topics)} topics — LLM picking best one for today...")

        try:
            topic = pick_daily_topic(topics[:30], recent_titles=recent_titles)
        except Exception as e:
            _log("WARNING", f"LLM topic pick failed ({e}) — falling back to top-scored topic")
            t = topics[0]
            topic = {
                "title": t["title"],
                "source_url": t.get("url", ""),
                "angle": t.get("description", t["title"]),
                "why": "Top-scored topic by SMB relevance",
                "format": "text",
            }

        state["topic"] = topic
        state["topic_pool"] = topics[:30]
        state["recent_titles"] = recent_titles
        state["tried_titles"] = {topic.get("title", "")}
        return {
            "status": "ok",
            "day": state["day"],
            "date": state["date"],
            "topic_title": topic.get("title", ""),
            "angle": topic.get("angle", ""),
            "format": topic.get("format", "text"),
        }

    def tool_pick_new_topic(hint: str = "") -> dict:
        """Re-pick a different topic from today's already-fetched pool (used for
        the Discord 'new topic' request — avoids re-running research from scratch)."""
        pool = state.get("topic_pool", [])
        tried = state.get("tried_titles", set())
        candidates = [t for t in pool if t["title"] not in tried]
        if not candidates:
            return {"status": "no_more_topics"}

        avoid_titles = list(state.get("recent_titles", [])) + list(tried)
        try:
            topic = pick_daily_topic(candidates[:30], recent_titles=avoid_titles, steer_hint=hint)
        except Exception as e:
            _log("WARNING", f"New-topic pick failed ({e}) — using next-highest-scored alternative")
            t = candidates[0]
            topic = {
                "title": t["title"],
                "source_url": t.get("url", ""),
                "angle": t.get("description", t["title"]),
                "why": "Next-highest-scored alternative topic",
                "format": "text",
            }

        state["topic"] = topic
        state["tried_titles"].add(topic.get("title", ""))
        state["generate_count"] = 0
        state["previous_posts"] = []
        state.pop("research", None)
        return {
            "status": "ok",
            "topic_title": topic.get("title", ""),
            "angle": topic.get("angle", ""),
        }

    def tool_get_analytics_summary() -> dict:
        try:
            summary = get_performance_summary()
            hashtags = get_top_hashtags(n=10)
            return {**summary, "top_hashtags": hashtags}
        except Exception as e:
            return {"error": str(e), "message": "Analytics unavailable — continue without it"}

    def tool_research_topic() -> dict:
        topic = state["topic"] or {}
        topic_title = topic.get("title", "")
        # Derive keywords from angle + title for deep research
        angle = topic.get("angle", "")
        keywords = [w for w in angle.split() if len(w) > 5][:4] if angle else []
        try:
            results = fetch_deep_topic_research(topic_title, keywords)
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

    def _generate_and_score(initial_hint: str = "") -> tuple[str | None, int]:
        """Run the generate -> score loop (up to 3 attempts total, shared budget
        with state['generate_count']), stopping early once the score clears the
        dynamic threshold. Returns (post_text, score), or (None, 0) on failure
        (tool_skip_today already called in that case)."""
        post_text = ""
        score = 0
        hint = initial_hint
        while state["generate_count"] < 3:
            gen = tool_generate_post(hint=hint)
            if "error" in gen:
                _log("ERROR", f"Generation failed: {gen['error']}")
                tool_skip_today(f"Generation failed: {gen['error']}")
                return None, 0
            post_text = gen["post_text"]

            scored = tool_score_post(post_text)
            score = scored["score"]
            _log("INFO", f"Attempt {state['generate_count']}/3 — score {score}/100")

            if scored["ready_to_send"] or state["generate_count"] >= 3:
                break
            hint = scored.get("advice") or "punchier hook, add a specific stat or number"

        return post_text, score

    def tool_send_for_approval(post_text: str, score: int = 0) -> dict:
        if preview:
            print("\n" + "=" * 60)
            print(f"[PREVIEW] Score: {score}/100  |  Day: {state['day']}")
            print("=" * 60)
            print(post_text)
            print("=" * 60 + "\n")
            log_preview.info("Auto-approving — not sending to Discord.")
            return {"action": "post", "auto": True}

        topic = state["topic"]
        day = state["day"]
        variants = [{"model_key": "deepseek-pro", "display_name": "DeepSeek Chat", "text": post_text}]
        msg_id = send_approval_message(variants, [score], topic, day)

        if not msg_id:
            log_agent.warning("WARNING: Discord not configured — cannot request approval. Skipping today's post.")
            log_agent.info("Set DISCORD_BOT_TOKEN and DISCORD_APPROVALS_CHANNEL_ID to enable approval flow.")
            return {"action": "skip", "reason": "Discord not configured — approval required but unavailable"}

        # Shorter wait after a "new topic" switch — first wait already used most
        # of the workflow's time budget.
        timeout = 120 if state["topic_switches"] == 0 else 60
        decision = wait_for_approval(msg_id, timeout_minutes=timeout, num_variants=1)
        return {
            "action": decision.get("action"),
            "hint": decision.get("hint", ""),
            "custom_text": decision.get("text", ""),
        }

    def tool_publish_post(post_text: str, chosen_model: str = "deepseek-pro") -> dict:
        topic = state["topic"] or {}
        day = state["day"]
        if preview:
            log_preview.info("Publish skipped — preview mode active.")
            state["done"] = True
            return {"status": "preview", "message": "Post generated and scored — not published."}
        try:
            result = post_to_linkedin(post_text)

            try:
                log_post({
                    "post_urn": result["urn"],
                    "post_text": post_text,
                    "topic_title": topic.get("title", ""),
                    "topic_angle": topic.get("angle", ""),
                    "day_of_week": day,
                    "posted_at": datetime.now().isoformat(),
                    "variant_chosen": 1,
                    "chosen_model": chosen_model,
                })
            except Exception as e:
                log_agent.warning(f"Analytics log failed: {e}")

            source_url = topic.get("source_url", "")
            landing = os.environ.get("LANDING_PAGE_URL", "")
            if source_url:
                comment = f"Source: {source_url}"
                if landing:
                    comment += f"\n\nLearn more: {landing}"
                post_first_comment(result["urn"], comment)

            send_posted_confirmation(result["url"], 1, post_text)
            state["done"] = True
            _log("INFO", f"Live: {result['url']}")
            return {"status": "published", "url": result["url"], "urn": result["urn"]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def tool_skip_today(reason: str = "") -> dict:
        try:
            notify_timeout(state["day"], state["date"])
        except Exception as e:
            log_agent.warning(f"notify_timeout failed: {e}")
        state["done"] = True
        _log("INFO", f"Skipped: {reason}")
        return {"status": "skipped", "reason": reason}

    # ── Direct pipeline ────────────────────────────────────────────────────────

    _log("INFO", "Starting daily posting pipeline...")

    # 1. Research trending topics + pick best one for today
    topic_result = tool_pick_daily_topic()
    _log("INFO", f"Topic status: {topic_result['status']}")
    if topic_result["status"] == "already_posted":
        _log("INFO", "Already posted today — skipping.")
        return
    if topic_result["status"] == "no_topics":
        _log("ERROR", topic_result.get("message", "No topics found"))
        try:
            from discord_bot import notify_workflow_failure
            notify_workflow_failure("⚠️ No trending topics found — research sources may be down.")
        except Exception:
            pass
        return

    _log("INFO", f"Topic: {topic_result['topic_title']}")
    _log("INFO", f"Angle: {topic_result['angle']}")

    # 2. Analytics (for context in generation)
    tool_get_analytics_summary()

    # 3. Deep research on the chosen topic
    research_result = tool_research_topic()
    _log("INFO", f"Research: {research_result.get('sources_found', 0)} sources")

    # 4–5. Generate + score (up to 3 attempts, stop early if score meets threshold)
    post_text, score = _generate_and_score()
    if post_text is None:
        return

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

        elif action == "new_topic" and state["topic_switches"] < MAX_TOPIC_SWITCHES:
            pick = tool_pick_new_topic(decision.get("hint", ""))
            if pick.get("status") != "ok":
                _log("WARNING", "No alternative topics left in today's pool — re-sending same post.")
                continue
            state["topic_switches"] += 1
            _log("INFO", f"New topic: {pick['topic_title']}")
            _log("INFO", f"Angle: {pick['angle']}")
            tool_research_topic()
            post_text, score = _generate_and_score()
            if post_text is None:
                return

        elif action == "timeout":
            _log("INFO", "Approval timeout — auto-publishing.")
            try:
                notify_auto_post(state["day"], state["date"])
            except Exception:
                pass
            tool_publish_post(post_text)
            return

        else:
            if action == "regenerate":
                reason = "max regenerations reached"
            elif action == "new_topic":
                reason = "max topic switches reached"
            else:
                reason = action
            tool_skip_today(reason)
            return
