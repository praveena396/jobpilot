"""SimplifyJobs New-Grad-Positions — community-maintained list of new grad roles.

The list lives on GitHub (github.com/SimplifyJobs/New-Grad-Positions) and is updated
many times a day. It is US/Canada/UK heavy, so it is only used for non-India scans.
"""

import httpx

from jobpilot import get
from jobpilot.scraper.jobs import JobListing, calculate_match_score, detect_level

LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/"
    ".github/scripts/listings.json"
)

# Categories worth scanning for a software / AI / ML profile
DEFAULT_CATEGORIES = ["Software", "Software Engineering", "AI/ML/Data",
                      "Data Science, AI & Machine Learning"]


def parse_simplify_listings(items: list[dict]) -> list[JobListing]:
    categories = set(get("job_search.simplify_categories", DEFAULT_CATEGORIES))
    jobs = []
    for item in items:
        if not item.get("active") or not item.get("is_visible", True):
            continue
        if categories and item.get("category") not in categories:
            continue
        title = item.get("title", "")
        level = detect_level(title)
        jobs.append(JobListing(
            source="simplify",
            company=item.get("company_name", ""),
            title=title,
            # Everything on this list is new-grad, so unmarked titles are entry level
            level="L3" if level == "L4" else level,
            location=", ".join(item.get("locations") or []),
            comp_min=0,
            comp_max=0,
            url=item.get("url", ""),
            description="",
            posted_at=str(item.get("date_posted", "")),
            match_score=calculate_match_score("", title),
        ))
    return jobs


async def scrape_simplify_newgrad(client: httpx.AsyncClient) -> list[JobListing]:
    try:
        resp = await client.get(LISTINGS_URL, timeout=30)
        resp.raise_for_status()
        return parse_simplify_listings(resp.json())
    except (httpx.HTTPError, ValueError):
        return []
