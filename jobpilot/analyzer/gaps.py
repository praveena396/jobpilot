"""What to learn next, decided by your own saved jobs rather than by a blog post.

One posting tells you little. Thirty postings you actually want tell you which
single skill would unlock the most of them. `skill_gaps` ranks missing skills by
how many of your saved jobs ask for them, weighting required over preferred and
weighting jobs you already match well, because those are the ones worth closing.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .jd import JobSpec
from .match import MatchResult, match
from .resume import Resume
from .skills import category_of


@dataclass
class Gap:
    skill: str
    category: str
    jobs_wanting: int          # how many saved jobs ask for it
    required_in: int           # ...and list it as required
    share: float               # fraction of saved jobs asking
    impact: float              # ranking score, see skill_gaps
    example_jobs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"skill": self.skill, "category": self.category, "jobs_wanting": self.jobs_wanting,
                "required_in": self.required_in, "share": round(self.share, 3),
                "impact": round(self.impact, 2), "example_jobs": self.example_jobs}


@dataclass
class Portfolio:
    """Every saved job scored against one resume."""

    results: list[tuple[JobSpec, MatchResult]] = field(default_factory=list)

    @property
    def average_score(self) -> float:
        if not self.results:
            return 0.0
        return round(sum(r.score for _, r in self.results) / len(self.results), 1)

    def strong_matches(self, threshold: int = 70) -> list[tuple[JobSpec, MatchResult]]:
        return [(s, r) for s, r in self.results if r.score >= threshold]


def analyze_portfolio(resume: Resume, specs: list[JobSpec]) -> Portfolio:
    return Portfolio(results=[(spec, match(resume, spec)) for spec in specs])


def skill_gaps(portfolio: Portfolio, limit: int = 12) -> list[Gap]:
    """Missing skills ranked by how much learning each would unlock.

    impact = sum over jobs asking for it of (1.0 required / 0.4 preferred)
             x (1 + score/100), so a gap in a job you nearly match counts
             roughly twice a gap in one you do not.
    """
    n = len(portfolio.results)
    if not n:
        return []
    count: dict[str, int] = defaultdict(int)
    required: dict[str, int] = defaultdict(int)
    impact: dict[str, float] = defaultdict(float)
    examples: dict[str, list[str]] = defaultdict(list)

    for spec, result in portfolio.results:
        label = " - ".join(p for p in (spec.title, spec.company) if p) or "Untitled role"
        for m in result.missing:
            count[m.skill] += 1
            required[m.skill] += int(m.required)
            impact[m.skill] += (1.0 if m.required else 0.4) * (1 + result.score / 100)
            if len(examples[m.skill]) < 3:
                examples[m.skill].append(label)

    gaps = [Gap(skill=s, category=category_of(s), jobs_wanting=c, required_in=required[s],
                share=c / n, impact=impact[s], example_jobs=examples[s])
            for s, c in count.items()]
    gaps.sort(key=lambda g: (-g.impact, -g.required_in, g.skill))
    return gaps[:limit]


def strengths(portfolio: Portfolio, limit: int = 10) -> list[dict[str, Any]]:
    """Skills you have that your saved jobs keep asking for: what to lead with."""
    count: dict[str, int] = defaultdict(int)
    required: dict[str, int] = defaultdict(int)
    for _, result in portfolio.results:
        for m in result.matched:
            count[m.skill] += 1
            required[m.skill] += int(m.required)
    n = len(portfolio.results) or 1
    ranked = sorted(count.items(), key=lambda kv: (-required[kv[0]], -kv[1], kv[0]))
    return [{"skill": skill, "category": category_of(skill), "jobs_wanting": jobs,
             "required_in": required[skill], "share": round(jobs / n, 3)}
            for skill, jobs in ranked[:limit]]
