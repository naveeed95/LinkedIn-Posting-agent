# CLAUDE.md

Guidance for Claude Code agents working in this repo.

## What this is

LinkedIn posting agent for **The Tech Tutors** — automated content engine that researches a fresh AI/SMB topic *every day at write-time* (no weekly pre-plan), generates a text post via LLM calls, routes it through Discord for human approval, then publishes to a LinkedIn **company page**. Runs 7 days/week via GitHub Actions cron at 1pm PKT.

## Stack

- **Language:** Python 3.11
- **LLM:** DeepSeek only — `deepseek-v4-pro` and `deepseek-v4-flash`, called through the **OpenAI SDK** against `https://api.deepseek.com`. Router lives in `llm_client.py`. Groq is present in the source but fully commented out (see "LLM provider reality" below).
- **Pipeline:** `agent_runner.run_agent()` — a **straight-line Python pipeline**, not an agentic loop (see "Not an agentic loop" below).
- **Posting target:** LinkedIn Company Page only (`LINKEDIN_ORG_URN` required, personal posting rejected in `linkedin_poster._author_urn`)
- **Approval UX:** Discord HTTP API (no gateway/websocket — text message polling only, no reactions)
- **Storage:** SQLite (`performance.db`) + JSON cache (`cache/linkedin_rules.json`) + git-committed JSON (`data/*.json`)
- **Scheduler:** GitHub Actions cron `0 8 * * *` (8am UTC = 1pm PKT, every day), with a watchdog fallback
- **Reporting:** Google Sheets (service-account JSON, base64 in env)

## Entry points

| Command | Purpose |
|---------|---------|
| `python run.py` | Full daily pipeline: research fresh topic → generate → score → Discord approval → publish. Used by Actions and as the only daily entry point. |
| `python run.py --preview` | Generate and score but do not publish or send to Discord. Auto-approves internally and prints the post. |
| `python linkedin_auth.py` | One-time OAuth flow. Writes tokens + org URN to `.env`. |
| `python token_refresher.py` | Refresh access token via stored refresh token. Updates GH secret if `GITHUB_PAT` + `GITHUB_REPO` set. |
| `python analytics_tracker.py --poll` | Poll metrics for last 7 days of posts. |
| `python analytics_tracker.py --weekly-report` | Print performance summary JSON. |
| `python discord_bot.py --send-report` | Build report, write to Sheets, post to Discord. |
| `python discord_bot.py --send-weekly-report` | Weekly variant of the report (used by `weekly_report.yml`). |
| `python discord_bot.py --rules-update` | Send LinkedIn algorithm change alert. |
| `python auto_responder.py` | Fetch unanswered comments, generate replies, queue to Discord. |
| `python reddit_leads.py` | Sitewide Reddit search for hiring-intent leads (any tech work), push raw posts to Discord. No LLM call, no drafted reply. |
| `python reddit_leads.py --dry-run` | Print candidates only — no Discord send, no seen-set save. |
| `python reddit_leads.py --fetch-only` | Same as `--dry-run`. |
| `python notify_failure.py --workflow-name X --run-url Y` | Post a workflow-failure alert to Discord. Called from workflow `if: failure()` steps, not by hand. |
| `python run_log.py summary --days 30` | Health read over the durable log: run count, how runs ended, where they die, average score, recorded outcomes. |
| `python run_log.py runs --days 14` | One line per run showing the stage sequence and final status. |
| `python run_log.py outcome --source post --ref <urn> --kind inbound --note "..."` | Record a real-world outcome. The only way attribution data enters the system. |

## File map

