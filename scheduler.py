"""
Manages the weekly posting schedule stored in weekly_schedule.json.
Week key is the ISO date of Monday (e.g. "2026-05-04").
"""
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

SCHEDULE_FILE = Path(__file__).parent / "weekly_schedule.json"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _week_start(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def load_schedule() -> dict:
    if SCHEDULE_FILE.exists():
        with open(SCHEDULE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_schedule(schedule: dict):
    # Atomic write: dump to a sibling temp file, fsync, then os.replace.
    # Prevents a corrupt JSON if the process is killed mid-write (GH Actions
    # cancel, OOM, crash) — readers always see either the old or new file.
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=SCHEDULE_FILE.name + ".",
        suffix=".tmp",
        dir=str(SCHEDULE_FILE.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(schedule, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, SCHEDULE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def build_week_slots() -> list[dict]:
    monday = _week_start()
    slots = []
    for i, day in enumerate(WEEKDAYS):
        slots.append({
            "day": day,
            "date": (monday + timedelta(days=i)).isoformat(),
            "topic": None,
            "format": None,
            "post_text": None,
            "design_brief": None,
            "status": "pending",
            "post_urn": None,
        })
    return slots


def init_week(slots: list[dict]) -> None:
    if len(slots) != 7:
        print(f"  [scheduler] WARNING: init_week received {len(slots)} slots (expected 7) — schedule may be incomplete")
    schedule = load_schedule()
    schedule[_week_start().isoformat()] = slots
    save_schedule(schedule)


def get_today_slot() -> dict | None:
    schedule = load_schedule()
    today = date.today().isoformat()
    for slot in schedule.get(_week_start().isoformat(), []):
        if slot["date"] == today:
            return slot
    return None


def update_slot(slot: dict) -> None:
    schedule = load_schedule()
    week_key = _week_start().isoformat()
    days = schedule.get(week_key, [])
    for i, s in enumerate(days):
        if s["date"] == slot["date"]:
            days[i] = slot
            break
    schedule[week_key] = days
    save_schedule(schedule)


def get_week_overview() -> list[dict]:
    schedule = load_schedule()
    slots = schedule.get(_week_start().isoformat(), [])
    if slots and len(slots) not in (0, 7):
        print(f"  [scheduler] WARNING: Week has {len(slots)} slots (expected 7) — schedule may be corrupt")
    return slots


def save_strategy(strategy: dict) -> None:
    schedule = load_schedule()
    schedule[f"{_week_start().isoformat()}_strategy"] = strategy
    save_schedule(schedule)


def get_strategy() -> dict:
    schedule = load_schedule()
    return schedule.get(f"{_week_start().isoformat()}_strategy", {})


def get_recent_topics(weeks_back: int = 2) -> list[str]:
    schedule = load_schedule()
    cutoff = _week_start() - timedelta(weeks=weeks_back)
    titles: list[str] = []
    for week_key, days in schedule.items():
        try:
            week_date = date.fromisoformat(week_key)
        except ValueError:
            continue
        if week_date >= cutoff:
            for slot in days:
                if slot.get("topic") and slot.get("status") in ("posted", "skipped"):
                    titles.append(slot["topic"]["title"])
    return titles
