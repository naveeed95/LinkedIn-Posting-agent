# CLAUDE.md

Guidance for Claude Code agents working in this repo.

## What this is

LinkedIn posting agent for **The Tech Tutors** — fully automated content engine that researches AI/SMB topics, generates text posts, routes them through Discord for human approval, then publishes to a LinkedIn **company page**. Runs 7 days/week via GitHub Actions cron at 1pm PKT.

## Stack

- **Language:** Python 3.11
- **LLM:** Groq (Llama 3.3 70B + Llama 3.1 8B) via `llm_client.py` router
- **Posting target:** LinkedIn Company Page only (`LINKEDIN_ORG_URN` required, personal posting disabled in `linkedin_poster._author_urn`)
- **Approval UX:** Discord HTTP API (no gateway/websocket — text message polling only, no reactions)
- **Storage:** SQLite (`performance.db`) + JSON (`weekly_schedule.json`) + JSON cache (`cache/linkedin_rules.json`)
- **Scheduler:** GitHub Actions cron `0 8 * * *` (8am UTC = 1pm PKT, every day)
- **Reporting:** Google Sheets (service-account JSON, base64 in env)

## Entry points

| Command | Purpose |
|---------|---------|
| `python run.py plan` | Quick pre-fetch → choose strategy → full research → plan Mon–Sun (7 slots). Sends plan to Discord #weekly-plan. |
| `python run.py` | Interactive: generate today's post, choose variant, publish. |
| `python run.py --preview` | Generate but do not publish. Auto-picks variant 1. |
| `python run.py --test` | Force-generate even if no slot matches today. |
| `python run.py auto` | Headless: generate → Discord approval → publish. Used by Actions. |
| `python run.py week` | Show this week's 7-day schedule. |
| `python run.py stats` | Engagement stats for posted slots. |
| `python linkedin_auth.py` | One-time OAuth flow. Writes tokens + org URN to `.env`. |
| `python token_refresher.py` | Refresh access token via stored refresh token. Updates GH secret if `GITHUB_PAT` + `GITHUB_REPO` set. |
| `python analytics_tracker.py --poll` | Poll metrics for last 7 days of posts. |
| `python analytics_tracker.py --weekly-report` | Print performance summary JSON. |
| `python discord_bot.py --send-report` | Build report, write to Sheets, post to Discord. |
| `python discord_bot.py --rules-update` | Send LinkedIn algorithm change alert. |
| `python auto_responder.py` | Fetch unanswered comments, generate replies, queue to Discord. |

## File map

```
run.py                     # CLI entrypoint, all command flows
content_generator.py       # Brand voice, prompts, variant gen, quality fix, strategy
llm_client.py              # Multi-model router (Groq), retries, fallback, parallel variants
research.py                # RSS, Reddit, HN, HuggingFace, Tavily, Exa, Supadata, article scrape
designer.py                # Pillow → 5-slide 1080x1080 carousel PDF (disabled in production)
linkedin_poster.py         # UGC post, asset upload, document upload, first comment, stats
linkedin_auth.py           # OAuth: localhost callback, state/CSRF, token + org URN to .env
token_refresher.py         # Refresh token; encrypt and PUT to GitHub secrets
linkedin_rules_fetcher.py  # Cached LinkedIn algorithm rules (7-day TTL, RSS + Reddit)
analytics_tracker.py       # SQLite schema, log_post, poll_metrics, summary, Sheets export
discord_bot.py             # HTTP API: approval messages, polling for replies, reports
auto_responder.py          # LinkedIn comment reply suggestions → Discord queue
scheduler.py               # weekly_schedule.json read/write, week slot logic (Mon–Sun)
test_llm.py                # Smoke test for Groq models
.github/workflows/
  daily_post.yml           # Cron: 0 8 * * * (1pm PKT daily) → python run.py auto
  weekly_plan.yml          # Cron: 0 13 * * 0 (6pm PKT Sunday) → python run.py plan
  weekly_report.yml        # Weekly analytics report to Discord + Sheets
  analytics.yml            # Daily metrics poll for recent posts
  comment_reply.yml        # Auto-responder for LinkedIn comments
  rules_update.yml         # Refresh LinkedIn rules cache weekly
  token_refresh.yml        # Rotate LinkedIn access token monthly
weekly_schedule.json       # State: per-week 7-day slots + strategy (Mon–Sun)
performance.db             # SQLite: posts, metrics, topics_history, hashtag_metrics
cache/linkedin_rules.json  # Algorithm rules cache (7-day TTL)
output/                    # Generated PDFs / PNGs (gitignored)
```

