export type Stage = "saved" | "applied" | "screen" | "interview" | "offer" | "rejected" | "withdrawn";
export const STAGES: Stage[] = ["saved", "applied", "screen", "interview", "offer", "rejected", "withdrawn"];
export const ACTIVE_STAGES: Stage[] = ["saved", "applied", "screen", "interview"];

export interface SkillMatch {
  skill: string;
  category: string;
  required: boolean;
  matched: boolean;
  years_wanted: number | null;
  evidence: string[];
  asked_in: string;
}
export interface Suggestion {
  skill: string; they_asked: string; your_evidence: string; why: string;
}
export interface Analysis {
  score: number;
  skill_score: number;
  experience_score: number;
  degree_score: number;
  matches: SkillMatch[];
  extra_skills: string[];
  notes: string[];
  verdict: string;
  matched_count: number;
  missing_required_count: number;
  total_requirements: number;
  suggestions?: Suggestion[];
  min_years?: number | null;
  degree?: string | null;
  resume_years?: number | null;
  resume_degree?: string | null;
  cached?: boolean;
}
export interface Posting {
  id: number; title: string; company: string; location: string; url: string;
  stage: Stage; notes: string; created_at: string; updated_at: string; score: number | null;
}
export interface Requirement { skill: string; required: boolean; years: number | null; source: string }
export interface PostingDetail {
  posting: Posting; requirements: Requirement[];
  min_years: number | null; degree: string | null;
}
export interface Gap {
  skill: string; category: string; jobs_wanting: number; required_in: number;
  share: number; impact: number; example_jobs: string[];
}
export interface Strength {
  skill: string; category: string; jobs_wanting: number; required_in: number; share: number;
}
export interface Insights {
  jobs: number; average_score: number; strong_matches?: number;
  gaps: Gap[]; strengths: Strength[]; funnel: Record<Stage, number>;
}
export interface ResumeRow { id: number; label: string; is_active: number; created_at: string; size: number }
export interface Health { status: string; active_resume: string | null; postings: number; skills_known: number }