```
agent_runner.py            # Straight-line daily pipeline — research, generate, score, approve, publish
run.py                     # CLI entrypoint — thin wrapper around agent_runner.run_agent
content_generator.py       # Brand voice, prompts, variant gen, quality fix, daily topic pick, scorer
llm_client.py              # DeepSeek router via OpenAI SDK — retries, fallback, parallel variants
research.py                # RSS, Reddit, HN, HuggingFace, Tavily, Exa, YouTube, article scrape
logger.py                  # Structured logging — text by default, JSON when LOG_FORMAT=json
linkedin_poster.py         # UGC post, first comment, get_recent_org_posts
linkedin_auth.py           # OAuth: localhost callback, state/CSRF, token + org URN to .env
token_refresher.py         # Refresh token; encrypt and PUT to GitHub secrets
linkedin_rules_fetcher.py  # LinkedIn algorithm rules via 5 parallel Tavily queries (24h TTL cache)
analytics_tracker.py       # SQLite schema, log_post, poll_metrics, summary, Sheets export
discord_bot.py             # HTTP API: approval messages, polling for replies, reports, alerts
auto_responder.py          # LinkedIn comment reply suggestions → Discord queue
reddit_leads.py            # Sitewide Reddit search for hiring-intent leads → raw posts to Discord (no LLM, no reply draft, no promo)
topic_similarity.py        # MiniLM embedding dedup: soft penalty, hard topic filter, post-content dup check
topic_log.py               # Permanent, git-committed log of posted topics/post text (data/posted_topics.json)
run_log.py                 # Durable append-only event stream — every run stage, metrics snapshots, outcomes
notify_failure.py          # argparse CLI — Discord failure alert, called from workflow failure steps
test_llm.py                # Smoke test: calls every model in llm_client.MODELS once
.github/workflows/
  daily_post.yml           # Cron: 0 8 * * * (1pm PKT daily) → python run.py
  watchdog.yml             # Cron: 0 9 + 0 11 * * * — re-triggers daily_post if the 8am cron was skipped
  weekly_report.yml        # Cron: 0 15 * * 0 (Sun 8pm PKT) → analytics report to Discord + Sheets
  analytics.yml            # Cron: 0 4 + 0 14 * * * (9am + 7pm PKT) → poll metrics, send report
  comment_reply.yml        # Cron: 0 */2 * * * (every 2 hours) → auto-responder
  rules_update.yml         # Cron: 0 1 * * 0 (Sun 6am PKT) → refresh LinkedIn rules cache
  token_refresh.yml        # Cron: 0 2 25 * * (25th monthly) → rotate LinkedIn access token
  reddit_leads.yml         # Cron: 0 4,12,20 * * * → python reddit_leads.py
performance.db             # SQLite: posts, metrics, topics_history, hashtag_metrics (gitignored, CI-cached)
output/                    # Stale PDFs/PNGs from a removed graphic feature — no code writes here
data/posted_topics.json    # Permanent dedup log — committed to git, never reset (see topic_log.py)
data/lead_query_state.json # Permanent, git-committed, rotation cursor over the hiring-intent query combos
data/run_history.jsonl     # Permanent, git-committed event stream — every stage of every run
data/metrics_history.jsonl # Permanent, git-committed engagement snapshots (survives performance.db eviction)
data/outcomes.jsonl        # Permanent, git-committed attribution — manually recorded, the revenue signal
cache/linkedin_rules.json  # Algorithm rules cache (24h TTL, Tavily-fetched, gitignored)
seen_reddit_leads.json     # Rolling dedup state (cache-tier, gitignored) — reddit_leads.py
seen_comment_urns.json     # Rolling dedup state (cache-tier, gitignored) — auto_responder.py
.st_cache/                 # MiniLM model weights, ~80MB (gitignored, CI-cached under key minilm-l6-v2)
```

## Required env vars

**LLM:**
- `DEEPSEEK_API_KEY` — *required*. Validated at startup by `run.py:_validate_env`; `llm_client._get_deepseek()` also raises `EnvironmentError` on first model call if missing.

**LinkedIn:**
- `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` — for OAuth + refresh.
- `LINKEDIN_ACCESS_TOKEN` — short-lived (60 days).
- `LINKEDIN_REFRESH_TOKEN` — long-lived. Set by `linkedin_auth.py`.
- `LINKEDIN_ORG_URN` — *required* (e.g. `urn:li:organization:12345`). Personal URN deliberately rejected.

**Discord:**
- `DISCORD_BOT_TOKEN`
- `DISCORD_APPROVALS_CHANNEL_ID` — daily post approval
- `DISCORD_POSTED_CHANNEL_ID` — post confirmation after publishing
- `DISCORD_ANALYTICS_CHANNEL_ID` — reports + failure alerts
- `DISCORD_COMMENTS_CHANNEL_ID` — comment reply suggestions
- `DISCORD_REDDIT_CHANNEL_ID` — *optional*. Daily Reddit draft (title + body, copy-paste-ready) is sent here after LinkedIn publishes. If unset, the Reddit draft step is skipped entirely (LinkedIn publish is unaffected).
- `DISCORD_REDDIT_LEADS_CHANNEL_ID` — *optional*. Raw hiring-intent Reddit posts (no drafted reply) sent here every 8 hours by `reddit_leads.py`. If unset, sending is skipped — fetch/filtering still runs harmlessly, just nothing is posted. Separate channel from `DISCORD_REDDIT_CHANNEL_ID`.

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

