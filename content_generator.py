import json
import os

from groq import Groq
from dotenv import load_dotenv

from llm_client import (
    MODELS,
    QUALITY_FIX_MODEL,
    STRATEGY_MODEL,
    UTILITY_MODEL,
    call_model,
    call_with_fallback,
    generate_variants,
)

load_dotenv()

# Direct Groq client retained for the cheap quality-fix pass
client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "llama-3.3-70b-versatile"

# ── Brand Identity ────────────────────────────────────────────────────────────

BRAND_CONTEXT = """You are the LinkedIn content writer for The Tech Tutors — a software and AI services company that builds custom AI tools, automations, and web apps for small and medium-sized businesses.

BRAND VOICE:
- Talk like a knowledgeable friend who cuts through the BS
- Direct, confident, never preachy
- Enthusiastic about AI but grounded in business reality
- Never salesy — earn trust by being genuinely useful
- Speak to business owners as equals, not students

TARGET READER:
- Business owner or entrepreneur, 30-55 years old
- Pressed for time, skeptical of hype
- Wants to use AI but doesn't know where to start
- Scared of being left behind by competitors
- Pain points: wasting time on manual tasks, high software costs, staff inefficiency

THE TECH TUTORS VALUE PROP:
We build the exact AI tools your business needs — automations, web apps, chatbots — so you stop doing manually what a machine should do."""

WRITING_SYSTEM = """
═══════════════════════════════════════════
   LINKEDIN POST MASTERY — COMPLETE RULES
═══════════════════════════════════════════

── FORMATTING (non-negotiable) ──────────────
• Every sentence or thought gets its OWN LINE
• One blank line between every paragraph/section
• Bullet points: each on its own line, starting with •
• Maximum 1-2 sentences per paragraph
• No markdown bold (**text**) — LinkedIn ignores it
• No italics, no headers
• Plain text only

── STRUCTURE (follow exactly) ───────────────
LINE 1:    Hook — single punchy line, max 12 words
           [blank line]
LINE 2-3:  Context — why this matters RIGHT NOW (1-2 sentences)
           [blank line]
LINES 4-8: Body — 3-5 short punchy lines, one insight each
           [blank line]
LINE 9:    The Insight — one sentence that reframes how they see something
           [blank line]
LINE 10:   Question — one genuine specific question
           [blank line]
LINE 11:   CTA — one line, soft sell only
           [blank line]
LINE 12:   Hashtags — 3 to 5, on ONE line

── HOOK FORMULAS ────────────────────────────
VARIANT 1 — QUESTION HOOK:
• Start with a thought-provoking question that challenges assumptions
• Example: "What if the tool your competitor is using cost nothing?"

VARIANT 2 — BOLD STATEMENT HOOK:
• Start with a counterintuitive or surprising claim
• Example: "Your spreadsheet is the most expensive tool in your business."

── BODY CONTENT RULES ───────────────────────
• Use REAL specifics — numbers, time saved, costs cut, tasks automated
• Each bullet = one standalone insight
• Short words beat long words every time
• Write at grade 6 reading level

── QUESTION RULES ───────────────────────────
• NEVER: "Do you agree?" / "What do you think?" / "Tag someone who..."
• GOOD: "Which of these tasks is eating the most time in your business?"

── BANNED WORDS & PHRASES ───────────────────
Never use: delve, leverage, synergy, game-changer, revolutionary,
           cutting-edge, in today's fast-paced world, are you ready to,
           I'm excited to share, at the end of the day, the future is now,
           it's no secret that, in conclusion, to summarize,
           The Tech Tutors as a standalone line

── CHARACTER TARGETS ────────────────────────
• Hook: under 80 characters
• Total post: 1,200 – 1,800 characters
• No URLs in post body — links go in FIRST COMMENT only

── HASHTAG RULES ────────────────────────────
• 3-5 hashtags, last line only, space-separated
• Mix: 1 broad + 2 niche + 1 brand (#TheTechTutors)
"""

