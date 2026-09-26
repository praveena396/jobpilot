import { useState } from "react";
import { api } from "../api";
import { MatchReport } from "../components/MatchReport";
import type { Analysis } from "../types";

/** Paste a posting, get an explained score. Optionally save it to the tracker. */
export function Analyze({ hasResume, onSaved }: { hasResume: boolean; onSaved: () => void }) {
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [url, setUrl] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const run = async () => {
    setBusy(true); setError(""); setSaved(false);
    try { setAnalysis(await api.analyze(text, undefined, title, company)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true); setError("");
    try {
      await api.addPosting({ text, title, company, url });
      setSaved(true);
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <div className="card">
        <h2>Analyze a job description</h2>
        <p className="muted">
          Paste a posting you found. It is scored against your active resume, on your machine.
        </p>
        <div className="fields">
          <input placeholder="Job title (optional)" value={title}
            onChange={(e) => setTitle(e.target.value)} />
          <input placeholder="Company (optional)" value={company}
            onChange={(e) => setCompany(e.target.value)} />
          <input placeholder="Link (optional)" value={url} onChange={(e) => setUrl(e.target.value)} />
        </div>
        <textarea rows={12} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Paste the full job description here, including the requirements section…" />
        <div className="actions">
          <button onClick={run} disabled={busy || text.trim().length < 20 || !hasResume}>
            {busy ? "Analyzing…" : "Analyze"}
          </button>
          <button className="ghost" onClick={save} disabled={busy || text.trim().length < 20}>
            Save to tracker
          </button>
          {!hasResume && <span className="muted">Add a resume first, on the Resume tab.</span>}
          {saved && <span className="ok">Saved.</span>}
        </div>
        {error && <p className="bad">{error}</p>}
      </div>
      {analysis && <MatchReport analysis={analysis} />}
    </div>
  );
}
