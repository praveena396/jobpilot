"""Turn a job description into structured requirements.

A posting is prose, but hiring decisions are made against a list. This module
produces that list: one `Requirement` per skill, marked required or preferred,
with the years asked for and the sentence it came from, so every later claim
can be traced back to the posting's own words.

Two signals decide required vs preferred, in order:
1. The section heading the line sits under ("Requirements" vs "Nice to have").
2. The wording of the line itself ("must have" vs "bonus", "familiarity with").
Heading wins, because a "Preferred qualifications" list full of "must" is still
preferred.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .skills import find_skills

# Headings that flip the section we are reading.
REQUIRED_HEADINGS = re.compile(
    r"^\W*(?:minimum|basic|required|requirements?|qualifications?|what you(?:'ll| will)? need|"
    r"who you are|must have|essential|we(?:'re| are) looking for|skills? (?:and|&) experience)\b",
    re.IGNORECASE)
PREFERRED_HEADINGS = re.compile(
    r"^\W*(?:preferred|nice[- ]to[- ]have|bonus|plus(?:es)?|desired|desirable|good to have|"
    r"additional|a plus|optional|ideal(?:ly)?|extra credit|you might also)\b",
    re.IGNORECASE)
# Headings that end a requirements list (so duties aren't read as requirements).
OTHER_HEADINGS = re.compile(
    r"^\W*(?:responsibilities|what you(?:'ll| will)? do|the role|about (?:us|the|our)|"
    r"benefits?|perks?|compensation|salary|equal opportunity|our mission|why (?:you|join))\b",
    re.IGNORECASE)

PREFERRED_PHRASES = re.compile(
    r"\b(?:nice to have|bonus|a plus|preferred|desirable|would be great|ideally|"
    r"familiarity with|exposure to|some experience|willingness to learn|openness to)\b",
    re.IGNORECASE)
REQUIRED_PHRASES = re.compile(
    r"\b(?:must have|must be|required|require[sd]?|strong (?:experience|background|knowledge)|"
    r"proficien\w+|expert(?:ise)?|solid (?:experience|understanding)|demonstrated|proven|"
    r"deep (?:experience|knowledge|understanding))\b",
    re.IGNORECASE)

# "3+ years", "3-5 years", "at least 2 years", "two years"
YEARS = re.compile(
    r"(?:(?P<lo>\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(?P<hi>\d{1,2})?\s*\+?\s*(?:years?|yrs?)|"
    r"(?P<word>one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:years?|yrs?))",
    re.IGNORECASE)
WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

DEGREE_LEVEL = re.compile(
    r"\b(?P<level>bachelor'?s?|b\.?s\.?|b\.?tech|master'?s?|m\.?s\.?|m\.?tech|ph\.?d\.?|doctorate)\b",
    re.IGNORECASE)
# "in Computer Science" immediately after a degree, stopping at punctuation so
# it cannot run on into the rest of the sentence.
DEGREE_FIELD = re.compile(r"[\s.,:;-]*(?:degree\s*)?\b(?:in|of)\b\s+(?P<field>[A-Za-z /&+-]{3,50})",
                          re.IGNORECASE)
FIELD_TAIL = re.compile(r"\s+(?:or|and|is|are|required|preferred|with|from|equivalent)\b.*$",
                        re.IGNORECASE)
DEGREE_RANK = {"bachelor": 1, "master": 2, "phd": 3}


@dataclass(frozen=True)
class Requirement:
    """One skill the posting asks for, and the evidence it asked."""

    skill: str
    required: bool
    years: int | None = None
    source: str = ""          # the sentence it came from, for traceability

    @property
    def weight(self) -> float:
        """Required requirements count more, and asking for years counts more."""
        base = 1.0 if self.required else 0.4
        return base * (1.25 if self.years else 1.0)


@dataclass
class JobSpec:
    """Everything structured that we could read out of one posting."""

    title: str = ""
    company: str = ""
    requirements: list[Requirement] = field(default_factory=list)
    min_years: int | None = None
    degree: str | None = None          # "bachelor" | "master" | "phd"
    degree_field: str | None = None
    raw_text: str = ""

    @property
    def required_skills(self) -> list[str]:
        return [r.skill for r in self.requirements if r.required]

    @property
    def preferred_skills(self) -> list[str]:
        return [r.skill for r in self.requirements if not r.required]


def _preferred_parentheticals(line: str) -> list[tuple[int, int]]:
    """Spans of bracketed text that themselves say "preferred", "optional", etc."""
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\(([^()]*)\)", line):
        if PREFERRED_PHRASES.search(m.group(1)):
            spans.append((m.start(), m.end()))
    return spans


def _lines(text: str) -> list[str]:
    """Split into lines, then into sentences, keeping bullet lines whole."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # A bullet is one unit even with internal full stops ("Node.js").
        if re.match(r"^\s*(?:[-*•·‣▪]|\d+[.)])\s+", line):
            out.append(re.sub(r"^\s*(?:[-*•·‣▪]|\d+[.)])\s+", "", line))
            continue
        out.extend(s.strip() for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z])", line) if s.strip())
    return out