DAY_STRATEGY = {
    0: "Monday — MOTIVATIONAL [TEXT]: Challenge a limiting belief business owners have about AI. Conversational, punchy text post.",
    1: "Tuesday — PRACTICAL TOOL [SLIDES]: Spotlight a specific AI tool or automation. Design a visual LIST or STAT slide showing exact time/money saved.",
    2: "Wednesday — HOW-TO [SLIDES]: A clear step-by-step framework. Design a STEPS carousel — numbered actions, immediately actionable.",
    3: "Thursday — INDUSTRY NEWS [SLIDES]: A real AI development. Design a STAT or COMPARISON slide — data-driven visual showing business impact.",
    4: "Friday — INSIGHT [TEXT]: A surprising truth about AI adoption. Conversational text post that ends the week memorably.",
}

DAY_FORMAT = {0: "text", 1: "design", 2: "design", 3: "design", 4: "text"}


def _generate(prompt: str, system_extra: str = "", max_tokens: int = 2048) -> str:
    """Single-shot generation for strategy and utility calls.

    Routes through the multi-provider router so we use the best available free
    model (and fall back if it's down). Variant generation does NOT go through
    here — it uses generate_variants() to produce one output per model.
    """
    system = BRAND_CONTEXT + "\n\n" + WRITING_SYSTEM
    if system_extra:
        system += "\n\n" + system_extra
    return call_with_fallback(
        model_keys = [STRATEGY_MODEL, "llama-70b", "cerebras-llama"],
        prompt     = prompt,
        system     = system,
        max_tokens = max_tokens,
    )


def _extract_json(text: str, opening: str) -> str:
    import re
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    close = "]" if opening == "[" else "}"
    start = text.find(opening)
    end = text.rfind(close) + 1
    raw = text[start:end]

    # Escape control characters inside JSON string values
    def _fix_string(m: re.Match) -> str:
        s = m.group(0)
        s = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
        return s

    raw = re.sub(r'"(?:[^"\\]|\\.)*"', _fix_string, raw, flags=re.DOTALL)
    return raw


def _fix_post_quality(raw: str) -> str:
    prompt = f"""Fix ONLY these violations in this LinkedIn post. Minimum changes — do not rewrite:

1. Remove banned words: delve, leverage, synergy, game-changer, revolutionary, cutting-edge, "in today's fast-paced world", "are you ready to", "I'm excited to share", "at the end of the day", "the future is now", "it's no secret that", "in conclusion", "to summarize"
2. Remove "The Tech Tutors" if it appears as a standalone line
3. Remove any URLs or links from the post body
4. Replace generic question closers ("Do you agree?", "What do you think?", "Tag someone") with a specific question
5. Hashtags on last line only, 3-5 max
6. Keep length 1,200-1,800 characters

Return ONLY the fixed post. No explanations.

POST:
{raw}"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


def _get_rules_prompt() -> str:
    try:
        from linkedin_rules_fetcher import fetch_rules, build_rules_prompt
        return build_rules_prompt(fetch_rules())
    except Exception as e:
        print(f"  [content] Rules fetch skipped: {e}")
        return ""


def engagement_scorer(variant: str, past_performance: dict) -> int:
    score = 50
    first_word = variant.strip().split()[0] if variant.strip() else ""
    hook_type = "question" if first_word in ("What", "Why", "How", "Is", "Are", "Do", "Can", "Have") else "bold"

    hook_scores = past_performance.get("hook_scores", {})
    if hook_scores:
        max_val = max(hook_scores.values()) or 1
        score += int((hook_scores.get(hook_type, 0) / max_val) * 20) - 10

    char_count = len(variant)
    if 1200 <= char_count <= 1800:
        score += 15
    elif char_count < 800 or char_count > 2500:
        score -= 15

    hashtag_count = sum(1 for w in variant.split() if w.startswith("#"))
    if 3 <= hashtag_count <= 5:
        score += 10
    else:
        score -= 5

    if "?" in variant:
        score += 5

    return max(0, min(100, score))


def choose_weekly_strategy(
    performance_data: dict | None = None,
    recent_titles: list[str] | None = None,
) -> dict:
    from datetime import date as _date

    perf_block = ""
    if performance_data and performance_data.get("top_post_topic"):
        perf_block = (
            "\nPAST PERFORMANCE:\n"
            f"  Best hook: {performance_data.get('best_hook_type', 'bold')}\n"
            f"  Best day:  {performance_data.get('best_day', 'Tuesday')}\n"
            f"  Top post:  {performance_data.get('top_post_topic', '—')}\n"
        )

    avoid_block = ""
    if recent_titles:
        avoid_block = "\nRECENTLY COVERED (avoid repeating):\n" + "\n".join(
            f"- {t}" for t in recent_titles[:10]
        )

    prompt = f"""You are The Tech Tutors' content strategist. Choose this week's LinkedIn content strategy.

