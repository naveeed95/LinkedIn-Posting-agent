# CLAUDE.md

Guidance for Claude Code agents working in this repo.

## What this is

LinkedIn posting agent for **The Tech Tutors** — fully automated content engine that researches a fresh AI/SMB topic *every day at write-time* (no weekly pre-plan), generates text posts via an agentic Groq tool-use loop, routes them through Discord for human approval, then publishes to a LinkedIn **company page**. Runs 7 days/week via GitHub Actions cron at 1pm PKT.

## Stack

- **Language:** Python 3.11
- **LLM / Agent:** Groq (Llama 3.3 70B + Llama 3.1 8B) via `llm_client.py` router; agentic loop in `agent_runner.py`
- **Posting target:** LinkedIn Company Page only (`LINKEDIN_ORG_URN` required, personal posting disabled in `linkedin_poster._author_urn`)
- **Approval UX:** Discord HTTP API (no gateway/websocket — text message polling only, no reactions)
- **Storage:** SQLite (`performance.db`) + JSON cache (`cache/linkedin_rules.json`)
- **Scheduler:** GitHub Actions cron `0 8 * * *` (8am UTC = 1pm PKT, every day)
- **Reporting:** Google Sheets (service-account JSON, base64 in env)

## Entry points

| Command | Purpose |
|---------|---------|
| `python run.py` | Headless agentic loop: research fresh topic → generate → Discord approval → publish. Used by Actions and as the only daily entry point. |
| `python run.py --preview` | Generate and score but do not publish or send to Discord. |
| `python linkedin_auth.py` | One-time OAuth flow. Writes tokens + org URN to `.env`. |
| `python token_refresher.py` | Refresh access token via stored refresh token. Updates GH secret if `GITHUB_PAT` + `GITHUB_REPO` set. |
| `python analytics_tracker.py --poll` | Poll metrics for last 7 days of posts. |
| `python analytics_tracker.py --weekly-report` | Print performance summary JSON. |
| `python discord_bot.py --send-report` | Build report, write to Sheets, post to Discord. |
| `python discord_bot.py --rules-update` | Send LinkedIn algorithm change alert. |
| `python auto_responder.py` | Fetch unanswered comments, generate replies, queue to Discord. |

## File map

