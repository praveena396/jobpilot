"""JobPilot CLI — main entry point."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(name="jobpilot", help="AI Job Auto-Apply Agent")
console = Console()


@app.command()
def profile(linkedin_url: str):
    """Scrape LinkedIn profile and store it."""
    from jobpilot.scraper.linkedin import scrape_linkedin_profile

    console.print(f"🔍 Scraping profile: {linkedin_url}")
    result = asyncio.run(scrape_linkedin_profile(linkedin_url))
    console.print(f"✅ Profile saved: {result.full_name}")
    console.print(f"   Headline: {result.headline}")
    console.print(f"   Experience: {len(result.work_history)} entries")
    console.print(f"   Skills: {len(result.skills)} skills")
    console.print(f"   Education: {len(result.education)} entries")


@app.command()
def scan(
    location: str = typer.Argument(
        "all",
        help="Location scope: bangalore, india, usa, or all",
    ),
):
    """Scan matching jobs for a location scope."""
    from jobpilot.scraper.jobs import scrape_all_sources
    from jobpilot.notify import notify_matched_jobs

    location_scope = _normalize_scope(location)

    console.print(f"🔍 Scanning {location_scope} jobs...")
    jobs = asyncio.run(scrape_all_sources(location_scope))
    if jobs:
        asyncio.run(notify_matched_jobs(jobs))
    else:
        console.print("No matching jobs found this cycle.")


@app.command()
def apply(limit: int = 5):
    """Auto-apply to top matched jobs."""
    from jobpilot.auto_apply import apply_to_matched_jobs

    console.print(f"🚀 Auto-applying to top {limit} matched jobs...")
    asyncio.run(apply_to_matched_jobs(limit))


@app.command()
def preview(limit: int = 20):
    """Preview matched jobs with links and resume info BEFORE applying."""
    from jobpilot import get
    from jobpilot.db import get_db
    from jobpilot.scraper.linkedin import load_profile_from_db
    from jobpilot.resume_gen import generate_resume
    from rich.table import Table

    db = get_db()
    rows = db.execute(
        """SELECT j.* FROM jobs j
           LEFT JOIN applications a ON j.id = a.job_id
           WHERE a.id IS NULL AND j.match_score >= ?
           ORDER BY j.match_score DESC LIMIT ?""",
        (get("job_search.match_threshold", 50), limit),
    ).fetchall()

    if not rows:
        console.print("No matched jobs yet. Run `jobpilot scan` first.")
        return

    profile = load_profile_from_db()

    table = Table(title=f"🎯 Top {len(rows)} Matched Jobs (not yet applied)")
    table.add_column("#", width=3)
    table.add_column("Score", width=5, style="green")
    table.add_column("Company", width=15, style="cyan")
    table.add_column("Role", width=30)
    table.add_column("Level", width=5)
    table.add_column("Location", width=20)
    table.add_column("Link", width=50)

    for i, row in enumerate(rows, 1):
        table.add_row(
            str(i),
            f"{row['match_score']}%",
            row["company"],
            row["title"],
            row["level"] or "?",
            (row["location"] or "")[:20],
            row["url"][:50] + "..." if len(row["url"]) > 50 else row["url"],
        )

    console.print(table)

    # Generate resumes for top 5
    if profile:
        console.print("\n📄 [bold]Resumes will be generated:[/bold]")
        safe_name = profile.full_name.replace(" ", "_")
        for row in rows[:5]:
            safe_role = row["title"].replace(" ", "_")[:20]
            safe_co = row["company"].replace(" ", "_")[:15]
            console.print(f"  → {safe_name}_{safe_role}_{safe_co}.docx")

    console.print(f"\n💡 To auto-apply: [bold]jobpilot apply --limit {min(len(rows), 10)}[/bold]")
    console.print("💡 To run 24/7:   [bold]jobpilot daemon[/bold]")
    console.print("💡 Full links:    [bold]jobpilot links[/bold]")


@app.command()
def links(limit: int = typer.Argument(50, help="Max number of links to show")):
    """Show full URLs of all matched jobs."""
    from jobpilot import get
    from jobpilot.db import get_db

    db = get_db()
    rows = db.execute(
        """SELECT company, title, match_score, level, url FROM jobs
           WHERE match_score >= ?
           ORDER BY match_score DESC LIMIT ?""",
        (get("job_search.match_threshold", 50), limit),
    ).fetchall()

    if not rows:
        console.print("No jobs found. Run `jobpilot scan` first.")
        return

    for i, r in enumerate(rows, 1):
        console.print(f"\n[cyan]{i}. {r['company']}[/cyan] — {r['title']} [{r['match_score']}%] ({r['level']})")
        console.print(f"   [link]{r['url']}[/link]")

    console.print(f"\nTotal: {len(rows)} jobs")


def _normalize_scope(location: str) -> str:
    location_scope = location.lower().strip()
    aliases = {"bengaluru": "bangalore", "us": "usa", "united-states": "usa"}
    location_scope = aliases.get(location_scope, location_scope)
    if location_scope not in {"all", "bangalore", "india", "usa"}:
        console.print("❌ Location must be one of: bangalore, india, usa, all")
        raise typer.Exit(2)
    return location_scope


@app.command()
def today(
    location: str = typer.Argument(
        None, help="bangalore, india, usa, or all (default: job_search.default_location)"
    ),
    limit: int = typer.Option(0, "--limit", "-n", help="Jobs to list (default: today's target)"),
    scan_first: bool = typer.Option(True, "--scan/--no-scan", help="Scan job boards first"),
):
    """Today's list of fresh entry-level jobs to apply to, with a CSV of links."""
    import csv
    from datetime import date

    from jobpilot import get, get_root
    from jobpilot.db import get_daily_queue, get_todays_application_count
    from jobpilot.matching import grad_eligibility, new_grad_signal, score_job
    from jobpilot.scraper.jobs import (
        SENIOR_LEVELS,
        _location_matches_scope,
        detect_level,
        min_years_required,
        scrape_all_sources,
    )
    from rich.table import Table

    location_scope = _normalize_scope(location or get("job_search.default_location", "all"))
    target = get("job_search.max_applications_per_day", 50)
    done = get_todays_application_count()
    remaining = max(target - done, 0)
    limit = limit or remaining
    if limit == 0:
        console.print(f"🎉 Daily target reached: {done}/{target} applications today.")
        return

    if scan_first:
        console.print(f"🔍 Scanning {location_scope} jobs...")
        asyncio.run(scrape_all_sources(location_scope))

    # Re-score everything against your current resume/config, so older rows stay accurate
    threshold = get("job_search.match_threshold", 55)
    title_only_threshold = get("job_search.match_threshold_title_only", threshold)
    max_years = get("job_search.max_years_experience", 2)
    rows = []
    for r in get_daily_queue(
        min_score=0, max_age_days=get("job_search.queue_max_age_days", 7), limit=5000
    ):
        if not _location_matches_scope(r["location"], location_scope):
            continue
        desc = r["description"] or ""
        level = detect_level(r["title"], desc)
        if level in SENIOR_LEVELS or (
            level == "INTERN" and not get("job_search.include_internships", False)
        ):
            continue
        years = min_years_required(desc)
        if years is not None and years > max_years:
            continue
        eligible, why = grad_eligibility(r["title"], desc)
        if eligible == "no" and get("job_search.hide_ineligible_grad_years", True):
            continue
        if get("job_search.new_grad_only", False) and not (
            eligible == "yes" or new_grad_signal(r["title"], desc, r["source"])
        ):
            continue
        score, skills = score_job(r["title"], desc, level)
        if score >= (threshold if desc else title_only_threshold):
            rows.append({**r, "level": level, "match_score": score, "skills": skills,
                         "eligible": eligible, "eligible_why": why})
    # Confirmed-eligible jobs first among similar scores
    bonus = {"yes": 8, "likely": 4}
    rows.sort(key=lambda r: r["match_score"] + bonus.get(r["eligible"], 0), reverse=True)
    rows = rows[:limit]

    if not rows:
        console.print(
            f"No jobs scored {threshold}+ yet. Lower job_search.match_threshold, "
            "raise max_age_days, or try `jobpilot today all`."
        )
        return

    table = Table(title=f"🎯 Apply today — {done}/{target} done, {len(rows)} queued")
    # ID and fit must always be readable (you type the ID into `jobpilot applied`)
    table.add_column("ID", style="bold", no_wrap=True, min_width=4)
    table.add_column("Fit", style="green", no_wrap=True, min_width=3)
    table.add_column("Company", style="cyan", max_width=12, no_wrap=True, overflow="ellipsis")
    table.add_column("Role", ratio=3, min_width=18)
    table.add_column("Location", max_width=11, no_wrap=True, overflow="ellipsis")
    table.add_column("Grad", no_wrap=True, min_width=6)
    show_skills = console.width >= 110  # narrow terminals: skills are still in the CSV
    if show_skills:
        table.add_column("Your skills", ratio=2, max_width=30)
    marks = {"yes": "[green]yes[/green]", "likely": "likely", "unknown": "[dim]?[/dim]"}
    for r in rows:
        skills = ", ".join(r["skills"][:4]) if r["description"] else "[dim](title only)[/dim]"
        cells = [str(r["id"]), str(r["match_score"]), r["company"], r["title"],
                 r["location"] or "", marks.get(r["eligible"], "?")]
        table.add_row(*cells, *([skills] if show_skills else []))
    console.print(table)

    out_dir = get_root() / "output" / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date.today().isoformat()}_{location_scope}.csv"
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:  # Excel-friendly
        writer = csv.writer(f)
        writer.writerow(["id", "score", "level", "company", "title", "location", "source",
                         "grad_year_eligible", "why", "matched_skills", "url"])
        for r in rows:
            writer.writerow([r["id"], r["match_score"], r["level"], r["company"], r["title"],
                             r["location"], r["source"], r["eligible"], r["eligible_why"],
                             "; ".join(r["skills"]), r["url"]])

    console.print(f"\n📄 Links saved to [bold]{out_path}[/bold]")
    console.print("✅ After applying:  [bold]jobpilot applied <ID> [<ID> ...][/bold]")
    console.print("🚫 Not a fit:       [bold]jobpilot skip <ID> [<ID> ...][/bold]")


