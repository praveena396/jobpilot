"""Resume-to-job match analysis: parse a posting, parse a resume, explain the fit."""

from .gaps import Gap, Portfolio, analyze_portfolio, skill_gaps, strengths
from .jd import JobSpec, Requirement, parse_job_description
from .match import MatchResult, SkillMatch, match, suggest_bullets
from .resume import Bullet, Resume, load_resume_text, parse_resume
from .skills import TAXONOMY, category_of, skills_in

__all__ = [
    "TAXONOMY", "Bullet", "Gap", "JobSpec", "MatchResult", "Portfolio", "Requirement",
    "Resume", "SkillMatch", "analyze_portfolio", "category_of", "load_resume_text", "match",
    "parse_job_description", "parse_resume", "skill_gaps", "skills_in", "strengths",
    "suggest_bullets",
]