## Required env vars

**LLM:**
- `GROQ_API_KEY` — *required*. Raises `EnvironmentError` on first model call if missing.

**LinkedIn:**
- `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` — for OAuth + refresh.
- `LINKEDIN_ACCESS_TOKEN` — short-lived (60 days). Raises `EnvironmentError` if missing.
- `LINKEDIN_REFRESH_TOKEN` — long-lived. Set by `linkedin_auth.py`.
- `LINKEDIN_ORG_URN` — *required* (e.g. `urn:li:organization:12345`). Personal URN deliberately rejected.

**Discord:**
- `DISCORD_BOT_TOKEN`
- `DISCORD_APPROVALS_CHANNEL_ID` — daily post approval
- `DISCORD_POSTED_CHANNEL_ID` — post confirmation after publishing
- `DISCORD_ANALYTICS_CHANNEL_ID` — reports + failure alerts
- `DISCORD_COMMENTS_CHANNEL_ID` — comment reply suggestions
- `DISCORD_PLAN_CHANNEL_ID` — weekly plan summary (channel: #weekly-plan, id: 1501381134083293324)

**GitHub (for token refresh):**
- `GITHUB_PAT` — PAT with `secrets:write` on this repo.
- `GITHUB_REPO` — `owner/name`.

**Optional research:**
- `TAVILY_API_KEY` — semantic search; queries dynamically generated from weekly domain
- `EXA_API_KEY` — find similar content to top past posts
- `SUPADATA_API_KEY` — YouTube transcripts (Matt Wolfe, Two Minute Papers, Karpathy)

**Optional reporting:**
- `GOOGLE_SERVICE_ACCOUNT_JSON` — base64-encoded service account JSON.
- `GOOGLE_SHEET_ID`
- `LANDING_PAGE_URL` — included in first-comment CTA.

## Architecture notes

### Weekly planning flow (`python run.py plan`)

```
1. Quick pre-fetch — RSS feeds + HN only (~45 topics, no API key needed)
         ↓
2. choose_weekly_strategy(trending_sample=top15)
   LLM picks domain grounded in REAL trending headlines (not just guessing)
   Returns: domain, content_pillar, focus_keywords, posting_time, rationale
         ↓
3. fetch_trending_topics(domain=..., focus_keywords=...)
   All sources run. Tavily uses dynamic domain-aware queries (not static hardcoded).
   Topics scored: smb_bonus=100, domain_bonus=60, kw_bonus=40, virality=log2(pts)*3
   SMB-relevant Tavily articles (~140) always outrank viral Reddit memes (~40).
         ↓
4. plan_weekly_posts(topics, strategy=strategy)
   7 slots Mon–Sun. Each day has strict per-day criteria (PURPOSE / ANGLE MUST /
   BEST TOPIC FIT / SCORING BONUS / ANGLE EXAMPLE / REJECT IF).
   Returns: title, source_url, angle, format, score, why per slot.
         ↓
5. init_week(slots) → weekly_schedule.json
6. send_weekly_plan() → Discord #weekly-plan (DISCORD_PLAN_CHANNEL_ID)
```

### Day strategy (all text format)

| Day | Purpose | Angle must include |
|-----|---------|-------------------|
| Mon | Challenge a limiting belief about AI cost/complexity | Specific belief + counter-fact with number |
| Tue | Spotlight one AI tool with measurable ROI | Tool name + time/money saved + price point |
| Wed | Step-by-step process a solo founder can implement | Process name + step count + time to implement |
| Thu | Data-driven AI development with direct SMB impact | Specific stat (%, $, hrs) + SMB implication |
| Fri | Counterintuitive insight that reframes AI adoption | Surprising truth + who it affects + implication |
| Sat | Quick AI tip/hack under 10 minutes | Shortcut name + time to do + problem solved |
| Sun | Conversation-starting question | Specific question inviting personal business experience |

Defined in `content_generator.DAY_STRATEGY` and `DAY_FORMAT` (all `"text"`).
**Always derive format from `DAY_FORMAT[day_index]`, never from `slot["format"]`** — slot field may be stale from old planning runs.

### Daily post flow (`python run.py auto`)

```
get_today_slot()
  → fetch_deep_topic_research(topic_title, focus_keywords)  # targeted Tavily + HN + Reddit
  → generate_text_post_variants(topic)                      # Llama 3.3 70B
  → _fix_post_quality()                                     # strip banned words
  → send_approval_message() → wait_for_approval(120 min)
  → post_to_linkedin() → post_first_comment()
  → log_post() → send_posted_confirmation()
```

Discord approval commands (reply in #approvals channel):
- `1` — post the variant
- `r make it punchier` — regenerate with hint (max 3 attempts)
- `edit: [full post text]` — post custom text verbatim
- `skip` — log slot as skipped

### LinkedIn rules injection
`linkedin_rules_fetcher.fetch_rules()` fetches from SocialMediaExaminer, Buffer Blog, Search Engine Journal RSS + Reddit r/linkedin (signal-only filter — user complaints and off-topic posts discarded). Cached 7 days. Injected into the system prompt for ALL LLM calls: post generation, strategy selection, and weekly planning via `_generate()`.

Reddit filter: only posts with keywords like `algorithm / reach / engagement / strategy / tip / visibility` pass through.

### Research scoring
```python
_score = smb_bonus(100) + domain_bonus(60) + kw_bonus(40) + int(log2(points+1) * 3)
```
A Tavily article about "AI automation ROI for SMBs" (score=140) always beats a viral Reddit meme (score≈40). Virality is a tie-breaker only.

### Weekly state
`weekly_schedule.json` keyed by ISO Monday of the week. Strategy stored as `{monday}_strategy`. 7 slots per week (Mon–Sun). Posts mutate slot in place. Persists between Action runs via artifact upload/download.

Schema:
```json
{
  "2026-05-04": [
    {
      "day": "Monday",
      "date": "2026-05-04",
      "topic": {
        "title": "AI Isn't Just for Big Business",
        "source_url": "https://example.com/article",
        "angle": "Most SMB owners think AI costs $500/month. The average is now $23.",
        "why": "Challenges the limiting belief that AI is too expensive for SMBs"
      },
      "format": "text",
      "post_text": null,
      "design_brief": null,
      "status": "pending",
      "post_urn": null,
      "chosen_model": null
    }
  ],
  "2026-05-04_strategy": {
    "domain": "AI Automation (no-code / low-code)",
    "content_pillar": "SMB owners need to automate repetitive tasks without coding knowledge",
    "focus_keywords": ["no-code automation 2026", "low-code ai tools", "small business productivity"],
    "posting_time": "1pm PKT",
    "rationale": "..."
  }
}
```

### Variant generation
`llm_client.generate_variants(job, ...)` runs every model in `VARIANT_MODELS[job]` in parallel via `ThreadPoolExecutor`. Currently `text` and `carousel` jobs use only `["llama-70b"]` → one variant per generation. Add more model keys to `MODELS` + `VARIANT_MODELS` to enable multi-model approval flow.

### Banned-word quality fix
Every post variant runs through `_fix_post_quality` — Llama 70B pass that strips banned words (`delve`, `leverage`, `synergy`, `game-changer`, `revolutionary`, `cutting-edge`, etc.), normalises hashtags to 3–5 at end only, removes URLs from post body. Never skip this pass — banned words cause LinkedIn algorithm penalty.

## GitHub Actions workflows

| Workflow | Cron (UTC) | PKT | What it does |
|----------|-----------|-----|-------------|
| `daily_post.yml` | `0 8 * * *` | 1pm daily | Generate → Discord approval → post |
| `weekly_plan.yml` | `0 13 * * 0` | 6pm Sunday | Research → plan 7 days → Discord |
| `weekly_report.yml` | Weekly | — | Analytics summary → Discord + Sheets |
| `analytics.yml` | Daily | — | Poll LinkedIn metrics for recent posts |
| `comment_reply.yml` | Daily | — | Fetch comments → suggest replies → Discord |
| `rules_update.yml` | Weekly | — | Refresh LinkedIn rules cache |
| `token_refresh.yml` | Monthly | — | Rotate LinkedIn access token |

Artifact persistence:
- `performance-db` — SQLite analytics DB (90-day retention)
- `weekly-schedule` — current week's 7-slot state (90-day retention)
- `linkedin-rules` — algorithm rules cache (7-day retention)

Concurrency group: `posting-agent-db` with `cancel-in-progress: false` on all workflows that touch the DB or schedule artifact.

## Known production gotchas

1. **Designer fonts** — `designer.py:46` hardcoded to `C:/Windows/Fonts/`. Falls back to bitmap font on Linux (GitHub Actions). Carousels disabled in production (`DAY_FORMAT` all-text) so this doesn't fire currently.
2. **`performance.db` lives in artifacts** — 90-day retention, no external backup. Failed upload loses analytics history.
3. **Supadata channel IDs stale** — Matt Wolfe and Karpathy YouTube channel IDs in `research.py` return "channel does not exist". Update or remove those entries.
4. **Hacker News** — returning 0 results in recent runs. Check if API query needs updating or if rate-limited.
5. **No structured logging** — `print` only with `[area]` prefix. Add `logging` module if integrating with cloud log aggregation.
6. **Discord 2000-char split** — `_send_long_message` splits at `━━━` dividers then newlines. No automated test covers boundary cases.
7. **Artifact race** — concurrency group prevents parallel runs but a cancelled mid-upload can corrupt state between runs.
8. **`linkedin_auth.py`** — writes tokens to `.env` via `set_key`. Never run in CI — requires interactive browser flow.

## Conventions

- `--preview` for dry-run (no publish, auto-picks variant 1). `--test` for off-schedule generation.
- All `print` lines prefixed `[area]` (e.g. `[research]`, `[discord]`, `[content]`, `[llm]`, `[rules]`) for grep-ability.
- `BRAND_CONTEXT` and `WRITING_SYSTEM` in `content_generator.py` are source of truth for brand voice. Never inline overrides — use `system_extra` parameter on `_generate()`.
- Brand colours in `designer.py:16-30` — modify both modern and legacy aliases together.
- Format always derived from `DAY_FORMAT[day_index]`, never from `slot["format"]` field.
- `auto_responder.fetch_recent_post_urns` — always check `isinstance(week_slots, list)` before iterating schedule values (strategy entries are dicts, not lists).

## Don'ts

- Don't post to a personal LinkedIn URN. `_author_urn()` enforces org-only.
- Don't add `cerebras-llama` or `OPENROUTER_API_KEY` paths — not in `MODELS`, will raise `KeyError`.
- Don't commit `.env`, `performance.db`, `cache/*.json`, or `output/`.
- Don't skip `_fix_post_quality`. Banned words leak into LinkedIn and cause algorithm penalty.
- Don't run `linkedin_auth.py` in CI — interactive browser flow only.
- Don't read format from `slot["format"]` — use `DAY_FORMAT[day_index]`. Slot format field may be stale after a replan.
- Don't add a personal LinkedIn fallback to `_author_urn()`.

## Tests

Only `test_llm.py` exists — smoke test for Groq models. No real test suite.

Run on Windows (avoids cp1252 emoji encoding crash):
```bash
python -c "import sys,io; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace'); exec(open('test_llm.py').read())"
```

Quick pipeline test without touching the schedule:
```bash
python run.py --test --preview
```