@app.command()
def applied(
    job_ids: list[int] = typer.Argument(..., help="Job IDs from `jobpilot today`"),
    follow_up_days: int = typer.Option(7, help="Days until a follow-up is due"),
):
    """Mark jobs as applied (for jobs you applied to yourself)."""
    from jobpilot import get
    from jobpilot.db import get_job, get_todays_application_count, mark_job_applied

    for job_id in job_ids:
        job = get_job(job_id)
        if not job:
            console.print(f"❌ No job with ID {job_id}")
            continue
        if mark_job_applied(job_id, follow_up_days) is None:
            console.print(f"⏭️  Already applied: {job['company']} — {job['title']}")
        else:
            console.print(f"✅ Applied: {job['company']} — {job['title']}")

    target = get("job_search.max_applications_per_day", 50)
    console.print(f"\n📊 Today: {get_todays_application_count()}/{target}")


@app.command()
def skip(job_ids: list[int] = typer.Argument(..., help="Job IDs to hide from the queue")):
    """Hide jobs from the daily queue."""
    from jobpilot.db import get_job, set_job_status

    for job_id in job_ids:
        job = get_job(job_id)
        if not job:
            console.print(f"❌ No job with ID {job_id}")
            continue
        set_job_status(job_id, "skipped")
        console.print(f"🚫 Skipped: {job['company']} — {job['title']}")


