"""Application tracker — reports, follow-ups, weekly summaries."""

from datetime import datetime, timedelta

from rich.console import Console
from rich.table import Table

from jobpilot.db import get_applications, get_pending_followups, get_db

console = Console()


def show_tracker(status: str | None = None):
    """Display application tracker table."""
    apps = get_applications(status)

    table = Table(title="📋 Application Tracker", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Date", width=10)
    table.add_column("Company", style="cyan", width=15)
    table.add_column("Role", width=25)
    table.add_column("Status", width=12)
    table.add_column("Resume", width=15)
    table.add_column("Follow-up", width=10)
    table.add_column("Notes", width=20)

    status_colors = {
        "applied": "yellow",
        "screening": "blue",
        "phone": "blue",
        "onsite": "magenta",
        "offer": "green",
        "negotiating": "green bold",
        "accepted": "green bold",
        "rejected": "red",
        "failed": "red dim",
    }

    for i, app in enumerate(apps, 1):
        st = app.get("status", "")
        color = status_colors.get(st, "white")
        table.add_row(
            str(i),
            app.get("applied_at", "")[:10],
            app.get("company", ""),
            app.get("title", ""),
            f"[{color}]{st}[/{color}]",
            app.get("resume_version", "")[:15],
            app.get("follow_up_date", "")[:10],
            (app.get("notes", "") or "")[:20],
        )

    console.print(table)
    console.print(f"\nTotal: {len(apps)} applications")


def show_pending_followups():
    """Show applications that need follow-up."""
    followups = get_pending_followups()
    if not followups:
        console.print("✅ No pending follow-ups.")
        return

    table = Table(title="📩 Pending Follow-ups")
    table.add_column("Company", style="cyan")
    table.add_column("Role")
    table.add_column("Applied")
    table.add_column("Follow-up Due", style="red")

    for f in followups:
        table.add_row(
            f["company"],
            f["title"],
            f["applied_at"][:10],
            f["follow_up_date"],
        )

    console.print(table)


def generate_followup_email(app: dict, attempt: int = 1) -> str:
    """Generate a follow-up email from real application data."""
    company = app.get("company", "the company")
    role = app.get("title", "the position")
    applied_date = app.get("applied_at", "")[:10]

    if attempt == 1:
        return (
            f"Subject: Following up — {role} Application\n\n"
            f"Hi,\n\n"
            f"I submitted my application for the {role} position on {applied_date} "
            f"and wanted to follow up on my candidacy. I remain very interested in "
            f"this opportunity at {company} and would welcome the chance to discuss "
            f"how I can contribute to your team.\n\n"
            f"Please let me know if you need any additional information.\n\n"
            f"Best regards"
        )
    else:
        return (
            f"Subject: Re: {role} Application — Second Follow-up\n\n"
            f"Hi,\n\n"
            f"I wanted to circle back regarding my application for the {role} role. "
            f"I understand hiring processes take time and I remain enthusiastic "
            f"about the opportunity at {company}.\n\n"
            f"If the position has been filled, I would appreciate knowing so I can "
            f"update my records. Otherwise, I would love to connect.\n\n"
            f"Thank you for your time."
        )


def weekly_report():
    """Generate weekly summary report."""
    db = get_db()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    stats = db.execute(
        """SELECT status, COUNT(*) as cnt
           FROM applications WHERE applied_at >= ?
           GROUP BY status""",
        (week_ago,),
    ).fetchall()

    total = db.execute(
        "SELECT COUNT(*) as cnt FROM applications WHERE applied_at >= ?",
        (week_ago,),
    ).fetchone()

    new_jobs = db.execute(
        "SELECT COUNT(*) as cnt FROM jobs WHERE discovered_at >= ?",
        (week_ago,),
    ).fetchone()

    console.print("\n📊 [bold]Weekly Report[/bold]")
    console.print(f"Period: {week_ago} to {datetime.now().strftime('%Y-%m-%d')}")
    console.print(f"Jobs discovered: {new_jobs['cnt']}")
    console.print(f"Applications sent: {total['cnt']}")

    for row in stats:
        console.print(f"  {row['status']}: {row['cnt']}")

    # Response rate
    responded = db.execute(
        """SELECT COUNT(*) as cnt FROM applications
           WHERE applied_at >= ? AND status NOT IN ('applied', 'failed')""",
        (week_ago,),
    ).fetchone()
    rate = (responded["cnt"] / max(total["cnt"], 1)) * 100
    console.print(f"Response rate: {rate:.0f}%")
