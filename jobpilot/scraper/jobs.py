"""Job scraper — monitors LinkedIn, Greenhouse, Lever, and company career pages."""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from jobpilot import get
from jobpilot.db import insert_job


@dataclass
class JobListing:
    source: str
    company: str
    title: str
    level: str
    location: str
    comp_min: int
    comp_max: int
    url: str
    description: str
    posted_at: str
    match_score: int = 0


# ── Level detection ──────────────────────────────────────────────────────────

LEVEL_PATTERNS = {
    "L3": r"\b(?:junior|entry|new grad|associate|L3|SDE\s*I\b|engineer\s*I\b|fresh|graduate)",
    "L4": r"\b(?:mid|L4|SDE\s*II|engineer\s*II|MTS\s*1|MTS\s*2)\b",
    "L5": r"\b(?:senior|sr\.?|L5|SDE\s*III|engineer\s*III|MTS\s*3|lead\s+engineer)\b",
    "L6": r"\b(?:staff|L6|principal\s*engineer|tech\s*lead|architect)\b",
    "L7": r"\b(?:principal|L7|distinguished|fellow|director\s*of\s*engineering)\b",
    "INTERN": r"\b(?:intern|internship|co.op|trainee|apprentice)\b",
    "MANAGER": r"\b(?:engineering\s*manager|eng\s*manager|manager.*engineer|head\s+of|VP|vice\s*president|CTO)\b",
}


def detect_level(title: str, description: str = "") -> str:
    text = f"{title} {description}".lower()
    # Check intern first — skip these
    if re.search(LEVEL_PATTERNS["INTERN"], text, re.IGNORECASE):
        return "INTERN"
    # Check manager — too senior
    if re.search(LEVEL_PATTERNS["MANAGER"], text, re.IGNORECASE):
        return "MANAGER"
    for level, pattern in reversed(list(LEVEL_PATTERNS.items())):
        if level in ("MANAGER", "INTERN"):
            continue
        if re.search(pattern, text, re.IGNORECASE):
            return level
    # No explicit level marker = likely senior at most companies
    return "L5"


# ── Skill matching ───────────────────────────────────────────────────────────

def calculate_match_score(job_desc: str, job_title: str) -> int:
    """Calculate match % between job and user's profile."""
    user_skills = [s.lower() for s in get("profile.tech_stack", [])]
    configured_roles = get("profile.target_roles", []) or get("profile.job_titles", [])
    user_roles = [r.lower() for r in configured_roles]
    text = f"{job_title} {job_desc}".lower()
    title_lower = job_title.lower()

    # Skill overlap (from description if available, else title)
    skill_matches = sum(1 for s in user_skills if s.lower() in text)
    skill_score = (skill_matches / max(len(user_skills), 1)) * 30

    # Role title match — THIS IS THE MOST IMPORTANT SIGNAL
    role_score = 0

    # Exact role match = highest priority
    for role in user_roles:
        words = role.split()
        if all(w in title_lower for w in words):
            role_score = 55  # exact match = near perfect
            break

    # If no exact match, check for keyword overlap
    if role_score == 0:
        role_keywords = [
            "engineer", "developer", "ai", "ml", "machine learning",
            "platform", "backend", "software", "python", "data",
            "devops", "mlops", "infrastructure", "llm", "deep learning",
        ]
        title_hits = sum(1 for kw in role_keywords if kw in title_lower)
        if title_hits >= 2:
            role_score = 40
        elif title_hits >= 1:
            role_score = 25

    # Level match — L3 target should match L3, L4, and unmarked roles
    # But NEVER match manager/staff/principal (way too senior for 1yr exp)
    detected = detect_level(job_title, job_desc)
    target = get("profile.target_level", "L3")
    level_map = {"L3": 3, "L4": 4, "L5": 5, "L6": 6, "L7": 7, "MANAGER": 8}
    target_num = level_map.get(target, 3)
    detected_num = level_map.get(detected, 4)
    diff = detected_num - target_num  # positive = job is higher level
    if detected in ("MANAGER", "L7", "L6"):
        level_score = -20  # actively penalize — way too senior
    elif detected == "INTERN":
        level_score = -15  # not an intern — have 1yr industry exp
    elif diff <= 0:
        level_score = 15  # at or below target — great
    elif diff == 1:
        level_score = 10  # one above — still apply
    elif diff == 2:
        level_score = 0   # two above — maybe stretch
    else:
        level_score = -10

    return max(min(int(skill_score + role_score + level_score), 100), 0)


