"""
Agentic LinkedIn posting runner using Groq tool-use (Llama 3.3 70B).
The LLM orchestrates the full workflow: research → generate → score → approve → post.
Called from run.py cmd_auto().
"""

import json
import os
from datetime import datetime

from groq import Groq

# ── Tool schemas ───────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_today_slot",
            "description": (
                "Get today's scheduled topic from the weekly plan. "
                "Returns slot info or a status indicating nothing to post."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_analytics_summary",
            "description": (
                "Get past performance data: best hook types, best posting days, top hashtags. "
                "Use to inform angle and hook choice before generating."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_topic",
            "description": (
                "Fetch fresh articles and data about today's topic. "
                "Always call this before generating a post."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_title": {
                        "type": "string",
                        "description": "Topic title to research",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Focus keywords for targeted search",
                    },
                },
                "required": ["topic_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_post",
            "description": (
                "Generate a LinkedIn post for today's topic. "
                "Returns post text and metadata. Max 3 calls total per run."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hint": {
                        "type": "string",
                        "description": "Optional improvement hint (e.g. 'add a concrete stat', 'punchier hook')",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_post",
            "description": (
                "Score a post for engagement potential (0-100). "
                "Score >=65 is ready to send for approval. Score >=80 is excellent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "post_text": {
                        "type": "string",
                        "description": "Post text to score",
                    },
                },
                "required": ["post_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_for_approval",
            "description": (
                "Send post to Discord for human approval. Blocks until response (up to 120 min). "
                "Returns action: post / edit / regenerate / skip / timeout, "
                "plus optional hint or custom_text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "post_text": {
                        "type": "string",
                        "description": "Post text to send for approval",
                    },
                    "score": {
                        "type": "integer",
                        "description": "Engagement score for context",
                    },
                },
                "required": ["post_text", "score"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_post",
            "description": (
                "Publish the approved post to LinkedIn, log analytics, post source comment. "
                "Call only after approval from send_for_approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "post_text": {
                        "type": "string",
                        "description": "Final post text to publish",
                    },
                    "chosen_model": {
                        "type": "string",
                        "description": "Model key that generated this post",
                    },
                },
                "required": ["post_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skip_today",
            "description": "Mark today's slot as skipped and notify Discord.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Reason for skipping",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

AGENT_SYSTEM = """You are The Tech Tutors autonomous LinkedIn posting agent.

Goal: research today's topic, generate a high-quality post, get human approval via Discord, publish to LinkedIn.

Strict workflow:
1. get_today_slot() — if status is no_slot or already_posted, respond with a text message saying why you stopped and call NO more tools.
2. get_analytics_summary() — note best_hook_type and top_hashtags to use.
3. research_topic(topic_title, keywords) — always research before generating.
4. generate_post() — generate the post.
5. score_post(post_text) — evaluate it. The result includes a dynamic `threshold` based on past performance.
   - score < threshold and attempts < 3: generate_post(hint from score_post advice) then score again.
   - score >= threshold: proceed to step 6.
   - score >= 80 is always excellent regardless of threshold.
6. send_for_approval(post_text, score) — wait for human decision:
   - "post": publish_post(post_text, chosen_model)
   - "edit": publish_post(custom_text, chosen_model="human-edit")
   - "regenerate": generate_post(hint=hint_from_decision), score again, send_for_approval again.
   - "skip" or "timeout": skip_today(reason)
7. After publish_post or skip_today succeeds, stop — do not call any more tools.

Hard rules:
- Never skip step 3 (research).
- Max 3 generate_post calls total across all retries.
- Score >= 80 is excellent — do not regenerate just for a higher number.
- Never call publish_post without prior approval from send_for_approval.
"""


def run_agent() -> None:
    """Agentic posting loop. Called from cmd_auto() in run.py."""

    from scheduler import get_today_slot, get_strategy, update_slot
    from content_generator import engagement_scorer, generate_text_post_variants
    from research import fetch_deep_topic_research
    from linkedin_poster import post_first_comment, post_to_linkedin
    from analytics_tracker import get_performance_summary, get_top_hashtags, log_post
    from discord_bot import (
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
        slot = get_today_slot()
        if not slot:
            # Fallback: use any pending slot from the current week
            from scheduler import get_week_overview
            week_slots = get_week_overview()
            pending = [s for s in week_slots if s.get("topic") and s.get("status") == "pending"]
            if pending:
                slot = pending[0]
                print(f"[agent] No slot for today — falling back to pending slot: {slot['day']} ({slot['date']})")
            else:
                # No plan at all — alert the user via Discord
                try:
                    from discord_bot import notify_workflow_failure
                    notify_workflow_failure(
                        "⚠️ **No content plan for this week** — run `python run.py plan` "
                        "to generate the week's schedule, then re-trigger the daily post."
                    )
                except Exception:
                    pass
                return {"status": "no_slot", "message": "No slot planned for today. Run plan first."}
        if slot.get("status") == "posted":
            return {"status": "already_posted", "date": slot["date"]}
        if slot.get("post_urn"):
            slot["status"] = "posted"
            update_slot(slot)
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
        score = engagement_scorer(post_text, past)
        # Threshold derived from past performance: 90% of recent avg, clamped 55–75.
        # Falls back to 62 when no history exists yet.
        recent_avg = past.get("recent_avg_score", 0)
        threshold = max(55, min(75, int(recent_avg * 0.9))) if recent_avg > 0 else 62
        return {
            "score": score,
            "threshold": threshold,
            "verdict": "excellent" if score >= 80 else "good" if score >= threshold else "weak",
            "ready_to_send": score >= threshold,
            "advice": "" if score >= threshold else f"Score {score} below threshold {threshold}. Try a more specific hook or add a concrete stat.",
        }

    def tool_send_for_approval(post_text: str, score: int = 0) -> dict:
        topic = state["topic"]
        day = state["day"]
        variants = [{"model_key": "llama-70b", "display_name": "Llama 70B", "text": post_text}]
        msg_id = send_approval_message(variants, [score], topic, day)

        if not msg_id:
            print("[agent] Discord not configured — auto-posting without approval.")
            return {"action": "post", "auto": True}

        decision = wait_for_approval(msg_id, timeout_minutes=120, num_variants=1)
        return {
            "action": decision.get("action"),
            "hint": decision.get("hint", ""),
            "custom_text": decision.get("text", ""),
        }

    def tool_publish_post(post_text: str, chosen_model: str = "llama-70b") -> dict:
        slot = state["slot"]
        topic = state["topic"]
        day = state["day"]
        try:
            result = post_to_linkedin(post_text)
            slot["status"] = "posted"
            slot["post_urn"] = result["urn"]
            slot["post_text"] = post_text
            slot["chosen_model"] = chosen_model
            update_slot(slot)

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
            update_slot(slot)
            try:
                notify_timeout(state["day"], slot.get("date", ""))
            except Exception:
                pass
        state["done"] = True
        print(f"[agent] Skipped: {reason}")
        return {"status": "skipped", "reason": reason}

    # ── Tool dispatcher ────────────────────────────────────────────────────────

    _DISPATCH = {
        "get_today_slot":        lambda a: tool_get_today_slot(),
        "get_analytics_summary": lambda a: tool_get_analytics_summary(),
        "research_topic":        lambda a: tool_research_topic(**a),
        "generate_post":         lambda a: tool_generate_post(**a),
        "score_post":            lambda a: tool_score_post(**a),
        "send_for_approval":     lambda a: tool_send_for_approval(**a),
        "publish_post":          lambda a: tool_publish_post(**a),
        "skip_today":            lambda a: tool_skip_today(**a),
    }

    def execute_tool(name: str, args: dict):
        fn = _DISPATCH.get(name)
        if not fn:
            return {"error": f"Unknown tool: {name}"}
        try:
            return fn(args)
        except Exception as e:
            return {"error": f"Tool {name} crashed: {e}"}

    # ── Agent loop ─────────────────────────────────────────────────────────────

    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    messages: list[dict] = [
        {"role": "user", "content": "Run today's LinkedIn posting workflow."}
    ]

    print("[agent] Starting agentic posting loop (Groq tool-use)...")

    for step in range(20):
        print(f"[agent] Step {step + 1}...")

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": AGENT_SYSTEM}] + messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=2048,
            temperature=0.2,
        )

        msg = response.choices[0].message

        assistant_entry: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_entry)

        if not msg.tool_calls:
            print(f"[agent] Done — {msg.content or '(no message)'}")
            break

        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}") or {}
            arg_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items())
            print(f"[agent]   -> {name}({arg_preview})")

            result = execute_tool(name, args)
            print(f"[agent]   <- {json.dumps(result, default=str)[:150]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

        if state["done"]:
            print("[agent] Workflow complete.")
            break

    else:
        print("[agent] Max steps reached — forcing skip.")
        tool_skip_today("Max agent iterations reached without completing workflow")
