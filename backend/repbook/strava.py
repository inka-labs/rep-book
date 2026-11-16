"""Runs (and other activities) from Strava's free data export.

Strava lets anyone download their data: Settings → My Account → Download or delete your account → Request your
archive. It emails a link to `export_<athlete id>.zip`, which has `activities.csv` (one row per activity) at its
root next to the activity files. Rep Book reads only that CSV. The archive always holds the whole history, so
importing a newer one adds the activities since the last import and refreshes the rest (matched on Strava's id).

activities.csv quirks handled here:
- Some column names appear twice: the first "Distance" is in km (formatted), the second in metres; the first
  "Elapsed Time" and "Max Heart Rate" are the summary ones. Missing columns are left empty.
- "Activity Date" is in UTC, like "Nov 16, 2026, 4:12:34 AM" (newer exports put a narrow no-break space
  before AM/PM). It's converted to this computer's time zone to pick the day.
"""

import csv
import io
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

EXPORT_NAME = re.compile(r"^export_\d+(?: \(\d+\))?\.zip$")  # export_12345678.zip, or "(1)" from a re-download
RUN_TYPES = {"Run", "Trail Run", "Virtual Run"}
DATE_FORMATS = ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y %I:%M:%S %p", "%d %b %Y, %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S")


class StravaError(ValueError):
    pass


def downloads_dir() -> Path:
    return Path(os.environ.get("REPBOOK_DOWNLOADS") or Path.home() / "Downloads")


def newest_export(folder: Path | None = None) -> Path | None:
    """The newest Strava export zip in the Downloads folder, if there is one."""
    folder = folder or downloads_dir()
    try:
        found = [p for p in folder.iterdir() if EXPORT_NAME.match(p.name) and p.is_file()]
    except OSError:
        return None
    return max(found, key=lambda p: p.stat().st_mtime, default=None)


def read_export(f: BinaryIO, filename: str = "") -> list[dict]:
    """Activities from a Strava export: the whole .zip or just its activities.csv."""
    head = f.read(4)
    f.seek(0)
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(f) as zf:
                names = [n for n in zf.namelist() if n.rsplit("/", 1)[-1].lower() == "activities.csv"]
                if not names:
                    raise StravaError("That zip has no activities.csv in it. Is it the export Strava emailed you?")
                raw = zf.read(min(names, key=len))  # the one at the root
        except zipfile.BadZipFile:
            raise StravaError("That zip file is damaged. Download it from Strava's email again.")
    elif filename.lower().endswith(".csv") or not filename:
        raw = f.read()
    else:
        raise StravaError("Pick the .zip Strava emailed you (or the activities.csv inside it).")
    return parse_csv(raw.decode("utf-8-sig", errors="replace"))


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip().replace(",", "")
    try:
        n = float(value)
    except ValueError:
        return None
    return n if n == n else None  # NaN -> None


def _when(value: str) -> datetime:
    value = re.sub(r"\s+", " ", value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).astimezone()
        except ValueError:
            continue
    raise StravaError(f"Couldn't read the date {value!r} in activities.csv.")


def parse_csv(text: str) -> list[dict]:
    rows = csv.reader(io.StringIO(text))
    header = next(rows, None) or []
    cols: dict[str, list[int]] = {}
    for i, name in enumerate(header):
        cols.setdefault(name.strip(), []).append(i)
    if "Activity ID" not in cols or "Activity Date" not in cols:
        raise StravaError("That isn't Strava's activities.csv (its columns are different). Rep Book needs the "
                          "export with English column names.")

    def get(row: list[str], name: str, which: int = 0) -> str | None:
        idx = cols.get(name) or []
        if not idx:
            return None
        i = idx[which] if which < len(idx) else idx[-1]
        return row[i] if i < len(row) else None

    out = []
    for row in rows:
        if not row or not (get(row, "Activity ID") or "").strip():
            continue
        start = _when(get(row, "Activity Date") or "")
        if len(cols.get("Distance", [])) > 1:
            distance = _num(get(row, "Distance", 1))  # metres
        else:
            km = _num(get(row, "Distance"))
            distance = km * 1000 if km is not None else None
        elapsed = _num(get(row, "Elapsed Time"))
        moving = _num(get(row, "Moving Time")) or elapsed
        out.append({
            "id": get(row, "Activity ID").strip()[:20],
            "date": start.date().isoformat(),
            "start": start.replace(tzinfo=None).isoformat(timespec="minutes"),
            "type": (get(row, "Activity Type") or "").strip()[:40] or "Activity",
            "name": (get(row, "Activity Name") or "").strip()[:200],
            "distance": distance,
            "moving": moving,
            "elapsed": elapsed,
            "elevation": _num(get(row, "Elevation Gain")),
            "avgHr": _num(get(row, "Average Heart Rate")),
            "maxHr": _num(get(row, "Max Heart Rate")),
            "calories": _num(get(row, "Calories")),
        })
    return out