```
agent_runner.py            # Groq tool-use agentic loop — researches + writes + posts, daily
run.py                     # CLI entrypoint — thin wrapper around agent_runner.run_agent
content_generator.py       # Brand voice, prompts, variant gen, quality fix, daily topic pick
llm_client.py              # Multi-model router (Groq), retries, fallback, parallel variants
research.py                # RSS, Reddit, HN, HuggingFace, Tavily, Exa, article scrape
logger.py                  # Structured logging — text by default, JSON when LOG_FORMAT=json
linkedin_poster.py         # UGC post, first comment
linkedin_auth.py           # OAuth: localhost callback, state/CSRF, token + org URN to .env
token_refresher.py         # Refresh token; encrypt and PUT to GitHub secrets
linkedin_rules_fetcher.py  # LinkedIn algorithm rules via Tavily search (24h TTL cache)
analytics_tracker.py       # SQLite schema, log_post, poll_metrics, summary, Sheets export
discord_bot.py             # HTTP API: approval messages, polling for replies, reports
auto_responder.py          # LinkedIn comment reply suggestions → Discord queue
topic_similarity.py        # MiniLM embedding dedup: soft penalty, hard topic filter, post-content dup check
topic_log.py               # Permanent, git-committed log of posted topics/post text (data/posted_topics.json)
test_llm.py                # Smoke test for Groq models
.github/workflows/
  daily_post.yml           # Cron: 0 8 * * * (1pm PKT daily) → python run.py
  weekly_report.yml        # Weekly analytics report to Discord + Sheets
  analytics.yml            # Daily metrics poll for recent posts
  comment_reply.yml        # Auto-responder for LinkedIn comments
  rules_update.yml         # Refresh LinkedIn rules cache
  token_refresh.yml        # Rotate LinkedIn access token monthly
performance.db             # SQLite: posts, metrics, topics_history, hashtag_metrics
data/posted_topics.json    # Permanent dedup log — committed to git, never reset (see topic_log.py)
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

### No weekly plan — daily research at write-time

There is **no pre-planning step and no `weekly_schedule.json`**. Every day, `agent_runner.run_agent()` researches and picks a fresh topic itself (`pick_daily_topic` in `content_generator.py`, guided by `topic_similarity.apply_dedup_penalty` to avoid repeating recent themes by semantic similarity to recently-posted topics). This replaced an older weekly-pre-plan flow (`run.py plan` / `scheduler.py` / `weekly_schedule.json`) that has been fully removed — don't reintroduce slot-based scheduling, `DAY_FORMAT`/`DAY_STRATEGY` constants, or per-day pre-assignment.

### Permanent topic-dedup (hard guarantee)

`performance.db` and `cache/*.json` live in CI cache and can be evicted or cold-start empty — never a reliable dedup source on their own. `data/posted_topics.json` (via `topic_log.py`) is **committed to git after every successful publish** and is the permanent source of truth:

- `tool_pick_daily_topic()` fetches `topic_log.get_all_titles()` (all-time, normalized) and passes it to `fetch_trending_topics(all_posted_titles=...)`, which calls `topic_similarity.filter_hard_duplicates()` to **structurally remove** any topic ever posted before — and any topic semantically ≥0.80 similar to a post from the last 30 days — before the LLM even sees the candidate list. A topic can never be picked twice.
- `topic_log.get_recent_topic_texts(days=30)` feeds `apply_dedup_penalty` (soft scoring penalty) same as before.
- `tool_score_post()` additionally calls `topic_similarity.is_duplicate_post()` against `topic_log.get_recent_post_texts(days=7)` — if the *generated post body* is ≥0.85 similar to anything published in the last week (even on a different topic/angle), it's scored as `ready_to_send: False` and the agent regenerates with a "make this distinctly different" hint.
- `tool_publish_post()` calls `topic_log.record_posted_topic(title, topic_text, source_url, post_text)` on every successful publish. `daily_post.yml` commits and pushes `data/posted_topics.json` at the end of the run (`permissions: contents: write`).

**Live LinkedIn ground-truth layer** (`linkedin_poster.get_recent_org_posts`): `tool_pick_daily_topic()` also fetches the org page's own last-30-days posts directly from the LinkedIn API and merges them into `recent_topic_texts` (feeds `filter_hard_duplicates`/`apply_dedup_penalty`) and into `state["recent_post_texts"]` (feeds `is_duplicate_post`, last-7-days). This covers topics posted *before* `data/posted_topics.json` existed (or after any future reset/eviction of that file) — LinkedIn itself is the source of truth, not just the git log. Fails open (empty list) if the API call errors, so it never blocks posting.

Don't bypass `topic_log` for dedup — `performance.db`-based history (`get_topic_history`, `get_recent_topic_texts` in `analytics_tracker.py`) is no longer used for this purpose because it's not durable.

### Daily post flow (`python run.py`)

```
agent_runner.run_agent()  ← Groq Llama 3.3 70B tool-use loop
  → get_analytics_summary()
  → research_topic()       # Tavily + HN + Reddit; also fetches fresh LinkedIn rules
  → pick_daily_topic()     # LLM picks today's topic from researched candidates, dedup-penalized
  → generate_post()        # Llama 3.3 70B, live rules injected
  → score_post()           # dynamic threshold (90% of recent_avg, clamped 55–75, fallback 62)
  → send_for_approval()    # Discord 120-min wait
  → publish_post()         # post_to_linkedin + first comment + log_post
```

Discord approval commands (reply in #approvals channel):
- `1` — post the variant
- `r make it punchier` — regenerate with hint (max 3 attempts)
- `new topic` / `new topic: focus on automation` — scrap current topic, pick a different one from today's research pool and regenerate (max 1 switch per run — second wait is 60min, not 120min)
- `edit: [full post text]` — post custom text verbatim
- `skip` — log slot as skipped

### LinkedIn rules injection
`linkedin_rules_fetcher.fetch_rules()` runs 5 parallel Tavily queries about current LinkedIn algorithm rules and best practices. Results cached 24 hours in `cache/linkedin_rules.json`. Injected into system prompt for ALL LLM calls via `_generate()`. If `TAVILY_API_KEY` is missing, rules injection is silently skipped — posts still generate without it.

### Research scoring
```python
_score = smb_bonus(100) + domain_bonus(60) + kw_bonus(40) + int(log2(points+1) * 3)
```
A Tavily article about "AI automation ROI for SMBs" (score=140) always beats a viral Reddit meme (score≈40). Virality is a tie-breaker only.

### Variant generation
`llm_client.generate_variants(job, ...)` runs every model in `VARIANT_MODELS[job]` in parallel via `ThreadPoolExecutor`. Currently the `text` and `research` jobs use only `["deepseek-pro"]` → one variant per generation. Add more model keys to `MODELS` + `VARIANT_MODELS` to enable multi-model approval flow.

### Banned-word quality fix
Every post variant runs through `_fix_post_quality` — Llama 70B pass that strips banned words (`delve`, `leverage`, `synergy`, `game-changer`, `revolutionary`, `cutting-edge`, etc.), normalises hashtags to 3–5 at end only, removes URLs from post body. Never skip this pass — banned words cause LinkedIn algorithm penalty.

### Engagement score threshold
`agent_runner.tool_score_post` computes a dynamic threshold: 90% of `recent_avg_score` from analytics, clamped 55–75. Falls back to 62 when no posting history exists. Agent regenerates if score is below threshold (max 3 attempts total).

## GitHub Actions workflows

| Workflow | Cron (UTC) | PKT | What it does |
|----------|-----------|-----|-------------|
| `daily_post.yml` | `0 8 * * *` | 1pm daily | Agentic generate → Discord approval → post |
| `weekly_report.yml` | Weekly | — | Analytics summary → Discord + Sheets |
| `analytics.yml` | Daily | — | Poll LinkedIn metrics for recent posts |
| `comment_reply.yml` | Daily | — | Fetch comments → suggest replies → Discord |
| `rules_update.yml` | Weekly | — | Refresh LinkedIn rules cache |
| `token_refresh.yml` | Monthly | — | Rotate LinkedIn access token |

Persistence (via `actions/cache@v4`, not artifacts — artifacts are run-scoped in v4 and can't be restored cross-run):
- `performance.db` — `performance-db-${{ github.run_id }}` key, `performance-db-` restore-keys prefix.
- `cache/linkedin_rules.json` — `linkedin-rules-<date>` key, `linkedin-rules-` restore-keys prefix (24h TTL enforced by `linkedin_rules_fetcher.py`, not the cache key).
- `data/posted_topics.json` — committed directly to git by `daily_post.yml` after publish (see "Permanent topic-dedup" above), not cached.

Concurrency group: `posting-agent-db` with `cancel-in-progress: false` on all workflows that touch the DB.

## Known production gotchas

1. **`performance.db` lives in CI cache** — subject to eviction (7-day idle, 10GB repo cap). It's a secondary signal only; permanent topic-dedup relies on `data/posted_topics.json`, not this DB.
2. **Hacker News** — three-tier fetch (keyword+date → top-stories-by-points → no-date fallback) in `fetch_hacker_news`. Browser-like UA in `HEADERS` since Algolia rejects niche User-Agents.
3. **Discord 2000-char split** — `_send_long_message` splits at `━━━` dividers then newlines. No automated test covers boundary cases.
4. **Artifact race** — concurrency group prevents parallel runs but a cancelled mid-upload can corrupt state between runs.
5. **`linkedin_auth.py`** — writes tokens to `.env` via `set_key`. Never run in CI — requires interactive browser flow.

## Conventions

- `--preview` for dry-run (generate + score, no publish, no Discord).
- **Structured logging** via `logger.get_logger("area")` — emits text locally, JSON when `LOG_FORMAT=json` (set in all workflows). Areas: `agent`, `analytics`, `auto`, `content`, `discord`, `linkedin`, `llm`, `preview`, `research`, `responder`, `rules`, `similarity`, `startup`, `token_refresher`. Use `extra={"key": value}` for structured fields. CLI UX prints (banners, separators, interactive prompts) stay as `print()`.
- `BRAND_CONTEXT` and `WRITING_SYSTEM` in `content_generator.py` are source of truth for brand voice. Never inline overrides — use `system_extra` parameter on `_generate()`.
- Post format/topic/angle are decided fresh each day by the agent loop at write-time — there is no pre-assigned per-day schedule to read from.

## Don'ts

- Don't post to a personal LinkedIn URN. `_author_urn()` enforces org-only.
- Don't add `cerebras-llama` or `OPENROUTER_API_KEY` paths — not in `MODELS`, will raise `KeyError`.
- Don't commit `.env`, `performance.db`, `cache/*.json`, or `output/`. (`data/posted_topics.json` IS committed — that's the permanent dedup log, see "Permanent topic-dedup".)
- Don't skip `_fix_post_quality`. Banned words leak into LinkedIn and cause algorithm penalty.
- Don't run `linkedin_auth.py` in CI — interactive browser flow only.
- Don't reintroduce weekly pre-planning, `weekly_schedule.json`, slot-based scheduling, or `DAY_FORMAT`/`DAY_STRATEGY` constants — topic + format are decided dynamically by the LLM at write-time, daily.
- Don't add a personal LinkedIn fallback to `_author_urn()`.

## Tests

Only `test_llm.py` exists — smoke test for Groq models. No real test suite.

Run on Windows (avoids cp1252 emoji encoding crash):
```bash
python -c "import sys,io; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace'); exec(open('test_llm.py').read())"
```

Quick pipeline test without publishing:
```bash
python run.py --preview
```
