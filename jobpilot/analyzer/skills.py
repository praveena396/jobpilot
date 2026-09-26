"""Skill taxonomy: canonical names, aliases and categories.

A job description says "K8s", a resume says "Kubernetes", and an ATS keyword
list says "kubernetes". All three are one skill. Everything downstream works
on canonical names, so matching never depends on how a phrase was written.

Aliases are matched as whole words (or exact multi-word phrases), case
insensitively. Short or punctuation-heavy aliases like "C++", "Go" and ".NET"
are handled by `SKILL_PATTERN`, which builds one regex per alias with
boundaries that suit that alias, rather than a single naive \\b...\\b.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# canonical name -> (category, aliases)
TAXONOMY: dict[str, tuple[str, tuple[str, ...]]] = {
    # --- languages ---
    "Python": ("language", ("python", "python3")),
    "JavaScript": ("language", ("javascript", "js", "es6", "ecmascript")),
    "TypeScript": ("language", ("typescript", "ts")),
    "Java": ("language", ("java",)),
    "C": ("language", ("c language", "ansi c")),
    "C++": ("language", ("c++", "cpp", "c plus plus")),
    "C#": ("language", ("c#", "csharp", "c sharp")),
    "Go": ("language", ("go", "golang")),
    "Rust": ("language", ("rust",)),
    "Ruby": ("language", ("ruby",)),
    "PHP": ("language", ("php",)),
    "Swift": ("language", ("swift",)),
    "Kotlin": ("language", ("kotlin",)),
    "Scala": ("language", ("scala",)),
    "R": ("language", ("r language",)),
    "MATLAB": ("language", ("matlab",)),
    "SQL": ("language", ("sql",)),
    "Bash": ("language", ("bash", "shell scripting", "shell script")),
    # --- frontend ---
    "React": ("frontend", ("react", "react.js", "reactjs")),
    "Next.js": ("frontend", ("next.js", "nextjs")),
    "Angular": ("frontend", ("angular", "angularjs")),
    "Vue": ("frontend", ("vue", "vue.js", "vuejs")),
    "HTML/CSS": ("frontend", ("html", "css", "html5", "css3", "scss", "sass", "tailwind")),
    "Redux": ("frontend", ("redux",)),
    "WebSockets": ("frontend", ("websocket", "websockets", "socket.io")),
    # --- backend / frameworks ---
    "Node.js": ("backend", ("node", "node.js", "nodejs")),
    "Express": ("backend", ("express", "express.js")),
    "Django": ("backend", ("django",)),
    "Flask": ("backend", ("flask",)),
    "FastAPI": ("backend", ("fastapi", "fast api")),
    "Spring": ("backend", ("spring", "spring boot", "springboot")),
    ".NET": ("backend", (".net", "dotnet", "asp.net")),
    "Rails": ("backend", ("rails", "ruby on rails")),
    "REST APIs": ("backend", ("rest", "restful", "rest api", "rest apis", "restful api")),
    "GraphQL": ("backend", ("graphql",)),
    "gRPC": ("backend", ("grpc",)),
    "Microservices": ("backend", ("microservice", "microservices")),
    # --- data stores ---
    "PostgreSQL": ("database", ("postgres", "postgresql", "psql")),
    "MySQL": ("database", ("mysql", "mariadb")),
    "MongoDB": ("database", ("mongo", "mongodb")),
    "Redis": ("database", ("redis",)),
    "Elasticsearch": ("database", ("elasticsearch", "elastic search", "opensearch")),
    "DynamoDB": ("database", ("dynamodb", "dynamo db")),
    "Cassandra": ("database", ("cassandra",)),
    "SQLite": ("database", ("sqlite",)),
    "TimescaleDB": ("database", ("timescaledb", "timescale")),
    "Snowflake": ("database", ("snowflake",)),
    # --- data / streaming ---
    "Kafka": ("data", ("kafka",)),
    "RabbitMQ": ("data", ("rabbitmq", "rabbit mq")),
    "Spark": ("data", ("spark", "pyspark", "apache spark")),
    "Airflow": ("data", ("airflow", "apache airflow")),
    "Pandas": ("data", ("pandas",)),
    "NumPy": ("data", ("numpy",)),
    "ETL": ("data", ("etl", "elt", "data pipeline", "data pipelines")),
    # --- cloud / infra ---
    "AWS": ("cloud", ("aws", "amazon web services", "ec2", "s3", "lambda")),
    "GCP": ("cloud", ("gcp", "google cloud")),
    "Azure": ("cloud", ("azure", "microsoft azure")),
    "Docker": ("cloud", ("docker", "containers", "containerization")),
    "Kubernetes": ("cloud", ("kubernetes", "k8s", "eks", "gke")),
    "Terraform": ("cloud", ("terraform", "infrastructure as code", "iac")),
    "CI/CD": ("cloud", ("ci/cd", "cicd", "continuous integration", "continuous delivery",
                        "jenkins", "github actions", "gitlab ci", "circleci")),
    "Linux": ("cloud", ("linux", "unix")),
    "Observability": ("cloud", ("prometheus", "grafana", "datadog", "observability",
                                "monitoring", "opentelemetry", "splunk")),
    # --- ai / ml ---
    "Machine Learning": ("ai", ("machine learning", "ml", "deep learning", "neural network",
                                "neural networks")),
    "PyTorch": ("ai", ("pytorch", "torch")),
    "TensorFlow": ("ai", ("tensorflow", "keras")),
    "NLP": ("ai", ("nlp", "natural language processing")),
    "Computer Vision": ("ai", ("computer vision", "opencv", "image recognition")),
    "LLMs": ("ai", ("llm", "llms", "large language model", "large language models",
                    "gpt", "openai api", "gemini", "claude", "prompt engineering")),
    "RAG": ("ai", ("rag", "retrieval augmented generation", "vector database", "embeddings")),
    "scikit-learn": ("ai", ("scikit-learn", "sklearn", "scikit learn")),
    # --- practices ---
    "Testing": ("practice", ("testing", "unit test", "unit tests", "unit testing", "pytest",
                             "jest", "junit", "test driven", "tdd", "integration test",
                             "integration tests", "automated testing", "qa", "test automation")),
    "Git": ("practice", ("git", "github", "gitlab", "version control")),
    "Agile": ("practice", ("agile", "scrum", "kanban", "sprint", "sprints")),
    "Code Review": ("practice", ("code review", "code reviews", "peer review")),
    "Distributed Systems": ("practice", ("distributed system", "distributed systems",
                                         "concurrency", "concurrent", "async", "asyncio",
                                         "multithreading", "parallel processing")),
    "System Design": ("practice", ("system design", "software design", "software architecture",
                                   "architectural design", "scalability")),
    "Debugging": ("practice", ("debugging", "troubleshooting", "root cause analysis")),
    "Security": ("practice", ("security", "authentication", "authorization", "oauth",
                              "encryption", "cybersecurity")),
    "Embedded": ("practice", ("embedded", "firmware", "rtos", "embedded systems",
                              "microcontroller", "i2c", "spi", "uart", "can bus")),
    # Its own skill, not an alias of Embedded: "real-time systems" in a robotics
    # posting means deterministic deadlines, while a streaming engineer means
    # low-latency data. Keeping them separate stops one being read as the other.
    "Real-time Systems": ("practice", ("real-time systems", "real time systems",
                                       "realtime systems", "hard real-time",
                                       "soft real-time", "low latency", "low-latency")),
    "Robotics": ("practice", ("robotics", "ros", "motion control", "kinematics")),
}

# Skills that one skill obviously demonstrates. Someone who shipped a FastAPI
# service has built REST APIs, even if the resume never says "REST". Only
# includes relations that are true by construction, never "related fields":
# knowing Kubernetes does not mean knowing AWS.
IMPLIES: dict[str, tuple[str, ...]] = {
    "FastAPI": ("REST APIs", "Python"),
    "Django": ("REST APIs", "Python"),
    "Flask": ("REST APIs", "Python"),
    "Express": ("REST APIs", "Node.js"),
    "Spring": ("REST APIs", "Java"),
    "Rails": ("REST APIs", "Ruby"),
    ".NET": ("C#",),
    "React": ("JavaScript",),
    "Next.js": ("React", "JavaScript"),
    "Vue": ("JavaScript",),
    "Angular": ("TypeScript", "JavaScript"),
    "Redux": ("React", "JavaScript"),
    "TypeScript": ("JavaScript",),
    "Node.js": ("JavaScript",),
    "PyTorch": ("Machine Learning", "Python"),
    "TensorFlow": ("Machine Learning", "Python"),
    "scikit-learn": ("Machine Learning", "Python"),
    "RAG": ("LLMs",),
    "Pandas": ("Python",),
    "NumPy": ("Python",),
    "Spark": ("ETL",),
    "Airflow": ("ETL",),
    "Kubernetes": ("Docker",),
    "TimescaleDB": ("PostgreSQL", "SQL"),
    "PostgreSQL": ("SQL",),
    "MySQL": ("SQL",),
    "SQLite": ("SQL",),
    "Terraform": ("CI/CD",),
}

CATEGORY_LABELS = {
    "language": "Languages", "frontend": "Frontend", "backend": "Backend & APIs",
    "database": "Databases", "data": "Data & Streaming", "cloud": "Cloud & Infrastructure",
    "ai": "AI & Machine Learning", "practice": "Practices & Concepts",
}


@dataclass(frozen=True)
class SkillHit:
    """One place a skill was mentioned in a text."""

    skill: str
    alias: str
    start: int
    end: int


def _alias_pattern(alias: str) -> str:
    """A regex for one alias, with boundaries that suit its characters.

    `\\b` fails on aliases that end in punctuation: `\\bc\\+\\+\\b` never matches
    "C++" because there is no word character after "+". So a boundary is only
    added on a side that starts or ends with a word character.
    """
    core = re.escape(alias)
    left = r"(?<![\w+#.])" if alias[0].isalnum() else r"(?<!\w)"
    right = r"(?![\w+#])" if alias[-1].isalnum() else r"(?!\w)"
    return left + core + right


# Longest aliases first so "machine learning" wins over a bare "ml" inside it.
_ALIAS_TO_SKILL: dict[str, str] = {
    alias: skill for skill, (_, aliases) in TAXONOMY.items() for alias in aliases
}
_SORTED_ALIASES = sorted(_ALIAS_TO_SKILL, key=len, reverse=True)
SKILL_PATTERN = re.compile("|".join(f"({_alias_pattern(a)})" for a in _SORTED_ALIASES),
                           re.IGNORECASE)


def category_of(skill: str) -> str:
    entry = TAXONOMY.get(skill)
    return entry[0] if entry else "other"


def find_skills(text: str) -> list[SkillHit]:
    """Every skill mention in `text`, in order, without overlaps."""
    hits: list[SkillHit] = []
    for m in SKILL_PATTERN.finditer(text):
        idx = m.lastindex
        if idx is None:
            continue
        alias = _SORTED_ALIASES[idx - 1]
        hits.append(SkillHit(_ALIAS_TO_SKILL[alias], alias, m.start(), m.end()))
    return hits


def skills_in(text: str) -> set[str]:
    """The distinct canonical skills mentioned in `text`."""
    return {h.skill for h in find_skills(text)}


def implied_by(skill: str) -> tuple[str, ...]:
    """What `skill` demonstrates in its own right (one level, no recursion)."""
    return IMPLIES.get(skill, ())
