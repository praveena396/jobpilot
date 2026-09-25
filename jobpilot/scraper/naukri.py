"""Naukri.com scraper — searches for matching jobs on India's largest job portal."""

import asyncio
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from jobpilot import get
from jobpilot.db import insert_job
from jobpilot.scraper.jobs import JobListing, calculate_match_score, detect_level


async def scrape_naukri(client: httpx.AsyncClient) -> list[JobListing]:
    """Scrape Naukri.com job listings using their search endpoint."""
    jobs = []
    roles = get("profile.target_roles", []) or get("profile.job_titles", ["Software Engineer"])
    skills = get("profile.tech_stack", [])

    # Build search queries from roles
    queries = []
    for role in roles[:4]:
        queries.append(role.replace(" ", "-").lower())

    # Also search by top skills
    skill_query = "-".join(skills[:3]).lower()
    queries.append(skill_query)

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    for query in queries:
        # Naukri search URL pattern
        # experience=0to2 for entry level, sort by date
        url = f"https://www.naukri.com/{query}-jobs?experience=0&experience=2&sort=date"

        try:
            resp = await client.get(url, headers=headers, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
        except (httpx.HTTPError, Exception):
            continue

        # Parse job cards
        job_cards = soup.select("article.jobTuple, div.srp-jobtuple-wrapper, div.cust-job-tuple")
        if not job_cards:
            # Try alternate selectors
            job_cards = soup.select("[data-job-id], .jobTupleHeader")

        for card in job_cards[:30]:
            try:
                # Title
                title_el = card.select_one("a.title, .jobTupleHeader a, .info h2 a, a[title]")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                job_url = title_el.get("href", "")
                if job_url and not job_url.startswith("http"):
                    job_url = "https://www.naukri.com" + job_url

                # Company
                company_el = card.select_one(".comp-name, .subTitle a, .companyInfo a")
                company = company_el.get_text(strip=True) if company_el else ""

                # Location
                loc_el = card.select_one(".loc, .locWdth, .location")
                location = loc_el.get_text(strip=True) if loc_el else "India"

                # Experience
                exp_el = card.select_one(".exp, .experience")
                exp_text = exp_el.get_text(strip=True) if exp_el else ""

                # Skip if requires too much experience
                exp_match = re.search(r"(\d+)", exp_text)
                if exp_match and int(exp_match.group(1)) > 3:
                    continue

                # Check against blacklist
                blacklist = [c.lower() for c in get("job_search.blacklisted_companies", [])]
                if company.lower() in blacklist:
                    continue

                match_score = calculate_match_score("", title)
                level = detect_level(title, "")

                jobs.append(JobListing(
                    source="naukri",
                    company=company,
                    title=title,
                    level=level,
                    location=location,
                    comp_min=0,
                    comp_max=0,
                    url=job_url,
                    description="",
                    posted_at=datetime.now().isoformat(),
                    match_score=match_score,
                ))
            except Exception:
                continue

    return jobs


async def scrape_naukri_jobs() -> list[JobListing]:
    """Run Naukri scraper."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await scrape_naukri(client)
