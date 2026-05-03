import json
import os

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

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

VARIANT_SEPARATOR = "---VARIANT 2---"


def _generate(prompt: str, system_extra: str = "", max_tokens: int = 2048) -> str:
    system = BRAND_CONTEXT + "\n\n" + WRITING_SYSTEM
    if system_extra:
        system += "\n\n" + system_extra
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


def _extract_json(text: str, opening: str) -> str:
    import re
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
    n: int = 2,
    hint: str = "",
    previous: list[str] | None = None,
    top_hashtags: list[str] | None = None,
) -> list[str]:
    rules_prompt = _get_rules_prompt()

    hint_block = f"\nUser instruction for regeneration: {hint}\n" if hint else ""

    hashtag_block = ""
    if top_hashtags:
        hashtag_block = f"\nTop-performing hashtags from our past posts (use 2-3 of these): {' '.join(top_hashtags[:8])}\n"

    previous_block = ""
    if previous:
        previous_block = "\nPrevious variants (generate genuinely different content — different hook, angle, examples):\n"
        for i, p in enumerate(previous, 1):
            previous_block += f"--- Previous Variant {i} ---\n{p[:400]}\n"

    prompt = f"""Write {n} LinkedIn post variants for The Tech Tutors.

TOPIC: {topic['title']}
ANGLE: {topic['angle']}
SOURCE URL (first comment only, NOT in post body): {topic['source_url']}
{hint_block}{hashtag_block}{previous_block}
VARIANT 1: QUESTION HOOK — start with a thought-provoking question
VARIANT 2: BOLD STATEMENT HOOK — start with a counterintuitive claim

Follow all formatting and structure rules exactly.
Every sentence on its own line. Blank line between sections.

Write Variant 1 in full, then write exactly "{VARIANT_SEPARATOR}" on its own line, then Variant 2 in full.

REMINDER: No links in post body. No standalone "The Tech Tutors" line. Hashtags last line only."""

    raw = _generate(prompt, system_extra=rules_prompt, max_tokens=3000)
    parts = [p.strip() for p in raw.split(VARIANT_SEPARATOR) if p.strip()]
    if len(parts) < 2:
        parts = [raw, raw]

    return [_fix_post_quality(p) for p in parts[:n]]


def generate_text_post(topic: dict) -> str:
    return generate_text_post_variants(topic, n=1)[0]


def generate_design_brief(topic: dict, hint: str = "", top_hashtags: list[str] | None = None) -> dict:
    rules_prompt = _get_rules_prompt()
    hint_block = f"\nUser instruction for regeneration: {hint}\n" if hint else ""
    hashtag_block = f"\nTop-performing hashtags from our past posts (use 2-3 in the caption): {' '.join(top_hashtags[:8])}\n" if top_hashtags else ""

    prompt = f"""Create a design brief + LinkedIn caption for The Tech Tutors:

Title: {topic['title']}
Angle: {topic['angle']}
Source: {topic['source_url']}
{hint_block}{hashtag_block}

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
