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


@pytest.mark.parametrize("date,body", [("2026-13-01", DAY), ("16-11-2026", DAY), ("2026-11-16", {**DAY, "type": "not a workout!"}),
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
    assert "2026-11-16,Push,Bench press,1,60.0,8.0,yes" in sets
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


def test_theme(client):
    assert client.get("/api/v1/state").json()["settings"]["theme"] == {"mode": "system", "accent": "blue"}
    base = client.get("/api/v1/state").json()["settings"]
    out = client.put("/api/v1/settings", json={**base, "theme": {"mode": "dark", "accent": "teal"}}).json()
    assert out["theme"] == {"mode": "dark", "accent": "teal"}
    # Saving targets without a theme keeps the one chosen
    assert client.put("/api/v1/settings", json={**base, "theme": None}).json()["theme"]["accent"] == "teal"
    assert client.put("/api/v1/settings", json={**base, "theme": {"accent": "pink"}}).status_code in (400, 422)


def test_1_0_database_gets_theme_column(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "db.sqlite3")
    con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, start_weight FLOAT, goal_weight FLOAT, goal_date VARCHAR(10), "
                "sessions_per_week INTEGER, schedule JSON, lift_targets JSON)")
    con.execute("""INSERT INTO settings VALUES (1, 80, 75, '', 4, '{"1": "A"}', '{"bench": 80}')""")
    con.commit()
    con.close()
    app = create_app(tmp_path, auto_backup=False)
    with TestClient(app) as c:
        c.cookies.set(COOKIE, app.state.token)
        s = c.get("/api/v1/state").json()["settings"]
        assert s["lifts"] == {"bench": 80} and s["theme"]["accent"] == "blue"


def test_plan_defaults_and_custom_workouts(client):
    base = client.get("/api/v1/state").json()["settings"]
    plan = base["plan"]
    assert [w["short"] for w in plan["workouts"]] == ["Push", "Pull", "Legs", "Upper"]
    assert plan["exercises"]["bench"] == {"n": "Bench press", "k": "w"}

    # Add an exercise to Push, rename one, and add a new workout type scheduled on Saturday
    plan["exercises"]["hipthrust"] = {"n": "Hip thrust", "k": "w"}
    plan["exercises"]["bench"]["n"] = "Barbell bench press"
    plan["workouts"].append({"id": "wglutes", "short": "Glutes", "name": "Glutes & Hamstrings", "color": "violet",
                             "ex": [{"id": "hipthrust", "s": 4, "r": "8–10"}, {"id": "rdl", "s": 3, "r": "8"}]})
    saved = client.put("/api/v1/settings", json={**base, "plan": plan, "schedule": {**base["schedule"], "6": "wglutes"}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["plan"]["workouts"][-1]["id"] == "wglutes"

    day = {"type": "wglutes", "done": True, "ex": {"hipthrust": {"sets": [{"w": 100, "r": 8}]},
                                                    "my-one-off": {"sets": [{"w": 10, "r": 12}]}}}
    assert client.put("/api/v1/days/2026-11-21", json=day).status_code == 200
    sets = client.get("/api/v1/export/sets.csv").text
    assert "2026-11-21,Glutes,Hip thrust,1,100.0,8.0," in sets
    assert "2026-11-21,Glutes,my-one-off,1,10.0,12.0," in sets  # not in the plan: its id stands in

    # Saving targets without a plan keeps the edited one
    client.put("/api/v1/settings", json={**base, "plan": None})
    assert client.get("/api/v1/state").json()["settings"]["plan"]["exercises"]["bench"]["n"] == "Barbell bench press"


@pytest.mark.parametrize("change", [
    lambda p: p["workouts"][0]["ex"].append({"id": "nope", "s": 3, "r": "8"}),  # undefined exercise
    lambda p: p["workouts"].append(dict(p["workouts"][0])),  # duplicate id
    lambda p: p["workouts"].append({"id": "cardio", "short": "Run", "ex": []}),  # built-in id
    lambda p: p["workouts"][0].update(color="gold"),
    lambda p: p["exercises"].update({"bad id!": {"n": "x", "k": "w"}}),
])
def test_bad_plans_refused(client, change):
    base = client.get("/api/v1/state").json()["settings"]
    plan = json.loads(json.dumps(base["plan"]))
    change(plan)
    assert client.put("/api/v1/settings", json={**base, "plan": plan}).status_code in (400, 422)


def test_nutrition_and_meal_weeks(client):
    st = client.get("/api/v1/state").json()
    assert st["settings"]["nutrition"]["goal"] == "maintain"
    assert st["food"]["currency"] == "KES" and st["meals"] == {}
    recipes = {r["id"] for r in st["food"]["recipes"]}
    for r in st["food"]["recipes"]:  # every recipe uses known ingredients
        assert all(i in st["food"]["ingredients"] for i, _ in r["ing"])

    base = st["settings"]
    nut = {"goal": "cut", "budget": True, "weeklyBudget": 2500, "maintenance": None, "prices": {"eggs": 16}}
    assert client.put("/api/v1/settings", json={**base, "nutrition": nut}).json()["nutrition"]["goal"] == "cut"

    week = {"slots": {"breakfast": {"recipe": "eggs-sweetpotato", "portions": None},
                      "lunch": {"recipe": "omena-ugali", "portions": 1.25}, "dinner": None, "snack": None},
            "days": 5, "checked": ["eggs"]}
    assert "omena-ugali" in recipes
    assert client.put("/api/v1/meals/2026-11-16", json=week).status_code == 200
    assert client.get("/api/v1/state").json()["meals"]["2026-11-16"]["days"] == 5
    assert client.put("/api/v1/meals/2026-11-17", json=week).status_code == 400  # not a Monday
    assert client.put("/api/v1/meals/2026-11-16", json={**week, "days": 9}).status_code in (400, 422)

    # Meal weeks travel with export / import
    data = client.get("/api/v1/export.json").json()
    assert data["meals"]["2026-11-16"]["slots"]["lunch"]["recipe"] == "omena-ugali"
    client.delete("/api/v1/meals/2026-11-16")
    client.post("/api/v1/import", files={"file": ("x.json", io.BytesIO(json.dumps(data).encode()))})
    assert "2026-11-16" in client.get("/api/v1/state").json()["meals"]
