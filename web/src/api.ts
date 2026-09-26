import type { Analysis, Health, Insights, Posting, PostingDetail, ResumeRow, Stage } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...init });
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string" ? detail
        : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ")
          : `${r.status} ${r.statusText}`,
    );
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export const api = {
  health: () => req<Health>("/api/health"),
  resumes: () => req<ResumeRow[]>("/api/resumes"),
  addResume: (label: string, text: string) =>
    req<{ id: number; skills: string[]; years_experience: number | null; degree: string | null }>(
      "/api/resumes", { method: "POST", body: JSON.stringify({ label, text }) }),
  activateResume: (id: number) => req(`/api/resumes/${id}/activate`, { method: "POST" }),
  deleteResume: (id: number) => req(`/api/resumes/${id}`, { method: "DELETE" }),

  postings: (stage?: Stage) => req<Posting[]>(`/api/postings${stage ? `?stage=${stage}` : ""}`),
  addPosting: (body: { text: string; title: string; company: string; url: string }) =>
    req<{ posting: Posting; analysis: Analysis | null }>("/api/postings",
      { method: "POST", body: JSON.stringify(body) }),
  posting: (id: number) => req<PostingDetail>(`/api/postings/${id}`),
  analysis: (id: number, refresh = false) =>
    req<Analysis>(`/api/postings/${id}/analysis${refresh ? "?refresh=true" : ""}`),
  setStage: (id: number, stage: Stage, notes?: string) =>
    req<Posting>(`/api/postings/${id}/stage`,
      { method: "POST", body: JSON.stringify({ stage, notes: notes ?? null }) }),
  deletePosting: (id: number) => req(`/api/postings/${id}`, { method: "DELETE" }),

  analyze: (job_text: string, resume_text?: string, title = "", company = "") =>
    req<Analysis>("/api/analyze",
      { method: "POST", body: JSON.stringify({ job_text, resume_text, title, company }) }),
  insights: () => req<Insights>("/api/insights"),
};

export const scoreColor = (score: number) =>
  score >= 75 ? "ok" : score >= 55 ? "warn" : "bad";
