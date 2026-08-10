# The Tech Tutors — LinkedIn Posting Agent

Automated LinkedIn content engine for **The Tech Tutors** company page. Every day it researches a fresh AI/SMB topic from scratch, generates a post with an LLM, routes it through Discord for human approval, then publishes to LinkedIn. Runs 7 days/week via GitHub Actions — there is no weekly pre-plan; research happens at write-time, daily.

## How it works

```
Daily post (1pm PKT) — agent_runner.run_agent(), a fixed-order Python pipeline
  1. pick_daily_topic     research all sources, drop anything ever posted before,
                          LLM picks today's topic from what survives
  2. get_analytics        recent performance + top hashtags for context
  3. research_topic       deeper search on the chosen topic
  4. generate + score     up to 3 attempts, stop early once the score clears
                          the dynamic threshold
  5. Discord approval     120-minute window in #approvals
  6. publish              LinkedIn UGC post, first comment, analytics log,
                          permanent topic log, Reddit draft to Discord
```

Topic, angle, and hook are decided fresh each day from live research, current LinkedIn algorithm rules fetched via Tavily, and recent post performance — nothing is pre-scheduled or hardcoded.

> **Silence publishes.** If nobody replies in Discord before the window closes, the post goes live automatically. The approval step is a veto window, not a gate — a post you don't want out has to be actively skipped.

## Stack

| Layer | Technology |
|-------|-----------|
| LLM | DeepSeek — `deepseek-v4-pro` (writing) + `deepseek-v4-flash` (scoring), via the OpenAI SDK |
| Posting target | LinkedIn Company Page (UGC API) |
| Approval UX | Discord HTTP API (polling, no gateway) |
| Research + Rules | Tavily, Exa, Reddit, Hacker News, RSS, HuggingFace, YouTube |
| Dedup | `all-MiniLM-L6-v2` sentence embeddings, run locally |
| Analytics | SQLite + Google Sheets |
| Scheduler | GitHub Actions cron (+ watchdog fallback) |

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in your keys

python run.py --preview       # generate and score only, nothing published
python run.py                 # full run: research, generate, Discord approval, publish
```

## Required environment variables

```env
# LLM
DEEPSEEK_API_KEY=

# LinkedIn
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_REFRESH_TOKEN=
LINKEDIN_ORG_URN=urn:li:organization:XXXXX   # required — personal posting is rejected

# Discord
DISCORD_BOT_TOKEN=
DISCORD_APPROVALS_CHANNEL_ID=
DISCORD_POSTED_CHANNEL_ID=
DISCORD_ANALYTICS_CHANNEL_ID=
DISCORD_COMMENTS_CHANNEL_ID=
DISCORD_REDDIT_CHANNEL_ID=         # optional — daily Reddit draft; skipped if unset
DISCORD_REDDIT_LEADS_CHANNEL_ID=   # optional — hiring-intent leads; skipped if unset

# Optional research + rules (strongly recommended)
TAVILY_API_KEY=        # topic research AND live LinkedIn algorithm rules
EXA_API_KEY=

# Optional reporting
GOOGLE_SERVICE_ACCOUNT_JSON=   # base64-encoded service account JSON
GOOGLE_SHEET_ID=
LANDING_PAGE_URL=

# Optional token rotation
GITHUB_PAT=
GITHUB_REPO=owner/repo

# Optional logging
LOG_FORMAT=json        # anything else = human-readable text (default)
LOG_LEVEL=INFO
```

## Commands

| Command | What it does |
|---------|-------------|
| `python run.py` | Research fresh topic, generate, Discord approval, publish (used by Actions) |
| `python run.py --preview` | Generate and score only, no publish or Discord |
| `python linkedin_auth.py` | One-time OAuth setup — interactive browser flow, never in CI |
| `python token_refresher.py` | Refresh LinkedIn access token, update GitHub secret |
| `python analytics_tracker.py --poll` | Poll LinkedIn metrics for recent posts |
| `python analytics_tracker.py --weekly-report` | Print performance summary as JSON |
| `python discord_bot.py --send-report` | Send analytics report to Discord + Sheets |
| `python discord_bot.py --send-weekly-report` | Send the weekly report variant |
| `python discord_bot.py --rules-update` | Send a LinkedIn algorithm change alert |
| `python auto_responder.py` | Fetch comments → suggest replies → Discord |
| `python run_log.py summary --days 30` | Health read: runs, outcomes, where failures cluster |
| `python run_log.py runs --days 14` | Recent runs and how each one ended |
| `python run_log.py outcome --source post --ref <urn> --kind inbound --note "..."` | Record a real outcome — the only attribution input |
| `python reddit_leads.py` | Sitewide Reddit hiring-intent scan → raw leads to Discord |
| `python reddit_leads.py --dry-run` | Print candidates only, no send, no state save |

## GitHub Actions workflows

| Workflow | Schedule (PKT) | Purpose |
|----------|---------------|---------|
| `daily_post.yml` | 1pm daily | Daily research, generation, approval, publishing |
| `watchdog.yml` | 2pm + 4pm daily | Re-triggers the daily post if the 1pm cron was skipped |
| `analytics.yml` | 9am + 7pm daily | Poll LinkedIn metrics, send report |
| `comment_reply.yml` | Every 2 hours | Comment reply suggestions → Discord |
| `weekly_report.yml` | Sunday 8pm | Analytics summary → Discord + Sheets |
| `rules_update.yml` | Sunday 6am | Refresh LinkedIn algorithm rules cache |
| `token_refresh.yml` | 25th monthly | Rotate LinkedIn access token |
| `reddit_leads.yml` | Every 8 hours | Sitewide Reddit hiring-intent lead scan |

## Discord approval commands

Reply in the `#approvals` channel within the 120-minute window:

