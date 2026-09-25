"""Auto-apply module — fills application forms using Playwright."""

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path

from jobpilot import get, get_root
from jobpilot.db import (
    get_db,
    get_todays_application_count,
    insert_application,
)
from jobpilot.resume_gen import generate_cover_letter, generate_resume
from jobpilot.scraper.linkedin import ProfileData, load_profile_from_db


async def auto_apply_to_job(job: dict, profile: ProfileData | None = None) -> bool:
    """Apply to a single job automatically.

    1. Generate tailored resume
    2. Generate cover letter if needed
    3. Fill the application form via Playwright
    4. Log the application
    """
    from playwright.async_api import async_playwright

    if profile is None:
        profile = load_profile_from_db()
        if profile is None:
            print("❌ No profile found. Run `jobpilot profile` first.")
            return False

    # Rate limit check
    max_daily = get("job_search.max_applications_per_day", 10)
    if get_todays_application_count() >= max_daily:
        print(f"⚠️  Daily limit ({max_daily}) reached. Skipping.")
        return False

    # Generate resume
    resume_path = generate_resume(
        profile=profile,
        job_title=job["title"],
        company=job["company"],
        job_description=job.get("description", ""),
    )

    # Generate cover letter
    cover_letter = generate_cover_letter(
        profile=profile,
        job_title=job["title"],
        company=job["company"],
        job_description=job.get("description", ""),
    )
    cl_path = resume_path.with_suffix(".txt")
    cl_path.write_text(cover_letter)

    # Apply via browser
    success = await _fill_application_form(job, resume_path, cover_letter, profile)

    if success:
        follow_up = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        insert_application({
            "job_id": job["id"],
            "resume_version": resume_path.name,
            "cover_letter_path": str(cl_path),
            "status": "applied",
            "follow_up_date": follow_up,
            "notes": f"Auto-applied on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        })
        print(f"✅ Applied to {job['title']} at {job['company']}")
    else:
        insert_application({
            "job_id": job["id"],
            "resume_version": resume_path.name,
            "cover_letter_path": str(cl_path),
            "status": "failed",
            "follow_up_date": "",
            "notes": "Auto-apply failed — manual submission needed",
        })
        print(f"⚠️  Auto-apply failed for {job['title']} at {job['company']} — resume saved at {resume_path}")

    return success


async def _fill_application_form(
    job: dict,
    resume_path: Path,
    cover_letter: str,
    profile: ProfileData,
) -> bool:
    """Navigate to application URL and fill the form.

    Handles Greenhouse, Lever, and generic application forms.
    """
    from playwright.async_api import async_playwright

    user_data_dir = get_root() / "data" / "browser_context"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()
            await page.goto(job["url"], wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            url = page.url.lower()

            if "greenhouse.io" in url:
                return await _fill_greenhouse(page, resume_path, cover_letter, profile)
            elif "lever.co" in url:
                return await _fill_lever(page, resume_path, cover_letter, profile)
            else:
                return await _fill_generic(page, resume_path, cover_letter, profile)

    except Exception as e:
        print(f"❌ Browser error: {e}")
        return False


async def _fill_greenhouse(page, resume_path: Path, cover_letter: str, profile: ProfileData) -> bool:
    """Fill a Greenhouse application form."""
    try:
        # Click Apply button if present
        apply_btn = await page.query_selector('a[href*="application"]')
        if apply_btn:
            await apply_btn.click()
            await page.wait_for_timeout(2000)

        # Name fields
        await _safe_fill(page, "#first_name", profile.full_name.split()[0] if profile.full_name else "")
        await _safe_fill(page, "#last_name", profile.full_name.split()[-1] if profile.full_name else "")

        # Email
        email = get("profile.portfolio.website", "")  # placeholder
        await _safe_fill(page, "#email", email)

        # Phone
        await _safe_fill(page, "#phone", "")

        # Resume upload
        file_input = await page.query_selector('input[type="file"]')
        if file_input:
            await file_input.set_input_files(str(resume_path))
            await page.wait_for_timeout(1000)

        # LinkedIn
        await _safe_fill(page, 'input[name*="linkedin"], input[id*="linkedin"]', profile.profile_url)

        # Cover letter textarea
        cl_field = await page.query_selector('textarea[id*="cover_letter"], textarea[name*="cover_letter"]')
        if cl_field:
            await cl_field.fill(cover_letter)

        # Answer common screening questions
        await _answer_screening_questions(page, profile)

        # Submit
        submit_btn = await page.query_selector('input[type="submit"], button[type="submit"]')
        if submit_btn:
            await submit_btn.click()
            await page.wait_for_timeout(3000)

        # Check for success
        content = await page.content()
        return "thank" in content.lower() or "received" in content.lower() or "success" in content.lower()

    except Exception as e:
        print(f"Greenhouse fill error: {e}")
        return False


async def _fill_lever(page, resume_path: Path, cover_letter: str, profile: ProfileData) -> bool:
    """Fill a Lever application form."""
    try:
        apply_btn = await page.query_selector('a.postings-btn')
        if apply_btn:
            await apply_btn.click()
            await page.wait_for_timeout(2000)

        await _safe_fill(page, 'input[name="name"]', profile.full_name)
        await _safe_fill(page, 'input[name="email"]', "")
        await _safe_fill(page, 'input[name="phone"]', "")
        await _safe_fill(page, 'input[name*="linkedin"], input[name*="urls[LinkedIn]"]', profile.profile_url)

        # Resume
        file_input = await page.query_selector('input[type="file"][name="resume"]')
        if file_input:
            await file_input.set_input_files(str(resume_path))
            await page.wait_for_timeout(1000)

        # Additional info / cover letter
        cl_field = await page.query_selector('textarea[name="comments"]')
        if cl_field:
            await cl_field.fill(cover_letter)

        await _answer_screening_questions(page, profile)

        submit_btn = await page.query_selector('button[type="submit"]')
        if submit_btn:
            await submit_btn.click()
            await page.wait_for_timeout(3000)

        content = await page.content()
        return "thank" in content.lower() or "application" in content.lower()

    except Exception as e:
        print(f"Lever fill error: {e}")
        return False


async def _fill_generic(page, resume_path: Path, cover_letter: str, profile: ProfileData) -> bool:
    """Best-effort fill for unknown application forms."""
    try:
        # Find and fill common fields
        name_fields = await page.query_selector_all('input[name*="name"], input[id*="name"], input[placeholder*="name"]')
        for field in name_fields[:2]:
            placeholder = await field.get_attribute("placeholder") or ""
            name_attr = await field.get_attribute("name") or ""
            combined = f"{placeholder} {name_attr}".lower()
            if "first" in combined:
                await field.fill(profile.full_name.split()[0] if profile.full_name else "")
            elif "last" in combined:
                await field.fill(profile.full_name.split()[-1] if profile.full_name else "")
            else:
                await field.fill(profile.full_name)

        # Email
        email_fields = await page.query_selector_all('input[type="email"], input[name*="email"]')
        for field in email_fields[:1]:
            await field.fill("")  # user must configure email

        # File upload
        file_input = await page.query_selector('input[type="file"]')
        if file_input:
            await file_input.set_input_files(str(resume_path))

        # LinkedIn field
        linkedin_fields = await page.query_selector_all('input[name*="linkedin"], input[placeholder*="linkedin"]')
        for field in linkedin_fields[:1]:
            await field.fill(profile.profile_url)

        print("⚠️  Generic form detected — please review and submit manually in the browser.")
        await page.wait_for_timeout(60000)  # Give user 60s to review
        return False  # Don't auto-submit unknown forms

    except Exception as e:
        print(f"Generic fill error: {e}")
        return False


async def _safe_fill(page, selector: str, value: str):
    """Safely fill a form field if it exists."""
    if not value:
        return
    try:
        el = await page.query_selector(selector)
        if el:
            await el.fill(value)
    except Exception:
        pass


async def _answer_screening_questions(page, profile: ProfileData):
    """Answer common screening/application questions."""
    visa_status = get("profile.visa_status", "citizen")
    sponsorship = get("profile.visa_sponsorship_needed", False)
    location_pref = get("profile.location", "remote")

    # Find all select dropdowns and try to answer
    selects = await page.query_selector_all("select")
    for select in selects:
        label = ""
        select_id = await select.get_attribute("id") or ""
        # Try to find associated label
        if select_id:
            label_el = await page.query_selector(f'label[for="{select_id}"]')
            if label_el:
                label = (await label_el.inner_text()).lower()

        name = (await select.get_attribute("name") or "").lower()
        combined = f"{label} {name}"

        if "sponsor" in combined or "visa" in combined or "authorization" in combined:
            if not sponsorship:
                await _select_option_containing(select, ["yes", "authorized", "citizen", "do not require"])
            else:
                await _select_option_containing(select, ["yes", "require", "need"])

        elif "relocate" in combined:
            if location_pref == "remote":
                await _select_option_containing(select, ["no", "remote"])
            else:
                await _select_option_containing(select, ["yes"])

        elif "experience" in combined or "years" in combined:
            stack = get("profile.tech_stack", [])
            target = get("profile.target_level", "L5")
            yrs = {"L3": "1", "L4": "3", "L5": "6", "L6": "9", "L7": "12"}.get(target, "5")
            await _select_option_containing(select, [yrs, f"{yrs}+"])

    # Text inputs for salary
    salary_inputs = await page.query_selector_all(
        'input[name*="salary"], input[name*="compensation"], input[id*="salary"]'
    )
    floor = get("profile.salary_floor_usd", 0)
    if floor:
        desired = int(floor * 1.2)  # floor + 20%
        for inp in salary_inputs[:1]:
            await inp.fill(str(desired))


async def _select_option_containing(select_el, preferred_texts: list[str]):
    """Select an option whose text contains one of the preferred strings."""
    options = await select_el.query_selector_all("option")
    for pref in preferred_texts:
        for opt in options:
            text = (await opt.inner_text()).lower()
            if pref.lower() in text:
                value = await opt.get_attribute("value")
                if value:
                    await select_el.select_option(value=value)
                    return


async def apply_to_matched_jobs(limit: int = 5):
    """Apply to top matched jobs that haven't been applied to yet."""
    profile = load_profile_from_db()
    if not profile:
        print("❌ No profile. Run `jobpilot profile <linkedin_url>` first.")
        return

    db = get_db()
    rows = db.execute(
        """SELECT j.* FROM jobs j
           LEFT JOIN applications a ON j.id = a.job_id
           WHERE a.id IS NULL AND j.match_score >= ?
           ORDER BY j.match_score DESC LIMIT ?""",
        (get("job_search.match_threshold", 70), limit),
    ).fetchall()

    if not rows:
        print("No new matching jobs to apply to.")
        return

    for row in rows:
        job = dict(row)
        print(f"\n📋 Applying: {job['title']} at {job['company']} (match: {job['match_score']}%)")
        await auto_apply_to_job(job, profile)
