import jobpilot
from jobpilot.latex_resume import build_latex_resume
from jobpilot.resume_gen import extract_jd_keywords
from jobpilot.scraper.linkedin import ProfileData


def test_extract_jd_keywords_filters_generic_noise() -> None:
    jd = (
        "Full stack engineer with AWS, Terraform, PostgreSQL, MySQL, REST, API, "
        "TDD, CI/CD. Global teams in Hyderabad. Job requirement for remote work."
    )

    keywords = extract_jd_keywords(jd)

    assert "AWS" in keywords
    assert "Terraform" in keywords
    assert "PostgreSQL" in keywords
    assert "MySQL" in keywords
    assert "REST" in keywords
    assert "CI/CD" in keywords
    assert "TDD" in keywords

    assert "Full" not in keywords
    assert "Global" not in keywords
    assert "Hyderabad" not in keywords
    assert "Job" not in keywords


def test_build_latex_resume_keeps_all_tech_stack_keywords() -> None:
    jobpilot._CONFIG = {
        "profile": {
            "email": "test@example.com",
            "phone": "+91-0000000000",
            "portfolio": {"github": "https://github.com/example"},
            "tech_stack": [f"Skill{i}" for i in range(1, 25)] + ["Kubernetes", "AWS", "Terraform", "PostgreSQL", "MySQL", "REST"],
            "achievements": ["Built backend systems"],
            "projects": [{"title": "Demo", "description": "Project"}],
            "work_history": [{"title": "AI Developer", "company": "Example", "dates": "2025", "description": "Built systems"}],
            "education": [{"institution": "NIT Trichy", "degree": "BTech"}],
        }
    }
    profile = ProfileData(
        full_name="Ankit Raj",
        headline="AI Engineer",
        location="Bengaluru, India",
        profile_url="https://www.linkedin.com/in/example",
        work_history=[{"title": "AI Developer", "company": "Example", "dates": "2025", "description": "Built systems"}],
        education=[{"institution": "NIT Trichy", "degree": "BTech"}],
    )

    latex = build_latex_resume(profile, "Software Engineer", "Example", "Need AWS, Terraform, PostgreSQL, MySQL, REST, Kubernetes.")

    for token in ["Kubernetes", "AWS", "Terraform", "PostgreSQL", "MySQL", "REST"]:
        assert token in latex
