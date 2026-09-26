import { useEffect, useState } from "react";
import { api } from "../api";
import type { Insights as InsightsData } from "../types";

/** What your own saved jobs say about what to learn next. */
export function Insights({ version }: { version: number }) {
  const [data, setData] = useState<InsightsData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.insights().then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [version]);

  if (error) return <p className="bad">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (data.jobs === 0) {
    return <div className="card muted">
      Save a few postings first. With ten or more, the gaps below become worth acting on.
    </div>;
  }

  const maxImpact = Math.max(...data.gaps.map((g) => g.impact), 1);

  return (
    <div>
      <div className="stats">
        <div className="card stat"><span className="stat-n">{data.jobs}</span>
          <span className="muted">jobs analyzed</span></div>
        <div className="card stat"><span className="stat-n">{data.average_score}</span>
          <span className="muted">average match</span></div>
        <div className="card stat"><span className="stat-n">{data.strong_matches ?? 0}</span>
          <span className="muted">strong matches (75+)</span></div>
      </div>

      <div className="card">
        <h3>Funnel</h3>
        <div className="funnel">
          {Object.entries(data.funnel).map(([stage, n]) => (
            <div className="funnel-step" key={stage}>
              <span className="stat-n">{n}</span><span className="muted">{stage}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Learn this next</h3>
        <p className="muted small">
          Ranked by how many of your saved jobs ask for the skill, weighted towards jobs you
          already nearly match, since those are the ones worth closing.
        </p>
        <table>
          <thead><tr><th>skill</th><th>wanted by</th><th>required in</th><th>impact</th><th>for example</th></tr></thead>
          <tbody>
            {data.gaps.map((g) => (
              <tr key={g.skill}>
                <td><strong>{g.skill}</strong> <span className="muted small">{g.category}</span></td>
                <td>{g.jobs_wanting} of {data.jobs} <span className="muted">
                  ({Math.round(g.share * 100)}%)</span></td>
                <td>{g.required_in}</td>
                <td><div className="bar"><div className="warn"
                  style={{ width: `${(g.impact / maxImpact) * 100}%` }} /></div></td>
                <td className="muted small">{g.example_jobs.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Lead with these</h3>
        <p className="muted small">Skills you already have that your saved jobs keep asking for.</p>
        <table>
          <thead><tr><th>skill</th><th>wanted by</th><th>required in</th></tr></thead>
          <tbody>
            {data.strengths.map((s) => (
              <tr key={s.skill}>
                <td><strong>{s.skill}</strong> <span className="muted small">{s.category}</span></td>
                <td>{s.jobs_wanting} jobs</td>
                <td>{s.required_in}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
