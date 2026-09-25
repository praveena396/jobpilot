import asyncio
import time
from datetime import datetime, timedelta

import httpx
import pytest

import jobpilot
from jobpilot import db, matching
from jobpilot.scraper import jobs as jobs_mod
from jobpilot.scraper.jobs import (
    JobListing,
    detect_level,
    fetch_linkedin_descriptions,
    is_entry_level,
    min_years_required,
    posted_within,
    scrape_ashby,
    scrape_greenhouse,
    scrape_linkedin_jobs,
)
from jobpilot.scraper.simplify import parse_simplify_listings


@pytest.fixture(autouse=True)
def config(tmp_path):
    jobpilot._CONFIG = {
        "profile": {
            "target_level": "L3",
            "job_titles": ["Software Engineer"],
            "tech_stack": ["Python"],
        },
        "job_search": {"max_years_experience": 2, "max_age_days": 1},
        "database": {"path": str(tmp_path / "test.db")},
    }
    db._conn = None
    matching.profile_skills.cache_clear()
    yield
    db._conn = None
    matching.profile_skills.cache_clear()
    jobpilot._CONFIG = None


def _job(title: str, description: str = "") -> JobListing:
    return JobListing(
        source="test", company="Acme", title=title, level=detect_level(title, description),
        location="Bengaluru", comp_min=0, comp_max=0, url=f"https://x/{title}",
        description=description, posted_at="", match_score=50,
    )


@pytest.mark.parametrize(
    ("title", "description", "level"),
    [
        ("Software Engineer I", "", "L3"),
        ("SDE-1", "", "L3"),
        ("Software Engineer, New Grad 2026", "", "L3"),
        ("Associate Software Engineer", "", "L3"),
        ("Software Engineer II", "", "L4"),
        ("Software Engineer", "", "L4"),
        ("Senior Software Engineer", "", "L5"),
        ("Engineering Manager", "", "MANAGER"),
        ("Software Engineering Intern", "", "INTERN"),
        ("Backend Engineer", "0-2 years of experience with Python", "L3"),
        ("ML Engineer", "Requires 5+ years of industry experience", "L5"),
        ("ML Engineer", "You will partner with senior engineers. Great for new grads.", "L3"),
    ],
)
def test_detect_level(title: str, description: str, level: str) -> None:
    assert detect_level(title, description) == level


def test_min_years_required() -> None:
    assert min_years_required("3+ years of professional experience") == 3
    assert min_years_required("1-3 years experience in Go") == 1
    assert min_years_required("No experience needed") is None


def test_is_entry_level_filters_senior_and_experience_heavy_roles() -> None:
    assert is_entry_level(_job("Software Engineer I"))
    assert is_entry_level(_job("Software Engineer"))
    assert not is_entry_level(_job("Senior Software Engineer"))
    assert not is_entry_level(_job("Staff Engineer"))
    assert not is_entry_level(_job("Software Engineering Intern"))
    assert not is_entry_level(_job("Software Engineer", "4+ years of backend experience"))


def test_posted_within() -> None:
    now = datetime.now()
    assert posted_within((now - timedelta(hours=3)).isoformat(), 1)
    assert not posted_within((now - timedelta(days=3)).isoformat(), 1)
    assert posted_within(str(int(time.time()) - 3600), 1)  # unix seconds
    assert not posted_within(str(int((time.time() - 5 * 86400) * 1000)), 1)  # unix ms
    assert posted_within(now.date().isoformat(), 1)  # date only
    assert posted_within("", 1)
    assert posted_within("not a date", 1)


def test_parse_simplify_listings() -> None:
    items = [
        {"active": True, "is_visible": True, "category": "Software", "company_name": "Acme",
         "title": "Software Engineer", "locations": ["NYC", "Remote in USA"],
         "url": "https://acme/1", "date_posted": 1790289694},
        {"active": False, "is_visible": True, "category": "Software", "company_name": "Old",
         "title": "Software Engineer", "locations": [], "url": "https://old/1", "date_posted": 1},
        {"active": True, "is_visible": True, "category": "Hardware", "company_name": "Chip",
         "title": "ASIC Engineer", "locations": [], "url": "https://chip/1", "date_posted": 1},
    ]
    jobs = parse_simplify_listings(items)
    assert [j.company for j in jobs] == ["Acme"]
    assert jobs[0].level == "L3"  # everything on the new grad list is entry level
    assert jobs[0].location == "NYC, Remote in USA"