@app.command()
def india(limit: int = typer.Argument(50, help="Max results")):
    """Show jobs in India only — Bengaluru, Hyderabad, Mumbai, Remote India."""
    from jobpilot.db import get_db

    db = get_db()
    rows = db.execute(
        """SELECT company, title, match_score, level, location, url FROM jobs
           WHERE match_score >= 35
           AND (location LIKE '%India%' OR location LIKE '%Bengaluru%'
           OR location LIKE '%Bangalore%' OR location LIKE '%Hyderabad%'
           OR location LIKE '%Mumbai%' OR location LIKE '%Chennai%'
           OR location LIKE '%Pune%' OR location LIKE '%Noida%'
           OR location LIKE '%Karnataka%' OR location LIKE '%Maharashtra%'
           OR location LIKE '%Remote - India%' OR location LIKE '%Remote India%')
           ORDER BY match_score DESC LIMIT ?""",
        (limit,),
    ).fetchall()

    if not rows:
        console.print("No India jobs found. Run `jobpilot scan` first.")
        return

    console.print(f"\n🇮🇳 [bold]Jobs in India ({len(rows)} found)[/bold]\n")
    for i, r in enumerate(rows, 1):
        level_color = "green" if r["level"] in ("L3", "L4") else "yellow"
        console.print(
            f"{i:2d}. [{level_color}]{r['match_score']}%[/{level_color}] "
            f"[cyan]{r['company'][:18]}[/cyan] — {r['title'][:45]}"
        )
        console.print(f"    📍 {r['location'][:30]} | {r['level']}")
        console.print(f"    [link]{r['url']}[/link]")


