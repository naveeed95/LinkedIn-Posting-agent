"""
Manages the weekly posting schedule stored in weekly_schedule.json.
Week key is the ISO date of Monday (e.g. "2026-05-04").
"""
import json
from datetime import date, timedelta
from pathlib import Path

SCHEDULE_FILE = Path(__file__).parent / "weekly_schedule.json"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _week_start(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def load_schedule() -> dict:
    if SCHEDULE_FILE.exists():
        with open(SCHEDULE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_schedule(schedule: dict):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule, f, indent=2, ensure_ascii=False)


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
    return schedule.get(_week_start().isoformat(), [])


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
