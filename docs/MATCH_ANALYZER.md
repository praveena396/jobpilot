# Match analyzer — design notes

## Why this exists
Applying to jobs is a matching problem run by keyword screens. This reads a
posting the way a screen does, then shows you the same view of your own resume,
with every claim traceable to a sentence on one side and a bullet on the other.

## How a score is built
```
overall = 0.75 x skills + 0.15 x experience + 0.10 x education

skills = sum(weight of matched requirements) / sum(weight of all requirements)
weight = (1.0 if required else 0.4) x (1.25 if a number of years is named)
```
Three components rather than one number, because "you are missing two years of
experience" and "you are missing Kubernetes" need different responses.

Deliberate choices:
- **No requirements parsed → score 0, not 100.** An empty denominator must not
  read as a perfect match.
- **Unknown experience → 50, not 0.** If a resume has no parseable dates, that
  is missing information, not a missing qualification.
- **Nothing is ever invented.** Suggestions point at bullets you already wrote.

## Pipeline
```
posting text ─► parse_job_description ─► JobSpec(requirements, min_years, degree)
                                              │
resume text ─► parse_resume ─► Resume(bullets, skill → evidence)
                                              │
                                              ▼
                                      match() ─► MatchResult
                                              │
             many postings ─► analyze_portfolio ─► skill_gaps / strengths
```

## The parts that were harder than they look

**Aliases.** A posting says "K8s", a resume says "Kubernetes". One taxonomy of
82 skills maps both to a canonical name. `\b` boundaries silently fail on "C++"
and ".NET", so each alias gets a boundary rule chosen from its own characters.
Longest aliases match first, so "machine learning" is never read as "ml".

**Required vs preferred.** Two signals, heading and wording, and the heading
wins: a "must have" under *Preferred qualifications* is still preferred. The
case that forced a rethink was `version control systems (Git preferred)` — the
"preferred" applies only inside the brackets, so scoping is per skill, not per
line. And a line naming a skill is never treated as a heading, because
"Must have familiarity with robotics" starts like one.

**"0-2 years" is not a requirement of zero years.** A zero lower bound means
new grads welcome, so it reads as no minimum. This one crashed a division first.

**Overlapping dates.** Two jobs in 2020-2023 and 2021-2024 are four years of
experience, not six, so ranges are merged before counting.

**Implied skills.** Shipping a FastAPI service is evidence of REST APIs. Only
relations that are true by construction are encoded — Kubernetes implies Docker,
but it says nothing about which cloud you used. Implied matches are labelled, so
you can add the exact words a keyword screen looks for.

**Real-time means two things.** In a robotics posting it means deterministic
deadlines; to a streaming engineer it means low latency. They are separate
skills so neither is read as the other.

## Gap ranking
```
impact = Σ over jobs asking for it of (1.0 required | 0.4 preferred) x (1 + score/100)
```
A gap in a job you already nearly match counts about twice one in a job you do
not, because that is the gap worth closing. Only active stages count: roles you
were rejected from should not steer what you learn next.