### LLM provider reality

`llm_client.py` runs **DeepSeek only**. Groq support was removed entirely (previously present as commented-out `llama-70b` / `llama-8b` entries and a dead `groq` provider branch). Do not describe this system as running on Llama or Groq, and don't re-add a Groq path without also adding the client, the `MODELS` entries, and the `_dispatch` branch together.

Two live models:

| Key | Model id | Temp | Used for |
|-----|----------|------|----------|
| `deepseek-pro` | `deepseek-v4-pro` | 0.8 | post generation, quality fix, topic pick (`STRATEGY_MODEL`, `QUALITY_FIX_MODEL`) |
| `deepseek-flash` | `deepseek-v4-flash` | 0.3 | engagement scoring, classification (`UTILITY_MODEL`) |

**Do not remove the `extra_body={"thinking": {"type": "disabled"}}` flag in `_dispatch()`.** DeepSeek V4 models are reasoning models; with thinking on they spend a highly variable number of completion tokens (observed 40 to 2500+ for the *same* prompt) on hidden reasoning before emitting content, so any fixed `max_tokens` can be swallowed whole and the call returns `""`. Tight-budget calls (scoring, topic-pick) fail intermittently without this flag.

### Not an agentic loop

`agent_runner.run_agent()` is a **deterministic straight-line pipeline**, despite the `tool_*` function names. There is no function-calling API, no tools schema, and no LLM orchestration of control flow. The `tool_*` functions are ordinary Python closures invoked in a fixed sequence at the bottom of the file, with a `while True` loop around the approval step only.

The LLM is called in exactly four places: `pick_daily_topic()`, `generate_text_post_variants()`, `engagement_scorer()`, and `adapt_post_for_reddit()`. Everything else — fetching, scoring bonuses, dedup, publishing, Discord — is plain Python.

Don't reintroduce the "agentic tool-use loop" framing in docs or comments; it was inaccurate and misled several earlier sessions.

### No weekly plan — daily research at write-time

There is **no pre-planning step and no `weekly_schedule.json`**. Every day, `run_agent()` researches and picks a fresh topic itself (`pick_daily_topic` in `content_generator.py`, guided by `topic_similarity.apply_dedup_penalty` to avoid repeating recent themes by semantic similarity to recently-posted topics). This replaced an older weekly-pre-plan flow (`run.py plan` / `scheduler.py` / `weekly_schedule.json`) that has been fully removed — don't reintroduce slot-based scheduling, `DAY_FORMAT`/`DAY_STRATEGY` constants, or per-day pre-assignment.

### Permanent topic-dedup (hard guarantee)

`performance.db` and `cache/*.json` live in CI cache and can be evicted or cold-start empty — never a reliable dedup source on their own. `data/posted_topics.json` (via `topic_log.py`) is **committed to git after every successful publish** and is the permanent source of truth:

- `tool_pick_daily_topic()` fetches `topic_log.get_all_titles()` (all-time, normalized) and passes it to `fetch_trending_topics(all_posted_titles=...)`, which calls `topic_similarity.filter_hard_duplicates()` to **structurally remove** any topic ever posted before — and any topic semantically ≥0.80 similar to a post from the last 30 days — before the LLM even sees the candidate list. A topic can never be picked twice.
- `topic_log.get_recent_topic_texts(days=30)` feeds `apply_dedup_penalty` (soft scoring penalty).
- `tool_score_post()` additionally calls `topic_similarity.is_duplicate_post()` against `topic_log.get_recent_post_texts(days=7)` — if the *generated post body* is ≥0.85 similar to anything published in the last week (even on a different topic/angle), it's scored as `ready_to_send: False` and the pipeline regenerates with a "make this distinctly different" hint.
- `tool_publish_post()` calls `topic_log.record_posted_topic(title, topic_text, source_url, post_text)` on every successful publish. `daily_post.yml` commits and pushes `data/posted_topics.json` at the end of the run (`permissions: contents: write`).

**Live LinkedIn ground-truth layer** (`linkedin_poster.get_recent_org_posts`): `tool_pick_daily_topic()` also fetches the org page's own last-30-days posts directly from the LinkedIn API and merges them into `recent_topic_texts` (feeds `filter_hard_duplicates`/`apply_dedup_penalty`) and into `state["recent_post_texts"]` (feeds `is_duplicate_post`, last-7-days). This covers topics posted *before* `data/posted_topics.json` existed (or after any future reset/eviction of that file) — LinkedIn itself is the source of truth, not just the git log. Fails open (empty list) if the API call errors, so it never blocks posting.

