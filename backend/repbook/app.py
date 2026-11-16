"""The FastAPI app: the API under /api/v1 and the page everywhere else."""

import hmac
import json
import re
from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from . import __version__, backup, paths, store
from .db import get_db, make_engine, make_sessionmaker
from .security import COOKIE, session_token

LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WORKOUTS = {"A", "B", "C", "D", "cardio", "rest"}


def _hostname(host: str) -> str:
    return host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]", 1)[0] + "]"


def _check_date(value: str) -> str:
    if not DATE.match(value):
        raise HTTPException(400, "Dates look like 2026-11-16.")
    try:
        Date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{value} isn't a real date.")
    return value


# ---------- request bodies ----------

class SetIn(BaseModel):
    w: float | None = Field(None, ge=0, le=1000)
    r: float | None = Field(None, ge=0, le=100000)


class ExerciseIn(BaseModel):
    done: bool = False
    sets: list[SetIn | None] = Field(default_factory=list, max_length=50)


class DayIn(BaseModel):
    type: str | None = None
    done: bool = False
    bw: float | None = Field(None, gt=0, le=500)
    waist: float | None = Field(None, gt=0, le=400)
    minutes: float | None = Field(None, ge=0, le=1440)
    energy: int | None = Field(None, ge=1, le=5)
    notes: str = Field("", max_length=5000)
    ex: dict[str, ExerciseIn] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def known_workout(cls, v):
        if v is not None and v not in WORKOUTS:
            raise ValueError(f"Workout must be one of {', '.join(sorted(WORKOUTS))}.")
        return v


class SettingsIn(BaseModel):
    startWeight: float | None = Field(None, gt=0, le=500)
    goalWeight: float | None = Field(None, gt=0, le=500)
    goalDate: str = ""
    sessionsPerWeek: int = Field(4, ge=1, le=7)
    schedule: dict[Literal["0", "1", "2", "3", "4", "5", "6"], Literal["A", "B", "C", "D"]] = Field(default_factory=dict)
    lifts: dict[str, float | None] = Field(default_factory=dict)


# ---------- app ----------

def create_app(data_dir: Path | None = None, *, lan: bool = False, auto_backup: bool = True) -> FastAPI:
    data = data_dir or paths.data_dir()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = backup.AutoBackup(data) if auto_backup else None
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    app = FastAPI(title="Rep Book", version=__version__, docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.data = data
    app.state.token = token = session_token(data)

    def open_database():
        app.state.engine = make_engine(data / "db.sqlite3")
        app.state.sessionmaker = make_sessionmaker(app.state.engine)

    open_database()

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not lan and _hostname(request.headers.get("host", "")) not in LOCAL_HOSTS:
            return JSONResponse({"detail": "Forbidden host."}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            if not hmac.compare_digest(request.cookies.get(COOKIE, ""), token):
                return JSONResponse({"detail": "Not signed in. Open Rep Book again from its shortcut "
                                               "(or the link it printed)."}, status_code=401)
            origin = request.headers.get("origin")
            if request.method not in ("GET", "HEAD") and origin and \
                    _hostname(origin.split("://", 1)[-1]) != _hostname(request.headers.get("host", "")):
                return JSONResponse({"detail": "Cross-origin request refused."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/auth", include_in_schema=False)
    def sign_in(request: Request):
        if not hmac.compare_digest(request.query_params.get("token", ""), token):
            return HTMLResponse("<p>That link isn't valid. Open Rep Book again from its shortcut (or use the "
                                "link it printed when it started).</p>", status_code=401)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 365)
        return resp

    @app.get("/api/health")
    def health():
        return {"app": "rep-book", "version": __version__}

    # ----- the log -----

    @app.get("/api/v1/state")
    def state(db: Session = Depends(get_db)):
        return {"settings": store.settings_out(store.get_settings(db)),
                "days": {d.date: store.day_out(d) for d in store.all_days(db)},
                "dataFolder": str(data), "version": __version__}

    @app.put("/api/v1/days/{date}")
    def save_day(date: str, body: DayIn, db: Session = Depends(get_db)):
        _check_date(date)
        return store.day_out(store.put_day(db, date, body.model_dump()))

    @app.delete("/api/v1/days/{date}", status_code=204)
    def remove_day(date: str, db: Session = Depends(get_db)):
        store.delete_day(db, _check_date(date))
        return Response(status_code=204)

    @app.put("/api/v1/settings")
    def save_settings(body: SettingsIn, db: Session = Depends(get_db)):
        if body.goalDate:
            _check_date(body.goalDate)
        return store.settings_out(store.put_settings(db, body.model_dump()))

    # ----- export / import -----

    def _download(text: str, name: str, media: str) -> Response:
        return Response(text, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/v1/export.json")
    def export_json(db: Session = Depends(get_db)):
        stamp = Date.today().isoformat()
        return _download(json.dumps(store.export_all(db), indent=1), f"rep-book-{stamp}.json", "application/json")

    @app.get("/api/v1/export/sets.csv")
    def export_sets(db: Session = Depends(get_db)):
        return _download(store.sets_csv(db), f"rep-book-sets-{Date.today().isoformat()}.csv", "text/csv")

    @app.get("/api/v1/export/days.csv")
    def export_days(db: Session = Depends(get_db)):
        return _download(store.days_csv(db), f"rep-book-days-{Date.today().isoformat()}.csv", "text/csv")

    @app.post("/api/v1/import")
    async def import_json(file: UploadFile = File(...), db: Session = Depends(get_db)):
        try:
            raw = json.loads(await file.read())
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "That file isn't a Rep Book export (it isn't JSON).")
        if not isinstance(raw, dict) or raw.get("app") != "rep-book" or not isinstance(raw.get("days"), list):
            raise HTTPException(400, "That file isn't a Rep Book export.")
        settings = SettingsIn.model_validate(raw.get("settings") or {})
        days = []
        for item in raw["days"]:
            _check_date(str(item.get("date", "")))
            days.append({"date": item["date"], **DayIn.model_validate(item).model_dump()})
        before = backup.make_backup(data, "before-import")
        count = store.import_all(db, {"settings": settings.model_dump(), "days": days})
        return {"days": count, "backup": before["name"]}

    # ----- backups -----

    @app.get("/api/v1/backups")
    def backups():
        return {"folder": str(backup.folder(data)), "items": backup.list_backups(data)}

    @app.post("/api/v1/backups")
    def backup_now():
        return backup.make_backup(data, "manual")

    @app.post("/api/v1/backups/{name}/restore")
    def restore(name: str):
        try:
            before = backup.restore(data, name, lambda: app.state.engine.dispose(), open_database)
        except backup.BackupError as e:
            raise HTTPException(400, str(e))
        return {"restored": name, "backup": before["name"]}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_api(rest: str):
        return JSONResponse({"detail": "Not found."}, status_code=404)

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str):
        return FileResponse(paths.STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app
