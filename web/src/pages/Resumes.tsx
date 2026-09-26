import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ResumeRow } from "../types";

/** Manage resume versions. The active one is what every score is measured against. */
export function Resumes({ onChange }: { onChange: () => void }) {
  const [rows, setRows] = useState<ResumeRow[]>([]);
  const [label, setLabel] = useState("");
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<{ skills: string[]; years: number | null } | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try { setRows(await api.resumes()); } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const add = async () => {
    setError("");
    try {
      const r = await api.addResume(label.trim() || `resume ${rows.length + 1}`, text);
      setParsed({ skills: r.skills, years: r.years_experience });
      setText(""); setLabel("");
      await load(); onChange();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <div>
      <div className="card">
        <h2>Your resume</h2>
        <p className="muted">
          Paste the text of your resume. Keep several versions and switch the active one to see
          how each scores against the same jobs.
        </p>
        <input placeholder="Label, e.g. backend-focused" value={label}
          onChange={(e) => setLabel(e.target.value)} />
        <textarea rows={12} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Paste your resume text here…" />
        <div className="actions">
          <button onClick={() => void add()} disabled={text.trim().length < 20}>Save resume</button>
        </div>
        {error && <p className="bad">{error}</p>}
        {parsed && (
          <p className="small">
            Found {parsed.skills.length} skills
            {parsed.years !== null && `, about ${parsed.years} years of experience`}:{" "}
            {parsed.skills.map((s) => <span className="tag" key={s}>{s}</span>)}
          </p>
        )}
      </div>

      <div className="card">
        <h3>Versions</h3>
        {rows.length === 0 && <p className="muted">None saved yet.</p>}
        <table>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td><strong>{r.label}</strong>{r.is_active ? <span className="pill req"> active</span> : null}</td>
                <td className="muted small">{r.created_at}</td>
                <td className="muted small">{r.size} chars</td>
                <td>
                  {!r.is_active && <button className="ghost" onClick={async () => {
                    await api.activateResume(r.id); await load(); onChange();
                  }}>Make active</button>}
                  <button className="ghost danger" onClick={async () => {
                    await api.deleteResume(r.id); await load(); onChange();
                  }}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