Don't bypass `topic_log` for dedup, and don't add `performance.db`-backed topic-history helpers to `analytics_tracker.py` — two of them (`get_topic_history`, `get_recent_topic_texts`) existed, went unused, and were removed. That DB is CI-cached and evictable, so it can never be the dedup source of truth.

### Daily post flow (`python run.py`)

```
agent_runner.run_agent()        ← plain Python, fixed order
  1. tool_pick_daily_topic()    # topic_log dedup + live LinkedIn history + fetch_trending_topics
                                #   → pick_daily_topic()      [LLM: deepseek-pro]
  2. tool_get_analytics_summary()
  3. tool_research_topic()      # fetch_deep_topic_research → topic["research_context"]
  4. _generate_and_score()      # loop, max 3 attempts total:
       tool_generate_post()     #   → generate_text_post_variants() [LLM: deepseek-pro]
       tool_score_post()        #   → engagement_scorer()           [LLM: deepseek-flash]
                                #     dynamic threshold: 90% of recent_avg, clamped 55–75, fallback 62
  5. while True:
       tool_send_for_approval() # Discord, 120-min wait (60 after a topic switch)
       → post / edit / regenerate / new_topic / timeout / skip
  6. tool_publish_post()        # post_to_linkedin + log_post + record_posted_topic
                                #   + post_first_comment + send_posted_confirmation
                                #   + adapt_post_for_reddit() [LLM] → send_reddit_draft()
```

