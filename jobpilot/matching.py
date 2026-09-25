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
    "Vector DB": [r"vector (?:db|database|store)s?", r"pinecone", r"faiss", r"chroma"],
    "Agents": [r"ai agents?", r"agentic", r"multi-agent"],
    "Robotics": [r"robotics?"],
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