| Reply | Action |
|-------|--------|
| `1` | Post the variant |
| `r make it punchier` | Regenerate with a hint (max 3 generations per run) |
| `new topic` / `new topic: focus on automation` | Pick a different topic from today's pool (max 1 switch; the second window is 60 minutes) |
| `edit: [full text]` | Post your own text verbatim |
| `skip` | Skip today, log as skipped |
| *(no reply)* | **Auto-publishes** after the window expires |

## What's stored where

| Path | Tier | Notes |
|------|------|-------|
| `data/posted_topics.json` | Permanent — committed to git | The dedup source of truth. A topic here can never be picked again. |
| `data/lead_query_state.json` | Permanent — committed to git | Rotation cursor for Reddit lead queries. |
| `data/run_history.jsonl` | Permanent — committed to git | Every stage of every run: topic, score, approval action, publish result, errors. |
| `data/metrics_history.jsonl` | Permanent — committed to git | Engagement snapshots. Mirrors `performance.db` so history survives cache eviction. |
| `data/outcomes.jsonl` | Permanent — committed to git | Which post or lead produced a real conversation. Filled in by hand. |
| `performance.db` | CI cache — evictable | Post metrics, hook/day performance, hashtag stats. Resets to defaults if evicted. |
| `cache/linkedin_rules.json` | CI cache — 24h TTL | Live LinkedIn algorithm rules from Tavily. |
| `seen_reddit_leads.json` | CI cache — 14-day window | Reddit lead dedup, including crosspost collapsing. |
| `.st_cache/` | CI cache | MiniLM embedding weights (~80MB). |

## Project structure

```
agent_runner.py            # Daily pipeline — research, generate, score, approve, publish
run.py                     # CLI entrypoint
content_generator.py       # Brand voice, prompts, topic pick, variant generation, scorer
llm_client.py              # DeepSeek router via the OpenAI SDK
research.py                # Tavily, Exa, Reddit, HN, RSS, HuggingFace, YouTube
topic_similarity.py        # MiniLM embedding dedup — hard filter + soft penalty
topic_log.py               # Permanent git-committed log of posted topics
linkedin_poster.py         # LinkedIn UGC API — post, first comment, recent posts
discord_bot.py             # Discord HTTP API — approvals, reports, alerts
analytics_tracker.py       # SQLite analytics, Google Sheets export
auto_responder.py          # LinkedIn comment reply suggestions
reddit_leads.py            # Sitewide Reddit hiring-intent lead discovery
linkedin_rules_fetcher.py  # Live LinkedIn algorithm rules via Tavily (24h cache)
notify_failure.py          # Discord failure alerts for workflow failure steps
logger.py                  # Structured logging (text or JSON)
```

## One-time LinkedIn OAuth setup

```bash
python linkedin_auth.py
# Opens browser → authorise → writes tokens + org URN to .env
```

## Known issues

- **Only one post variant is generated.** `VARIANT_MODELS` lists a single model, so the approval step never presents a real choice. Add model keys to `MODELS` + `VARIANT_MODELS` to enable it.
- **No test suite.** `test_llm.py` is a model-connectivity smoke test only. The Discord 2000-character splitter, the banned-word fixer, and the dedup filter are all untested.
- **`performance.db` is not durable.** It lives in GitHub Actions cache and can be evicted, resetting the derived stats (hook performance, score threshold). Raw engagement numbers now survive in `data/metrics_history.jsonl`.
- **Attribution is manual.** `data/outcomes.jsonl` exists and nothing fills it automatically — you record an outcome when a post or lead produces a real conversation. Until it has rows, engagement is still the only thing being measured.
