# CLAUDE.md

Guidance for Claude Code agents working in this repo.

## What this is

LinkedIn posting agent for **The Tech Tutors** — fully automated content engine that researches AI/SMB topics, generates text posts via an agentic Groq tool-use loop, routes them through Discord for human approval, then publishes to a LinkedIn **company page**. Runs 7 days/week via GitHub Actions cron at 1pm PKT.

## Stack

- **Language:** Python 3.11
- **LLM / Agent:** Groq (Llama 3.3 70B + Llama 3.1 8B) via `llm_client.py` router; agentic loop in `agent_runner.py`
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
| `python run.py auto` | Headless agentic loop (agent_runner.py). Used by Actions. |
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
agent_runner.py            # Groq tool-use agentic loop (8 tools, daily posting)
run.py                     # CLI entrypoint, all command flows
content_generator.py       # Brand voice, prompts, variant gen, quality fix, strategy
llm_client.py              # Multi-model router (Groq), retries, fallback, parallel variants
research.py                # RSS, Reddit, HN, HuggingFace, Tavily, Exa, article scrape
logger.py                  # Structured logging — text by default, JSON when LOG_FORMAT=json
designer.py                # Pillow → 5-slide 1080x1080 carousel PDF (disabled in production)
linkedin_poster.py         # UGC post, asset upload, document upload, first comment, stats
linkedin_auth.py           # OAuth: localhost callback, state/CSRF, token + org URN to .env
token_refresher.py         # Refresh token; encrypt and PUT to GitHub secrets
linkedin_rules_fetcher.py  # LinkedIn algorithm rules via Tavily search (24h TTL cache)
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
  rules_update.yml         # Refresh LinkedIn rules cache
  token_refresh.yml        # Rotate LinkedIn access token monthly
weekly_schedule.json       # State: per-week 7-day slots + strategy (Mon–Sun)
performance.db             # SQLite: posts, metrics, topics_history, hashtag_metrics
cache/linkedin_rules.json  # Algorithm rules cache (24h TTL, Tavily-fetched)
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
- `TAVILY_API_KEY` — semantic search for topics AND LinkedIn algorithm rules fetch (also used for YouTube broad search)
- `EXA_API_KEY` — find similar content to top past posts

**Logging:**
- `LOG_FORMAT` — `json` for one-line-per-record JSON output (set in all GH Actions workflows), anything else for human-readable text (default).
- `LOG_LEVEL` — `INFO` (default), `DEBUG`, `WARNING`, etc.

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
   LLM derives domain FREELY from trending headlines — no hardcoded domain list.
   Returns: domain, content_pillar, focus_keywords, posting_time, rationale
         ↓
3. fetch_trending_topics(domain=..., focus_keywords=...)
   All sources run. Tavily uses dynamic domain-aware queries.
   Topics scored: smb_bonus=100, domain_bonus=60, kw_bonus=40, virality=log2(pts)*3
         ↓
4. plan_weekly_posts(topics, strategy=strategy)
   7 slots Mon–Sun. LLM decides angle + content style for EACH day dynamically,
   guided by live LinkedIn algorithm rules (Tavily-fetched) injected in system prompt.
   Returns: title, source_url, angle, format, score, why per slot.
         ↓
5. init_week(slots) → weekly_schedule.json
6. send_weekly_plan() → Discord #weekly-plan (DISCORD_PLAN_CHANNEL_ID)
```

### Day strategy — fully dynamic

Day strategies are **not hardcoded**. During weekly planning the LLM:
- Reads live LinkedIn algorithm rules fetched via Tavily (injected into system prompt)
- Reviews trending topics and past performance analytics
- Decides angle, hook style, and content type for each day
- Varies content mix (insights, how-tos, tools, stats, questions, opinions) to avoid repetition

`slot["format"]` set during planning is the authoritative source for post format — read it directly. There is no `DAY_FORMAT` or `DAY_STRATEGY` constant.

### Daily post flow (`python run.py auto`)

```
agent_runner.run_agent()  ← Groq Llama 3.3 70B tool-use loop
  → get_today_slot()
  → get_analytics_summary()
  → research_topic()       # Tavily + HN + Reddit; also fetches fresh LinkedIn rules
  → generate_post()        # Llama 3.3 70B, live rules injected
  → score_post()           # dynamic threshold (90% of recent_avg, clamped 55–75, fallback 62)
  → send_for_approval()    # Discord 120-min wait
  → publish_post()         # post_to_linkedin + first comment + log_post
```

Discord approval commands (reply in #approvals channel):
- `1` — post the variant
- `r make it punchier` — regenerate with hint (max 3 attempts)
- `edit: [full post text]` — post custom text verbatim
- `skip` — log slot as skipped

### LinkedIn rules injection
`linkedin_rules_fetcher.fetch_rules()` runs 5 parallel Tavily queries about current LinkedIn algorithm rules and best practices. Results cached 24 hours in `cache/linkedin_rules.json`. Injected into system prompt for ALL LLM calls via `_generate()`. If `TAVILY_API_KEY` is missing, rules injection is silently skipped — posts still generate without it.

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
        "why": "LLM chose this angle based on trending headlines + LinkedIn rules"
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
    "domain": "AI invoice automation for freelancers",
    "content_pillar": "Solo founders waste 4hrs/week on invoicing that AI handles in minutes",
    "focus_keywords": ["ai invoice automation 2026", "freelancer ai tools", "small business billing ai"],
    "posting_time": "8am PKT",
    "rationale": "..."
  }
}
```

