"""LaTeX resume generator with optional PDF and DOCX export."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from jobpilot import get, get_root
from jobpilot.resume_gen import calculate_ats_score, extract_jd_keywords
from jobpilot.scraper.linkedin import ProfileData


def _latex_escape(text: str) -> str:
    """Escape characters that are special in LaTeX."""
    replacements = {
        "\\": r"\\textbackslash{}",
        "&": r"\\&",
        "%": r"\\%",
        "$": r"\\$",
        "#": r"\\#",
        "_": r"\\_",
        "{": r"\\{",
        "}": r"\\}",
        "~": r"\\textasciitilde{}",
        "^": r"\\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _normalize_bullets(text: str) -> list[str]:
    parts = re.split(r"\n|[;•]", text)
    return [p.strip() for p in parts if p.strip()]


def _profile_summary(profile: ProfileData, job_title: str) -> str:
    achievements = get("profile.achievements", [])
    metric = achievements[0] if achievements else ""
    summary = (
        f"{job_title} with 1+ year of industry experience building scalable AI platforms, "
        f"distributed systems, and production ML infrastructure. "
        f"{profile.headline}."
    )
    if metric:
        summary += f" Highlight: {metric}."
    return summary


def build_latex_resume(profile: ProfileData, job_title: str, company: str, jd_text: str) -> str:
    """Build LaTeX source from profile + target role context."""
    email = get("profile.email", "")
    phone = get("profile.phone", "")
    github = get("profile.portfolio.github", "")
    linkedin = profile.profile_url
    location = profile.location or "Bengaluru, India"

    summary = _latex_escape(_profile_summary(profile, job_title))

    skills = get("profile.tech_stack", [])
    skills_line = _latex_escape(", ".join(skills))

    work_blocks: list[str] = []
    for job in profile.work_history[:3]:
        title = _latex_escape(job.get("title", ""))
        company_name = _latex_escape(job.get("company", ""))
        dates = _latex_escape(job.get("dates", ""))
        desc = job.get("description", "")
        bullets = _normalize_bullets(desc)[:6]
        bullet_tex = "\n".join(f"\\item {_latex_escape(b)}" for b in bullets)
        work_blocks.append(
            f"""
\\textbf{{{title}}} \\hfill \\textit{{{company_name}}}\\
\\textit{{{dates}}}
\\begin{{itemize}}
{bullet_tex}
\\end{{itemize}}
"""
        )

    education_rows: list[str] = []
    for edu in profile.education[:2]:
        inst = _latex_escape(edu.get("institution", ""))
        degree = _latex_escape(edu.get("degree", ""))
        education_rows.append(f"\\textbf{{{inst}}} --- {degree}")

    projects = get("profile.projects", [])
    project_rows: list[str] = []
    for proj in projects[:3]:
        p_title = _latex_escape(proj.get("title", ""))
        p_desc = _latex_escape(proj.get("description", ""))
        project_rows.append(f"\\textbf{{{p_title}}}: {p_desc}")

    achievements = get("profile.achievements", [])
    achievement_rows = "\n".join(f"\\item {_latex_escape(a)}" for a in achievements[:5])

    latex = f"""\\documentclass[10pt,a4paper]{{article}}
\\usepackage[top=0.45in,bottom=0.45in,left=0.55in,right=0.55in]{{geometry}}
\\usepackage[T1]{{fontenc}}
\\usepackage[utf8]{{inputenc}}
\\usepackage{{hyperref}}
\\usepackage{{xcolor}}
\\usepackage{{enumitem}}
\\usepackage{{microtype}}
\\definecolor{{darkblue}}{{rgb}}{{0.0,0.0,0.5}}
\\hypersetup{{colorlinks=true,linkcolor=darkblue,urlcolor=darkblue}}
\\pagestyle{{empty}}
\\setlength{{\\parindent}}{{0pt}}
\\setlength{{\\parskip}}{{0pt}}
\\setlist[itemize,1]{{leftmargin=0.18in,label=\\textbullet,itemsep=1.2pt,topsep=1.5pt,parsep=0pt,partopsep=0pt}}

\\begin{{document}}
\\begin{{center}}
{{\\Large \\textbf{{{_latex_escape(profile.full_name)}}}}} \\
{{\\small {_latex_escape(profile.headline)}}} \\
\\textcolor{{darkblue}}{{\\href{{mailto:{email}}}{{{_latex_escape(email)}}} \\,|\\, \\href{{tel:{phone}}}{{{_latex_escape(phone)}}}}} \\
\\textcolor{{darkblue}}{{\\href{{{github}}}{{GitHub}} \\,|\\, \\href{{{linkedin}}}{{LinkedIn}}}} \\
{_latex_escape(location)}
\\end{{center}}

\\section*{{Professional Summary}}
{summary}

\\section*{{Core Skills}}
{skills_line}

\\section*{{Professional Experience}}
{''.join(work_blocks)}

\\section*{{Education}}
{'\\\n'.join(education_rows)}

\\section*{{Projects}}
{'\\\n'.join(project_rows)}

\\section*{{Key Achievements}}
\\begin{{itemize}}
{achievement_rows}
\\end{{itemize}}

\\end{{document}}
"""
    return latex


def generate_latex_resume(
    profile: ProfileData,
    job_title: str,
    company: str,
    job_description: str,
) -> dict:
    """Generate TEX, PDF, optional DOCX, and ATS score metadata."""
    out_dir = get_root() / get("resume.output_dir", "output/resumes")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r"[^a-zA-Z]", "_", profile.full_name).strip("_")
    safe_role = re.sub(r"[^a-zA-Z]", "_", job_title).strip("_")
    safe_company = re.sub(r"[^a-zA-Z]", "_", company).strip("_")
    base = f"{safe_name}_{safe_role}_{safe_company}"

    tex_path = out_dir / f"{base}.tex"
    pdf_path = out_dir / f"{base}.pdf"
    docx_path = out_dir / f"{base}.docx"

    tex_content = build_latex_resume(profile, job_title, company, job_description)
    tex_path.write_text(tex_content, encoding="utf-8")

    pdf_generated = False
    if shutil.which("pdflatex"):
        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={str(out_dir)}",
            str(tex_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        pdf_generated = proc.returncode == 0 and pdf_path.exists()

    docx_generated = False
    if shutil.which("pandoc"):
        cmd = ["pandoc", str(tex_path), "-o", str(docx_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        docx_generated = proc.returncode == 0 and docx_path.exists()

    jd_keywords = extract_jd_keywords(job_description)
    score = calculate_ats_score(tex_content, jd_keywords)

    return {
        "tex": str(tex_path),
        "pdf": str(pdf_path),
        "pdf_generated": pdf_generated,
        "docx": str(docx_path),
        "docx_generated": docx_generated,
        "ats": score,
    }