The Tech Tutors builds custom AI tools and automations for small and medium businesses.
Target audience: business owners 30-55, pressed for time, skeptical of hype.
Today: {_date.today().isoformat()}
{perf_block}{avoid_block}

Pick the single AI subdomain to own this week — most timely and relevant for SMB owners right now:
- AI Agents & Autonomous Workflows
- AI Tools for Small Business
- LLM Cost & Efficiency
- AI Automation (no-code / low-code)
- Generative AI for Marketing & Content
- AI in Customer Service
- Machine Learning for Business Analytics
- AI Security & Risk Management
- AI for HR & Recruitment
- Other (specify the domain)

Also pick the best LinkedIn posting time (7am, 8am, 9am, or 10am PKT).
Tue-Thu 8-10am typically peaks for B2B audiences.

Return ONLY valid JSON:
{{
  "domain": "AI Agents & Autonomous Workflows",
  "focus_keywords": ["AI agents 2026", "autonomous AI SMB", "agentic workflow automation"],
  "posting_time": "8am PKT",
  "rationale": "One sentence explaining why this domain and time this week."
}}"""

    raw = _generate(prompt, max_tokens=400)
    return json.loads(_extract_json(raw, "{"))


def plan_weekly_posts(
    topics: list[dict],
    num_posts: int = 5,
    recent_titles: list[str] | None = None,
    performance_data: dict | None = None,
) -> list[dict]:
    topics_text = "\n".join(
        f"{i+1}. [{t['source']}] {t['title']} — {t.get('description', '')} ({t['url']})"
        for i, t in enumerate(topics[:30])
    )

    avoid_block = ""
    if recent_titles:
        avoid_block = (
            "\nTopics covered recently — DO NOT repeat these themes:\n"
            + "\n".join(f"- {t}" for t in recent_titles)
        )

    perf_block = ""
    if performance_data and performance_data.get("top_post_topic"):
        best_hook = performance_data.get("best_hook_type", "bold")
        best_day  = performance_data.get("best_day", "Tuesday")
        top_topic = performance_data.get("top_post_topic", "")
        hook_scores = performance_data.get("hook_scores", {})
        day_scores  = performance_data.get("day_scores", {})
        hook_lines  = ", ".join(f"{h}={s}" for h, s in hook_scores.items()) if hook_scores else "no data yet"
        day_lines   = ", ".join(f"{d}={s}" for d, s in day_scores.items()) if day_scores else "no data yet"
        perf_block = (
            "\nPAST PERFORMANCE DATA — use this to pick better topics and formats:\n"
            f"  Best hook type: {best_hook} (hook scores: {hook_lines})\n"
            f"  Best posting day: {best_day} (day scores: {day_lines})\n"
            f"  Top-performing topic: {top_topic}\n"
            "  → Favour topics that suit the best hook type and best day patterns.\n"
        )

    day_block = "\n".join(f"  Day {i}: {v}" for i, v in DAY_STRATEGY.items())

    prompt = f"""Here are trending AI topics from the past week:

{topics_text}
{avoid_block}
{perf_block}
Plan The Tech Tutors' LinkedIn content for Mon–Fri (5 posts).

Day strategy:
{day_block}

Score each topic 1–10 for business-owner relevance. Pick best match per day.

Format assignments (fixed — do not change):
- Day 0 (Monday): format = "text"
- Day 1 (Tuesday): format = "design"
- Day 2 (Wednesday): format = "design"
- Day 3 (Thursday): format = "design"
- Day 4 (Friday): format = "text"

For design days, pick topics that translate well into a visual (stats, steps, comparisons, lists of tools).
For text days, pick topics that work as a punchy conversational post.

