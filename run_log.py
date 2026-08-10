"""
Durable, append-only event log for every automated run.

Why this exists separately from performance.db and the JSON logger:
  - performance.db lives in GitHub Actions cache and is evictable (7-day idle,
    10GB repo cap). Anything only stored there silently disappears.
  - logger.py writes to stdout. In CI that is the Actions run log, which is
    retained for a limited window and cannot be queried across runs.
  - This module writes JSON Lines into data/, which daily_post.yml and
    reddit_leads.yml commit to git. Permanent tier, same as posted_topics.json.

Design: an event stream, not a per-run record. Every call appends one self-
contained line tagged with run_id, so a crashed or cancelled run still leaves
everything that happened before the crash on disk. Reconstruct a run by
grouping on run_id.

Files (all JSON Lines, one object per line, append-only):
  data/run_history.jsonl      every stage of every run
  data/metrics_history.jsonl  durable snapshots of polled LinkedIn metrics
  data/outcomes.jsonl         manual attribution — which post or lead produced
                              a real conversation, and what it was worth

Public API:
  new_run_id(kind)                       -> str
  record(run_id, stage, **fields)        -> None
  snapshot_metrics(post_id, metrics)     -> None
  record_outcome(source, ref, kind, ...) -> None
  read_runs(days)                        -> list[dict]   grouped by run_id
  read_events(days, stage)               -> list[dict]
  summarize(days)                        -> dict         counts by stage/status

Never raises into the caller. Recording is observability, not business logic —
a disk problem must not take down a publish that already succeeded.
"""

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from logger import get_logger

log = get_logger("run_log")

_DATA_DIR = Path(__file__).parent / "data"
RUN_HISTORY     = _DATA_DIR / "run_history.jsonl"
METRICS_HISTORY = _DATA_DIR / "metrics_history.jsonl"
OUTCOMES        = _DATA_DIR / "outcomes.jsonl"

# Fields that must never reach a git-committed file.
_REDACT_KEYS = ("token", "secret", "key", "password", "authorization")


def _redact(fields: dict) -> dict:
    """Drop anything that looks like a credential, and clamp long strings.

    These files are committed to git, so a stray token in an error message
    would be published permanently.
    """
    clean = {}
    for k, v in fields.items():
        if any(marker in k.lower() for marker in _REDACT_KEYS):
            clean[k] = "[redacted]"
        elif isinstance(v, str) and len(v) > 4000:
            clean[k] = v[:4000] + f"…[truncated {len(v) - 4000} chars]"
        else:
            clean[k] = v
    return clean


def _append(path: Path, obj: dict) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        # Observability must never break the pipeline it observes.
        log.warning(f"run_log append failed ({path.name}): {e}")


def _read(path: Path, days: int | None) -> list[dict]:
    if not path.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).isoformat() if days else None
    out = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate a torn line from a killed process
                if cutoff and obj.get("at", "") < cutoff:
                    continue
                out.append(obj)
    except Exception as e:
        log.warning(f"run_log read failed ({path.name}): {e}")
    return out


# ── Writing ───────────────────────────────────────────────────────────────────

def new_run_id(kind: str = "daily_post") -> str:
    """Short, sortable, unique id for one run. Prefix keeps kinds separable."""
    return f"{kind}-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"


def record(run_id: str, stage: str, **fields) -> None:
    """Append one event. `stage` is a short slug: run_start, topic_pick,
    generate, score, approval, publish, error, run_end."""
    _append(RUN_HISTORY, {
        "run_id":  run_id,
        "stage":   stage,
        "at":      datetime.now().isoformat(),
        "gh_run":  os.environ.get("GITHUB_RUN_ID", ""),
        **_redact(fields),
    })


def snapshot_metrics(post_id: str, metrics: dict) -> None:
    """Durable copy of a LinkedIn metrics poll.

    performance.db holds the same numbers but is evictable; this keeps the
    engagement history queryable even after a cold start.
    """
    _append(METRICS_HISTORY, {
        "post_id": post_id,
        "at":      datetime.now().isoformat(),
        **{k: metrics.get(k, 0) for k in
           ("likes", "comments", "shares", "impressions", "clicks")},
    })