### Variant generation
`llm_client.generate_variants(job, ...)` runs every model in `VARIANT_MODELS[job]` in parallel via `ThreadPoolExecutor`. Currently `text` and `carousel` jobs use only `["llama-70b"]` → one variant per generation. Add more model keys to `MODELS` + `VARIANT_MODELS` to enable multi-model approval flow.

### Banned-word quality fix
Every post variant runs through `_fix_post_quality` — Llama 70B pass that strips banned words (`delve`, `leverage`, `synergy`, `game-changer`, `revolutionary`, `cutting-edge`, etc.), normalises hashtags to 3–5 at end only, removes URLs from post body. Never skip this pass — banned words cause LinkedIn algorithm penalty.

### Engagement score threshold
`agent_runner.tool_score_post` computes a dynamic threshold: 90% of `recent_avg_score` from analytics, clamped 55–75. Falls back to 62 when no posting history exists. Agent regenerates if score is below threshold (max 3 attempts total).

## GitHub Actions workflows

| Workflow | Cron (UTC) | PKT | What it does |
|----------|-----------|-----|-------------|
| `daily_post.yml` | `0 8 * * *` | 1pm daily | Agentic generate → Discord approval → post |
| `weekly_plan.yml` | `0 13 * * 0` | 6pm Sunday | Research → plan 7 days → Discord |
| `weekly_report.yml` | Weekly | — | Analytics summary → Discord + Sheets |
| `analytics.yml` | Daily | — | Poll LinkedIn metrics for recent posts |
| `comment_reply.yml` | Daily | — | Fetch comments → suggest replies → Discord |
| `rules_update.yml` | Weekly | — | Refresh LinkedIn rules cache |
| `token_refresh.yml` | Monthly | — | Rotate LinkedIn access token |

Artifact persistence:
- `performance-db` — SQLite analytics DB (90-day retention)
- `weekly-schedule` — current week's 7-slot state (90-day retention)
- `linkedin-rules` — algorithm rules cache (1-day retention)

Concurrency group: `posting-agent-db` with `cancel-in-progress: false` on all workflows that touch the DB or schedule artifact.

## Known production gotchas

1. **Designer fonts** — `designer.py:46` hardcoded to `C:/Windows/Fonts/`. Falls back to bitmap font on Linux (GitHub Actions). Carousels are text-only in production so this doesn't fire currently.
2. **`performance.db` lives in artifacts** — 90-day retention, no external backup. Failed upload loses analytics history.
3. **Hacker News** — three-tier fetch (keyword+date → top-stories-by-points → no-date fallback) in `fetch_hacker_news`. Browser-like UA in `HEADERS` since Algolia rejects niche User-Agents.
4. **Discord 2000-char split** — `_send_long_message` splits at `━━━` dividers then newlines. No automated test covers boundary cases.
5. **Artifact race** — concurrency group prevents parallel runs but a cancelled mid-upload can corrupt state between runs.
6. **`linkedin_auth.py`** — writes tokens to `.env` via `set_key`. Never run in CI — requires interactive browser flow.

## Conventions

- `--preview` for dry-run (no publish, auto-picks variant 1). `--test` for off-schedule generation.
- **Structured logging** via `logger.get_logger("area")` — emits text locally, JSON when `LOG_FORMAT=json` (set in all workflows). Areas: `agent`, `analytics`, `auto`, `content`, `discord`, `linkedin`, `llm`, `plan`, `preview`, `research`, `responder`, `rules`, `scheduler`, `startup`, `token_refresher`. Use `extra={"key": value}` for structured fields. CLI UX prints (banners, separators, interactive prompts) stay as `print()`.
- `BRAND_CONTEXT` and `WRITING_SYSTEM` in `content_generator.py` are source of truth for brand voice. Never inline overrides — use `system_extra` parameter on `_generate()`.
- Brand colours in `designer.py:16-30` — modify both modern and legacy aliases together.
- Post format comes from `slot["format"]` set at planning time — read it directly. No `DAY_FORMAT` constant exists.
- `auto_responder.fetch_recent_post_urns` — always check `isinstance(week_slots, list)` before iterating schedule values (strategy entries are dicts, not lists).

## Don'ts

- Don't post to a personal LinkedIn URN. `_author_urn()` enforces org-only.
- Don't add `cerebras-llama` or `OPENROUTER_API_KEY` paths — not in `MODELS`, will raise `KeyError`.
- Don't commit `.env`, `performance.db`, `cache/*.json`, or `output/`.
- Don't skip `_fix_post_quality`. Banned words leak into LinkedIn and cause algorithm penalty.
- Don't run `linkedin_auth.py` in CI — interactive browser flow only.
- Don't add a `DAY_FORMAT` or `DAY_STRATEGY` constant — day strategies are decided dynamically by the LLM during weekly planning.
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