@app.command()
def bangalore(limit: int = typer.Argument(50, help="Max results")):
    """Show matching jobs in Bengaluru/Bangalore."""
    from jobpilot import get
    from jobpilot.db import get_db

    db = get_db()
    rows = db.execute(
        """SELECT company, title, match_score, level, location, url FROM jobs
           WHERE match_score >= ?
           AND (LOWER(location) LIKE '%bengaluru%'
           OR LOWER(location) LIKE '%bangalore%'
           OR LOWER(location) LIKE '%karnataka%')
           ORDER BY match_score DESC LIMIT ?""",
        (get("job_search.match_threshold", 35), limit),
    ).fetchall()

    if not rows:
        console.print("No Bengaluru/Bangalore jobs found. Run `jobpilot scan` first.")
        return

    console.print(f"\n[bold]Bengaluru/Bangalore Jobs ({len(rows)} found)[/bold]\n")
    for i, row in enumerate(rows, 1):
        console.print(
            f"{i:2d}. [green]{row['match_score']}%[/green] "
            f"[cyan]{row['company'][:18]}[/cyan] - {row['title'][:45]}"
        )
        console.print(f"    Location: {row['location'][:40]} | {row['level']}")
        console.print(f"    [link]{row['url']}[/link]")


@app.command()
def abroad(limit: int = typer.Argument(50, help="Max results")):
    """Show jobs abroad that typically sponsor visas — US, UK, Singapore, etc."""
    from jobpilot.db import get_db

    db = get_db()
    rows = db.execute(
        """SELECT company, title, match_score, level, location, url FROM jobs
           WHERE match_score >= 50
           AND level IN ('L3', 'L4')
           AND location NOT LIKE '%India%'
           AND location NOT LIKE '%Bengaluru%' AND location NOT LIKE '%Bangalore%'
           AND location NOT LIKE '%Hyderabad%' AND location NOT LIKE '%Mumbai%'
           AND location NOT LIKE '%Chennai%' AND location NOT LIKE '%Pune%'
           AND location NOT LIKE '%Noida%' AND location NOT LIKE '%Karnataka%'
           ORDER BY match_score DESC LIMIT ?""",
        (limit,),
    ).fetchall()

    if not rows:
        console.print("No abroad entry-level jobs found.")
        return

    console.print(f"\n🌍 [bold]Abroad Entry-Level Jobs ({len(rows)} found)[/bold]")
    console.print("(These companies typically sponsor visas for top candidates)\n")
    for i, r in enumerate(rows, 1):
        console.print(
            f"{i:2d}. [{r['match_score']}%] [cyan]{r['company'][:18]}[/cyan] — {r['title'][:45]}"
        )
        console.print(f"    📍 {r['location'][:30]} | {r['level']}")
        console.print(f"    [link]{r['url']}[/link]")


