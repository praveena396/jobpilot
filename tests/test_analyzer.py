"""Tests for the resume-to-job match analyzer."""
import pytest

from jobpilot.analyzer import (
    analyze_portfolio,
    match,
    parse_job_description,
    parse_resume,
    skill_gaps,
    strengths,
    suggest_bullets,
)
from jobpilot.analyzer.jd import extract_degree, extract_years
from jobpilot.analyzer.resume import estimate_years
from jobpilot.analyzer.skills import skills_in

JD = """Software Engineer (New Grad)

Requirements:
- B.S. in Computer Science or related field
- 2+ years of software development experience
- Strong experience with Python and PostgreSQL
- Knowledge of debugging, testing and version control systems (Git preferred)

Preferred qualifications:
- Experience with Kubernetes and AWS
- Must have familiarity with robotics

Responsibilities:
- Work with Docker daily
"""

RESUME = """Praveena Ganesan

Summary
Software engineer working in Python and distributed systems.

Experience
Software Engineer, Acme Corp    Jan 2024 - Present
- Built a real-time telemetry pipeline in Python asyncio sustaining 85k events/s
- Wrote unit tests with pytest and set up CI/CD in GitHub Actions

Education
B.S. in Computer Science, 2023

Skills
Python, PostgreSQL, Kubernetes, Git
"""


# ---------------- skills ----------------
@pytest.mark.parametrize("text, expected", [
    ("We use K8s and Golang", {"Kubernetes", "Go"}),
    ("Strong C++ and C# skills", {"C++", "C#"}),
    ("Experience with .NET", {".NET"}),
    ("node.js and Express", {"Node.js", "Express"}),
    ("machine learning models", {"Machine Learning"}),
    ("asyncio and concurrency", {"Distributed Systems"}),
])
def test_skill_aliases_map_to_one_canonical_name(text, expected):
    assert expected <= skills_in(text)


def test_punctuation_skills_are_not_missed_by_word_boundaries():
    # \b fails after "+", so C++ needs its own boundary rule
    assert "C++" in skills_in("proficient in C++.")
    assert "C#" in skills_in("(C#)")


def test_longer_alias_wins_over_substring():
    found = skills_in("machine learning pipelines")
    assert "Machine Learning" in found


# ---------------- job description parsing ----------------
def test_required_and_preferred_sections():
    spec = parse_job_description(JD, "SWE", "Acme")
    assert {"Python", "PostgreSQL"} <= set(spec.required_skills)
    # a "must have" inside a Preferred heading is still preferred
    assert "Robotics" in spec.preferred_skills
    assert {"Kubernetes", "AWS"} <= set(spec.preferred_skills)


def test_parenthetical_preferred_does_not_demote_the_whole_line():
    spec = parse_job_description(JD)
    assert "Testing" in spec.required_skills
    assert "Debugging" in spec.required_skills


def test_years_and_degree():
    spec = parse_job_description(JD)
    assert spec.min_years == 2
    assert spec.degree == "bachelor"
    assert extract_years("at least three years") == 3
    assert extract_years("3-5 years") == 3
    assert extract_years("no numbers here") is None


def test_zero_lower_bound_is_not_a_minimum():
    # "0-2 years" means new grads welcome, not "requires 0 years"
    assert extract_years("0-2 years of experience") is None
    spec = parse_job_description("Requirements:\n- 0-2 years of Python experience")
    assert spec.min_years is None


def test_lowest_degree_wins():
    level, field = extract_degree(
        "Master's degree preferred; Bachelor's in Computer Science required")
    assert level == "bachelor" and field and "Computer Science" in field


def test_responsibilities_are_not_required_skills():
    spec = parse_job_description(JD)
    assert "Docker" not in spec.required_skills


def test_requirements_keep_the_sentence_they_came_from():
    spec = parse_job_description(JD)
    python = next(r for r in spec.requirements if r.skill == "Python")
    assert "Python" in python.source


# ---------------- resume parsing ----------------
def test_resume_sections_and_evidence():
    resume = parse_resume(RESUME)
    assert resume.degree == "bachelor"
    evidence = resume.evidence_for("Python")
    assert evidence and evidence[0].section == "experience"      # experience beats the skills list
    assert "telemetry" in evidence[0].text


def test_estimate_years_merges_overlapping_ranges():
    assert estimate_years("2020 - 2024", today_year=2026) == 4.0
    # two overlapping jobs are not four years
    assert estimate_years("Jan 2020 - 2023\nMar 2021 - 2024", today_year=2026) == 4.0
    assert estimate_years("no dates") is None


def test_present_counts_to_today():
    assert estimate_years("Jan 2024 - Present", today_year=2026) == 2.0


