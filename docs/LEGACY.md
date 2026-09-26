# Legacy modules: scraper and auto-apply

`jobpilot/scraper/` and `jobpilot/auto_apply.py` predate the match analyzer. They
are kept for reference and are not used by it.

**They are not recommended, for two practical reasons.**

**The LinkedIn scraper risks the account you are job hunting with.** It drives a
logged-in browser session against LinkedIn. That is against their terms, it is
detectable, and the account at risk is the one you need.

**Automated form submission is worse than useless on an application.** Most job
boards prohibit it, and a hiring manager who learns an application was submitted by
a bot has been given a reason to say no. The `fake-useragent` dependency exists to
evade detection, which is a poor thing to have on a portfolio project.

The parts worth keeping — matching, requirement extraction, tracking — were rebuilt
properly in `jobpilot/analyzer/`, working only on text you supply yourself.

If you want them gone entirely:

```bash
git rm -r jobpilot/scraper jobpilot/auto_apply.py tests/test_entry_level_jobs.py
```
