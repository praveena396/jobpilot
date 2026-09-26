"""Fetch job descriptions from a posting URL via the hiring system's public API.

Aggregator lists (like SimplifyJobs) only give a title and a link. For links to
Workday, Greenhouse, Lever, Ashby and SmartRecruiters we can fetch the full description,
so the job can be matched against your resume and checked for graduation-year limits.
"""

import asyncio
import html
import re

import httpx
from bs4 import BeautifulSoup

from jobpilot import get

_WORKDAY = re.compile(
    r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)/(job/[^?#]+)"
)
_GREENHOUSE = re.compile(
    r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)|[?&]for=([\w-]+).*?[?&]token=(\d+)"
)
_LEVER = re.compile(r"jobs\.(eu\.)?lever\.co/([\w.-]+)/([0-9a-f-]{36})")
_ASHBY = re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})")
_SMARTRECRUITERS = re.compile(r"smartrecruiters\.com/([^/?#]+)/(\d+)")


def _text(markup: str) -> str:
    return BeautifulSoup(html.unescape(markup or ""), "html.parser").get_text(" ", strip=True)


async def fetch_description(
    client: httpx.AsyncClient, url: str, ashby_boards: dict[str, list[dict]] | None = None
) -> str:
    """Plain-text description for a job URL, or "" if unsupported/unavailable."""
    try:
        if m := _WORKDAY.search(url):
            tenant, wd, site, path = m.groups()
            path = re.sub(r"/apply(?:/.*)?$", "", path)
            api = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/{path}"
            resp = await client.get(api, headers={"Accept": "application/json"}, timeout=15)
            resp.raise_for_status()
            return _text(resp.json().get("jobPostingInfo", {}).get("jobDescription", ""))

        if m := _GREENHOUSE.search(url):
            slug, job_id = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            host = "boards-api.eu.greenhouse.io" if ".eu.greenhouse" in url else (
                "boards-api.greenhouse.io"
            )
            resp = await client.get(f"https://{host}/v1/boards/{slug}/jobs/{job_id}", timeout=15)
            resp.raise_for_status()
            return _text(resp.json().get("content", ""))

        if m := _LEVER.search(url):
            eu, slug, job_id = m.groups()
            api = f"https://api.{eu or ''}lever.co/v0/postings/{slug}/{job_id}"
            resp = await client.get(api, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            parts = [data.get("descriptionPlain", ""), data.get("additionalPlain", "")]
            parts += [_text(section.get("content", "")) for section in data.get("lists", [])]
            return " ".join(p for p in parts if p)

        if m := _ASHBY.search(url):
            slug, job_id = m.groups()
            boards = ashby_boards if ashby_boards is not None else {}
            if slug not in boards:
                resp = await client.get(
                    f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=15
                )
                resp.raise_for_status()
                boards[slug] = resp.json().get("jobs", [])
            for job in boards[slug]:
                if job.get("id") == job_id or job_id in job.get("jobUrl", ""):
                    return job.get("descriptionPlain", "") or _text(job.get("descriptionHtml", ""))
            return ""

        if m := _SMARTRECRUITERS.search(url):
            company, job_id = m.groups()
            resp = await client.get(
                f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}",
                timeout=15,
            )
            resp.raise_for_status()
            sections = resp.json().get("jobAd", {}).get("sections", {})
            texts = [_text(s.get("text", "")) for s in sections.values() if isinstance(s, dict)]
            return " ".join(t for t in texts if t)
    except (httpx.HTTPError, ValueError, AttributeError):
        return ""
    return ""


async def enrich_descriptions(client: httpx.AsyncClient, jobs: list) -> int:
    """Fetch descriptions for jobs that have none and whose title fits. Returns count fetched."""
    from jobpilot.matching import score_job, title_fit
    from jobpilot.scraper.jobs import SENIOR_LEVELS, detect_level

    max_fetch = get("job_search.max_descriptions", 300)
    candidates = [
        j for j in jobs
        if not j.description and j.source != "linkedin"
        and j.level not in SENIOR_LEVELS and title_fit(j.title)[0] > 0
    ][:max_fetch]
    semaphore = asyncio.Semaphore(8)
    ashby_boards: dict[str, list[dict]] = {}

    async def enrich(job) -> bool:
        async with semaphore:
            desc = await fetch_description(client, job.url, ashby_boards)
        if not desc:
            return False
        job.description = desc[:5000]
        level = detect_level(job.title, job.description)
        # Aggregator lists are already entry level; only let the JD move the level down/up
        if level != "L4" or job.level not in ("L3", "L4"):
            job.level = level
        job.match_score = score_job(job.title, job.description, job.level)[0]
        return True

    results = await asyncio.gather(*(enrich(j) for j in candidates))
    return sum(results)
