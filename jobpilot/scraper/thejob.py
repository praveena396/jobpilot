"""thejob.dev scraper — Indian job aggregator for product companies."""

import asyncio
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from jobpilot import get
from jobpilot.scraper.jobs import JobListing, calculate_match_score, detect_level


# Search groups on thejob.dev relevant to the user
THEJOB_SEARCH_URLS = [
    "https://www.thejob.dev/group/software-engineering",
    "https://www.thejob.dev/group/data-science-ml",
    "https://www.thejob.dev/group/devops-cloud",
    "https://www.thejob.dev/group/backend-development",
    "https://www.thejob.dev/group/internships",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}


async def scrape_thejob(client: httpx.AsyncClient) -> list[JobListing]:
    """Scrape thejob.dev for matching jobs."""
    jobs = []
    blacklist = [c.lower() for c in get("job_search.blacklisted_companies", [])]

    for page_url in THEJOB_SEARCH_URLS:
        try:
            resp = await client.get(page_url, headers=HEADERS, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
        except (httpx.HTTPError, Exception):
            continue

        # Find job links — thejob.dev uses card-style listings
        links = soup.select("a[href*='/job/']")
        seen_urls = set()

        for link in links[:40]:
            href = link.get("href", "")
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            job_url = href if href.startswith("http") else f"https://www.thejob.dev{href}"

            # Extract text from the card
            card_text = link.get_text(" ", strip=True)
            parts = card_text.split()

            # Try to extract company, title, location from card text
            # Cards typically show: CompanyLogo Company Location Title Type
            title = ""
            company = ""
            location = ""

            # Look for common patterns
            title_el = link.select_one("h3, h2, [class*='title'], [class*='name']")
            if title_el:
                title = title_el.get_text(strip=True)

            company_el = link.select_one("[class*='company'], [class*='org']")
            if company_el:
                company = company_el.get_text(strip=True)

            loc_el = link.select_one("[class*='location'], [class*='loc']")
            if loc_el:
                location = loc_el.get_text(strip=True)

            # Fallback: parse from card text
            if not title and card_text:
                # Usually format: "CompanyName Location Title Type Posted X days ago"
                title = card_text[:80]

            if not title:
                continue

            # Check blacklist
            if company.lower() in blacklist:
                continue

            match_score = calculate_match_score("", title)
            if match_score < 20:
                continue

            level = detect_level(title, "")

            jobs.append(JobListing(
                source="thejob.dev",
                company=company or "Unknown",
                title=title[:100],
                level=level,
                location=location or "India",
                comp_min=0,
                comp_max=0,
                url=job_url,
                description="",
                posted_at=datetime.now().isoformat(),
                match_score=match_score,
            ))

    return jobs
