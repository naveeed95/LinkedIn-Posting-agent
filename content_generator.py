import json
import re
import time
from datetime import date as _date

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
   LINKEDIN VIRAL POST SYSTEM — FULL RULES
═══════════════════════════════════════════

── THE #1 RULE ──────────────────────────────
LinkedIn shows only the first ~210 characters before "see more."
Hook + line 2 combined must be under 210 characters.
If those 2 lines don't make the reader NEED to click, nobody reads the rest.
The hook is everything — but line 2 seals the click.

── FORMATTING (non-negotiable) ──────────────
• Every sentence gets its OWN LINE — maximum 12 words per line
• One blank line between every paragraph/section
• Bullet points: each on its own line, starting with •
• No markdown bold (**text**) — LinkedIn strips it
• No italics, no headers, no em-dashes
• Plain text only — white space IS the design

── STRUCTURE (follow exactly) ───────────────
LINE 1:    Hook — ONE punchy line, max 12 words, ends WITHOUT a period
           [blank line]
LINE 2:    Tension — the pain or paradox that makes them click "see more"
           (Lines 1+2 combined must be under 210 characters)
           [blank line]
LINES 3-7: Body — 4-6 short punchy lines, one concrete insight each
           Include 1 SAVE-WORTHY line (stat, formula, or tool name to screenshot)
           Mix bullets and short paragraphs, never walls of text
           [blank line]
LINE 8:    The Reframe — ONE sentence that flips how they see the problem
           [blank line]
LINE 9:    Depth question — specific, personal, requires 15+ word answer
           [blank line]
LINE 10:   Soft CTA — one line max, no exclamation marks
           [blank line]
LINE 11:   Hashtags — 1 to 3 max, on ONE line, space-separated

── HOOK FORMULAS (pick the ONE that hits hardest for THIS topic) ──
1. NUMBER SHOCK:    "73% of small businesses are paying for software they don't need"
2. CALL OUT:        "If your team still does [task] manually, this is for you"
3. CONTRARIAN:      "Stop using [popular thing]. Here's what actually works."
4. BEFORE/AFTER:    "6 months ago: 14 hours on invoices. Today: 40 minutes."
5. SECRET/INSIDER:  "Most business owners don't know their [tool] has a free AI mode"
6. HARD TRUTH:      "Your [tool] is costing you more than your rent"
7. STORY OPEN:      "A client came to us spending $3,200/month on software."

── FIRST 3 WORDS RULE ───────────────────────
The first 3 words determine click-through on mobile.
Start with: a number, "Stop", "Most", "Your", "Why", "A [noun]"
NEVER start with: "I", "We", "In today's", "As a", "It's"

── BODY CONTENT RULES ───────────────────────
• Every bullet = one SPECIFIC, STANDALONE insight with a number or name
• Short words beat long words — if a 5-year-old wouldn't say it, cut it
• Grade 6 reading level — Hemingway short sentences win every time
• Use tool names, dollar amounts, hours saved, % improvements
• One idea per line — readers skim vertically, not horizontally

── COMMENT ENGINEERING (critical — 15+ word comments weighted 2.5x by algorithm) ──
The closing question MUST force a specific, personal answer of 15+ words.
• BAD (yes/no): "Do you agree?" / "Have you tried this?"
• BAD (vague): "What do you think?" / "Thoughts?" / "Tag someone..."
• BAD (engagement bait — -60% reach): "Like if you agree" / "Tag 3 people"
• GOOD: "How many hours a week does your team spend on [specific task] — and what would you do with that time back?"
• GOOD: "What's the one manual process in your business you've been meaning to automate for months but haven't yet — and what's stopped you?"
• GOOD: "If you could eliminate one bottleneck in your workflow this week, what would it be and why?"

── SAVES ENGINEERING (saves now outrank likes in algorithm weight) ────────────
Include exactly ONE of these in the body — something users will screenshot:
• A specific formula: "Time saved = [X hrs/week] × $[hourly rate] × 52 = real annual cost"
• A concrete before/after: "Manual: 14 hrs/week. Automated: 40 min/week."
• A specific tool + use case: "[Tool name] + [use case] = [specific outcome]"
• A counterintuitive stat that reframes their thinking

── DEPTH ENGINEERING (algorithm measures 30+ second dwell time) ───────────────
Line 2 must TEASE what's in the body — create a loop the brain needs to close.
Example: "Here's what the $28/month AI stack actually looks like." → reader MUST scroll to see the stack.
Never give away the payoff in the first 2 lines — earn every scroll.

