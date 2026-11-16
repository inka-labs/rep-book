"""The SQLite database: one row per logged day, its exercises and their sets, and the targets.

    days            date (YYYY-MM-DD), workout, done, body weight, waist, minutes, energy, notes
    exercise_logs   one exercise on one day (ticked done or not)
    sets            one set of it: kg and reps (seconds for timed holds)
    settings        one row: weight goal, sessions per week, training days, lift targets
"""

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

DEFAULT_SCHEDULE = {"1": "A", "2": "B", "4": "C", "5": "D"}  # Mon Push, Tue Pull, Thu Legs, Fri Upper


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Day(Base):
    __tablename__ = "days"
    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    workout: Mapped[str | None] = mapped_column(String(12))  # A B C D cardio rest
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    body_weight: Mapped[float | None] = mapped_column(Float)
    waist: Mapped[float | None] = mapped_column(Float)
    minutes: Mapped[float | None] = mapped_column(Float)
    energy: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    exercises: Mapped[list["ExerciseLog"]] = relationship(
        back_populates="day", cascade="all, delete-orphan", order_by="ExerciseLog.id")


class ExerciseLog(Base):
    __tablename__ = "exercise_logs"
    __table_args__ = (UniqueConstraint("date", "exercise"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(ForeignKey("days.date", ondelete="CASCADE"), index=True)
    exercise: Mapped[str] = mapped_column(String(40))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    day: Mapped[Day] = relationship(back_populates="exercises")
    sets: Mapped[list["SetLog"]] = relationship(
        back_populates="log", cascade="all, delete-orphan", order_by="SetLog.set_no")


class SetLog(Base):
    __tablename__ = "sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    log_id: Mapped[int] = mapped_column(ForeignKey("exercise_logs.id", ondelete="CASCADE"), index=True)
    set_no: Mapped[int] = mapped_column(Integer)  # 1, 2, 3…
    weight: Mapped[float | None] = mapped_column(Float)  # kg (added kg for bodyweight moves)
    reps: Mapped[float | None] = mapped_column(Float)  # reps, or seconds for timed holds
    log: Mapped[ExerciseLog] = relationship(back_populates="sets")


class Settings(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    start_weight: Mapped[float | None] = mapped_column(Float)
    goal_weight: Mapped[float | None] = mapped_column(Float)
    goal_date: Mapped[str] = mapped_column(String(10), default="")
    sessions_per_week: Mapped[int] = mapped_column(Integer, default=4)
    schedule: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_SCHEDULE))
    lift_targets: Mapped[dict] = mapped_column(JSON, default=dict)


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.close()

    Base.metadata.create_all(engine)
    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session