Discord approval commands (reply in #approvals channel):
- `1` — post the variant
- `r make it punchier` — regenerate with hint (max 3 generations per run, shared with the scoring loop's budget)
- `new topic` / `new topic: focus on automation` — scrap current topic, pick a different one from today's research pool and regenerate (max 1 switch per run — second wait is 60min, not 120min)
- `edit: [full post text]` — post custom text verbatim (logged with `chosen_model="human-edit"`)
- `skip` — log slot as skipped

**Silence auto-publishes.** If nobody replies before the wait expires, `wait_for_approval` returns `{"action": "timeout"}` and `run_agent` publishes the post anyway, after sending a "no response after 2 hours — auto-posting" notice via `notify_auto_post()`. Approval is a veto window, not a gate. Anything that must not go out has to be actively skipped.

### Reddit draft (manual posting, no API)

Reddit closed self-service API app creation in Nov 2025 (Responsible Builder Policy — see support.reddithelp.com) — no new OAuth app can be created for this account, so there is no automated Reddit posting. After LinkedIn publishes successfully, `run_agent()` rewrites the post for Reddit via `content_generator.adapt_post_for_reddit()` and sends the title/body as a copy-paste-ready message to its own Discord channel (`send_reddit_draft()` in `discord_bot.py`, posted to `DISCORD_REDDIT_CHANNEL_ID`) — no polling, no approval flow, no actual posting. A human pastes it into Reddit manually. Skipped entirely if that env var is unset. Any failure in this block is caught and logged; it never affects the already-published LinkedIn post.

### Reddit leads (hiring-intent, sitewide search, discovery-only, no API)

`reddit_leads.py` runs every 8 hours (`reddit_leads.yml`, its own `reddit-leads` concurrency group). It searches **all of Reddit** — via Reddit's sitewide search Atom feed (`https://www.reddit.com/search.rss?q=...&sort=new`), not a fixed sub list — for a hiring/outsourcing intent signal: people explicitly looking to pay/hire someone for tech work of any kind (web dev, apps, automation, AI, chatbots). `_is_hiring_lead` is pure regex, no LLM.

**Discovery-only — no LLM, no drafted reply, no self-promo:** this script never calls an LLM and never mentions The Tech Tutors or links anywhere. It only surfaces the raw matching post (subreddit, title, link, snippet, age) to Discord via `send_reddit_leads()` — the human reads them and decides manually whether/how to respond. This was an explicit design choice, not an oversight: keep this flow to pure lead discovery.

**Dynamic queries — template × keyword combinatorial, with rotation, no LLM:** query groups in the config block cover the full spectrum of how real people phrase a buying ask, not just the textbook "hire a developer": `PRODUCT`/`PERSON` (classic gig post), `COST` (price-shopping — "how much to build a {x}", the strongest real buying signal and previously uncovered), `RECOMMEND` (referral-seeking — "can anyone recommend a {x}"), `NEEDED` (noun-first — "{x} needed"/"{x} wanted"), plus `FIXED_QUERIES` (automation, vibe-code rescue, technical-cofounder asks that don't fit a template grid). `_all_queries()` crosses each template group with its matching keyword group via `itertools.product` (~270 deterministic strings). The query set and every filter accept/reject rule below were validated against real Reddit posts (r/smallbusiness, r/Entrepreneur, r/automation, r/forhire) — the phrasings people actually use ("rather pay someone to do it", "how much to build my app", "can AI handle our invoicing", "any consultants here?"), not textbook wording. Querying all every run would hammer rate limits, so `next_query_batch()` takes the next N (`QUERIES_PER_RUN`, **15**) from a rotation cursor persisted in `data/lead_query_state.json`, wrapping around — every phrasing gets queried roughly evenly (full rotation ~4 days at 3 runs/day, inside the 14-day seen window). This file is **git-committed** (same tier as `data/posted_topics.json`) by `reddit_leads.yml`, not cached.

**Filter — layered accept/reject, order matters (`_is_hiring_lead`):** the sitewide search matches loosely on individual words, so the filter carries the precision. Order:
1. **Reject** `_NOT_A_LEAD_PATTERNS` — career/jobseeker/learning posts ("how do I become a dev", "should I learn X", "looking for a job", "am I focusing on the wrong skills"). This is what the CS-student post that got cross-posted 9x tripped.
2. **Reject** `_CONTENT_GUIDE_PATTERNS` — SEO/content-marketing articles agencies farm onto Reddit around the exact keyword ("MVP Development Cost: Complete Breakdown for 2026", "What Startups Actually Spend", "real data from 50+ projects"). They hit the cost pattern + a tech target but are vendors, not buyers; markers are guide/breakdown framing a one-line buyer question never uses.
3. **Reject** `_FOR_HIRE_PATTERNS` — self-promo / freelancers advertising themselves ("[for hire]", "I'm a / I am a … developer", "currently available for new projects").
4. **Reject** `_JOB_BOARD_BOT_PATTERN` — machine-generated FTE job-board aggregator posts (r/jobhuntify, r/jobboardsearch), detected by their emoji/field signature (`🧑‍💻 Level:`, `💵 Salary:`, `Apply & Description 👉`), not by subreddit.
5. **Accept** `_TARGET_INCLUSIVE_HIRE_PATTERNS` — hire phrase that already names a dev target ("need a developer", plurals "looking for developers", noun-first "programmer wanted", "recommend a dev agency", "can AI handle/automate our X", "any consultants here?"). Placed **before** the non-tech reject so a real dev lead that mentions a non-tech role in passing isn't killed.
6. **Reject** `_NON_TECH_ROLE_PATTERNS` — hiring, but for UGC creators / video editors / social-media managers / VAs etc. (these flooded the feed because the company is often an "AI-powered X app", putting a tech word in range). Anchored to the hire verb + ≤2 filler tokens so only the hired role itself matches.
7. **Accept** `_GENERIC_HIRE_PATTERNS` / `_COST_HIRE_PATTERNS` **only** when a tech target (`_NEAR_TARGET_PATTERN` — dev nouns, product nouns, `mvp`/`workflow`/`crm`/`billing`, and no-code/AI build tools Lovable/Cursor/Webflow/Zapier/n8n/GHL …) appears within `_PROXIMITY_WINDOW` (70 chars) **after** the phrase. Generic covers the real outsourcing verbs ("<verb> someone to build", "pay/hire someone to", "who should I hire", "looking to automate my X"); cost covers price-shopping ("how much to build a website"). Forward-only, because a symmetric window re-admits the CS-student post ("engineer" sits ~40 chars *before* "who can build").

**`search.rss` rate limit, measured empirically:** repeated manual requests spaced 6-25s apart still hit 429 more often than not during design; only ~45-60s gaps consistently returned 200 (behaves like a slow-refilling token bucket, not a flat per-request cooldown). `SEARCH_QUERY_PAUSE_SECONDS = 55` and a `(30, 60)`-second retry backoff in `fetch_search_new()` reflect that measurement. 15 queries × 55s ≈ 14 min per run.

**Output floor — at least 10 posts, newest-first:** `queue_leads()` targets a floor of `MIN_LEADS` (10) posts per run, sorted by recency (`created_utc` descending) rather than relevance score, since freshness was the explicit requirement. If fewer than 10 pass the hiring-intent filter within the recency window, it sends what's found and logs the shortfall rather than reaching further back in time.

**Seen-set correctness + crosspost dedup:** every fetched candidate is marked seen (`seen_reddit_leads.json`, 14-day window), not just the ones actually sent to Discord — otherwise lower-ranked-but-still-fresh candidates would get resurfaced as duplicates on a later run. The seen-set holds two key types: Reddit fullnames (`t3_…`) AND content-keys (`ct:<md5>` of normalized title + selftext head, via `_content_key`). The content-key catches the same post crossposted to N subreddits — each crosspost has a distinct fullname but identical content, and one spam post (e.g. "[HIRING] Long-Term YouTube/TikTok Editor" appeared 8x) would otherwise fill the whole `MIN_LEADS` batch. Crossposts are collapsed within a run and across runs.

### LinkedIn rules injection

`linkedin_rules_fetcher.fetch_rules()` runs 5 parallel Tavily queries about current LinkedIn algorithm rules and best practices. Results cached 24 hours in `cache/linkedin_rules.json` (`CACHE_TTL_HOURS = 24`). Injected into the system prompt for LLM calls that route through `content_generator._generate()`. If `TAVILY_API_KEY` is missing, rules injection is silently skipped — posts still generate without it.

### Research scoring

```python
_score = smb_bonus(100) + domain_bonus(60) + kw_bonus(40) + int(log2(points+1) * 3)
```

A Tavily article about "AI automation ROI for SMBs" (score=140) always beats a viral Reddit meme (score≈40). Virality is a tie-breaker only. `SMB_BOOST_KEYWORDS` in `research.py` drives the 100-point bonus.

Dedup inside a run: exact lowercase title match, then `SequenceMatcher` ratio > 0.85 against a sliding window of the last 20 accepted items.

### Variant generation

`llm_client.generate_variants(job, ...)` runs every model in `VARIANT_MODELS[job]` in parallel via `ThreadPoolExecutor` (90s overall timeout, partial results kept). Currently both the `text` and `research` jobs are `["deepseek-pro"]` → **exactly one variant per generation**.

Consequence: the Discord approval message always shows a single variant, `wait_for_approval` is called with `num_variants=1`, and replying `1` is the only valid selection. The multi-variant selection code is live but has nothing to choose between. Add more model keys to `MODELS` + `VARIANT_MODELS` to make the choice real.

### Banned-word quality fix

Every post variant runs through `_fix_post_quality` — a `deepseek-pro` pass that strips banned words (`delve`, `leverage`, `synergy`, `game-changer`, `revolutionary`, `cutting-edge`, etc.), removes "The Tech Tutors" as a standalone line, removes URLs from the post body, replaces generic question closers, normalises hashtags to **1–3 on the last line only**, and holds length to 1,200–1,800 characters. Never skip this pass — banned words cause LinkedIn algorithm penalty.

`_BANNED_WORDS_PATTERN` in `content_generator.py` re-checks the result; it covers a subset of the prompt's banned list.

### Engagement score threshold

`agent_runner.tool_score_post` computes a dynamic threshold: 90% of `recent_avg_score` from analytics, clamped 55–75. Falls back to 62 when no posting history exists. The pipeline regenerates if score is below threshold (max 3 generations total per run, shared with Discord-triggered regenerations).

### Durable recording (`run_log.py`)

Three storage tiers exist in this repo, and the distinction matters:

| Tier | Example | Survives? |
|------|---------|-----------|
| stdout logs | `logger.get_logger()` output | No — Actions run retention only, not queryable across runs |
| CI cache | `performance.db`, `cache/*.json` | No — evicted at 7-day idle or the 10GB repo cap |
| **git-committed** | `data/*.json`, `data/*.jsonl` | **Yes — permanent** |

`run_log.py` writes to the third tier. It records an **event stream, not per-run records**: every call appends one self-contained JSON line tagged with `run_id`, so a killed or cancelled run still leaves everything up to the kill point on disk. Reconstruct a run by grouping on `run_id`.

Stages recorded by `agent_runner`: `run_start`, `topic_pick`, `research`, `generate` (per attempt, with full post text), `score` (with threshold and duplicate similarity), `approval` (including whether it auto-published on timeout), `topic_switch`, `publish`, `skip`, `error`, `run_end`. `reddit_leads` records `leads_scan` and one `lead` per surfaced post.

Three rules when touching this module:

1. **It must never raise into the caller.** Every write is wrapped — observability cannot take down a publish that already succeeded. Keep that property.
2. **Everything written is committed to git.** `_redact()` strips any field whose name contains token/secret/key/password/authorization and clamps long strings. Never bypass it; a token in an error message would be published permanently.
3. **Every workflow that writes these files must also commit them.** `daily_post.yml`, `reddit_leads.yml`, `analytics.yml`, and `weekly_report.yml` each have a commit step and `permissions: contents: write`. A workflow that writes without committing silently loses the data.

`data/outcomes.jsonl` is the one file nothing writes automatically. It's the attribution record — which post or lead produced a real conversation — and it only fills up when a human runs `run_log.py outcome`. Engagement metrics cannot answer that question, which is why this file exists separately.

### Hook classification

`analytics_tracker.log_post` infers `hook_type` from the post's first line by regex into four buckets: `question`, `stat`, `contrarian`, `bold`. `bold` is the catch-all. This is reverse-engineered after the fact, not emitted by the generator, so it does not map onto the seven named hook formulas in `WRITING_SYSTEM`.

## GitHub Actions workflows

| Workflow | Cron (UTC) | PKT | Concurrency group | What it does |
|----------|-----------|-----|-------------------|-------------|
| `daily_post.yml` | `0 8 * * *` | 1pm daily | `posting-agent-db` | Full pipeline → Discord approval → post. `timeout-minutes: 210`. Commits `data/posted_topics.json`. |
| `watchdog.yml` | `0 9 * * *`, `0 11 * * *` | 2pm, 4pm | — | Checks whether daily_post ran today; if not, triggers it via `workflow_dispatch` and alerts Discord. |
| `analytics.yml` | `0 4 * * *`, `0 14 * * *` | 9am, 7pm | `posting-agent-db` | Poll LinkedIn metrics, send report to Discord. |
| `comment_reply.yml` | `0 */2 * * *` | every 2h | `comment-reply` | Fetch comments → suggest replies → Discord. |
| `weekly_report.yml` | `0 15 * * 0` | Sun 8pm | `posting-agent-db` | Poll all recent metrics → `discord_bot.py --send-weekly-report`. |
| `rules_update.yml` | `0 1 * * 0` | Sun 6am | `rules-update` | Refresh LinkedIn rules cache, alert on changes. |
| `token_refresh.yml` | `0 2 25 * *` | 25th, 7am | `token-refresh` | Rotate LinkedIn access token (30-day cycle on a 60-day token). |
| `reddit_leads.yml` | `0 4,12,20 * * *` | every 8h | `reddit-leads` | Sitewide Reddit hiring-intent search → raw posts to Discord. Commits `data/lead_query_state.json`. |

All scheduled workflows use `cancel-in-progress: false`.

Persistence (via `actions/cache@v4`, not artifacts — artifacts are run-scoped in v4 and can't be restored cross-run):
- `performance.db` — `performance-db-${{ github.run_id }}` key, `performance-db-` restore-keys prefix.
- `cache/linkedin_rules.json` — `linkedin-rules-<date>` key, `linkedin-rules-` restore-keys prefix (24h TTL enforced by `linkedin_rules_fetcher.py`, not the cache key).
- `.st_cache` — `minilm-l6-v2` key, MiniLM weights (~80MB) so dedup doesn't re-download each run.
- `seen_reddit_leads.json` — `reddit-leads-seen-${{ github.run_id }}` key, `reddit-leads-seen-` restore-keys prefix (cache-tier, evictable).
- `data/posted_topics.json` and `data/lead_query_state.json` — committed directly to git (`permissions: contents: write`), not cached. Permanent tier.

Exception: `rules_update.yml` uploads `cache/linkedin_rules.json` as an **artifact** named `linkedin-rules`, not as a cache entry — so that copy is not restorable by other workflows. `daily_post.yml` restores the rules cache from the `linkedin-rules-` cache prefix instead.

`daily_post.yml`, `reddit_leads.yml`, and `token_refresh.yml` each end with an `if: failure()` step calling `notify_failure.py`.

## Known production gotchas

1. **`performance.db` lives in CI cache** — subject to eviction (7-day idle, 10GB repo cap). Everything computed from it (hook/day performance, top hashtags, the dynamic score threshold) silently resets to defaults when evicted. Raw engagement numbers are now mirrored durably to `data/metrics_history.jsonl` on every poll, so the history survives even though the derived stats reset.
2. **Approval timeout publishes.** See "Daily post flow". No reply within the window means the post goes live.
3. **Hacker News** — three-tier fetch (keyword+date → top-stories-by-points → no-date fallback) in `fetch_hacker_news`. Browser-like UA in `HEADERS` since Algolia rejects niche User-Agents.
4. **Discord 2000-char split** — `_send_long_message` splits at `━━━` dividers then newlines. No automated test covers boundary cases.
5. **`linkedin_auth.py`** — writes tokens to `.env` via `set_key`. Never run in CI — requires interactive browser flow.
6. **`output/` has no writer.** The directory holds PDFs/PNGs from a carousel/graphic feature that no longer exists. Nothing in the codebase writes there; the `.gitignore` entry is kept only so stale local artifacts stay untracked.

## Conventions

- `--preview` for dry-run (generate + score, no publish, no Discord).
- **Structured logging** via `logger.get_logger("area")` — emits text locally, JSON when `LOG_FORMAT=json` (set in all workflows). Areas: `agent`, `analytics`, `auto`, `content`, `discord`, `linkedin`, `llm`, `preview`, `reddit_leads`, `research`, `responder`, `rules`, `similarity`, `startup`, `token_refresher`. Use `extra={"key": value}` for structured fields. CLI UX prints (banners, separators, interactive prompts) stay as `print()`.
- `BRAND_CONTEXT` and `WRITING_SYSTEM` in `content_generator.py` are source of truth for brand voice. Never inline overrides — use the `system_extra` parameter on `_generate()`.
- Post format/topic/angle are decided fresh each day at write-time — there is no pre-assigned per-day schedule to read from.

## Don'ts

- Don't describe this as a Groq, Llama, or agentic tool-use system. It is a straight-line pipeline on DeepSeek.
- Don't re-add `groq`, `Pillow`, or `reportlab` to `requirements.txt` — all three were removed because nothing imports them. `openai` is the real LLM dependency and is now declared explicitly rather than arriving transitively via `exa-py`.
- Don't remove `extra_body={"thinking": {"type": "disabled"}}` from `llm_client._dispatch()` — tight-budget calls start returning empty strings.
- Don't post to a personal LinkedIn URN. `_author_urn()` enforces org-only and raises without `LINKEDIN_ORG_URN`.
- Don't add `cerebras-llama` or `OPENROUTER_API_KEY` paths — not in `MODELS`, will raise `KeyError`.
- Don't commit `.env`, `performance.db`, `cache/*.json`, `.st_cache/`, or `output/`. (`data/posted_topics.json` and `data/lead_query_state.json` ARE committed — permanent tier.)
- Don't skip `_fix_post_quality`. Banned words leak into LinkedIn and cause algorithm penalty.
- Don't run `linkedin_auth.py` in CI — interactive browser flow only.
- Don't reintroduce a Reddit OAuth app/poster (`reddit_poster.py`, `reddit_auth.py`) — self-service Reddit API app creation is closed platform-wide (Responsible Builder Policy, Nov 2025); Reddit is copy-paste-manual via `send_reddit_draft()` until/unless a manually-approved app exists. `reddit_leads.py` follows the same constraint — it only ever pushes to Discord, never calls a Reddit write endpoint.
- Don't add reply drafting, an LLM call, or any self-promo/link back to `reddit_leads.py` — it's deliberately discovery-only (explicit user decision).
- Don't reintroduce `reddit_engagement.py` / a curated-subreddit advice-seeking scan with drafted replies — this was deliberately removed. Reddit lead-gen is `reddit_leads.py` (sitewide hiring-intent search, discovery-only) only.
- Don't reintroduce weekly pre-planning, `weekly_schedule.json`, slot-based scheduling, or `DAY_FORMAT`/`DAY_STRATEGY` constants — topic + format are decided dynamically by the LLM at write-time, daily.
- Don't add a personal LinkedIn fallback to `_author_urn()`.

## Tests

Only `test_llm.py` exists — it calls every model in `llm_client.MODELS` once with a tiny prompt and reports pass/fail. There is no real test suite; nothing covers the Discord message splitter, `_fix_post_quality`, or `filter_hard_duplicates`.

Run on Windows (avoids cp1252 emoji encoding crash):
```bash
python -c "import sys,io; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace'); exec(open('test_llm.py').read())"
```

Quick pipeline test without publishing:
```bash
python run.py --preview
```