def test_scrape_ashby() -> None:
    payload = {"jobs": [
        {"title": "Software Engineer, Early Career", "location": "Bengaluru", "isRemote": False,
         "isListed": True, "descriptionPlain": "Python, 0-1 years of experience",
         "publishedAt": "2026-09-24T10:00:00.000+00:00", "jobUrl": "https://jobs.ashbyhq.com/a/1"},
        {"title": "Hidden", "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/a/2"},
    ]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async def run() -> list[JobListing]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await scrape_ashby(client, "acme")

    jobs = asyncio.run(run())
    assert len(jobs) == 1
    assert jobs[0].level == "L3"
    assert jobs[0].url == "https://jobs.ashbyhq.com/a/1"


LINKEDIN_CARD = """
<li><div>
  <a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/{n}?refId=x"></a>
  <h3 class="base-search-card__title">Software Engineer {n}</h3>
  <h4 class="base-search-card__subtitle">Company {n}</h4>
  <span class="job-search-card__location">Bengaluru, Karnataka, India</span>
  <time datetime="2026-09-25"></time>
</div></li>
"""


def test_linkedin_uses_entry_level_filters_and_paginates(monkeypatch) -> None:
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs_mod.asyncio, "sleep", lambda _s: real_sleep(0))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        start = int(request.url.params["start"])
        if start >= 4:
            return httpx.Response(200, text="")
        html = "".join(LINKEDIN_CARD.format(n=start + i) for i in range(2))
        return httpx.Response(200, text=html)

    async def run() -> list[JobListing]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await scrape_linkedin_jobs(client, "bangalore")

    jobs = asyncio.run(run())
    assert [r.url.params["start"] for r in requests] == ["0", "2", "4"]
    assert requests[0].url.params["f_E"] == "2,3"
    assert requests[0].url.params["f_TPR"] == "r86400"
    assert len(jobs) == 4
    assert jobs[0].url == "https://in.linkedin.com/jobs/view/0"
    assert jobs[0].posted_at == "2026-09-25"


def test_daily_queue_and_mark_applied() -> None:
    for i, title in enumerate(["Software Engineer I", "Backend Engineer", "Data Engineer"]):
        db.insert_job({
            "source": "test", "company": f"Co{i}", "title": title, "level": "L3",
            "location": "Bengaluru", "comp_min": 0, "comp_max": 0, "url": f"https://x/{i}",
            "description": "", "match_score": 60 - i, "posted_at": "",
        })

    queue = db.get_daily_queue(min_score=35, max_age_days=7, limit=10)
    titles = [j["title"] for j in queue]
    assert titles == ["Software Engineer I", "Backend Engineer", "Data Engineer"]

    assert db.mark_job_applied(queue[0]["id"]) is not None
    assert db.mark_job_applied(queue[0]["id"]) is None  # no duplicate applications
    db.set_job_status(queue[1]["id"], "skipped")

    remaining = db.get_daily_queue(min_score=35, max_age_days=7, limit=10)
    assert [j["title"] for j in remaining] == ["Data Engineer"]
    assert db.get_todays_application_count() == 1


# ── Resume-based matching ────────────────────────────────────────────────────

@pytest.fixture
def ml_profile():
    jobpilot._CONFIG["profile"].update({
        "job_titles": ["ML Engineer", "Software Engineer", "Backend Engineer"],
        "tech_stack": ["Python", "PyTorch", "FastAPI", "Docker", "React"],
        "core_skills": ["Python", "PyTorch", "FastAPI"],
        "focus_keywords": ["ml", "machine learning", "ai"],
    })
    jobpilot._CONFIG["job_search"]["exclude_title_keywords"] = ["java", "analyst", "manager"]
    matching.profile_skills.cache_clear()


