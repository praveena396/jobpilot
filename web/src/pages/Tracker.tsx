import { useCallback, useEffect, useState } from "react";
import { api, scoreColor } from "../api";
import { MatchReport } from "../components/MatchReport";
import { ACTIVE_STAGES, STAGES, type Analysis, type Posting, type Stage } from "../types";

/** Saved applications, their stage, and the full report for whichever is open. */
export function Tracker({ version }: { version: number }) {
  const [rows, setRows] = useState<Posting[]>([]);
  const [filter, setFilter] = useState<Stage | "all">("all");
  const [openId, setOpenId] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try { setRows(await api.postings(filter === "all" ? undefined : filter)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, [filter]);

  useEffect(() => { void load(); }, [load, version]);

  const open = async (id: number) => {
    if (openId === id) { setOpenId(null); setAnalysis(null); return; }
    setOpenId(id); setAnalysis(null);
    try { setAnalysis(await api.analysis(id)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const move = async (id: number, stage: Stage) => {
    await api.setStage(id, stage);
    await load();
  };

  const remove = async (id: number) => {
    await api.deletePosting(id);
    if (openId === id) { setOpenId(null); setAnalysis(null); }
    await load();
  };

  return (
    <div>
      <div className="toolbar">
        <h2>Applications <span className="muted">({rows.length})</span></h2>
        <select value={filter} onChange={(e) => setFilter(e.target.value as Stage | "all")}>
          <option value="all">All stages</option>
          {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      {error && <p className="bad">{error}</p>}
      {rows.length === 0 && <div className="card muted">
        Nothing saved yet. Analyze a posting and click “Save to tracker”.
      </div>}

      {rows.map((p) => (
        <div className="card posting" key={p.id}>
          <div className="posting-head">
            <button className="link" onClick={() => void open(p.id)}>
              <strong>{p.title || "Untitled role"}</strong>
              {p.company && <span className="muted"> · {p.company}</span>}
            </button>
            <div className="posting-right">
              {p.score !== null &&
                <span className={`score-chip ${scoreColor(p.score)}`}>{p.score}</span>}
              <select value={p.stage} onChange={(e) => void move(p.id, e.target.value as Stage)}>
                {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button className="ghost danger" onClick={() => void remove(p.id)}>Delete</button>
            </div>
          </div>
          {p.notes && <p className="muted small">{p.notes}</p>}
          {p.url && <a className="small" href={p.url} target="_blank" rel="noreferrer">Open posting</a>}
          {openId === p.id && (analysis
            ? <MatchReport analysis={analysis} />
            : <p className="muted">Loading the report…</p>)}
        </div>
      ))}
      <p className="muted small">
        Insights count the stages {ACTIVE_STAGES.join(", ")} — rejected and withdrawn roles
        should not steer what you learn next.
      </p>
    </div>
  );
}
