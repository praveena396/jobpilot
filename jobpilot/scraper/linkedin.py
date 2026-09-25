"""LinkedIn profile scraper using Playwright (headless browser)."""

import json
import re
import time
from dataclasses import dataclass, field

from jobpilot import get, get_root
from jobpilot.db import get_db


@dataclass
class ProfileData:
    full_name: str = ""
    headline: str = ""
    summary: str = ""
    location: str = ""
    work_history: list[dict] = field(default_factory=list)
    education: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    recommendations_count: int = 0
    profile_url: str = ""


async def scrape_linkedin_profile(linkedin_url: str) -> ProfileData:
    """Scrape a public LinkedIn profile using Playwright.

    Requires the user to be logged into LinkedIn in the browser context.
    Uses a persistent browser context to reuse the session.
    """
    from playwright.async_api import async_playwright

    profile = ProfileData(profile_url=linkedin_url)
    user_data_dir = get_root() / "data" / "browser_context"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,  # first run needs manual login
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()

        # Check if logged in
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        if "login" in page.url or "authwall" in page.url:
            print("\n⚠️  Please log into LinkedIn in the browser window that just opened.")
            print("   After logging in, press Enter here to continue...")
            input()
            await page.wait_for_timeout(3000)

        # Navigate to profile and wait for the profile header, not just the document shell.
        await page.goto(linkedin_url, wait_until="domcontentloaded")
        if _needs_linkedin_login(page.url):
            print("\n⚠️  LinkedIn requires login or verification for this profile.")
            print("   Complete it in the browser window, then press Enter here to continue...")
            input()
            await page.goto(linkedin_url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("h1, a[href*='/in/'] p", timeout=15000)
        except Exception as exc:
            page_title = await page.title()
            raise RuntimeError(
                f"LinkedIn profile did not load correctly (current URL: {page.url}, "
                f"title: {page_title!r}). LinkedIn may be showing a login, verification, "
                "consent, or restricted-profile page."
            ) from exc

        # Extract name
        name_el = await page.query_selector("h1.text-heading-xlarge, main h1, h1")
        if name_el:
            profile.full_name = (await name_el.inner_text()).strip()
        else:
            profile_link_text = await page.locator("a[href*='/in/'] p").all_inner_texts()
            if profile_link_text:
                profile.full_name = profile_link_text[0].strip()

        # Headline
        headline_el = await page.query_selector(
            "main div.text-body-medium.break-words, div.text-body-medium"
        )
        if headline_el:
            profile.headline = (await headline_el.inner_text()).strip()
        else:
            profile_link_text = await page.locator("a[href*='/in/'] p").all_inner_texts()
            if len(profile_link_text) > 1:
                profile.headline = profile_link_text[1].strip()

        # Summary / About
        about_section = await page.query_selector("#about ~ div.display-flex .visually-hidden")
        if about_section:
            profile.summary = (await about_section.inner_text()).strip()

        # Experience section
        profile.work_history = await _extract_experience(page, linkedin_url)

        # Education
        profile.education = await _extract_education(page, linkedin_url)

        if not profile.full_name:
            raise RuntimeError(
                f"LinkedIn returned no profile data (current URL: {page.url}). "
                f"Page title: {await page.title()!r}. "
                "Check that the profile is visible to this logged-in account."
            )

        # Skills
        profile.skills = await _extract_skills(page, linkedin_url)

        await browser.close()

    # Save to DB
    _save_profile_to_db(profile)
    return profile


async def _extract_experience(page, profile_url: str) -> list[dict]:
    """Extract work experience entries."""
    entries = []
    await page.goto(profile_url.rstrip("/") + "/details/experience/", wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    lines = [line.strip() for line in (await page.locator("body").inner_text()).splitlines() if line.strip()]
    try:
        start = lines.index("Experience") + 1
        end = next((i for i in range(start, len(lines)) if lines[i] in ("Education", "Skills")), len(lines))
        for index in range(start, end - 2):
            if " · " not in lines[index + 1] or not re.search(r"\b\d{4}\b", lines[index + 2]):
                continue
            entries.append({
                "title": lines[index],
                "company": lines[index + 1].split(" · ", 1)[0],
                "dates": lines[index + 2],
                "description": "",
            })
        if entries:
            return entries[:20]
    except ValueError:
        pass

    exp_section = await page.query_selector_all(
        "section:has(#experience) li.artdeco-list__item, "
        "#experience ~ div.pvs-list__outer-container li.artdeco-list__item"
    )
    for item in exp_section[:20]:  # cap to avoid infinite
        entry = {}
        title_el = await item.query_selector("span.mr1.t-bold span[aria-hidden='true']")
        if title_el:
            entry["title"] = (await title_el.inner_text()).strip()

        company_el = await item.query_selector("span.t-14.t-normal span[aria-hidden='true']")
        if company_el:
            entry["company"] = (await company_el.inner_text()).strip()

        date_el = await item.query_selector("span.t-14.t-normal.t-black--light span[aria-hidden='true']")
        if date_el:
            date_text = (await date_el.inner_text()).strip()
            entry["dates"] = date_text

        desc_el = await item.query_selector("div.display-flex.align-items-center span[aria-hidden='true']")
        if desc_el:
            entry["description"] = (await desc_el.inner_text()).strip()

        if entry.get("title"):
            entries.append(entry)
    return entries


async def _extract_education(page, profile_url: str) -> list[dict]:
    entries = []
    await page.goto(profile_url.rstrip("/") + "/details/education/", wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    lines = [line.strip() for line in (await page.locator("body").inner_text()).splitlines() if line.strip()]
    try:
        start = lines.index("Education") + 1
        end = next((i for i in range(start, len(lines)) if lines[i] == "Profile language"), len(lines))
        for index in range(start, end - 1):
            if index + 1 < end and ("degree" in lines[index + 1].lower() or "standard" in lines[index + 1].lower()):
                entries.append({"institution": lines[index], "degree": lines[index + 1]})
        if entries:
            return entries[:10]
    except ValueError:
        pass

    edu_section = await page.query_selector_all(
        "section:has(#education) li.artdeco-list__item, "
        "#education ~ div.pvs-list__outer-container li.artdeco-list__item"
    )
    for item in edu_section[:10]:
        entry = {}
        school_el = await item.query_selector("span.mr1.hoverable-link-text.t-bold span[aria-hidden='true']")
        if school_el:
            entry["institution"] = (await school_el.inner_text()).strip()

        degree_el = await item.query_selector("span.t-14.t-normal span[aria-hidden='true']")
        if degree_el:
            entry["degree"] = (await degree_el.inner_text()).strip()

        if entry.get("institution"):
            entries.append(entry)
    return entries


async def _extract_skills(page, profile_url: str) -> list[dict]:
    """Navigate to skills page and extract."""
    skills = []
    skills_url = profile_url.rstrip("/") + "/details/skills/"
    await page.goto(skills_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    skill_items = await page.query_selector_all(
        "li.pvs-list__paged-list-item span.mr1.t-bold span[aria-hidden='true'], "
        "main li span.mr1.t-bold span[aria-hidden='true']"
    )
    for item in skill_items[:50]:
        name = (await item.inner_text()).strip()
        if name:
            skills.append({"name": name, "endorsements": 0})
    if skills:
        return skills

    lines = [line.strip() for line in (await page.locator("body").inner_text()).splitlines() if line.strip()]
    try:
        start = lines.index("Other Skills") + 1
        end = next((i for i in range(start, len(lines)) if lines[i] == "Who your viewers also viewed"), len(lines))
        ignored = {"All", "Industry Knowledge", "Tools & Technologies", "Other Skills"}
        for index in range(start, end - 1):
            if lines[index] in ignored:
                continue
            context = lines[index + 1].lower()
            if " at " in context or " experiences" in context:
                skills.append({"name": lines[index], "endorsements": 0})
    except ValueError:
        pass
    return skills


def _save_profile_to_db(profile: ProfileData):
    db = get_db()
    cur = db.execute(
        """INSERT INTO profiles (linkedin_url, full_name, headline, summary, raw_json)
           VALUES (?, ?, ?, ?, ?)""",
        (
            profile.profile_url,
            profile.full_name,
            profile.headline,
            profile.summary,
            json.dumps({
                "work_history": profile.work_history,
                "education": profile.education,
                "skills": [s["name"] for s in profile.skills],
                "certifications": profile.certifications,
            }),
        ),
    )
    profile_id = cur.lastrowid

    for i, job in enumerate(profile.work_history):
        db.execute(
            """INSERT INTO work_history (profile_id, company, title, start_date, end_date, bullets, order_idx)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (profile_id, job.get("company", ""), job.get("title", ""),
             job.get("dates", ""), "", job.get("description", ""), i),
        )

    for edu in profile.education:
        db.execute(
            """INSERT INTO education (profile_id, institution, degree, field)
               VALUES (?, ?, ?, ?)""",
            (profile_id, edu.get("institution", ""), edu.get("degree", ""), ""),
        )

    for skill in profile.skills:
        db.execute(
            """INSERT INTO skills (profile_id, name, endorsements)
               VALUES (?, ?, ?)""",
            (profile_id, skill["name"], skill.get("endorsements", 0)),
        )

    db.commit()


def _needs_linkedin_login(url: str) -> bool:
    """Return whether LinkedIn redirected to an authentication flow."""
    lowered_url = url.lower()
    return any(
        marker in lowered_url
        for marker in ("/login", "authwall", "/checkpoint", "/challenge")
    )


def load_profile_from_db() -> ProfileData | None:
    """Load the most recent profile from the database."""
    db = get_db()
    row = db.execute("SELECT * FROM profiles ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        # Fall back to config-based profile
        return load_profile_from_config()

    profile = ProfileData(
        full_name=row["full_name"],
        headline=row["headline"],
        summary=row["summary"],
        profile_url=row["linkedin_url"],
    )

    raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
    profile.work_history = raw.get("work_history", [])
    profile.skills = [{"name": s} for s in raw.get("skills", [])]
    profile.certifications = raw.get("certifications", [])

    edu_rows = db.execute(
        "SELECT * FROM education WHERE profile_id = ?", (row["id"],)
    ).fetchall()
    profile.education = [dict(r) for r in edu_rows]

    return profile


def load_profile_from_config() -> ProfileData | None:
    """Load profile from config/settings.yaml (resume PDF data)."""
    from jobpilot import get

    linkedin = get("profile.linkedin_url", "")
    if not linkedin:
        return None

    tech_stack = get("profile.tech_stack", [])
    achievements = get("profile.achievements", [])
    work_history = get("profile.work_history", [])
    education = get("profile.education", [])
    projects = get("profile.projects", [])

    # Build work history entries
    history = []
    for job in (work_history or []):
        entry = {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "dates": job.get("dates", ""),
            "description": "\n".join(job.get("bullets", [])),
        }
        history.append(entry)

    # Add projects as experience entries
    for proj in (projects or []):
        history.append({
            "title": proj.get("title", ""),
            "company": "Project",
            "dates": proj.get("dates", ""),
            "description": proj.get("description", ""),
        })

    profile = ProfileData(
        full_name="Praveena Ganesan",
        headline="Software Engineer | AI/ML | Backend & Full-Stack Development",
        summary=(
            "AI Developer building scalable, production-grade systems for robotics autonomy "
            "and LLM orchestration. End-to-end ownership of 5 repositories serving distributed "
            "robot fleets. 40% latency reduction, zero-downtime migrations, 100% CI pass rate. "
            "NIT Trichy graduate (8.19 CGPA)."
        ),
        location="Bengaluru, India",
        work_history=history,
        education=[{"institution": e.get("institution", ""), "degree": e.get("degree", "")} for e in (education or [])],
        skills=[{"name": s, "endorsements": 0} for s in tech_stack],
        certifications=get("profile.certifications", []) or [],
        profile_url=linkedin,
    )
    return profile