def test_find_skills_matches_whole_words_only() -> None:
    text = "We are interested in email automation and the rest of the team uses Javascript."
    assert matching.find_skills(text) == ["JavaScript"]
    assert "REST APIs" in matching.find_skills("Build RESTful services")
    assert "C++" in matching.find_skills("Strong C++ and Go skills")


def test_resume_skills_come_from_profile(ml_profile) -> None:
    jobpilot._CONFIG["profile"]["work_history"] = [
        {"title": "Engineer", "bullets": ["Deployed models with TensorRT on Kubernetes"]}
    ]
    matching.profile_skills.cache_clear()
    core, all_skills = matching.profile_skills()
    assert core == {"Python", "PyTorch", "FastAPI"}
    assert {"Docker", "React", "TensorRT", "Kubernetes"} <= all_skills


def test_resume_file_is_read(ml_profile, tmp_path) -> None:
    resume = tmp_path / "resume.txt"
    resume.write_text("Built RAG pipelines with LangChain", encoding="utf-8")
    jobpilot._CONFIG["profile"]["resume_path"] = str(resume)
    matching.profile_skills.cache_clear()
    assert {"RAG", "LangChain"} <= matching.profile_skills()[1]


def test_score_job_ranks_relevant_jobs_first(ml_profile) -> None:
    ml_jd = "Train PyTorch models and serve them with FastAPI in Python."
    ml, ml_skills = matching.score_job("Machine Learning Engineer", ml_jd, "L3")
    generic_fit, _ = matching.score_job("Software Engineer", ml_jd, "L3")
    generic_off, _ = matching.score_job("Software Engineer", "Spring Boot and Oracle", "L3")
    assert ml > generic_fit > generic_off
    assert ml_skills[:3] == ["Python", "FastAPI", "PyTorch"]
    assert matching.score_job("Java Developer", ml_jd, "L3")[0] == 0  # excluded keyword
    assert matching.score_job("Data Analyst", ml_jd, "L3")[0] == 0
    assert matching.score_job("Nurse", ml_jd, "L3")[0] == 0  # not a target role


def test_greenhouse_uses_descriptions(ml_profile) -> None:
    payload = {"jobs": [
        {"title": "ML Engineer", "absolute_url": "https://gh/1", "location": {"name": "Remote"},
         "content": "&lt;p&gt;Python and PyTorch, 1+ years of experience&lt;/p&gt;"},
        {"title": "Account Executive", "absolute_url": "https://gh/2", "content": ""},
    ]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["content"] == "true"
        return httpx.Response(200, json=payload)

    async def run() -> list[JobListing]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await scrape_greenhouse(client, "acme")

    jobs = asyncio.run(run())
    assert [j.title for j in jobs] == ["ML Engineer"]
    assert jobs[0].description == "Python and PyTorch, 1+ years of experience"
    assert jobs[0].level == "L3"


LINKEDIN_POSTING = """
<div class="show-more-less-html__markup">Python, PyTorch and FastAPI for LLM serving.</div>
<ul><li class="description__job-criteria-item"><h3>Seniority level</h3>
<span>Entry level</span></li></ul>
"""


def test_fetch_linkedin_descriptions(ml_profile, monkeypatch) -> None:
    real_sleep = asyncio.sleep
    monkeypatch.setattr(jobs_mod.asyncio, "sleep", lambda _s: real_sleep(0))
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(request.url.path)
        return httpx.Response(200, text=LINKEDIN_POSTING)

    def li_job(title: str, job_id: str) -> JobListing:
        return JobListing("linkedin", "Acme", title, detect_level(title), "Bengaluru", 0, 0,
                          f"https://in.linkedin.com/jobs/view/{title.lower()}-{job_id}", "", "", 0)

    jobs = [li_job("ML Engineer", "4000000001"), li_job("Nurse", "4000000002")]

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fetch_linkedin_descriptions(client, jobs)

    asyncio.run(run())
    assert fetched == ["/jobs-guest/jobs/api/jobPosting/4000000001"]  # Nurse never fetched
    assert jobs[0].description.startswith("Python, PyTorch")
    assert jobs[0].level == "L3"  # from LinkedIn's "Entry level" tag
    assert jobs[0].match_score >= 80
