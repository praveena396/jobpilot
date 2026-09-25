"""Resume-based job matching.

Scores a job by (1) how well its title fits your target roles and focus area and
(2) how many of *your* skills (read from your resume + config) its description asks for.
All matching is whole-word, so "rest" never matches "interested" and "ai" never matches "email".
"""

import re
from functools import lru_cache
from pathlib import Path

from jobpilot import get, get_root

# Canonical skill -> regex alternatives. Only skills found in your resume/config are used.
SKILL_VOCAB: dict[str, list[str]] = {
    "Python": [r"python"],
    "C++": [r"c\+\+"],
    "Java": [r"java"],
    "Go": [r"golang", r"go\s+lang"],
    "Rust": [r"rust"],
    "JavaScript": [r"javascript", r"js"],
    "TypeScript": [r"typescript"],
    "Ruby": [r"ruby"],
    "Rails": [r"rails", r"ruby on rails"],
    "SQL": [r"sql"],
    "FastAPI": [r"fastapi"],
    "Flask": [r"flask"],
    "Django": [r"django"],
    "Node.js": [r"node\.?js", r"express\.?js"],
    "React": [r"react(?:\.js)?"],
    "Celery": [r"celery"],
    "Redis": [r"redis"],
    "Kafka": [r"kafka"],
    "Pub/Sub": [r"pub\s*/\s*sub"],
    "PostgreSQL": [r"postgres(?:ql)?"],
    "MySQL": [r"mysql"],
    "MongoDB": [r"mongo(?:db)?"],
    "Docker": [r"docker"],
    "Kubernetes": [r"kubernetes", r"k8s"],
    "Terraform": [r"terraform"],
    "AWS": [r"aws", r"amazon web services"],
    "GCP": [r"gcp", r"google cloud"],
    "Azure": [r"azure"],
    "CI/CD": [r"ci\s*/\s*cd"],
    "GitHub Actions": [r"github actions"],
    "Microservices": [r"micro-?services?"],
    "REST APIs": [r"restful", r"rest\s*apis?"],
    "Distributed Systems": [r"distributed systems?"],
    "Machine Learning": [r"machine learning", r"ml"],
    "Deep Learning": [r"deep learning"],
    "PyTorch": [r"pytorch"],
    "TensorFlow": [r"tensorflow"],
    "scikit-learn": [r"scikit-learn", r"sklearn"],
    "LLM": [r"llms?", r"large language models?"],
    "Generative AI": [r"generative ai", r"gen\s*ai"],
    "LangChain": [r"langchain"],
    "RAG": [r"rag", r"retrieval[- ]augmented"],
    "NLP": [r"nlp", r"natural language processing"],
    "Computer Vision": [r"computer vision"],
    "Fine-tuning": [r"fine[- ]?tun(?:e|ed|ing)"],
    "MLOps": [r"mlops"],
    "Model Inference": [r"inference"],
    "ONNX": [r"onnx"],
    "TensorRT": [r"tensorrt"],
    "Quantization": [r"quantization"],
    "CUDA": [r"cuda"],
    "OpenAI API": [r"openai"],
    "Hugging Face": [r"hugging\s*face", r"transformers"],
    "Vector DB": [r"vector (?:db|database|store|search)s?", r"pinecone", r"faiss",
                  r"chroma(?:db)?", r"weaviate", r"pgvector"],
    "Agents": [r"(?:ai|llm) agents?", r"agentic", r"multi-agent", r"autonomous agents?"],
    "Robotics": [r"robotics?"],
    "Next.js": [r"next\.?js"],
    "LangGraph": [r"langgraph"],
    "MCP": [r"mcp", r"model context protocol"],
    "Function Calling": [r"function[- ]calling", r"tool[- ](?:calling|use)"],
    "Gemini API": [r"gemini"],
    "Embeddings": [r"embeddings?"],
    "WebSockets": [r"websockets?"],
    "asyncio": [r"asyncio", r"async(?:hronous)? python"],
    "Full Stack": [r"full[- ]?stack"],
    "Salesforce": [r"salesforce"],
    "pytest": [r"pytest"],
    "TDD": [r"tdd", r"test[- ]driven"],
}

_COMPILED = {
    name: re.compile(r"(?<![\w+#])(?:" + "|".join(alts) + r")(?![\w+#])", re.IGNORECASE)
    for name, alts in SKILL_VOCAB.items()
}


def find_skills(text: str, skills: set[str] | None = None) -> list[str]:
    """Skills (from SKILL_VOCAB, optionally limited to `skills`) mentioned in text."""
    if not text:
        return []
    names = skills if skills is not None else set(SKILL_VOCAB)
    return [n for n, rx in _COMPILED.items() if n in names and rx.search(text)]


