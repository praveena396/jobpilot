"""Notification system — Telegram, Email, Desktop."""

import asyncio
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

from jobpilot import get
from jobpilot.scraper.jobs import JobListing


def format_job_alert(job: JobListing) -> str:
    comp_str = ""
    if job.comp_min and job.comp_max:
        comp_str = f"${job.comp_min:,}-${job.comp_max:,} TC"
    elif job.comp_max:
        comp_str = f"Up to ${job.comp_max:,} TC"
    else:
        comp_str = "Comp not listed"

    delay = get("notifications.auto_apply_delay_minutes", 30)

    return (
        f"🔔 NEW MATCH — Score: {job.match_score}/100\n"
        f"Company: {job.company}\n"
        f"Role: {job.title} ({job.level})\n"
        f"Location: {job.location}\n"
        f"Source: {job.source}\n"
        f"Link: {job.url}\n"
        f"⚡ Auto-applying in {delay} min unless you say STOP"
    )


async def send_notification(message: str):
    method = get("notifications.method", "desktop")
    if not get("notifications.enabled", True):
        return

    if method == "telegram":
        await _send_telegram(message)
    elif method == "email":
        _send_email(message)
    else:
        _send_desktop(message)


async def _send_telegram(message: str):
    token = get("notifications.telegram.bot_token", "")
    chat_id = get("notifications.telegram.chat_id", "")
    if not token or not chat_id:
        print("⚠️  Telegram not configured. Set bot_token and chat_id in config.")
        return

    import httpx

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
        except httpx.HTTPError as e:
            print(f"Telegram error: {e}")


def _send_email(message: str):
    host = get("notifications.email.smtp_host", "")
    port = get("notifications.email.smtp_port", 587)
    user = get("notifications.email.username", "")
    password = get("notifications.email.password", "")
    to_addr = get("notifications.email.to_address", "")

    if not all([host, user, password, to_addr]):
        print("⚠️  Email not configured.")
        return

    msg = MIMEText(message)
    msg["Subject"] = "JobPilot — New Job Match"
    msg["From"] = user
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Email error: {e}")


def _send_desktop(message: str):
    """Desktop notification fallback — prints to console."""
    print(f"\n{'='*60}")
    print(message)
    print(f"{'='*60}\n")


async def notify_matched_jobs(jobs: list[JobListing]):
    """Send notifications for all matched jobs."""
    for job in jobs[:10]:  # cap notifications
        msg = format_job_alert(job)
        await send_notification(msg)
