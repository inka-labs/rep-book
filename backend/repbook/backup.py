"""Backups: a zip holding a copy of the database, made once a day automatically and whenever you ask, kept in
<data folder>/backups (the newest KEEP of them).

Restoring first backs up what's there now, then swaps the database in place.
"""

import re
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

KEEP = 30
EVERY = timedelta(hours=24)
NAME = re.compile(r"^repbook-(\d{8}-\d{6})-(auto|manual|before-restore|before-import)\.zip$")

_lock = threading.Lock()  # one backup or restore at a time


class BackupError(Exception):
    pass


def folder(data: Path) -> Path:
    path = data / "backups"
    path.mkdir(exist_ok=True)
    return path


def list_backups(data: Path) -> list[dict]:
    rows = []
    for path in folder(data).glob("repbook-*.zip"):
        if m := NAME.match(path.name):
            stamp = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
            rows.append({"name": path.name, "size": path.stat().st_size,
                         "created_at": stamp.isoformat(timespec="seconds"), "reason": m.group(2)})
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


def make_backup(data: Path, reason: str = "manual") -> dict:
    with _lock:
        return _make(data, reason)


def _make(data: Path, reason: str) -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder(data) / f"repbook-{stamp}-{reason}.zip"
    if not target.exists():
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "db.sqlite3"
            # SQLite's online backup: a consistent copy even while the app is writing
            src, dst = sqlite3.connect(data / "db.sqlite3"), sqlite3.connect(snapshot)
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
            partial = target.with_suffix(".part")
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(snapshot, "db.sqlite3")
            partial.replace(target)
    _prune(data)
    return next(b for b in list_backups(data) if b["name"] == target.name)


def _prune(data: Path) -> None:
    for old in list_backups(data)[KEEP:]:
        (folder(data) / old["name"]).unlink(missing_ok=True)


def due(data: Path) -> bool:
    autos = [b for b in list_backups(data) if b["reason"] == "auto"]
    return not autos or datetime.now() - datetime.fromisoformat(autos[0]["created_at"]) >= EVERY


def restore(data: Path, name: str, close_database, reopen_database) -> dict:
    """Swap the database for the one in backup `name`; returns the backup made of what was there before."""
    if not NAME.match(name) or not (folder(data) / name).is_file():
        raise BackupError("That backup doesn't exist.")
    with _lock:
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(folder(data) / name) as zf:
                if "db.sqlite3" not in zf.namelist():
                    raise BackupError("That file isn't a Rep Book backup.")
                zf.extract("db.sqlite3", tmp)
            candidate = Path(tmp) / "db.sqlite3"
            con = sqlite3.connect(candidate)
            try:
                tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            finally:
                con.close()
            if not {"days", "settings"} <= tables:
                raise BackupError("That file isn't a Rep Book backup.")
            before = _make(data, "before-restore")
            close_database()
            for suffix in ("-wal", "-shm"):
                (data / f"db.sqlite3{suffix}").unlink(missing_ok=True)
            shutil.copyfile(candidate, data / "db.sqlite3")
        reopen_database()
        return before


class AutoBackup:
    """Checks every hour and makes the daily backup when one is due."""

    def __init__(self, data: Path):
        self.data, self._stop = data, threading.Event()
        self._thread = threading.Thread(target=self._run, name="repbook-backup", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if due(self.data):
                    make_backup(self.data, "auto")
            except Exception as e:  # never take the app down over a backup
                print(f"Automatic backup failed: {e}")
            self._stop.wait(3600)