# ── Greenhouse Scraper ───────────────────────────────────────────────────────

async def scrape_greenhouse(client: httpx.AsyncClient, company_slug: str) -> list[JobListing]:
    """Scrape jobs from a Greenhouse board — fast mode (title matching only)."""
    jobs = []
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    try:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return jobs

    for item in data.get("jobs", []):
        title = item.get("title", "")
        location = item.get("location", {}).get("name", "")
        abs_url = item.get("absolute_url", "")

        match_score = calculate_match_score("", title)
        if match_score < 15:
            continue

        level = detect_level(title, "")

        jobs.append(JobListing(
            source="greenhouse",
            company=company_slug,
            title=title,
            level=level,
            location=location,
            comp_min=0,
            comp_max=0,
            url=abs_url or url,
            description="",
            posted_at=item.get("updated_at", ""),
            match_score=match_score,
        ))
    return jobs


# ── Lever Scraper ────────────────────────────────────────────────────────────

async def scrape_lever(client: httpx.AsyncClient, company_slug: str) -> list[JobListing]:
    """Scrape jobs from a Lever posting board."""
    jobs = []
    url = f"https://api.lever.co/v0/postings/{company_slug}"
    try:
        resp = await client.get(url, params={"mode": "json"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return jobs

    for item in data:
        title = item.get("text", "")
        location = item.get("categories", {}).get("location", "")
        desc = item.get("descriptionPlain", "") + " " + " ".join(
            l.get("content", "") for l in item.get("lists", [])
        )
        desc = BeautifulSoup(desc, "html.parser").get_text(" ", strip=True)

        match_score = calculate_match_score(desc, title)

        jobs.append(JobListing(
            source="lever",
            company=company_slug,
            title=title,
            level=detect_level(title, desc),
            location=location if isinstance(location, str) else "",
            comp_min=0,
            comp_max=0,
            url=item.get("hostedUrl", ""),
            description=desc[:5000],
            posted_at=str(item.get("createdAt", "")),
            match_score=match_score,
        ))
    return jobs


# ── LinkedIn Job Scraper (via public search — no API key needed) ─────────

async def scrape_linkedin_jobs(
    client: httpx.AsyncClient,
    location_scope: str = "all",
) -> list[JobListing]:
    """Scrape LinkedIn job listings using public search endpoint."""
    jobs = []
    roles = get("profile.target_roles", []) or get("profile.job_titles", ["Software Engineer"])

    location_options = {
        "bangalore": [("Bengaluru", "105214831")],
        "india": [("India", "102713980")],
        "usa": [("United States", "103644278"), ("Remote", "")],
        "all": [
        ("India", "102713980"),       # India geoId
        ("Bengaluru", "105214831"),   # Bengaluru geoId
        ("United States", "103644278"),
        ("Remote", ""),
        ],
    }
    search_locations = location_options.get(location_scope, location_options["all"])

    for role in roles[:4]:
        for loc_name, geo_id in search_locations:
            params = {
                "keywords": role,
                "sortBy": "DD",  # date descending
            }
            if geo_id:
                params["geoId"] = geo_id
            if loc_name == "Remote":
                params["f_WT"] = "2"  # remote filter

            url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            try:
                resp = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
                    timeout=15,
                )
                soup = BeautifulSoup(resp.text, "html.parser")
            except httpx.HTTPError:
                continue

            for card in soup.select("li")[:20]:
                title_el = card.select_one("h3.base-search-card__title")
                company_el = card.select_one("h4.base-search-card__subtitle")
                link_el = card.select_one("a.base-card__full-link")
                loc_el = card.select_one("span.job-search-card__location")

                if not title_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else ""
                job_url = link_el.get("href", "").split("?")[0]
                loc = loc_el.get_text(strip=True) if loc_el else loc_name

                # Check blacklist
                blacklist = [c.lower() for c in get("job_search.blacklisted_companies", [])]
                if company.lower() in blacklist:
                    continue

                match_score = calculate_match_score("", title)

                jobs.append(JobListing(
                    source="linkedin",
                    company=company,
                    title=title,
                    level=detect_level(title),
                    location=loc,
                    comp_min=0,
                    comp_max=0,
                    url=job_url,
                    description="",
                    posted_at=datetime.now().isoformat(),
                    match_score=match_score,
                ))
    return jobs


# ── Company career page scrapers ─────────────────────────────────────────

GREENHOUSE_COMPANIES = [
    # Verified working Greenhouse boards
    "stripe", "databricks", "anthropic", "figma",
    "airbnb", "coinbase", "discord", "cloudflare", "datadog",
    # Quant / Trading
    "jumptrading", "janestreet",
    # Enterprise / SaaS
    "twilio", "okta",
    # Indian product companies
    "groww", "postman",
    # Other
    "instacart", "lyft",
]

LEVER_COMPANIES = [
    # Verified working Lever boards
    "cred", "meesho", "palantir", "paytm",
]


async def scrape_all_sources(location_scope: str = "all") -> list[JobListing]:
    """Run scrapers for a location scope and return combined results."""
    all_jobs: list[JobListing] = []
    threshold = get("job_search.match_threshold", 70)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = []

        # Greenhouse boards
        for slug in GREENHOUSE_COMPANIES:
            tasks.append(scrape_greenhouse(client, slug))

        # Lever boards
        for slug in LEVER_COMPANIES:
            tasks.append(scrape_lever(client, slug))

        # LinkedIn location search
        tasks.append(scrape_linkedin_jobs(client, location_scope))

        if location_scope in ("all", "india", "bangalore"):
            # Naukri.com (India)
            from jobpilot.scraper.naukri import scrape_naukri
            tasks.append(scrape_naukri(client))

            # thejob.dev (India job aggregator)
            from jobpilot.scraper.thejob import scrape_thejob
            tasks.append(scrape_thejob(client))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_jobs.extend(result)

    # Filter by match threshold and salary floor
    salary_floor = get("profile.salary_floor_usd", 0)
    blacklist = [c.lower() for c in get("job_search.blacklisted_companies", [])]

    matched = []
    for job in all_jobs:
        if job.match_score < threshold:
            continue
        if job.company.lower() in blacklist:
            continue
        if salary_floor and job.comp_max > 0 and job.comp_max < salary_floor:
            continue
        if not _location_matches_scope(job.location, location_scope):
            continue
        matched.append(job)

    # Sort by match score descending
    matched.sort(key=lambda j: j.match_score, reverse=True)

    # Save to DB
    saved_count = 0
    for job in matched:
        row_id = insert_job({
            "source": job.source,
            "company": job.company,
            "title": job.title,
            "level": job.level,
            "location": job.location,
            "comp_min": job.comp_min,
            "comp_max": job.comp_max,
            "url": job.url,
            "description": job.description,
            "match_score": job.match_score,
            "posted_at": job.posted_at,
        })
        if row_id:
            saved_count += 1

    print(f"🔍 Found {len(all_jobs)} jobs, {len(matched)} matched, {saved_count} new")
    return matched


def _location_matches_scope(location: str, location_scope: str) -> bool:
    """Keep location-specific scans from mixing unrelated job results."""
    if location_scope == "all":
        return True
    normalized = (location or "").lower()
    if location_scope == "bangalore":
        return any(term in normalized for term in ("bangalore", "bengaluru", "karnataka"))
    if location_scope == "india":
        return any(term in normalized for term in (
            "india", "bangalore", "bengaluru", "hyderabad", "mumbai", "chennai",
            "pune", "noida", "gurgaon", "gurugram", "karnataka", "remote",
        ))
    if location_scope == "usa":
        return any(term in normalized for term in (
            "united states", "usa", "u.s.", "new york", "california", "texas",
            "seattle", "boston", "chicago", "austin", "remote",
        ))
    return True
