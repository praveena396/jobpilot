"""REST API for the match analyzer and application tracker.

Run: uvicorn jobpilot.api.server:app --port 8000

Everything is local: one SQLite file, no outbound calls, no scraping. You paste
postings you found yourself.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..analyzer import (
    analyze_portfolio,
    parse_job_description,
    parse_resume,
    skill_gaps,
    strengths,
    suggest_bullets,
)
from ..analyzer.jd import highlight_skills as highlight_jd
from ..analyzer.match import match as run_match
from ..analyzer.skills import CATEGORY_LABELS, TAXONOMY
from ..analyzer.store import ACTIVE_STAGES, STAGES, NotFoundError, Store


class PostingIn(BaseModel):
    text: str = Field(min_length=20, max_length=100_000,
                      description="the job description, pasted as text")
    title: str = Field("", max_length=200)
    company: str = Field("", max_length=200)
    location: str = Field("", max_length=200)
    url: str = Field("", max_length=1000)


class ResumeIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=20, max_length=200_000)
    make_active: bool = True


class StageIn(BaseModel):
    stage: Literal["saved", "applied", "screen", "interview", "offer", "rejected", "withdrawn"]
    notes: str | None = Field(None, max_length=5000)


class AnalyzeIn(BaseModel):
    """Score without saving anything: paste a JD and a resume, get the result."""

    job_text: str = Field(min_length=20, max_length=100_000)
    resume_text: str | None = Field(None, max_length=200_000,
                                    description="omit to use the saved active resume")
    title: str = Field("", max_length=200)
    company: str = Field("", max_length=200)


def get_store(request: Request) -> Store:
    """The store for whichever app instance is serving this request."""
    store: Store = request.app.state.store
    return store


# Module level on purpose: FastAPI resolves annotations against module globals,
# so an alias defined inside create_app() would be invisible and every endpoint
# would read `store` as a query parameter.
StoreDep = Annotated[Store, Depends(get_store)]


def create_app(db_path: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.store = Store.open(db_path or os.environ.get("JOBPILOT_DB"))
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(title="JobPilot Match Analyzer", version="2.0.0", lifespan=lifespan)

    def _found(fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except NotFoundError as e:
            raise HTTPException(404, str(e)) from None

    @app.get("/api/health")
    async def health(store: StoreDep) -> dict[str, Any]:
        active = store.active_resume()
        return {"status": "ok", "active_resume": active["label"] if active else None,
                "postings": sum(store.funnel().values()), "skills_known": len(TAXONOMY)}

    @app.get("/api/skills")
    async def skills() -> dict[str, Any]:
        """The taxonomy, so the UI can show what the analyzer can recognise."""
        by_cat: dict[str, list[str]] = {}
        for name, (cat, _) in TAXONOMY.items():
            by_cat.setdefault(cat, []).append(name)
        return {"categories": [{"key": k, "label": CATEGORY_LABELS.get(k, k),
                                "skills": sorted(v)} for k, v in sorted(by_cat.items())],
                "total": len(TAXONOMY)}

    # ---------------- resumes ----------------
    @app.get("/api/resumes")
    async def list_resumes(store: StoreDep) -> list[dict[str, Any]]:
        return store.list_resumes()

    @app.post("/api/resumes", status_code=201)
    async def add_resume(body: ResumeIn, store: StoreDep) -> dict[str, Any]:
        rid = store.add_resume(body.label, body.text, body.make_active)
        parsed = parse_resume(body.text, body.label)
        return {"id": rid, "label": body.label, "skills": sorted(parsed.skills),
                "bullets": len(parsed.bullets), "years_experience": parsed.years_experience,
                "degree": parsed.degree}

    @app.post("/api/resumes/{resume_id}/activate")
    async def activate_resume(resume_id: int, store: StoreDep) -> dict[str, Any]:
        _found(store.set_active_resume, resume_id)
        return {"id": resume_id, "active": True}

    @app.delete("/api/resumes/{resume_id}", status_code=204)
    async def delete_resume(resume_id: int, store: StoreDep) -> None:
        store.delete_resume(resume_id)

    # ---------------- postings ----------------
    @app.get("/api/postings")
    async def list_postings(store: StoreDep, stage: str | None = None,
                            limit: int = Query(200, gt=0, le=1000)) -> list[dict[str, Any]]:
        if stage and stage not in STAGES:
            raise HTTPException(422, f"unknown stage {stage!r}")
        return store.list_postings(stage, limit)

    @app.post("/api/postings", status_code=201)
    async def add_posting(body: PostingIn, store: StoreDep) -> dict[str, Any]:
        pid = store.add_posting(body.text, body.title, body.company, body.location, body.url)
        posting = store.get_posting(pid)
        try:
            analysis = store.analyze(pid)
        except NotFoundError:
            analysis = None          # no resume saved yet: still keep the posting
        return {"posting": posting, "analysis": analysis}

    @app.get("/api/postings/{posting_id}")
    async def get_posting(posting_id: int, store: StoreDep) -> dict[str, Any]:
        posting = _found(store.get_posting, posting_id)
        spec = parse_job_description(posting["text"], posting["title"], posting["company"])
        return {"posting": posting,
                "requirements": [{"skill": r.skill, "required": r.required, "years": r.years,
                                  "source": r.source} for r in spec.requirements],
                "min_years": spec.min_years, "degree": spec.degree,
                "highlights": highlight_jd(posting["text"])}

    @app.post("/api/postings/{posting_id}/stage")
    async def set_stage(posting_id: int, body: StageIn, store: StoreDep) -> dict[str, Any]:
        row: dict[str, Any] = _found(store.set_stage, posting_id, body.stage, body.notes)
        return row

    @app.delete("/api/postings/{posting_id}", status_code=204)
    async def delete_posting(posting_id: int, store: StoreDep) -> None:
        store.delete_posting(posting_id)

    @app.get("/api/postings/{posting_id}/analysis")
    async def get_analysis(posting_id: int, store: StoreDep,
                           refresh: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = _found(store.analyze, posting_id, None, refresh)
        return result

    # ---------------- one-off analysis ----------------
    @app.post("/api/analyze")
    async def analyze(body: AnalyzeIn, store: StoreDep) -> dict[str, Any]:
        """Score a posting against a resume without saving either."""
        if body.resume_text:
            resume = parse_resume(body.resume_text, "pasted")
        else:
            active = store.active_resume()
            if active is None:
                raise HTTPException(400, "no resume: paste resume_text or save one first")
            resume = parse_resume(active["text"], active["label"])
        spec = parse_job_description(body.job_text, body.title, body.company)
        result = run_match(resume, spec)
        return {**result.to_dict(),
                "min_years": spec.min_years, "degree": spec.degree,
                "resume_years": resume.years_experience, "resume_degree": resume.degree,
                "suggestions": suggest_bullets(resume, result)}

    # ---------------- portfolio insight ----------------
    @app.get("/api/insights")
    async def insights(store: StoreDep, limit: int = Query(12, gt=0, le=50)) -> dict[str, Any]:
        """What your saved jobs say about what to learn next."""
        resume, specs = _found(store.specs_and_resume)
        if not specs:
            return {"jobs": 0, "average_score": 0, "gaps": [], "strengths": [],
                    "funnel": store.funnel()}
        portfolio = analyze_portfolio(resume, specs)
        return {"jobs": len(specs), "average_score": portfolio.average_score,
                "strong_matches": len(portfolio.strong_matches()),
                "gaps": [g.to_dict() for g in skill_gaps(portfolio, limit)],
                "strengths": strengths(portfolio), "funnel": store.funnel(),
                "counted_stages": list(ACTIVE_STAGES)}

    # ---------------- dashboard ----------------
    static_dir = os.environ.get("STATIC_DIR", "web/dist")
    static = Path(static_dir)
    if (static / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = (static / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(static.resolve()):
                return FileResponse(candidate)
            return FileResponse(static / "index.html")

    return app


app = create_app()