Return ONLY a valid JSON array with exactly 5 objects (day_index 0–4):
[
  {{
    "day_index": 0,
    "title": "short topic title",
    "source_url": "url",
    "angle": "one punchy sentence: the exact hook angle for The Tech Tutors audience — must reference a specific business pain point or benefit",
    "format": "text",
    "score": 8
  }}
]"""

    raw = _generate(prompt, max_tokens=1500)
    return json.loads(_extract_json(raw, "["))


def generate_text_post_variants(
    topic: dict,
    n: int = 2,                          # kept for backward compatibility, ignored
    hint: str = "",
    previous: list[str] | None = None,
    top_hashtags: list[str] | None = None,
) -> list[dict]:
    """Generate one LinkedIn post per enabled creative model.

    Returns a list of dicts: [{"model_key", "display_name", "text"}, ...]
    The number of variants depends on how many models are enabled in
    llm_client.VARIANT_MODELS["text"] and how many succeed.
    """
    rules_prompt = _get_rules_prompt()

    hint_block = f"\nUser instruction for regeneration: {hint}\n" if hint else ""

    hashtag_block = ""
    if top_hashtags:
        hashtag_block = f"\nTop-performing hashtags from our past posts (use 2-3 of these): {' '.join(top_hashtags[:8])}\n"

    previous_block = ""
    if previous:
        previous_block = "\nPrevious attempts (write something genuinely different — different hook, different angle, different examples):\n"
        for i, p in enumerate(previous, 1):
            previous_block += f"--- Previous {i} ---\n{p[:400]}\n"

    research_block = ""
    if topic.get("research_context"):
        research_block = f"\nLATEST RESEARCH FOUND TODAY (use specific facts/stats from these sources):\n{topic['research_context']}\n"

    prompt = f"""Write ONE LinkedIn post for The Tech Tutors.

TOPIC: {topic['title']}
ANGLE: {topic['angle']}
SOURCE URL (first comment only, NOT in post body): {topic['source_url']}
{hint_block}{hashtag_block}{research_block}{previous_block}
Write your single best version. Pick whichever hook style works best for THIS topic — question, bold statement, story, surprising fact, whatever pulls strongest. Make it sound like *you* wrote it, in your own voice.

Follow all formatting and structure rules exactly.
Every sentence on its own line. Blank line between sections.

REMINDER: No links in post body. No standalone "The Tech Tutors" line. Hashtags last line only.
Return ONLY the post text — no preamble, no explanations, no labels."""

    system = BRAND_CONTEXT + "\n\n" + WRITING_SYSTEM
    if rules_prompt:
        system += "\n\n" + rules_prompt

    variants = generate_variants(
        job        = "text",
        prompt     = prompt,
        system     = system,
        max_tokens = 2500,
    )

    # Quality-fix every variant
    for v in variants:
        try:
            v["text"] = _fix_post_quality(v["text"])
        except Exception as e:
            print(f"  [content] Quality fix failed for {v['display_name']}: {e}")

    return variants


def generate_text_post(topic: dict) -> str:
    """Backward-compat helper: returns text of the first successful variant."""
    variants = generate_text_post_variants(topic)
    return variants[0]["text"] if variants else ""


def generate_carousel_content(
    topic: dict,
    article_text: str = "",
    top_hashtags: list[str] | None = None,
) -> list[dict]:
    """Generate one structured 5-slide carousel per enabled creative model.

    Returns a list of dicts: [{"model_key", "display_name", "content"}, ...]
    where `content` is the parsed JSON carousel structure (slide1..slide5 + caption).
    Models that fail to produce valid JSON are dropped with a warning.
    """
    rules_prompt  = _get_rules_prompt()
    hashtag_block = f"\nTop-performing hashtags (use 2-3 in caption): {' '.join(top_hashtags[:8])}\n" if top_hashtags else ""

    if article_text:
        source_block = f"\nFULL ARTICLE TEXT (extract REAL numbers, facts, and quotes from this — do NOT make up statistics):\n{article_text[:7000]}\n"
    elif topic.get("research_context"):
        source_block = f"\nRESEARCH SOURCES:\n{topic['research_context']}\n"
    else:
        source_block = ""

    prompt = f"""You are creating LinkedIn carousel content for The Tech Tutors — a company that builds custom AI tools and automations for small and medium businesses.

TOPIC:  {topic['title']}
ANGLE:  {topic['angle']}
SOURCE: {topic['source_url']}
{source_block}{hashtag_block}

TARGET AUDIENCE: Small/medium business owners, 30-55. Time-pressed, skeptical of hype. They want SPECIFIC numbers and outcomes — not vague advice.