def _read_resume_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            print("⚠️  Install pypdf to read PDF resumes: pip install pypdf")
            return ""
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        from docx import Document

        return "\n".join(p.text for p in Document(str(path)).paragraphs)
    return path.read_text(encoding="utf-8", errors="ignore")


def resume_text() -> str:
    """Your resume as text: the file at profile.resume_path (if set) plus config profile."""
    parts: list[str] = []
    resume_path = get("profile.resume_path", "")
    if resume_path:
        path = Path(resume_path).expanduser()
        if not path.is_absolute():
            path = get_root() / path
        if path.exists():
            parts.append(_read_resume_file(path))
        else:
            print(f"⚠️  Resume not found at {path} — using config profile only")

    parts += [str(s) for s in get("profile.tech_stack", []) or []]
    parts += [str(a) for a in get("profile.achievements", []) or []]
    for job in get("profile.work_history", []) or []:
        parts.append(str(job.get("title", "")))
        parts += [str(b) for b in job.get("bullets", []) or []]
        parts.append(str(job.get("description", "")))
    for project in get("profile.projects", []) or []:
        parts.append(f"{project.get('title', '')} {project.get('description', '')}")
    return "\n".join(parts)


@lru_cache(maxsize=1)
def profile_skills() -> tuple[frozenset[str], frozenset[str]]:
    """(core skills, all resume skills). Core skills count most toward a match."""
    all_skills = set(find_skills(resume_text()))
    core = set(get("profile.core_skills", []) or [])
    unknown = core - set(SKILL_VOCAB)
    if unknown:
        print(f"⚠️  Unknown core_skills (ignored): {', '.join(sorted(unknown))}")
    core &= set(SKILL_VOCAB)
    if not core:
        core = all_skills
    return frozenset(core), frozenset(all_skills | core)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]+", text.lower()))


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<![\w+#])" + re.escape(phrase.lower()) + r"(?![\w+#])", text) is not None


def title_fit(title: str) -> tuple[int, str]:
    """(0-45 points, reason). 0 means the title doesn't fit your target roles."""
    t = title.lower()
    for kw in get("job_search.exclude_title_keywords", []) or []:
        if _has_phrase(t, kw):
            return 0, f"excluded: {kw}"

    roles = get("profile.target_roles", []) or get("profile.job_titles", [])
    title_words = _words(t)
    role_hit = any(_words(r) and _words(r) <= title_words for r in roles)

    focus = [f for f in get("profile.focus_keywords", []) or [] if _has_phrase(t, f)]
    if role_hit and focus:
        return 45, f"role + focus ({focus[0]})"
    if focus:
        return 35, f"focus ({focus[0]})"
    if role_hit:
        return 25, "role"
    return 0, "title not in target roles"


LEVEL_POINTS = {"L3": 15, "L4": 10, "L5": -10, "L6": -20, "L7": -20, "MANAGER": -20, "INTERN": -15}


def score_job(title: str, description: str, level: str) -> tuple[int, list[str]]:
    """Match score 0-100 and the resume skills the job asks for."""
    title_points, _reason = title_fit(title)
    if title_points == 0:
        return 0, []
    core, all_skills = profile_skills()
    matched = find_skills(f"{title}\n{description}", set(all_skills))
    core_hits = [s for s in matched if s in core]
    other_hits = [s for s in matched if s not in core]
    skill_points = min(len(core_hits) * 7, 42) + min(len(other_hits) * 2, 8)
    score = title_points + skill_points + LEVEL_POINTS.get(level, 10)
    # Put your core skills first so the table shows the strongest reasons
    return max(min(score, 100), 0), core_hits + other_hits


# ── Graduation-year eligibility ──────────────────────────────────────────────

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "six": 6, "twelve": 12, "eighteen": 18,
              "twenty-four": 24}
