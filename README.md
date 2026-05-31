# The Tech Tutors — LinkedIn Posting Agent

Fully automated LinkedIn content engine for **The Tech Tutors** company page. Researches AI/SMB topics, generates posts via an agentic LLM loop, routes through Discord for human approval, then publishes to LinkedIn. Runs 7 days/week via GitHub Actions.

## How it works

```
Weekly plan (Sunday 6pm PKT)
  └─ Research trending AI topics
     → LLM derives domain freely from headlines (no hardcoded list)
     → LLM plans 7-day content strategy using live LinkedIn algorithm rules
     → Plan sent to Discord #weekly-plan

Daily post (1pm PKT)
  └─ Groq agent loop (Llama 3.3 70B tool-use):
       get_today_slot → get_analytics → research_topic + fetch fresh LinkedIn rules
       → generate_post → score_post (dynamic threshold) → Discord approval
       → publish_post → log analytics
```

The daily flow is **agentic** — Llama 3.3 70B orchestrates its own tool calls via Groq's function-calling API. Day strategies are decided dynamically each week by the LLM based on live LinkedIn algorithm rules fetched via Tavily — nothing is hardcoded.

## Stack

| Layer | Technology |
|-------|-----------|
| LLM / Agent | Groq (Llama 3.3 70B + Llama 3.1 8B) |
| Posting target | LinkedIn Company Page (UGC API) |
| Approval UX | Discord HTTP API (no gateway) |
| Research + Rules | Tavily, Exa, Reddit, HN, RSS, HuggingFace |
| Analytics | SQLite + Google Sheets |
| Scheduler | GitHub Actions cron |

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys

python run.py plan     # plan this week's 7 posts
python run.py          # interactive: generate, pick, publish
python run.py auto     # headless agentic mode (used by GitHub Actions)
python run.py --preview  # generate only, no publish
```

## Required environment variables

```env
# LLM
GROQ_API_KEY=

# LinkedIn
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_REFRESH_TOKEN=
LINKEDIN_ORG_URN=urn:li:organization:XXXXX

# Discord
DISCORD_BOT_TOKEN=
DISCORD_APPROVALS_CHANNEL_ID=
DISCORD_POSTED_CHANNEL_ID=
DISCORD_ANALYTICS_CHANNEL_ID=
DISCORD_COMMENTS_CHANNEL_ID=
DISCORD_PLAN_CHANNEL_ID=

# Optional research + rules (strongly recommended)
TAVILY_API_KEY=        # used for topic research AND live LinkedIn algorithm rules
EXA_API_KEY=

# Optional reporting
GOOGLE_SERVICE_ACCOUNT_JSON=   # base64-encoded service account JSON
GOOGLE_SHEET_ID=
LANDING_PAGE_URL=

# Optional token rotation
GITHUB_PAT=
GITHUB_REPO=owner/repo
```

## Commands

| Command | What it does |
|---------|-------------|
| `python run.py plan` | Research + plan Mon–Sun dynamically, send to Discord |
| `python run.py` | Interactive: generate, pick variant, publish |
| `python run.py auto` | Headless agentic loop (GitHub Actions) |
| `python run.py --preview` | Generate only, no publish |
| `python run.py week` | Show this week's schedule |
| `python run.py stats` | Engagement stats for posted content |
| `python linkedin_auth.py` | One-time OAuth setup |
| `python token_refresher.py` | Refresh LinkedIn access token |
| `python analytics_tracker.py --poll` | Poll LinkedIn metrics |
| `python discord_bot.py --send-report` | Send analytics report to Discord |
| `python auto_responder.py` | Fetch comments → suggest replies → Discord |

## GitHub Actions workflows

| Workflow | Schedule (PKT) | Purpose |
|----------|---------------|---------|
| `daily_post.yml` | 1pm daily | Agentic post generation + publishing |
| `weekly_plan.yml` | 6pm Sunday | Research + dynamic 7-day plan |
| `weekly_report.yml` | 8pm Sunday | Analytics summary → Discord + Sheets |
| `analytics.yml` | 9am + 7pm | Poll LinkedIn metrics for recent posts |
| `comment_reply.yml` | Every 2 hours | Comment reply suggestions → Discord |
| `rules_update.yml` | Weekly | Refresh LinkedIn algorithm rules cache |
| `token_refresh.yml` | Monthly | Rotate LinkedIn access token |

## Discord approval commands

Reply in `#approvals` channel:

| Reply | Action |
|-------|--------|
| `1` | Post the variant |
| `r make it punchier` | Regenerate with hint (max 3 attempts) |
| `edit: [full text]` | Post your own custom text verbatim |
| `skip` | Skip today, log as skipped |

## Project structure

```
agent_runner.py            # Groq tool-use agent loop (8 tools, daily posting)
run.py                     # CLI entrypoint
content_generator.py       # Brand voice, prompts, dynamic generation + strategy
llm_client.py              # Groq multi-model router
research.py                # Tavily, Exa, Reddit, HN, RSS, HuggingFace
linkedin_poster.py         # LinkedIn UGC API — post, upload, stats
discord_bot.py             # Discord HTTP API — approvals, reports
scheduler.py               # weekly_schedule.json read/write
analytics_tracker.py       # SQLite analytics, Google Sheets export
auto_responder.py          # LinkedIn comment reply suggestions
linkedin_rules_fetcher.py  # Live LinkedIn algorithm rules via Tavily (24h cache)
```

## One-time LinkedIn OAuth setup

```bash
python linkedin_auth.py
# Opens browser → authorise → writes tokens + org URN to .env
```