BRAND VOICE: Direct, confident, zero fluff. Like a knowledgeable friend. Grade 6 reading level. Short sentences win.

CRITICAL RULES:
- Use REAL specific numbers from the article. If no number exists, use a reasonable estimate and flag it as "est."
- Every point must be immediately useful or surprising
- No corporate jargon. No "leverage", "synergy", "game-changer"
- Each slide has ONE job. Do not mix messages.

CREATE CONTENT FOR 5 SLIDES:

SLIDE 1 — HOOK (makes someone stop scrolling)
  headline: Bold statement or provocative fact, max 8 words, makes them NEED to read on
  subheadline: What they'll learn from this carousel, max 10 words

SLIDE 2 — SITUATION (3 hard facts about what's happening right now)
  section_title: "WHAT'S HAPPENING" (exact wording)
  stats: exactly 3 items, each with:
    stat: The number itself — e.g. "67%", "10 hrs/week", "$4,200 saved" — max 5 words
    context: Plain English explanation of that number — max 12 words

SLIDE 3 — IMPACT (why SMB owners specifically should care)
  section_title: "WHY YOUR BUSINESS IS AFFECTED" (exact wording)
  impacts: exactly 3 items, each with:
    title: The specific outcome for an SMB — max 7 words, starts with a noun
    detail: One supporting fact with a number or timeframe — max 14 words

SLIDE 4 — ACTION (3 things to do THIS week, not someday)
  section_title: "YOUR ACTION PLAN" (exact wording)
  steps: exactly 3 steps, each with:
    action: Strong verb + what to do — max 7 words
    detail: Specific how-to with a tool name or timeframe — max 14 words

SLIDE 5 — TAKEAWAY + CTA
  takeaway: One sentence they will screenshot. Quotable. Punchy. Max 18 words.
  cta: "Follow The Tech Tutors for weekly AI insights that grow your business" (exact wording)

ALSO: caption — full LinkedIn post (1,200-1,800 chars):
  - Hook line first (single punchy line, max 12 words)
  - Reference 2-3 specific facts from the slides
  - Every sentence on its own line, blank line between sections
  - End with ONE specific question relevant to their business
  - Last line: 3-5 hashtags including #TheTechTutors

Return ONLY valid JSON, no markdown fences:
{{
  "slide1": {{"headline": "...", "subheadline": "..."}},
  "slide2": {{"section_title": "WHAT'S HAPPENING", "stats": [{{"stat": "...", "context": "..."}}, {{"stat": "...", "context": "..."}}, {{"stat": "...", "context": "..."}}]}},
  "slide3": {{"section_title": "WHY YOUR BUSINESS IS AFFECTED", "impacts": [{{"title": "...", "detail": "..."}}, {{"title": "...", "detail": "..."}}, {{"title": "...", "detail": "..."}}]}},
  "slide4": {{"section_title": "YOUR ACTION PLAN", "steps": [{{"action": "...", "detail": "..."}}, {{"action": "...", "detail": "..."}}, {{"action": "...", "detail": "..."}}]}},
  "slide5": {{"takeaway": "...", "cta": "Follow The Tech Tutors for weekly AI insights that grow your business"}},
  "caption": "..."
}}"""

    system = BRAND_CONTEXT + "\n\n" + WRITING_SYSTEM
    if rules_prompt:
        system += "\n\n" + rules_prompt

    raw_variants = generate_variants(
        job        = "carousel",
        prompt     = prompt,
        system     = system,
        max_tokens = 3000,
    )

    results: list[dict] = []
    for v in raw_variants:
        try:
            content = json.loads(_extract_json(v["text"], "{"))
            try:
                content["caption"] = _fix_post_quality(content.get("caption", ""))
            except Exception as e:
                print(f"  [content] Quality fix failed for {v['display_name']}: {e}")
            results.append({
                "model_key":    v["model_key"],
                "display_name": v["display_name"],
                "content":      content,
            })
        except Exception as e:
            print(f"  [content] {v['display_name']} carousel JSON failed: {str(e)[:120]} — dropping")
            continue

    if not results:
        raise RuntimeError("All carousel models failed to produce valid JSON")

    return results


def generate_research_report(
    topic: dict,
    hint: str = "",
    top_hashtags: list[str] | None = None,
) -> dict:
    rules_prompt   = _get_rules_prompt()
    hint_block     = f"\nUser instruction: {hint}\n" if hint else ""
    hashtag_block  = f"\nTop-performing hashtags (use 2-3 in caption): {' '.join(top_hashtags[:8])}\n" if top_hashtags else ""
    research_block = f"\nLATEST RESEARCH (use specific facts and stats from these sources):\n{topic['research_context']}\n" if topic.get("research_context") else ""

    prompt = f"""Write a professional AI research brief for The Tech Tutors LinkedIn audience.

TOPIC:  {topic['title']}
ANGLE:  {topic['angle']}
SOURCE: {topic['source_url']}
{hint_block}{hashtag_block}{research_block}

Create a complete structured research report with these exact sections:

1. HEADLINE — one powerful declarative statement, max 12 words, all caps energy
2. EXECUTIVE_SUMMARY — 2-3 sentences: the situation, why it matters RIGHT NOW, the opportunity for SMBs
3. KEY_FINDINGS — exactly 5 specific findings with real numbers, percentages, or timeframes (each under 35 words)
4. BUSINESS_IMPACT — exactly 4 actionable points specifically for small/medium business owners (each under 30 words)
5. TECH_TUTORS_TAKE — 2-3 sentences of The Tech Tutors' expert perspective and recommendation
6. KEY_TAKEAWAY — one memorable closing sentence, max 20 words, punchy and memorable
7. CAPTION — full LinkedIn post caption (1200-1800 chars, follow all writing rules: one idea per line, blank lines between sections, specific question, 3-5 hashtags last line, no links in body)

Return ONLY valid JSON:
{{
  "headline": "...",
  "executive_summary": "...",
  "key_findings": ["finding 1", "finding 2", "finding 3", "finding 4", "finding 5"],
  "business_impact": ["impact 1", "impact 2", "impact 3", "impact 4"],
  "tech_tutors_take": "...",
  "key_takeaway": "...",
  "caption": "full LinkedIn caption text here..."
}}"""

    raw    = _generate(prompt, system_extra=rules_prompt, max_tokens=2500)
    result = json.loads(_extract_json(raw, "{"))
    result["caption"] = _fix_post_quality(result["caption"])
    return result


def generate_design_brief(topic: dict, hint: str = "", top_hashtags: list[str] | None = None) -> dict:
    rules_prompt = _get_rules_prompt()
    hint_block = f"\nUser instruction for regeneration: {hint}\n" if hint else ""
    hashtag_block = f"\nTop-performing hashtags from our past posts (use 2-3 in the caption): {' '.join(top_hashtags[:8])}\n" if top_hashtags else ""

    research_block = ""
    if topic.get("research_context"):
        research_block = f"\nLATEST RESEARCH FOUND TODAY (use specific facts/stats from these):\n{topic['research_context']}\n"

    prompt = f"""Create a design brief + LinkedIn caption for The Tech Tutors:

Title: {topic['title']}
Angle: {topic['angle']}
Source: {topic['source_url']}
{hint_block}{hashtag_block}{research_block}

Pick the best visual template:
- "list": bulleted tips or features
- "steps": numbered step-by-step process
- "comparison": two-column before/after or A vs B
- "stat": large central statistic with supporting points

Return ONLY valid JSON:
{{
  "graphic_title": "ALL CAPS bold hook headline — max 8 words, high impact",
  "hook_subtext": "one amplifying line max 10 words — shown below the headline",
  "template": "list|steps|comparison|stat",
  "graphic_layout": "one-line layout description",
  "graphic_points": ["5-7 specific points — each under 15 words, include numbers and business outcomes, format as 'Headline — specific detail with number'"],
  "cta_text": "Save this post and follow The Tech Tutors for weekly AI tips that grow your business.",
  "brand_note": "dark navy background, white text, electric blue accents",
  "caption": "LinkedIn caption — 1200-1800 chars, no link in body, blank lines between sections, ends with specific question + 3-5 hashtags"
}}"""

    raw = _generate(prompt, system_extra=rules_prompt, max_tokens=1500)
    result = json.loads(_extract_json(raw, "{"))
    result["caption"] = _fix_post_quality(result["caption"])
    return result