def extract_years(text: str) -> int | None:
    """The smallest number of years asked for in `text` ("3-5 years" -> 3).

    "0-2 years" means no minimum, so a zero lower bound reads as None rather
    than as a requirement of zero.
    """
    found: list[int] = []
    for m in YEARS.finditer(text):
        if m.group("word"):
            found.append(WORD_NUMBERS[m.group("word").lower()])
        elif m.group("lo"):
            found.append(int(m.group("lo")))
    smallest = min(found) if found else None
    return smallest if smallest else None


def extract_degree(text: str) -> tuple[str | None, str | None]:
    """The lowest degree the posting accepts, and its field if stated."""
    best: tuple[int, str, str | None] | None = None
    for m in DEGREE_LEVEL.finditer(text):
        raw = m.group("level").lower().replace(".", "").replace("'", "")
        if raw.startswith(("bachelor", "bs", "btech")):
            level = "bachelor"
        elif raw.startswith(("master", "ms", "mtech")):
            level = "master"
        else:
            level = "phd"
        field_: str | None = None
        fm = DEGREE_FIELD.match(text, m.end())
        if fm:
            field_ = FIELD_TAIL.sub("", fm.group("field")).strip(" ,.;") or None
        rank = DEGREE_RANK[level]
        if best is None or rank < best[0] or (rank == best[0] and field_ and not best[2]):
            best = (rank, level, field_)
    return (best[1], best[2]) if best else (None, None)


def parse_job_description(text: str, title: str = "", company: str = "") -> JobSpec:
    """Read a posting into a `JobSpec`. Pure text in, structure out."""
    spec = JobSpec(title=title.strip(), company=company.strip(), raw_text=text)
    section: str | None = None          # "required" | "preferred" | "other"
    # skill -> (required, years, source); the strongest mention of a skill wins
    best: dict[str, tuple[bool, int | None, str]] = {}

    for line in _lines(text):
        hits = find_skills(line)
        head = line.rstrip(":").strip()
        # Headings are short and name no skills: "Must have" is a heading,
        # "Must have familiarity with robotics" is a requirement.
        if not hits and len(head) <= 80:
            if PREFERRED_HEADINGS.match(head):
                section = "preferred"
                continue
            if REQUIRED_HEADINGS.match(head):
                section = "required"
                continue
            if OTHER_HEADINGS.match(head):
                section = "other"
                continue

        if not hits:
            continue

        if section == "preferred":
            required = False          # the heading wins over any "must" wording
        elif section == "required":
            outside = re.sub(r"\([^()]*\)", " ", line)   # ignore bracketed asides
            required = not PREFERRED_PHRASES.search(outside)
        else:
            # No heading context: trust the wording, and default to required
            # only when the line states a requirement.
            if PREFERRED_PHRASES.search(line):
                required = False
            elif REQUIRED_PHRASES.search(line) or section is None:
                required = True
            else:
                required = False

        years = extract_years(line)
        # "(Git preferred)" makes Git preferred, not everything else on the line.
        soft_spans = _preferred_parentheticals(line)
        for hit in hits:
            skill = hit.skill
            skill_required = required and not any(a <= hit.start and hit.end <= b
                                                  for a, b in soft_spans)
            prev = best.get(skill)
            cand = (skill_required, years, line)
            # Prefer a required mention; among equals prefer one that names years.
            if prev is None or (cand[0], cand[1] is not None) > (prev[0], prev[1] is not None):
                best[skill] = cand

    spec.requirements = sorted(
        (Requirement(skill=s, required=r, years=y, source=src) for s, (r, y, src) in best.items()),
        key=lambda r: (not r.required, r.skill))

    # Overall experience: the smallest year count on a line that is about
    # experience generally, not about one specific skill.
    overall: list[int] = []
    for line in _lines(text):
        if OTHER_HEADINGS.match(line.rstrip(":")):
            continue
        y = extract_years(line)
        if y is not None and re.search(r"\bexperience\b", line, re.IGNORECASE):
            overall.append(y)
    spec.min_years = min(overall) if overall else None
    spec.degree, spec.degree_field = extract_degree(text)
    return spec


def highlight_skills(text: str) -> list[dict[str, object]]:
    """Skill mentions with offsets, so a UI can highlight the posting."""
    return [{"skill": h.skill, "start": h.start, "end": h.end, "text": text[h.start:h.end]}
            for h in find_skills(text)]