── BANNED WORDS & PHRASES ───────────────────
Never use: delve, leverage, synergy, game-changer, revolutionary,
           cutting-edge, in today's fast-paced world, are you ready to,
           I'm excited to share, at the end of the day, the future is now,
           it's no secret that, in conclusion, to summarize, utilize,
           unlock, empower, seamless, robust, scalable, innovative,
           The Tech Tutors as a standalone line

── CHARACTER TARGETS ────────────────────────
• Hook line: under 70 characters
• Total post: 1,200 – 1,800 characters
• No URLs in post body — links go in FIRST COMMENT only

── HASHTAG RULES ────────────────────────────
• 1-3 hashtags MAX — 2026 research shows 3+ hashtags REDUCE reach
• Last line only, space-separated
• Pick: 1 niche + 1 brand (#TheTechTutors)
• Never hashtag a word mid-post
"""

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Pre-compiled regex for banned-word detection (used in scorer and quality-fix verification)
_BANNED_WORDS_PATTERN = re.compile(
    r'\b(delve|leverage|synergy|game[-\s]changer|revolutionary|cutting[-\s]edge)\b'
    r"|in today's fast[-\s]paced world|are you ready to|i'm excited to share"
    r'|at the end of the day|the future is now|it\'s no secret that'
    r'|in conclusion|to summarize',
    re.IGNORECASE,
)

# Module-level rules cache: (prompt_str, timestamp)
_rules_cache: tuple[str, float] | None = None
_RULES_CACHE_TTL = 3600  # 1 hour


def _generate(prompt: str, system_extra: str = "", max_tokens: int = 2048) -> str:
    """Single-shot generation for strategy and utility calls.

    Routes through the multi-provider router so we use the best available free
    model (and fall back if it's down). Variant generation does NOT go through
    here — it uses generate_variants() to produce one output per model.
    """
    system = BRAND_CONTEXT + "\n\n" + WRITING_SYSTEM
    rules = _get_rules_prompt()
    if rules:
        system += "\n\n" + rules
    if system_extra:
        system += "\n\n" + system_extra
    return call_with_fallback(
        model_keys = [STRATEGY_MODEL],
        prompt     = prompt,
        system     = system,
        max_tokens = max_tokens,
    )


def _extract_json(text: str, opening: str) -> str:
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    close = "]" if opening == "[" else "}"
    start = text.find(opening)
    end = text.rfind(close) + 1
    if start == -1 or end <= start:
        raise ValueError(
            f"No {opening}...{close} block found in LLM response "
            f"(first 200 chars): {text[:200]!r}"
        )
    raw = text[start:end]

    # Escape control characters inside JSON string values
    def _fix_string(m: re.Match) -> str:
        s = m.group(0)
        s = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
        return s

    raw = re.sub(r'"(?:[^"\\]|\\.)*"', _fix_string, raw, flags=re.DOTALL)
    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Extracted JSON is not parseable ({e}): {raw[:200]!r}") from e
    return raw


def _fix_post_quality(raw: str) -> str:
    prompt = f"""Fix ONLY these violations in this LinkedIn post. Minimum changes — do not rewrite:

1. Remove banned words: delve, leverage, synergy, game-changer, revolutionary, cutting-edge, "in today's fast-paced world", "are you ready to", "I'm excited to share", "at the end of the day", "the future is now", "it's no secret that", "in conclusion", "to summarize"
2. Remove "The Tech Tutors" if it appears as a standalone line
3. Remove any URLs or links from the post body
4. Replace generic question closers ("Do you agree?", "What do you think?", "Tag someone") with a specific question
5. Hashtags on last line only, 1-3 max
6. Keep length 1,200-1,800 characters

Return ONLY the fixed post. No explanations.

POST:
{raw}"""
    return call_model(
        QUALITY_FIX_MODEL,
        prompt,
        max_tokens  = 2000,
        temperature = 0.2,
    )


def _get_rules_prompt() -> str:
    global _rules_cache
    now = time.time()
    if _rules_cache is not None and (now - _rules_cache[1]) < _RULES_CACHE_TTL:
        return _rules_cache[0]
    try:
        from linkedin_rules_fetcher import fetch_rules, build_rules_prompt
        result = build_rules_prompt(fetch_rules())
        _rules_cache = (result, now)
        return result
    except Exception as e:
        print(f"  [content] Rules fetch skipped: {e}")
        return ""


def _rule_based_score(variant: str, past_performance: dict) -> dict:
    score = 50
    first_line = variant.strip().split("\n")[0] if variant.strip() else ""
    first_word = first_line.split()[0] if first_line.split() else ""
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
    if 1 <= hashtag_count <= 3:
        score += 10
    else:
        score -= 5

    if "?" in first_line:
        score += 5
    if _BANNED_WORDS_PATTERN.search(variant):
        score -= 10
    if "http" in variant:
        score -= 10

    score = max(0, min(100, score))
    return {"score": score, "advice": "Rule-based fallback — LLM scorer unavailable."}


def engagement_scorer(variant: str, past_performance: dict) -> dict:
    """Score a LinkedIn post using Llama 8B. Returns {"score": int, "advice": str}.
    Falls back to rule-based scoring if the LLM call fails.
    """
    prompt = f"""Score this LinkedIn post for The Tech Tutors — a company that builds AI tools for small businesses.

Target audience: SMB owners, 30–55, time-pressed, skeptical of hype. They want specific numbers and real outcomes.

POST TO SCORE:
{variant}

Score 0–100 across these seven areas (2026 LinkedIn algorithm weights):

1. Hook (0–20): First line — punchy, specific, impossible to ignore? Starts with number/"Stop"/"Most"/"Your"/"Why"? Vague openers = 0.
2. See-More Click (0–15): Lines 1+2 combined under 210 chars AND line 2 teases the body without giving away the payoff?
3. Specificity (0–20): Real numbers, tool names, dollar amounts, hours saved, concrete outcomes? "A lot" / "many" = 0.
4. Saves potential (0–10): Is there ONE line specific/actionable enough to screenshot — a formula, before/after, or tool+outcome?
5. Comment quality trigger (0–15): Does the closing question FORCE a 15+ word personal answer? Yes/no questions = 0. "Do you agree" = 0.
6. Readability (0–10): Short sentences, one thought per line, grade 6 level, no jargon, white space between sections?
7. Format (0–10): 1–3 hashtags on last line only, 1,200–1,800 characters, no URLs in body, no markdown bold?

Automatic deductions:
- Banned word (delve, leverage, synergy, game-changer, revolutionary, cutting-edge, seamless, robust): −10
- URL in post body: −10
- Engagement bait ("like if", "tag someone", "comment a number"): −15

Return ONLY valid JSON, nothing else:
{{"score": <integer 0-100>, "advice": "<one sentence: the single most impactful change to push the score above 80>"}}"""

    try:
        raw = call_model(UTILITY_MODEL, prompt, max_tokens=120, temperature=0.1)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(raw[start:end])
            score = max(0, min(100, int(data["score"])))
            advice = str(data.get("advice", "")).strip()
            print(f"  [content] LLM score: {score}/100")
            return {"score": score, "advice": advice}
    except Exception as e:
        print(f"  [content] LLM scorer failed ({e}) — falling back to rule-based scorer")

    return _rule_based_score(variant, past_performance)


def choose_weekly_strategy(
    performance_data: dict | None = None,
    recent_titles: list[str] | None = None,
    trending_sample: list[dict] | None = None,
) -> dict:

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
        avoid_block = "\nRECENTLY COVERED — do NOT repeat these themes:\n" + "\n".join(
            f"- {t}" for t in recent_titles[:10]
        )

    trending_block = ""
    if trending_sample:
        lines = [
            f"{i+1}. [{t['source']}] {t['title']}"
            for i, t in enumerate(trending_sample[:15])
        ]
        trending_block = "\nTHIS WEEK'S TOP TRENDING AI HEADLINES (use these to ground your choice):\n" + "\n".join(lines) + "\n"

    prompt = f"""You are The Tech Tutors' content strategist. Choose this week's LinkedIn content strategy.

TODAY: {_date.today().isoformat()}
AUDIENCE: SMB owners (1–50 employees), 30–55, pressed for time, skeptical of hype.
GOAL: Based on what is actually trending RIGHT NOW, identify the ONE AI subdomain with the highest urgency for SMB owners this week.
{trending_block}{perf_block}{avoid_block}

SELECTION CRITERIA — pick the domain that scores highest on ALL of these:
✓ Directly supported by 2+ of the trending headlines above (ground your choice in real evidence)
✓ Has a specific monetary or time-saving benefit for a business under 50 people
✓ Something a business owner can act on this week without hiring a developer
✓ Not covered in the RECENTLY COVERED list above
✓ Ideally under $100/month for the owner to try

Do NOT pick from a fixed list — derive the domain from the headlines themselves.
Name it specifically (e.g. "AI invoice automation for freelancers", not "AI Tools").

Also pick the best LinkedIn posting time based on current algorithm rules in your context (typically 8–10am local for B2B).

Return ONLY valid JSON:
{{
  "domain": "specific AI subdomain derived from trending headlines",
  "focus_keywords": ["3–5 specific search terms relevant RIGHT NOW, include year 2026"],
  "content_pillar": "one sentence: the single most urgent SMB pain point this domain solves this week",
  "posting_time": "8am PKT",
  "rationale": "2 sentences: (1) which headlines support this domain, (2) specific SMB pain it addresses"
}}"""

    raw = _generate(prompt, max_tokens=500)
    return json.loads(_extract_json(raw, "{"))


def plan_weekly_posts(
    topics: list[dict],
    num_posts: int = 7,
    recent_titles: list[str] | None = None,
    performance_data: dict | None = None,
    strategy: dict | None = None,
) -> list[dict]:
    topics_text = "\n".join(
        f"{i+1}. [{t['source']}] {t['title']} — {t.get('description', '')} ({t['url']})"
        for i, t in enumerate(topics[:35])
    )

    avoid_block = ""
    if recent_titles:
        avoid_block = (
            "\nRECENTLY COVERED — do NOT repeat these themes:\n"
            + "\n".join(f"- {t}" for t in recent_titles)
        )

    perf_block = ""
    if performance_data and performance_data.get("top_post_topic"):
        best_hook   = performance_data.get("best_hook_type", "bold")
        best_day    = performance_data.get("best_day", "Tuesday")
        top_topic   = performance_data.get("top_post_topic", "")
        hook_scores = performance_data.get("hook_scores", {})
        day_scores  = performance_data.get("day_scores", {})
        hook_lines  = ", ".join(f"{h}={s}" for h, s in hook_scores.items()) if hook_scores else "no data yet"
        day_lines   = ", ".join(f"{d}={s}" for d, s in day_scores.items()) if day_scores else "no data yet"
        perf_block = (
            "\nPAST PERFORMANCE — favour topics that match these patterns:\n"
            f"  Best hook type: {best_hook} (scores: {hook_lines})\n"
            f"  Best posting day: {best_day} (scores: {day_lines})\n"
            f"  Top-performing topic: {top_topic}\n"
        )

    strategy_block = ""
    if strategy:
        strategy_block = f"""
THIS WEEK'S FOCUS
═══════════════════════════════════════════════════════════
Domain:         {strategy.get('domain', 'AI for Small Business')}
Content Pillar: {strategy.get('content_pillar', '')}
Keywords:       {', '.join(strategy.get('focus_keywords', []))}
Rationale:      {strategy.get('rationale', '')}
═══════════════════════════════════════════════════════════
"""

    domain_name = strategy.get("domain", "") if strategy else ""

    prompt = f"""You are planning The Tech Tutors' LinkedIn content for Mon–Sun (7 posts, one per day).

AUDIENCE: SMB owners (1–50 employees), 30–55, pressed for time, skeptical of hype.
They care about: saving hours/week, cutting costs, staying competitive without needing developers.
They ignore: generic AI hype, academic research, enterprise-only tools.
{strategy_block}
TRENDING TOPICS THIS WEEK (pick from these):
{topics_text}
{avoid_block}
{perf_block}

YOUR TASK:
For each of the 7 days (Monday–Sunday), pick the BEST topic and decide the post angle and strategy.
Use the LinkedIn algorithm rules injected in your system context to decide what content style performs best on each day.
Vary the content mix across the week — different angles, different hook styles, different content types (insights, how-tos, tools, stats, questions, opinions) so the week doesn't feel repetitive.

QUALITY RULES for every slot:
• Angle must contain a specific number, tool name, time saving, or concrete outcome — no vague claims
• Topic must be actionable for a business owner without a developer
• Reject any topic that is enterprise-only, purely academic, or has no clear SMB benefit
• Use past performance data above to favour hook styles and days that have worked

SCORING (apply per topic):
• Base 1–10: SMB relevance (not general AI importance)
• +2 if aligns with this week's domain: {domain_name}
• +2 if contains specific numbers (%, $, hrs, price)
• -3 if enterprise/government/academic focus
• -3 if in the RECENTLY COVERED list

Return ONLY valid JSON array, exactly 7 objects (day_index 0–6):
[
  {{
    "day_index": 0,
    "title": "topic title under 8 words",
    "source_url": "exact URL from topic list above",
    "angle": "one sentence under 20 words — specific tool/number/outcome",
    "format": "text",
    "score": 8,
    "why": "one sentence: what post style you chose for this day and why"
  }}
]"""

    raw = _generate(prompt, max_tokens=2000)
    planned = json.loads(_extract_json(raw, "["))
    # Ensure exactly 7 slots — pad with fallback entries if LLM returned fewer
    existing_indices = {p.get("day_index") for p in planned}
    for i in range(7):
        if i not in existing_indices:
            print(f"  [content] WARNING: LLM returned no slot for day_index {i} — inserting fallback")
            planned.append({
                "day_index": i,
                "title": "— fallback slot —",
                "source_url": "",
                "angle": "",
                "format": "text",
                "score": 0,
                "why": "auto-generated fallback",
            })
    planned.sort(key=lambda x: x.get("day_index", 99))
    return planned[:7]


def generate_text_post_variants(
    topic: dict,
    n: int = 2,                          # kept for backward compatibility, ignored
    hint: str = "",
    # n is intentionally ignored — variant count is controlled by llm_client.VARIANT_MODELS["text"]
    previous: list[str] | None = None,
    top_hashtags: list[str] | None = None,
) -> list[dict]:
    """Generate one LinkedIn post per enabled creative model.

    Returns a list of dicts: [{"model_key", "display_name", "text"}, ...]
    The number of variants depends on how many models are enabled in
    llm_client.VARIANT_MODELS["text"] and how many succeed.
    """
    if n != 2:
        print(f"  [content] WARNING: n={n} ignored — variant count controlled by llm_client.VARIANT_MODELS")
    rules_prompt = _get_rules_prompt()

    hint_block = f"\nUser instruction for regeneration: {hint}\n" if hint else ""

    hashtag_block = ""
    if top_hashtags:
        hashtag_block = f"\nTop-performing hashtags from our past posts (use 2-3 of these): {' '.join(top_hashtags[:8])}\n"

    previous_block = ""
    if previous:
        previous_block = "\nPrevious attempts (write something genuinely different — different hook, different angle, different examples):\n"
        for i, p in enumerate(previous, 1):
            previous_block += f"--- Previous {i} ---\n{p[:1800]}\n"

    research_block = ""
    if topic.get("research_context"):
        research_block = f"\nLATEST RESEARCH FOUND TODAY (use specific facts/stats from these sources):\n{topic['research_context']}\n"

    prompt = f"""Write ONE high-performing LinkedIn post for The Tech Tutors.

TOPIC: {topic['title']}
ANGLE: {topic['angle']}
SOURCE URL (first comment only, NOT in post body): {topic['source_url']}
{hint_block}{hashtag_block}{research_block}{previous_block}
━━━ YOUR EXECUTION CHECKLIST ━━━

HOOK (line 1):
Choose the formula that hits HARDEST for this specific topic:
1. NUMBER SHOCK:   "73% of small businesses are paying for software they don't need"
2. CALL OUT:       "If your team still does [task] manually, read this"
3. CONTRARIAN:     "Stop using [popular thing]. Here's what actually works"
4. BEFORE/AFTER:   "6 months ago: 14 hours on invoices. Today: 40 minutes"
5. SECRET:         "Most business owners don't know their [tool] has a free AI mode"
6. HARD TRUTH:     "Your [tool] is costing you more than your rent"
7. STORY OPEN:     "A client came to us spending $3,200/month on software"
Start with: a number, "Stop", "Most", "Your", "Why", or "A [noun]"
NEVER start with: "I", "We", "In today's", "As a", "It's"

SEE MORE THRESHOLD:
Lines 1+2 combined must be under 210 characters.
Line 2 must TEASE what's coming — create a loop the brain needs to close.
NEVER give away the payoff in the first 2 lines. Earn every scroll.

BODY MUST CONTAIN:
• 4-6 lines, one specific insight each
• ONE save-worthy line: a formula, before/after number, or specific tool+outcome
• At least one dollar amount, percentage, or hours-saved figure
• A tool name or specific business type (not generic "businesses")

CLOSING QUESTION (most important for algorithm reach):
Must force a 15+ word personal answer — not a yes/no.
GOOD: "How many hours a week does your team spend on [task] — and what would you do with that time back?"
GOOD: "What's the one manual process you've been meaning to automate for months — and what's stopped you?"
BAD: "Do you agree?" / "What do you think?" / "Thoughts?" / "Tag someone"

HARD RULES:
• No links in post body
• No "The Tech Tutors" as standalone line
• 1-3 hashtags on last line only
• No "like if you agree" or any engagement bait
• Total: 1,200–1,800 characters

Return ONLY the post text — no preamble, no labels, no explanations."""

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
            found = _BANNED_WORDS_PATTERN.findall(v["text"])
            if found:
                print(f"  [content] WARNING: banned words remain after quality fix for {v['display_name']}: {found}")
        except Exception as e:
            print(f"  [content] Quality fix failed for {v['display_name']}: {e}")

    return variants


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
