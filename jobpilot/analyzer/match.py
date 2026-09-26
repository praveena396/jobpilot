"""Score a resume against a job spec, and explain every point.

The score is a weighted coverage ratio, not a bag of keywords:

    skill fit = sum(weight of matched requirements) / sum(weight of all requirements)

where a required skill weighs 1.0, a preferred one 0.4, and asking for a number
of years multiplies by 1.25. Experience and degree are separate components, so
a missing year of experience never looks like a missing skill.

Every matched skill carries the resume bullets that prove it, and every missing
one carries the sentence in the posting that asked for it. A score you cannot
explain is not worth showing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .jd import JobSpec, Requirement
from .resume import Bullet, Resume
from .skills import category_of

# Component weights of the overall score.
W_SKILLS, W_EXPERIENCE, W_DEGREE = 0.75, 0.15, 0.10


@dataclass
class SkillMatch:
    """One requirement, and whether the resume answers it."""

    skill: str
    category: str
    required: bool
    matched: bool
    years_wanted: int | None = None
    evidence: list[str] = field(default_factory=list)   # resume bullets that prove it
    asked_in: str = ""                                  # the posting's own sentence
    implied_by: str = ""                                # set when never stated directly

    @property
    def weight(self) -> float:
        return Requirement(self.skill, self.required, self.years_wanted).weight


@dataclass
class MatchResult:
    score: int                       # 0-100 overall
    skill_score: int                 # 0-100 skills only
    experience_score: int
    degree_score: int
    matches: list[SkillMatch] = field(default_factory=list)
    extra_skills: list[str] = field(default_factory=list)   # yours, not asked for
    notes: list[str] = field(default_factory=list)          # plain-language findings
    verdict: str = ""

    @property
    def matched(self) -> list[SkillMatch]:
        return [m for m in self.matches if m.matched]

    @property
    def missing(self) -> list[SkillMatch]:
        return [m for m in self.matches if not m.matched]

    @property
    def missing_required(self) -> list[SkillMatch]:
        return [m for m in self.missing if m.required]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["matched_count"] = len(self.matched)
        d["missing_required_count"] = len(self.missing_required)
        d["total_requirements"] = len(self.matches)
        return d


def _verdict(score: int, missing_required: int) -> str:
    if score >= 75 and missing_required == 0:
        return "Strong match — apply, and mirror their wording in your resume."
    if score >= 60:
        return "Good match — worth applying; close the gaps below in your bullets."
    if score >= 40:
        return "Partial match — apply only if the role interests you; expect competition."
    return "Weak match — the posting asks for things your resume does not show."


def match(resume: Resume, spec: JobSpec) -> MatchResult:
    """Compare one resume with one posting and explain the result."""
    matches: list[SkillMatch] = []
    for req in spec.requirements:
        evidence = [b.text for b in resume.evidence_for(req.skill)]
        matches.append(SkillMatch(
            skill=req.skill, category=category_of(req.skill), required=req.required,
            matched=bool(evidence), years_wanted=req.years,
            evidence=evidence, asked_in=req.source,
            implied_by=resume.implied_from.get(req.skill, "")))

    total_w = sum(m.weight for m in matches)
    got_w = sum(m.weight for m in matches if m.matched)
    # No parseable requirements: report 0 rather than a misleading 100.
    skill_score = int(round(100 * got_w / total_w)) if total_w else 0

    # Experience: full marks when the posting asks for nothing, or you meet it.
    if not spec.min_years:
        experience_score = 100
    elif resume.years_experience is None:
        experience_score = 50          # unknown, not zero: dates may be unparseable
    else:
        experience_score = int(round(100 * min(resume.years_experience / spec.min_years, 1.0)))

    rank = {"bachelor": 1, "master": 2, "phd": 3}
    if spec.degree is None:
        degree_score = 100
    elif resume.degree is None:
        degree_score = 50
    else:
        degree_score = 100 if rank.get(resume.degree, 0) >= rank.get(spec.degree, 0) else 40

    overall = int(round(W_SKILLS * skill_score + W_EXPERIENCE * experience_score
                        + W_DEGREE * degree_score))

    notes: list[str] = []
    if spec.min_years and resume.years_experience is not None:
        if resume.years_experience + 0.01 < spec.min_years:
            notes.append(f"Asks for {spec.min_years}+ years; your resume shows about "
                         f"{resume.years_experience:g}. Many postings treat this as a guide, "
                         f"so apply anyway if the skills line up.")
        else:
            notes.append(f"Meets the {spec.min_years}+ years of experience asked for.")
    if spec.min_years and resume.years_experience is None:
        notes.append(f"Asks for {spec.min_years}+ years, but no date ranges were found in your "
                     f"resume — check your dates are written like 'Jan 2024 - Present'.")
    if spec.degree and resume.degree and rank.get(resume.degree, 0) < rank.get(spec.degree, 0):
        notes.append(f"Asks for a {spec.degree}'s degree; your resume shows a {resume.degree}'s.")

    missing_req = [m.skill for m in matches if not m.matched and m.required]
    if missing_req:
        notes.append("Missing required: " + ", ".join(missing_req[:6])
                     + (f" and {len(missing_req) - 6} more" if len(missing_req) > 6 else ""))

    inferred = [m for m in matches if m.matched and m.implied_by]
    if inferred:
        notes.append("Inferred, not stated: "
                     + ", ".join(f"{m.skill} (from {m.implied_by})" for m in inferred[:4])
                     + ". Keyword screens look for the exact words, so say them outright.")

    weak = [m.skill for m in matches if m.matched and not m.implied_by
            and all(b.section == "skills" for b in resume.evidence_for(m.skill))]
    if weak:
        notes.append("Only listed in your skills section, with no experience bullet behind it: "
                     + ", ".join(weak[:5])
                     + ". Add a bullet showing where you used each one.")

    asked = {m.skill for m in matches}
    extra = sorted(s for s in resume.skills if s not in asked)

    return MatchResult(score=overall, skill_score=skill_score,
                       experience_score=experience_score, degree_score=degree_score,
                       matches=matches, extra_skills=extra, notes=notes,
                       verdict=_verdict(overall, len(missing_req)))


def suggest_bullets(resume: Resume, result: MatchResult, limit: int = 5) -> list[dict[str, str]]:
    """Which resume bullet to put against which requirement, and why.

    This never writes new experience. It points at a bullet you already have
    and at the posting's wording, so you can align the two honestly.
    """
    out: list[dict[str, str]] = []
    for m in sorted(result.matched, key=lambda m: (not m.required, m.skill)):
        best: Bullet | None = next(iter(resume.evidence_for(m.skill, limit=1)), None)
        if best is None or best.section == "skills":
            continue
        out.append({
            "skill": m.skill,
            "they_asked": m.asked_in.strip(),
            "your_evidence": best.text,
            "why": f"Your {best.section} bullet already shows {m.skill}; use their wording "
                   f"for it so keyword screens match.",
        })
        if len(out) >= limit:
            break
    return out