# ---------------- matching ----------------
def test_match_explains_every_requirement():
    result = match(parse_resume(RESUME), parse_job_description(JD, "SWE", "Acme"))
    assert 0 <= result.score <= 100
    matched = {m.skill for m in result.matched}
    assert {"Python", "PostgreSQL"} <= matched
    assert "AWS" in {m.skill for m in result.missing}
    python = next(m for m in result.matches if m.skill == "Python")
    assert python.evidence and python.asked_in          # proof on both sides
    assert result.verdict


def test_required_gaps_weigh_more_than_preferred_gaps():
    # Same two skills either way: having the required one must score higher
    # than having only the preferred one.
    jd = ("Requirements:\n- Strong experience with Python\n"
          "Preferred qualifications:\n- Experience with Rust\n")
    has_required = match(parse_resume("Experience\n- Shipped a service in Python"),
                         parse_job_description(jd))
    has_preferred = match(parse_resume("Experience\n- Shipped a service in Rust"),
                          parse_job_description(jd))
    assert has_required.score > has_preferred.score
    assert has_required.skill_score == 71 and has_preferred.skill_score == 29


def test_skill_only_in_skills_section_is_flagged_as_weak():
    result = match(parse_resume(RESUME), parse_job_description(JD))
    assert any("no experience bullet" in n for n in result.notes)


def test_no_requirements_scores_zero_not_full():
    result = match(parse_resume(RESUME), parse_job_description("We are a great company."))
    assert result.skill_score == 0


def test_unknown_resume_experience_is_not_zero():
    spec = parse_job_description("Requirements:\n- 5+ years of Python experience")
    result = match(parse_resume("Skills\nPython"), spec)   # no dates in the resume
    assert result.experience_score == 50
    assert any("date ranges" in n for n in result.notes)


def test_suggestions_point_at_real_bullets_only():
    resume = parse_resume(RESUME)
    result = match(resume, parse_job_description(JD))
    for s in suggest_bullets(resume, result):
        assert s["your_evidence"] in RESUME          # never invents experience
        assert s["they_asked"]


# ---------------- portfolio gaps ----------------
def test_gaps_rank_by_how_many_jobs_want_the_skill():
    resume = parse_resume("Skills\nPython")
    specs = [parse_job_description("Requirements:\n- Strong experience with AWS", f"Job {i}")
             for i in range(3)]
    specs.append(parse_job_description("Requirements:\n- Strong experience with Rust", "Job 4"))
    gaps = skill_gaps(analyze_portfolio(resume, specs))
    assert gaps[0].skill == "AWS" and gaps[0].jobs_wanting == 3
    assert gaps[0].share == 0.75 and gaps[0].example_jobs


def test_strengths_are_skills_you_have_that_jobs_ask_for():
    resume = parse_resume(RESUME)
    specs = [parse_job_description(JD, "A"), parse_job_description(JD, "B")]
    top = strengths(analyze_portfolio(resume, specs))
    names = {row["skill"] for row in top}
    assert {"Python", "PostgreSQL"} <= names
    assert all(row["jobs_wanting"] == 2 for row in top)      # both jobs ask for each
    assert top[0]["required_in"] >= top[-1]["required_in"]   # required skills lead


def test_empty_portfolio_is_safe():
    assert skill_gaps(analyze_portfolio(parse_resume(RESUME), [])) == []


# ---------------- implied skills ----------------
def test_framework_implies_the_thing_it_is():
    resume = parse_resume("Experience\n- Shipped a FastAPI service for payments")
    assert {"FastAPI", "REST APIs", "Python"} <= resume.skills
    assert resume.implied_from["REST APIs"] == "FastAPI"
    assert resume.evidence_for("REST APIs")[0].text.startswith("Shipped a FastAPI")


def test_implication_does_not_override_a_direct_mention():
    resume = parse_resume(
        "Experience\n- Shipped a FastAPI service\n- Designed REST APIs for the mobile app")
    assert "REST APIs" not in resume.implied_from       # stated outright, so not inferred
    assert resume.evidence_for("REST APIs")[0].text.startswith("Designed REST APIs")


def test_implied_match_is_flagged_so_you_can_say_it_outright():
    resume = parse_resume("Experience\n- Shipped a FastAPI service for payments")
    result = match(resume, parse_job_description("Requirements:\n- Experience building REST APIs"))
    rest = next(m for m in result.matches if m.skill == "REST APIs")
    assert rest.matched and rest.implied_by == "FastAPI"
    assert any("Inferred, not stated" in n for n in result.notes)


def test_implications_are_not_guesses_about_related_fields():
    from jobpilot.analyzer.skills import implied_by
    # knowing Kubernetes says nothing about which cloud you used
    assert "AWS" not in implied_by("Kubernetes")
    assert implied_by("Kubernetes") == ("Docker",)