_YEAR_LIST = r"((?:20\d\d\s*(?:,|/|or|and|&|-|–)\s*)*20\d\d)"
# "Class of 2026", "2025 or 2026 graduates", "New Grad 2026", "graduating in May 2026"
_COHORT_RES = [
    re.compile(r"class of\s+" + _YEAR_LIST),
    re.compile(_YEAR_LIST + r"\s+(?:new\s+|university\s+|college\s+)?grad(?:uate)?s?\b"),
    re.compile(r"new\s*grad(?:uate)?s?\s*[-–(,:]?\s*(?:[a-z]+\s+)?" + _YEAR_LIST),
    re.compile(r"(?:graduating|graduation|to graduate|graduate)\s+(?:date\s+)?(?:in|by|from|of)?"
               r"\s*(?:[a-z]+\s+)?" + _YEAR_LIST),
]
# "2027 Start", "starting in January 2026", "start date: 2026"
_START_RES = [
    re.compile(r"(20\d\d)\s+start\b"),
    re.compile(r"start(?:ing)?(?:\s+date)?\s*(?:in|:)?\s*(?:[a-z]+\s+)?(20\d\d)\b"),
]
_RANGE_RE = re.compile(
    r"graduat\w*[^.]{0,60}?between\s+(?:([a-z]+)\.?\s+)?(20\d\d)\s+(?:and|-|–|to)\s+"
    r"(?:([a-z]+)\.?\s+)?(20\d\d)"
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _month(word: str | None, default: int) -> int:
    return _MONTHS.get((word or "")[:3], default)
_WITHIN_RE = re.compile(
    r"graduated\s+(?:with)?in\s+the\s+(?:last|past)\s+(\d+|[a-z-]+)\s+(months?|years?)"
)
_STUDENT_ONLY_RE = re.compile(
    r"currently\s+(?:enrolled|pursuing)|must\s+be\s+(?:currently\s+)?enrolled"
    r"|returning\s+to\s+school|final[- ]year\s+students?"
)
_RECENT_GRAD_RE = re.compile(
    r"recent(?:ly)?\s+(?:graduat|complet)|early[- ]career|entry[- ]level|new\s*grad"
    r"|0\s*(?:-|–|to)\s*[123]\s*(?:years?|yrs?)|[12]\+?\s*years?"
)


def _graduation() -> tuple[int, int]:
    """(year, month) you graduated: profile.graduation_date "YYYY-MM" or education end_year."""
    raw = str(get("profile.graduation_date", "") or "")
    m = re.match(r"(20\d\d)(?:-(\d{1,2}))?", raw)
    if m:
        return int(m.group(1)), int(m.group(2) or 6)
    years = [e.get("end_year") for e in get("profile.education", []) or [] if e.get("end_year")]
    return (int(max(years)), 6) if years else (0, 0)


def _years(group: str) -> list[int]:
    return [int(y) for y in re.findall(r"20\d\d", group)]


def grad_eligibility(title: str, description: str = "") -> tuple[str, str]:
    """("yes" | "likely" | "no" | "unknown", reason) for your graduation date."""
    grad_year, grad_month = _graduation()
    if not grad_year:
        return "unknown", ""
    t = title.lower()
    d = (description or "").lower()
    text = f"{t}\n{d}"

    m = _RANGE_RE.search(text)
    if m:
        lo = (int(m.group(2)), _month(m.group(1), 1))
        hi = (int(m.group(4)), _month(m.group(3), 12))
        label = f"grads {m.group(1) or ''} {lo[0]} - {m.group(3) or ''} {hi[0]}"
        label = re.sub(r"\s+", " ", label).title().replace("Grads", "grads")
        if lo <= (grad_year, grad_month) <= hi:
            return "yes", label
        return "no", f"{label} only"

    m = _WITHIN_RE.search(text)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS.get(m.group(1), 0)
        months = n * 12 if m.group(2).startswith("year") else n
        from datetime import date

        today = date.today()
        since = (today.year - grad_year) * 12 + today.month - grad_month
        if n:
            return ("yes", f"grads in last {n} {m.group(2)}") if since <= months else (
                "no", f"grads in last {n} {m.group(2)} only")

    cohort = [y for rx in _COHORT_RES for g in rx.findall(text) for y in _years(g)]
    starts = [y for rx in _START_RES for g in rx.findall(text) for y in _years(g)]
    # A bare year in a job title ("ML Engineer - 2027") is the graduating class
    if not cohort and not starts:
        cohort = _years(t)
    if cohort:
        if grad_year in cohort:
            return "yes", f"class of {grad_year} ok"
        if min(cohort) > grad_year:
            return "no", f"class of {min(cohort)}+"
        return "no", f"class of {max(cohort)} only"
    if starts and min(starts) > grad_year + 1:
        return "no", f"{min(starts)} start (students)"

    recent_grads_ok = re.search(r"recent(?:ly)?\s+(?:graduat|complet)", text)
    if _STUDENT_ONLY_RE.search(text) and not recent_grads_ok:
        return "no", "current students only"
    if _RECENT_GRAD_RE.search(text):
        return "likely", "entry level / recent grads"
    return "unknown", ""