def record_outcome(
    source: str,
    ref: str,
    kind: str,
    note: str = "",
    value: float = 0.0,
) -> None:
    """Attribution — the thing engagement metrics cannot tell you.

    source: "post" | "reddit_lead" | "agency_lead" | "other"
    ref:    post URN, lead id, or agency license number
    kind:   "inbound" | "reply" | "call_booked" | "proposal" | "won" | "lost"
    value:  deal value if known, else 0
    """
    _append(OUTCOMES, {
        "at":     datetime.now().isoformat(),
        "source": source,
        "ref":    ref,
        "kind":   kind,
        "note":   note[:1000],
        "value":  value,
    })
    log.info(f"Outcome recorded: {source}/{kind}", extra={"ref": ref, "value": value})


# ── Reading ───────────────────────────────────────────────────────────────────

def read_events(days: int | None = 30, stage: str = "") -> list[dict]:
    events = _read(RUN_HISTORY, days)
    return [e for e in events if e.get("stage") == stage] if stage else events


def read_runs(days: int | None = 30) -> list[dict]:
    """Group the event stream back into runs, newest first."""
    runs: dict[str, dict] = {}
    for e in _read(RUN_HISTORY, days):
        rid = e.get("run_id", "unknown")
        run = runs.setdefault(rid, {"run_id": rid, "started_at": e.get("at"), "events": []})
        run["events"].append(e)
        if e.get("stage") == "run_end":
            run["status"] = e.get("status", "")
            run["ended_at"] = e.get("at")
    return sorted(runs.values(), key=lambda r: r.get("started_at", ""), reverse=True)


def summarize(days: int = 30) -> dict:
    """Cheap health read: how many runs, how they ended, where they die."""
    runs = read_runs(days)
    statuses: dict[str, int] = {}
    error_stages: dict[str, int] = {}
    scores: list[float] = []

    for run in runs:
        statuses[run.get("status", "incomplete")] = statuses.get(run.get("status", "incomplete"), 0) + 1
        for e in run["events"]:
            if e.get("stage") == "error":
                where = e.get("where", "unknown")
                error_stages[where] = error_stages.get(where, 0) + 1
            elif e.get("stage") == "score" and isinstance(e.get("score"), (int, float)):
                scores.append(float(e["score"]))

    outcomes = _read(OUTCOMES, days)
    outcome_kinds: dict[str, int] = {}
    for o in outcomes:
        outcome_kinds[o.get("kind", "?")] = outcome_kinds.get(o.get("kind", "?"), 0) + 1

    return {
        "days":            days,
        "runs":            len(runs),
        "by_status":       statuses,
        "errors_by_stage": error_stages,
        "avg_score":       round(sum(scores) / len(scores), 1) if scores else 0,
        "score_samples":   len(scores),
        "outcomes":        outcome_kinds,
        "outcome_value":   round(sum(o.get("value", 0) for o in outcomes), 2),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Durable run log — inspect history, record outcomes.")
    sub = parser.add_subparsers(dest="cmd")

    p_sum = sub.add_parser("summary", help="Health summary over the last N days")
    p_sum.add_argument("--days", type=int, default=30)

    p_runs = sub.add_parser("runs", help="List recent runs and how they ended")
    p_runs.add_argument("--days", type=int, default=14)

    p_out = sub.add_parser("outcome", help="Record a real-world outcome")
    p_out.add_argument("--source", required=True, choices=["post", "reddit_lead", "agency_lead", "other"])
    p_out.add_argument("--ref", required=True, help="post URN, lead id, or license number")
    p_out.add_argument("--kind", required=True,
                       choices=["inbound", "reply", "call_booked", "proposal", "won", "lost"])
    p_out.add_argument("--note", default="")
    p_out.add_argument("--value", type=float, default=0.0)

    args = parser.parse_args()

    if args.cmd == "summary":
        print(json.dumps(summarize(days=args.days), indent=2))
    elif args.cmd == "runs":
        for run in read_runs(days=args.days):
            stages = " → ".join(e.get("stage", "?") for e in run["events"])
            print(f"{run.get('started_at', '?')[:19]}  {run.get('status', 'incomplete'):<10}  {stages}")
    elif args.cmd == "outcome":
        record_outcome(args.source, args.ref, args.kind, args.note, args.value)
        print("Recorded.")
    else:
        parser.print_help()