@app.command()
def resume(
    job_url: str = typer.Argument(None, help="Job URL or paste job description"),
    title: str = typer.Option("Software Engineer", "--title", "-t"),
    company: str = typer.Option("Company", "--company", "-c"),
):
    """Generate a tailored resume for a specific job."""
    from jobpilot.resume_gen import generate_resume
    from jobpilot.scraper.linkedin import load_profile_from_db

    profile = load_profile_from_db()
    if not profile:
        console.print("❌ No profile. Run `jobpilot profile <linkedin_url>` first.")
        raise typer.Exit(1)

    # If URL provided, try to fetch JD
    jd = ""
    if job_url and job_url.startswith("http"):
        import httpx
        try:
            from bs4 import BeautifulSoup
            resp = httpx.get(job_url, follow_redirects=True, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            jd = soup.get_text(" ", strip=True)[:5000]
        except Exception:
            console.print("⚠️  Could not fetch JD. Generating generic resume.")
    elif job_url:
        jd = job_url  # treat as pasted JD text

    path = generate_resume(profile, title, company, jd)
    console.print(f"📄 Resume: {path}")


@app.command(name="resume-latex")
def resume_latex(
    job_url: str = typer.Argument(None, help="Job URL or paste job description"),
    title: str = typer.Option("Software Engineer", "--title", "-t"),
    company: str = typer.Option("Company", "--company", "-c"),
):
    """Generate LaTeX resume and export TEX/PDF/(optional)DOCX with ATS score."""
    from jobpilot.latex_resume import generate_latex_resume
    from jobpilot.scraper.linkedin import load_profile_from_db

    profile = load_profile_from_db()
    if not profile:
        console.print("❌ No profile. Run jobpilot profile <linkedin_url> first.")
        raise typer.Exit(1)

    jd = ""
    if job_url and job_url.startswith("http"):
        import httpx
        try:
            from bs4 import BeautifulSoup

            resp = httpx.get(job_url, follow_redirects=True, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            jd = soup.get_text(" ", strip=True)[:12000]
        except Exception:
            console.print("⚠️ Could not fetch job description from URL.")
    elif job_url:
        jd = job_url

    result = generate_latex_resume(profile, title, company, jd)
    console.print(f"📄 TEX: {result['tex']}")
    if result["pdf_generated"]:
        console.print(f"📘 PDF: {result['pdf']}")
    else:
        console.print("⚠️ PDF not generated (pdflatex not found).")
    if result["docx_generated"]:
        console.print(f"📄 DOCX: {result['docx']}")
    else:
        console.print("ℹ️ DOCX not generated (pandoc not found).")

    ats = result["ats"]
    console.print(f"📊 ATS Score: {ats['total']:.0f}/100")
    if ats["missing_keywords"]:
        console.print("Missing keywords: " + ", ".join(ats["missing_keywords"][:12]))


@app.command(name="level")
def show_level():
    """Show configured target level and where to change it."""
    from jobpilot import get

    console.print(f"Current target level: {get('profile.target_level', 'L4')}")
    console.print("Edit config/settings.yaml -> profile.target_level to L3/L4/L5/L6/L7")


@app.command()
def tracker(status: str = typer.Argument(None, help="Filter by status")):
    """Show application tracker."""
    from jobpilot.tracker import show_tracker

    show_tracker(status)


@app.command()
def followups():
    """Show pending follow-ups and generate emails."""
    from jobpilot.tracker import show_pending_followups, generate_followup_email, get_pending_followups

    show_pending_followups()
    pending = get_pending_followups()
    if pending:
        console.print("\n📧 Follow-up email for first pending:")
        console.print(generate_followup_email(pending[0]))


@app.command()
def report():
    """Show weekly summary report."""
    from jobpilot.tracker import weekly_report

    weekly_report()


@app.command()
def daemon():
    """Run continuous job scanning daemon."""
    import schedule
    import time

    from jobpilot import get
    from jobpilot.scraper.jobs import scrape_all_sources
    from jobpilot.notify import notify_matched_jobs

    interval = get("job_search.check_interval_minutes", 30)
    console.print(f"🤖 JobPilot daemon started — scanning every {interval} min")

    def scan_and_notify():
        try:
            jobs = asyncio.run(scrape_all_sources())
            if jobs:
                asyncio.run(notify_matched_jobs(jobs))
        except Exception as e:
            console.print(f"❌ Scan error: {e}")

    scan_and_notify()  # Run immediately
    schedule.every(interval).minutes.do(scan_and_notify)

    while True:
        schedule.run_pending()
        time.sleep(60)


@app.command()
def init():
    """Initialize config from template."""
    from jobpilot import get_root

    src = get_root() / "config" / "settings.example.yaml"
    dst = get_root() / "config" / "settings.yaml"
    if dst.exists():
        console.print("⚠️  config/settings.yaml already exists.")
        return
    dst.write_text(src.read_text())
    console.print("✅ Created config/settings.yaml — edit it with your details.")


@app.command()
def status():
    """Show current profile and config status."""
    from jobpilot import get
    from jobpilot.scraper.linkedin import load_profile_from_db
    from jobpilot.db import get_db

    profile = load_profile_from_db()
    db = get_db()

    console.print("\n🤖 [bold]JobPilot Status[/bold]")

    if profile:
        console.print(f"  Profile: {profile.full_name} ✅")
        console.print(f"  Skills: {len(profile.skills)}")
        console.print(f"  Experience: {len(profile.work_history)} entries")
    else:
        console.print("  Profile: ❌ Not set up. Run `jobpilot profile <linkedin_url>`")

    job_count = db.execute("SELECT COUNT(*) as cnt FROM jobs").fetchone()["cnt"]
    app_count = db.execute("SELECT COUNT(*) as cnt FROM applications").fetchone()["cnt"]
    console.print(f"  Jobs tracked: {job_count}")
    console.print(f"  Applications: {app_count}")
    console.print(f"  Target: {get('profile.target_level', '?')} {', '.join(get('profile.target_roles', []))}")
    console.print(f"  Salary floor: ${get('profile.salary_floor_usd', 0):,}")


if __name__ == "__main__":
    app()
