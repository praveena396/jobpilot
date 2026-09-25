# JobPilot — AI Job Auto-Apply Agent

Automated job hunting system: scrapes LinkedIn + job boards, generates ATS-optimized resumes (90+ score, no AI watermarks), and auto-applies via browser automation.

## Quick Start

```bash
# 1. Install
pip install -e ".[dev]"
playwright install chromium

# 2. Initialize config
jobpilot init
# Edit config/settings.yaml with your details

# 3. Import your LinkedIn profile
jobpilot profile "https://linkedin.com/in/your-profile"
# A browser window opens — log into LinkedIn if needed

# 4. Scan for matching jobs
jobpilot scan

# 5. Auto-apply to top matches
jobpilot apply --limit 5

# 6. Run continuous daemon
jobpilot daemon
```

## Commands

| Command | Description |
|---------|-------------|
| `jobpilot init` | Create config from template |
| `jobpilot profile <url>` | Scrape LinkedIn and store profile |
| `jobpilot scan` | Scan all job boards for matches |
| `jobpilot apply [--limit N]` | Auto-apply to top N matched jobs |
| `jobpilot resume [JD_TEXT] -t TITLE -c COMPANY` | Generate a resume for a specific job |
| `jobpilot tracker [STATUS]` | View application tracker |
| `jobpilot followups` | Show pending follow-ups + email drafts |
| `jobpilot report` | Weekly summary |
| `jobpilot daemon` | Continuous scanning + notifications |
| `jobpilot status` | Show current profile & stats |

## How It Works

1. **Profile Import** — Scrapes your LinkedIn profile via Playwright (uses your real browser session)
2. **Job Scanning** — Monitors Greenhouse, Lever, LinkedIn public search
3. **Matching** — Scores jobs against your skills/roles/level/salary/location
4. **Resume Generation** — Creates tailored `.docx` using `python-docx` (no AI text = no watermarks)
   - Mirrors exact JD keywords in your skills section
   - Prioritizes matching skills first
   - Every bullet starts with an action verb + metric
   - Single-column, ATS-parseable format
5. **Auto-Apply** — Fills Greenhouse/Lever/generic forms via Playwright
6. **Tracking** — SQLite database tracks all applications, follow-ups, statuses
7. **Notifications** — Telegram, email, or desktop alerts for new matches

## ATS Score > 90 Strategy

- Keywords extracted from JD and matched against your real skills
- Skills section reordered to front-load JD matches
- Standard section names (`PROFESSIONAL EXPERIENCE`, not creative headers)
- Single-column layout, Calibri font, no tables/graphics
- File naming: `FirstName_LastName_Role_Company.docx`

## No AI Watermarks

The resume generator uses **zero AI-generated text**. All content comes from:
- Your actual LinkedIn profile data
- Your config file achievements/skills
- Structural templates (action verbs, section headers)
- JD keyword integration into your existing content

## Config

Edit `config/settings.yaml`:
- Profile details (skills, target roles, salary, location)
- Job search parameters (match threshold, sources, blacklist)
- Notification settings (Telegram bot token, email SMTP)
- AI settings (only used if you want AI to rewrite bullets — optional)

## Job Sources

- **Greenhouse** — stripe, databricks, anthropic, openai, figma, notion, airbnb, coinbase, discord, plaid, ramp
- **Lever** — netflix
- **LinkedIn** — public job search (no API key needed)

Add more companies by editing `GREENHOUSE_COMPANIES` / `LEVER_COMPANIES` in `jobpilot/scraper/jobs.py`.
