# The Tech Tutors — LinkedIn Posting Agent

Fully automated LinkedIn content engine for **The Tech Tutors** company page. Every day it researches a fresh AI/SMB topic from scratch, generates a post via an agentic LLM loop, routes it through Discord for human approval, then publishes to LinkedIn. Runs 7 days/week via GitHub Actions — there is no weekly pre-plan; research happens at write-time, daily.

## How it works

```
Daily post (1pm PKT)
  └─ Groq agent loop (Llama 3.3 70B tool-use):
       get_analytics → research_topic + fetch fresh LinkedIn rules
       → pick_daily_topic (LLM picks from researched candidates, dedup-penalized
         against recent posts via local MiniLM embedding similarity)
       → generate_post → score_post (dynamic threshold) → Discord approval
       → publish_post → log analytics
```

The flow is **agentic** — Llama 3.3 70B orchestrates its own tool calls via Groq's function-calling API. Topic, angle, and format are decided fresh each day based on live LinkedIn algorithm rules fetched via Tavily and recent performance — nothing is pre-scheduled or hardcoded.

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

python run.py            # research fresh topic, generate, Discord approval, publish
python run.py --preview  # generate and score only, no publish
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
| `python run.py` | Research fresh topic, generate, Discord approval, publish (used by Actions) |
| `python run.py --preview` | Generate and score only, no publish or Discord |
| `python linkedin_auth.py` | One-time OAuth setup |
| `python token_refresher.py` | Refresh LinkedIn access token |
| `python analytics_tracker.py --poll` | Poll LinkedIn metrics |
| `python discord_bot.py --send-report` | Send analytics report to Discord |
| `python auto_responder.py` | Fetch comments → suggest replies → Discord |

## GitHub Actions workflows

| Workflow | Schedule (PKT) | Purpose |
|----------|---------------|---------|
| `daily_post.yml` | 1pm daily | Agentic daily research + post generation + publishing |
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
agent_runner.py            # Groq tool-use agent loop — daily research, generate, score, publish
run.py                     # CLI entrypoint
content_generator.py       # Brand voice, prompts, daily topic pick + variant generation
llm_client.py              # Groq multi-model router
research.py                # Tavily, Exa, Reddit, HN, RSS, HuggingFace
topic_similarity.py        # MiniLM embedding dedup — penalizes topics close to recent posts
linkedin_poster.py         # LinkedIn UGC API — post, first comment
discord_bot.py             # Discord HTTP API — approvals, reports
analytics_tracker.py       # SQLite analytics, Google Sheets export
auto_responder.py          # LinkedIn comment reply suggestions
linkedin_rules_fetcher.py  # Live LinkedIn algorithm rules via Tavily (24h cache)
```

## One-time LinkedIn OAuth setup

```bash
python linkedin_auth.py
# Opens browser → authorise → writes tokens + org URN to .env
```
