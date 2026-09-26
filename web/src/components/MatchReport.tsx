import type { Analysis, SkillMatch } from "../types";
import { Bar, ScoreRing } from "./Score";

function SkillRow({ m }: { m: SkillMatch }) {
  return (
    <li className={`skill ${m.matched ? "have" : m.required ? "gap-req" : "gap-pref"}`}>
      <div className="skill-head">
        <span className="skill-name">{m.matched ? "✓" : "✗"} {m.skill}</span>
        <span className={`pill ${m.required ? "req" : ""}`}>
          {m.required ? "required" : "preferred"}{m.years_wanted ? ` · ${m.years_wanted}+ yrs` : ""}
        </span>
      </div>
      {m.matched
        ? <p className="evidence">Your resume: “{m.evidence[0]}”</p>
        : m.asked_in && <p className="evidence muted">They asked: “{m.asked_in}”</p>}
    </li>
  );
}

/** The whole explanation: score, components, what matched, what is missing. */
export function MatchReport({ analysis }: { analysis: Analysis }) {
  const matched = analysis.matches.filter((m) => m.matched);
  const missingRequired = analysis.matches.filter((m) => !m.matched && m.required);
  const missingPreferred = analysis.matches.filter((m) => !m.matched && !m.required);

  return (
    <div className="report">
      <div className="report-head card">
        <ScoreRing score={analysis.score} />
        <div className="report-summary">
          <h3>{analysis.verdict}</h3>
          <p className="muted">
            {analysis.matched_count} of {analysis.total_requirements} requirements matched
            {analysis.missing_required_count > 0 &&
              ` · ${analysis.missing_required_count} required still missing`}
          </p>
          <Bar label="Skills" value={analysis.skill_score} />
          <Bar label="Experience" value={analysis.experience_score} />
          <Bar label="Education" value={analysis.degree_score} />
        </div>
      </div>

      {analysis.notes.length > 0 && (
        <div className="card notes">
          <h4>What to fix</h4>
          <ul>{analysis.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}

      {analysis.suggestions && analysis.suggestions.length > 0 && (
        <div className="card">
          <h4>Bullets to lead with</h4>
          <p className="muted small">
            Your own experience, matched to their wording. Nothing here is invented.
          </p>
          {analysis.suggestions.map((s) => (
            <div className="suggestion" key={s.skill}>
              <strong>{s.skill}</strong>
              <p className="evidence">“{s.your_evidence}”</p>
              <p className="muted small">They wrote: “{s.they_asked}”</p>
            </div>
          ))}
        </div>
      )}

      <div className="columns">
        <div className="card">
          <h4>You match <span className="count ok">{matched.length}</span></h4>
          <ul className="skills">{matched.map((m) => <SkillRow key={m.skill} m={m} />)}</ul>
          {matched.length === 0 && <p className="muted">Nothing matched yet.</p>}
        </div>
        <div className="card">
          <h4>Gaps <span className="count bad">{missingRequired.length}</span> required</h4>
          <ul className="skills">
            {missingRequired.map((m) => <SkillRow key={m.skill} m={m} />)}
            {missingPreferred.map((m) => <SkillRow key={m.skill} m={m} />)}
          </ul>
          {missingRequired.length + missingPreferred.length === 0 &&
            <p className="muted">No gaps — apply.</p>}
        </div>
      </div>

      {analysis.extra_skills.length > 0 && (
        <div className="card">
          <h4>Not asked for</h4>
          <p className="muted small">
            On your resume but absent from this posting — consider trimming for this application.
          </p>
          <p>{analysis.extra_skills.map((s) => <span className="tag" key={s}>{s}</span>)}</p>
        </div>
      )}
    </div>
  );
}
