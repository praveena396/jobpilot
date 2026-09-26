"""Command line for the match analyzer, for when a browser is overkill.

    jobpilot-match resume my_resume.pdf            # save and activate a resume
    jobpilot-match score job.txt                   # score a posting, explain it
    jobpilot-match save job.txt -t "SWE" -c Acme   # save it to the tracker
    jobpilot-match list [--stage applied]
    jobpilot-match stage 3 applied
    jobpilot-match insights
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .gaps import analyze_portfolio, skill_gaps, strengths
from .jd import parse_job_description
from .match import match, suggest_bullets
from .resume import load_resume_text, parse_resume
from .store import STAGES, NotFoundError, Store


def _read(path: str) -> str:
    return load_resume_text(path) if Path(path).exists() else path


def _print_report(result, spec) -> None:  # type: ignore[no-untyped-def]
    print(f"\n  SCORE {result.score}/100   {result.verdict}")
    print(f"  skills {result.skill_score} | experience {result.experience_score} "
          f"| education {result.degree_score}")
    if spec.min_years:
        print(f"  asks for {spec.min_years}+ years")
    print(f"\n  MATCHED ({len(result.matched)})")
    for m in result.matched:
        tag = "required" if m.required else "preferred"
        extra = f"  [inferred from {m.implied_by}]" if m.implied_by else ""
        print(f"    + {m.skill:22} {tag}{extra}")
        if m.evidence:
            print(f"        your resume: {m.evidence[0][:88]}")
    print(f"\n  MISSING ({len(result.missing)})")
    for m in result.missing:
        print(f"    - {m.skill:22} {'REQUIRED' if m.required else 'preferred'}")
        if m.asked_in:
            print(f"        they asked: {m.asked_in[:88]}")
    if result.notes:
        print("\n  NOTES")
        for n in result.notes:
            print(f"    * {n}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jobpilot-match", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", help="SQLite path (default: data/jobpilot.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resume", help="save and activate a resume")
    r.add_argument("path", help=".txt, .md, .docx or .pdf")
    r.add_argument("-l", "--label", default="")

    s = sub.add_parser("score", help="score a posting without saving it")
    s.add_argument("path", help="a file, or the text itself")

    sv = sub.add_parser("save", help="save a posting to the tracker and score it")
    sv.add_argument("path")
    sv.add_argument("-t", "--title", default="")
    sv.add_argument("-c", "--company", default="")
    sv.add_argument("-u", "--url", default="")

    ls = sub.add_parser("list", help="list saved postings")
    ls.add_argument("--stage", choices=STAGES)

    st = sub.add_parser("stage", help="move a posting to a stage")
    st.add_argument("id", type=int)
    st.add_argument("stage", choices=STAGES)
    st.add_argument("-n", "--notes", default=None)

    sub.add_parser("insights", help="what your saved jobs say to learn next")

    a = p.parse_args(argv)
    store = Store.open(a.db)
    try:
        if a.cmd == "resume":
            text = load_resume_text(a.path)
            rid = store.add_resume(a.label or Path(a.path).stem, text)
            parsed = parse_resume(text)
            print(f"saved resume {rid} ({a.label or Path(a.path).stem}), now active")
            years = (f", about {parsed.years_experience:g} years"
                     if parsed.years_experience else "")
            print(f"  {len(parsed.bullets)} bullets, {len(parsed.skills)} skills{years}")
            print("  " + ", ".join(sorted(parsed.skills)))
            return 0

        if a.cmd in {"score", "save"}:
            text = _read(a.path)
            title = getattr(a, "title", "")
            company = getattr(a, "company", "")
            active = store.active_resume()
            if active is None:
                print("no resume saved yet: run `jobpilot-match resume <file>` first")
                return 1
            spec = parse_job_description(text, title, company)
            resume = parse_resume(active["text"], active["label"])
            result = match(resume, spec)
            if a.cmd == "save":
                pid = store.add_posting(text, title, company, url=a.url)
                store.analyze(pid, refresh=True)
                print(f"saved posting {pid}")
            _print_report(result, spec)
            tips = suggest_bullets(resume, result)
            if tips:
                print("\n  LEAD WITH")
                for t in tips:
                    print(f"    {t['skill']}: {t['your_evidence'][:84]}")
            return 0

        if a.cmd == "list":
            rows = store.list_postings(a.stage)
            if not rows:
                print("nothing saved")
                return 0
            print(f"{'id':>4}  {'score':>5}  {'stage':<10} title")
            for row in rows:
                score = "-" if row["score"] is None else str(row["score"])
                label = " · ".join(x for x in (row["title"], row["company"]) if x) or "untitled"
                print(f"{row['id']:>4}  {score:>5}  {row['stage']:<10} {label}")
            return 0

        if a.cmd == "stage":
            row = store.set_stage(a.id, a.stage, a.notes)
            print(f"posting {a.id} -> {row['stage']}")
            return 0

        if a.cmd == "insights":
            resume, specs = store.specs_and_resume()
            if not specs:
                print("save some postings first")
                return 0
            portfolio = analyze_portfolio(resume, specs)
            print(f"{len(specs)} jobs, average match {portfolio.average_score}, "
                  f"{len(portfolio.strong_matches())} strong (75+)\n")
            print("LEARN NEXT")
            for g in skill_gaps(portfolio):
                print(f"  {g.skill:22} wanted by {g.jobs_wanting}/{len(specs)} "
                      f"({g.share:.0%}), required in {g.required_in}")
            print("\nLEAD WITH")
            for row in strengths(portfolio):
                print(f"  {row['skill']:22} {row['jobs_wanting']} jobs, "
                      f"required in {row['required_in']}")
            return 0
    except NotFoundError as e:
        print(f"not found: {e}")
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
