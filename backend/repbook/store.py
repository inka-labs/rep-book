"""Reading and writing the log in the shape the page uses.

A day, as the page sends and receives it:

    {"date": "2026-11-16", "type": "A", "done": true, "bw": 78.4, "waist": null, "minutes": 45,
     "energy": 4, "notes": "", "ex": {"bench": {"done": true, "sets": [{"w": 60, "r": 8}, ...]}}}

Settings: {"startWeight", "goalWeight", "goalDate", "sessionsPerWeek", "schedule", "lifts"}.
"""

import csv
import io
import json
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .db import DEFAULT_SCHEDULE, DEFAULT_THEME, Day, ExerciseLog, MealWeek, SetLog, Settings

# The plan a new log starts with: Push / Pull / Legs / Upper and their exercises. Edited in the Workouts tab, and
# then saved in settings.plan.
DEFAULT_PLAN = json.loads((Path(__file__).parent / "default_plan.json").read_text())
# Ingredients (nutrition, estimated prices) and starter recipes for the Meals tab
FOOD = json.loads((Path(__file__).parent / "food.json").read_text(encoding="utf-8"))
DEFAULT_NUTRITION = {"goal": "maintain", "budget": False, "weeklyBudget": None, "maintenance": None, "prices": {}}
OTHER_NAMES = {"cardio": "Cardio", "rest": "Rest"}


def plan_of(row: Settings) -> dict:
    return row.plan or DEFAULT_PLAN


def _names(db: Session) -> tuple[dict, dict]:
    """Workout id -> short name, exercise id -> name (for the CSV exports)."""
    plan = plan_of(get_settings(db))
    workouts = {w["id"]: w["short"] for w in plan["workouts"]} | OTHER_NAMES
    exercises = {k: v["n"] for k, v in plan["exercises"].items()}
    return workouts, exercises


# ---------- days ----------

def day_out(day: Day) -> dict:
    ex = {}
    for log in day.exercises:
        size = max((s.set_no for s in log.sets), default=0)
        sets = [{"w": None, "r": None} for _ in range(size)]
        for s in log.sets:
            sets[s.set_no - 1] = {"w": s.weight, "r": s.reps}
        ex[log.exercise] = {"done": log.done, "sets": sets}
    return {"date": day.date, "type": day.workout, "done": day.done, "bw": day.body_weight, "waist": day.waist,
            "minutes": day.minutes, "energy": day.energy, "notes": day.notes or "", "ex": ex}


def all_days(db: Session) -> list[Day]:
    query = select(Day).options(selectinload(Day.exercises).selectinload(ExerciseLog.sets)).order_by(Day.date)
    return list(db.scalars(query))


def get_day(db: Session, date: str) -> Day | None:
    return db.scalars(select(Day).where(Day.date == date)
                      .options(selectinload(Day.exercises).selectinload(ExerciseLog.sets))).first()


def put_day(db: Session, date: str, body: dict) -> Day:
    """Replace the day with `body` (the page always sends the whole day)."""
    day = get_day(db, date) or Day(date=date)
    day.workout = body.get("type")
    day.done = bool(body.get("done"))
    day.body_weight = body.get("bw")
    day.waist = body.get("waist")
    day.minutes = body.get("minutes")
    day.energy = body.get("energy")
    day.notes = body.get("notes") or ""
    day.exercises.clear()
    db.add(day)
    db.flush()  # the old exercise rows go before new ones with the same (date, exercise) are added
    for name, entry in (body.get("ex") or {}).items():
        sets = [SetLog(set_no=i + 1, weight=s.get("w"), reps=s.get("r"))
                for i, s in enumerate(entry.get("sets") or []) if s and (s.get("w") is not None or s.get("r") is not None)]
        if sets or entry.get("done"):
            day.exercises.append(ExerciseLog(exercise=name, done=bool(entry.get("done")), sets=sets))
    db.commit()
    return get_day(db, date)


def delete_day(db: Session, date: str) -> None:
    db.execute(delete(Day).where(Day.date == date))
    db.commit()


