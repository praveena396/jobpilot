"""API and storage tests. Every test gets its own in-memory database."""
import pytest
from fastapi.testclient import TestClient

from jobpilot.analyzer.store import NotFoundError, Store
from jobpilot.api.server import create_app

JD = """Requirements:
- 2+ years of software development experience
- Strong experience with Python and PostgreSQL
Preferred qualifications:
- Experience with Kubernetes
"""
RESUME = """Experience
Engineer, Acme    Jan 2023 - Present
- Built services in Python backed by PostgreSQL
"""


@pytest.fixture
def client():
    with TestClient(create_app(":memory:")) as c:
        yield c


@pytest.fixture
def store():
    s = Store.open(":memory:")
    yield s
    s.close()


def test_health_and_skills(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["skills_known"] > 50
    skills = client.get("/api/skills").json()
    assert skills["total"] == health["skills_known"]
    assert any(c["label"] == "Languages" for c in skills["categories"])


def test_analyze_without_saving_anything(client):
    r = client.post("/api/analyze", json={"job_text": JD, "resume_text": RESUME})
    assert r.status_code == 200
    body = r.json()
    assert body["score"] > 0 and body["min_years"] == 2
    assert {m["skill"] for m in body["matches"] if m["matched"]} >= {"Python", "PostgreSQL"}
    assert body["suggestions"] and body["suggestions"][0]["your_evidence"] in RESUME
    assert client.get("/api/postings").json() == []          # nothing was stored


def test_analyze_needs_a_resume(client):
    assert client.post("/api/analyze", json={"job_text": JD}).status_code == 400


def test_full_flow_save_analyze_and_track(client):
    client.post("/api/resumes", json={"label": "main", "text": RESUME})
    created = client.post("/api/postings", json={"text": JD, "title": "SWE", "company": "Acme"})
    assert created.status_code == 201
    pid = created.json()["posting"]["id"]
    assert created.json()["analysis"]["score"] > 0           # scored on save

    detail = client.get(f"/api/postings/{pid}").json()
    assert detail["min_years"] == 2
    assert any(r["skill"] == "Python" and r["required"] for r in detail["requirements"])
    assert detail["highlights"][0]["skill"]

    moved = client.post(f"/api/postings/{pid}/stage",
                        json={"stage": "applied", "notes": "referred by a friend"})
    assert moved.json()["stage"] == "applied" and "referred" in moved.json()["notes"]
    assert client.get("/api/postings", params={"stage": "applied"}).json()[0]["id"] == pid
    assert client.get("/api/postings", params={"stage": "saved"}).json() == []


def test_stage_must_be_known(client):
    client.post("/api/resumes", json={"label": "main", "text": RESUME})
    pid = client.post("/api/postings", json={"text": JD}).json()["posting"]["id"]
    assert client.post(f"/api/postings/{pid}/stage", json={"stage": "hired"}).status_code == 422
    assert client.get("/api/postings", params={"stage": "hired"}).status_code == 422


def test_missing_things_are_404_not_500(client):
    assert client.get("/api/postings/999").status_code == 404
    assert client.get("/api/postings/999/analysis").status_code == 404
    assert client.post("/api/resumes/999/activate").status_code == 404


def test_short_posting_is_rejected(client):
    assert client.post("/api/postings", json={"text": "hi"}).status_code == 422


def test_insights_rank_gaps_across_saved_jobs(client):
    client.post("/api/resumes", json={"label": "main", "text": RESUME})
    for i in range(3):
        client.post("/api/postings", json={"text": "Requirements:\n- Strong experience with AWS",
                                           "title": f"Job {i}"})
    client.post("/api/postings", json={"text": JD, "title": "Python job"})
    insights = client.get("/api/insights").json()
    assert insights["jobs"] == 4
    assert insights["gaps"][0]["skill"] == "AWS" and insights["gaps"][0]["jobs_wanting"] == 3
    assert insights["funnel"]["saved"] == 4
    assert any(s["skill"] == "Python" for s in insights["strengths"])


def test_insights_empty_is_not_an_error(client):
    client.post("/api/resumes", json={"label": "main", "text": RESUME})
    assert client.get("/api/insights").json()["jobs"] == 0


# ---------------- store ----------------
def test_analysis_is_cached_until_refreshed(store):
    rid = store.add_resume("main", RESUME)
    pid = store.add_posting(JD)
    first = store.analyze(pid)
    assert first["cached"] is False and first["resume_id"] == rid
    assert store.analyze(pid)["cached"] is True
    assert store.analyze(pid, refresh=True)["cached"] is False


def test_switching_the_active_resume_changes_the_score(store):
    store.add_resume("weak", "Skills\nJava")
    strong = store.add_resume("strong", RESUME)
    pid = store.add_posting(JD)
    assert store.analyze(pid)["resume_id"] == strong
    weak_id = next(r["id"] for r in store.list_resumes() if r["label"] == "weak")
    store.set_active_resume(weak_id)
    assert store.analyze(pid)["score"] < store.get_analysis(pid, strong)["score"]


def test_stage_changes_are_recorded(store):
    store.add_resume("main", RESUME)
    pid = store.add_posting(JD)
    store.set_stage(pid, "applied")
    store.set_stage(pid, "applied")        # no change: no extra event
    store.set_stage(pid, "screen")
    events = store.conn.execute(
        "SELECT from_stage, to_stage FROM stage_events WHERE posting_id = ? ORDER BY id",
        (pid,)).fetchall()
    assert [(e["from_stage"], e["to_stage"]) for e in events] == [
        (None, "saved"), ("saved", "applied"), ("applied", "screen")]


def test_deleting_a_posting_removes_its_analysis(store):
    store.add_resume("main", RESUME)
    pid = store.add_posting(JD)
    store.analyze(pid)
    store.delete_posting(pid)
    assert store.conn.execute("SELECT COUNT(*) c FROM analyses").fetchone()["c"] == 0


def test_analysis_without_a_resume_raises_not_found(store):
    pid = store.add_posting(JD)
    with pytest.raises(NotFoundError):
        store.analyze(pid)
