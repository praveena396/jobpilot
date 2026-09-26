"""Read a resume into sections and bullets, and index where each skill appears.

The point is evidence. "You match Python" is not useful; "you match Python —
'Built a real-time pipeline in Python asyncio', Experience' is. So the resume is
kept as a list of `Bullet`s, each knowing its section, and each skill is indexed
back to the bullets that mention it.

Input is plain text. `.docx` and `.pdf` are converted by `load_resume_text`
when the optional libraries are installed.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .skills import IMPLIES, find_skills, skills_in

SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("summary", re.compile(r"^\W*(summary|objective|profile|about)\b", re.I)),
    ("experience", re.compile(r"^\W*(experience|employment|work history|professional)\b", re.I)),
    ("projects", re.compile(r"^\W*(projects?|personal projects?|portfolio)\b", re.I)),
    ("education", re.compile(r"^\W*(education|academics?)\b", re.I)),
    ("skills", re.compile(r"^\W*(skills?|technical skills?|technologies|tech stack)\b", re.I)),
    ("certifications", re.compile(r"^\W*(certification|certificates?|awards?|honors?)\b", re.I)),
]
BULLET_PREFIX = re.compile(r"^\s*(?:[-*•·‣▪]|\d+[.)])\s+")
# "Jan 2023 - Present", "2021-2024", "06/2022 – 08/2023"
DATE_RANGE = re.compile(
    r"(?P<start>(?:\w{3,9}\.?\s+)?(?:\d{1,2}/)?(?P<sy>(?:19|20)\d{2}))\s*(?:-|–|—|to)\s*"
    r"(?P<end>present|current|now|(?:\w{3,9}\.?\s+)?(?:\d{1,2}/)?(?P<ey>(?:19|20)\d{2}))",
    re.IGNORECASE)
METRIC = re.compile(r"(\d+(?:\.\d+)?\s*(?:%|percent|x\b|k\b|m\b|ms\b|s\b|/s\b)|\$\s?\d|\b\d{3,}\b)")


@dataclass(frozen=True)
class Bullet:
    """One line of the resume, and where it sits."""

    text: str
    section: str
    line_no: int

    @property
    def has_metric(self) -> bool:
        return bool(METRIC.search(self.text))


@dataclass
class Resume:
    name: str = ""
    raw_text: str = ""
    bullets: list[Bullet] = field(default_factory=list)
    # canonical skill -> the bullets that mention it
    skill_evidence: dict[str, list[Bullet]] = field(default_factory=dict)
    years_experience: float | None = None
    degree: str | None = None
    # skill -> the skill that implied it, when it was never stated directly
    implied_from: dict[str, str] = field(default_factory=dict)

    @property
    def skills(self) -> set[str]:
        return set(self.skill_evidence)

    def evidence_for(self, skill: str, limit: int = 3) -> list[Bullet]:
        """The strongest bullets naming `skill`: real experience first, then metrics."""
        rank = {"experience": 0, "projects": 1, "summary": 2, "skills": 4, "education": 3}
        found = self.skill_evidence.get(skill, [])
        return sorted(found, key=lambda b: (rank.get(b.section, 5), not b.has_metric,
                                            -len(b.text)))[:limit]


def _section_of(line: str) -> str | None:
    """The section a heading line starts, or None if it isn't a heading."""
    stripped = line.strip().rstrip(":")
    if not stripped or len(stripped) > 40 or BULLET_PREFIX.match(line):
        return None
    # A heading is short and has few words; "Skills: Python, Go" is not one.
    if len(stripped.split()) > 4:
        return None
    for name, pattern in SECTION_PATTERNS:
        if pattern.match(stripped):
            return name
    return None


def estimate_years(text: str, today_year: int = 2026) -> float | None:
    """Total years covered by date ranges, merging overlaps so they aren't double counted."""
    spans: list[tuple[int, int]] = []
    for m in DATE_RANGE.finditer(text):
        start = int(m.group("sy"))
        end_raw = m.group("end").lower()
        end = today_year if end_raw in {"present", "current", "now"} else int(m.group("ey") or 0)
        if end and end >= start and (end - start) <= 50:
            spans.append((start, end))
    if not spans:
        return None
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    total = sum(e - s for s, e in merged)
    return float(total) if total else None


def parse_resume(text: str, name: str = "") -> Resume:
    """Read resume text into sections, bullets and a skill index."""
    resume = Resume(name=name, raw_text=text)
    section = "summary"
    evidence: dict[str, list[Bullet]] = defaultdict(list)

    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line:
            continue
        found = _section_of(line)
        if found:
            section = found
            continue
        body = BULLET_PREFIX.sub("", line).strip()
        if len(body) < 3:
            continue
        bullet = Bullet(text=body, section=section, line_no=i)
        resume.bullets.append(bullet)
        for skill in skills_in(body):
            evidence[skill].append(bullet)

    # A FastAPI bullet is also evidence of REST APIs. Implied evidence is added
    # only where the resume never states the skill directly, so direct wording
    # always wins when ranking bullets.
    implied: dict[str, list[Bullet]] = defaultdict(list)
    for skill, bullets in evidence.items():
        for target in IMPLIES.get(skill, ()):
            if target not in evidence:
                implied[target].extend(bullets)
                resume.implied_from.setdefault(target, skill)
    for target, bullets in implied.items():
        evidence[target] = bullets

    resume.skill_evidence = dict(evidence)
    resume.years_experience = estimate_years(text)
    from .jd import extract_degree  # local import: jd imports nothing from here
    resume.degree, _ = extract_degree(text)
    return resume


def load_resume_text(path: str | Path) -> str:
    """Read a resume from .txt, .md, .docx or .pdf."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in {".txt", ".md", ""}:
        return p.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as e:  # pragma: no cover - depends on optional install
            raise RuntimeError("reading .docx needs python-docx: pip install python-docx") from e
        doc = Document(str(p))
        parts = [para.text for para in doc.paragraphs]
        for table in doc.tables:
            parts += [cell.text for row in table.rows for cell in row.cells]
        return "\n".join(parts)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:  # pragma: no cover - depends on optional install
            raise RuntimeError("reading .pdf needs pypdf: pip install pypdf") from e
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)
    raise ValueError(f"unsupported resume format {suffix!r}; use .txt, .md, .docx or .pdf")


def highlight_skills(text: str) -> list[dict[str, object]]:
    """Skill mentions with offsets, so a UI can highlight the resume."""
    return [{"skill": h.skill, "start": h.start, "end": h.end, "text": text[h.start:h.end]}
            for h in find_skills(text)]
