import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Analyze } from "./pages/Analyze";
import { Insights } from "./pages/Insights";
import { Resumes } from "./pages/Resumes";
import { Tracker } from "./pages/Tracker";
import type { Health } from "./types";

type Tab = "analyze" | "tracker" | "insights" | "resume";
const TABS: { key: Tab; label: string }[] = [
  { key: "analyze", label: "Analyze" },
  { key: "tracker", label: "Applications" },
  { key: "insights", label: "Insights" },
  { key: "resume", label: "Resume" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>(
    () => (location.hash.replace("#/", "") as Tab) || "analyze");
  const [health, setHealth] = useState<Health | null>(null);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => {
    setVersion((v) => v + 1);
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    refresh();
    const onHash = () => setTab((location.hash.replace("#/", "") as Tab) || "analyze");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [refresh]);

  const go = (t: Tab) => { location.hash = `#/${t}`; setTab(t); };

  return (
    <div className="app">
      <header>
        <h1>JobPilot</h1>
        <nav>
          {TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? "active" : ""}
              onClick={() => go(t.key)}>{t.label}</button>
          ))}
        </nav>
        <div className="status muted">
          {health
            ? <>
              <span>resume: <b>{health.active_resume ?? "none"}</b></span>
              <span>saved: <b>{health.postings}</b></span>
              <span>skills known: <b>{health.skills_known}</b></span>
            </>
            : <span className="bad">API not reachable</span>}
        </div>
      </header>
      <main>
        {tab === "analyze" &&
          <Analyze hasResume={!!health?.active_resume} onSaved={refresh} />}
        {tab === "tracker" && <Tracker version={version} />}
        {tab === "insights" && <Insights version={version} />}
        {tab === "resume" && <Resumes onChange={refresh} />}
      </main>
    </div>
  );
}