# ---------- settings ----------

def get_settings(db: Session) -> Settings:
    row = db.get(Settings, 1)
    if row is None:
        row = Settings(id=1, schedule=dict(DEFAULT_SCHEDULE), lift_targets={})
        db.add(row)
        db.commit()
    return row


def settings_out(row: Settings) -> dict:
    return {"startWeight": row.start_weight, "goalWeight": row.goal_weight, "goalDate": row.goal_date or "",
            "sessionsPerWeek": row.sessions_per_week, "schedule": dict(row.schedule or {}),
            "lifts": dict(row.lift_targets or {}), "theme": {**DEFAULT_THEME, **(row.theme or {})},
            "plan": plan_of(row), "nutrition": {**DEFAULT_NUTRITION, **(row.nutrition or {})}}


def put_settings(db: Session, body: dict) -> Settings:
    row = get_settings(db)
    row.start_weight = body.get("startWeight")
    row.goal_weight = body.get("goalWeight")
    row.goal_date = body.get("goalDate") or ""
    row.sessions_per_week = int(body.get("sessionsPerWeek") or 4)
    row.schedule = {str(k): v for k, v in (body.get("schedule") or {}).items()}
    row.lift_targets = {k: v for k, v in (body.get("lifts") or {}).items() if v is not None}
    if body.get("theme"):
        row.theme = {**DEFAULT_THEME, **body["theme"]}
    if body.get("plan"):
        row.plan = body["plan"]
    if body.get("nutrition"):
        row.nutrition = {**DEFAULT_NUTRITION, **body["nutrition"]}
    db.commit()
    return row


# ---------- meal prep ----------

def all_meals(db: Session) -> dict:
    return {m.week: m.plan for m in db.scalars(select(MealWeek).order_by(MealWeek.week))}


def put_meals(db: Session, week: str, plan: dict) -> dict:
    row = db.get(MealWeek, week) or MealWeek(week=week)
    row.plan = plan
    db.add(row)
    db.commit()
    return row.plan


def delete_meals(db: Session, week: str) -> None:
    db.execute(delete(MealWeek).where(MealWeek.week == week))
    db.commit()


# ---------- export / import ----------

def export_all(db: Session) -> dict:
    return {"app": "rep-book", "version": __version__,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "settings": settings_out(get_settings(db)), "days": [day_out(d) for d in all_days(db)],
            "meals": all_meals(db)}


def import_all(db: Session, data: dict) -> int:
    """Replace everything with an export's contents; returns how many days were loaded."""
    db.execute(delete(SetLog))
    db.execute(delete(ExerciseLog))
    db.execute(delete(Day))
    db.execute(delete(MealWeek))
    db.commit()
    put_settings(db, data.get("settings") or {})
    days = data.get("days") or []
    for day in days:
        put_day(db, day["date"], day)
    for week, plan in (data.get("meals") or {}).items():
        put_meals(db, week, plan)
    return len(days)


def _csv(rows: list[list]) -> str:
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()


def sets_csv(db: Session) -> str:
    workouts, exercises = _names(db)
    rows = [["date", "workout", "exercise", "set", "kg", "reps_or_seconds", "exercise_done"]]
    for day in all_days(db):
        for log in day.exercises:
            for s in log.sets:
                rows.append([day.date, workouts.get(day.workout or "", ""), exercises.get(log.exercise, log.exercise), s.set_no,
                             s.weight if s.weight is not None else "", s.reps if s.reps is not None else "",
                             "yes" if log.done else ""])
    return _csv(rows)


def days_csv(db: Session) -> str:
    workouts, _ = _names(db)
    rows = [["date", "workout", "session_done", "body_weight_kg", "waist_cm", "minutes", "energy_1_to_5", "notes"]]
    for d in all_days(db):
        rows.append([d.date, workouts.get(d.workout or "", ""), "yes" if d.done else "",
                     *("" if v is None else v for v in (d.body_weight, d.waist, d.minutes, d.energy)), d.notes or ""])
    return _csv(rows)
