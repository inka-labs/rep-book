import io
import json

import pytest
from fastapi.testclient import TestClient

from repbook.app import create_app
from repbook.security import COOKIE

DAY = {"type": "A", "done": True, "bw": 78.4, "waist": None, "minutes": 45, "energy": 4, "notes": "Felt strong",
       "ex": {"bench": {"done": True, "sets": [{"w": 60, "r": 8}, {"w": 62.5, "r": 6}, None, {"w": 65, "r": 4}]},
              "plank": {"done": False, "sets": [{"w": None, "r": 45}]},
              "fly": {"done": False, "sets": [{"w": None, "r": None}]}}}


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, auto_backup=False)
    with TestClient(app) as c:
        c.cookies.set(COOKIE, app.state.token)
        c.data = tmp_path
        yield c


def test_needs_sign_in(tmp_path):
    app = create_app(tmp_path, auto_backup=False)
    with TestClient(app) as c:
        assert c.get("/api/health").json()["app"] == "rep-book"
        assert c.get("/api/v1/state").status_code == 401
        assert c.get(f"/auth?token={app.state.token}", follow_redirects=False).status_code == 303
        assert c.get("/api/v1/state").status_code == 200


def test_other_hosts_refused(client):
    assert client.get("/api/v1/state", headers={"host": "evil.example"}).status_code == 403


def test_empty_state_has_default_schedule(client):
    st = client.get("/api/v1/state").json()
    assert st["days"] == {}
    assert st["settings"]["schedule"] == {"1": "A", "2": "B", "4": "C", "5": "D"}
    assert st["settings"]["sessionsPerWeek"] == 4


def test_day_round_trip(client):
    saved = client.put("/api/v1/days/2026-11-16", json=DAY).json()
    assert saved["ex"]["bench"]["sets"] == [{"w": 60, "r": 8}, {"w": 62.5, "r": 6}, {"w": None, "r": None},
                                            {"w": 65, "r": 4}]
    assert saved["ex"]["plank"]["sets"] == [{"w": None, "r": 45}]
    assert "fly" not in saved["ex"]  # nothing logged, not ticked
    assert client.get("/api/v1/state").json()["days"]["2026-11-16"] == saved

    # Saving again replaces the day
    again = client.put("/api/v1/days/2026-11-16", json={**DAY, "ex": {"bench": {"sets": [{"w": 70, "r": 3}]}}}).json()
    assert again["ex"] == {"bench": {"done": False, "sets": [{"w": 70, "r": 3}]}}

    assert client.delete("/api/v1/days/2026-11-16").status_code == 204
    assert client.get("/api/v1/state").json()["days"] == {}


@pytest.mark.parametrize("date,body", [("2026-13-01", DAY), ("16-11-2026", DAY), ("2026-11-16", {**DAY, "type": "X"}),
                                       ("2026-11-16", {**DAY, "energy": 9}), ("2026-11-16", {**DAY, "bw": -3})])
def test_bad_days_refused(client, date, body):
    assert client.put(f"/api/v1/days/{date}", json=body).status_code in (400, 422)


def test_settings(client):
    body = {"startWeight": 82, "goalWeight": 75, "goalDate": "2027-03-01", "sessionsPerWeek": 4,
            "schedule": {"1": "A", "3": "B", "5": "C", "6": "D"}, "lifts": {"bench": 80, "squat": None}}
    out = client.put("/api/v1/settings", json=body).json()
    assert out["lifts"] == {"bench": 80}
    assert client.get("/api/v1/state").json()["settings"]["schedule"] == body["schedule"]
    assert client.put("/api/v1/settings", json={**body, "schedule": {"9": "A"}}).status_code in (400, 422)


def test_export_import_and_csv(client):
    client.put("/api/v1/days/2026-11-16", json=DAY)
    client.put("/api/v1/days/2026-11-17", json={"type": "B", "bw": 78.1})
    exported = client.get("/api/v1/export.json")
    assert "attachment" in exported.headers["content-disposition"]
    data = exported.json()
    assert len(data["days"]) == 2

    sets = client.get("/api/v1/export/sets.csv").text.splitlines()
    assert sets[0].startswith("date,workout,exercise,set,kg")
    assert "2026-11-16,Push,bench,1,60.0,8.0,yes" in sets
    assert "78.1" in client.get("/api/v1/export/days.csv").text

    client.delete("/api/v1/days/2026-11-16")
    r = client.post("/api/v1/import", files={"file": ("x.json", io.BytesIO(json.dumps(data).encode()))}).json()
    assert r["days"] == 2 and r["backup"].endswith("-before-import.zip")
    assert set(client.get("/api/v1/state").json()["days"]) == {"2026-11-16", "2026-11-17"}

    bad = client.post("/api/v1/import", files={"file": ("x.json", io.BytesIO(b'{"hello": 1}'))})
    assert bad.status_code == 400


def test_backup_and_restore(client):
    client.put("/api/v1/days/2026-11-16", json=DAY)
    made = client.post("/api/v1/backups").json()
    client.put("/api/v1/days/2026-11-18", json={"type": "C", "bw": 77.9})
    assert len(client.get("/api/v1/state").json()["days"]) == 2

    r = client.post(f"/api/v1/backups/{made['name']}/restore").json()
    assert r["backup"].endswith("-before-restore.zip")
    assert list(client.get("/api/v1/state").json()["days"]) == ["2026-11-16"]
    # The app keeps working on the restored database
    assert client.put("/api/v1/days/2026-11-19", json={"type": "D"}).status_code == 200
    assert client.post("/api/v1/backups/nope.zip/restore").status_code == 400


def test_page_served(client):
    r = client.get("/week")
    assert r.status_code == 200 and "<title>Rep Book</title>" in r.text
