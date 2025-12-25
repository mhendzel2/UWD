import React, { useCallback, useMemo, useState } from "react";
import UploadDataset from "./components/UploadDataset";
import SessionDashboard from "./components/SessionDashboard";
import ManualOutcomeLabel from "./components/ManualOutcomeLabel";
import LogsPanel from "./components/LogsPanel";

const API_BASE = "http://localhost:8000";

type Decision = { underlying: string; regime: string; confidence: string };

function App() {
  const [sessionId, setSessionId] = useState<string>("");
  const [sessionDate, setSessionDate] = useState<string>("");
  const [strategyMode, setStrategyMode] = useState<string>("INDEX_EOD");
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [logs, setLogs] = useState<string[]>([]);

  const createSession = useCallback(async () => {
    const form = new FormData();
    form.append("session_date", sessionDate);
    form.append("strategy_mode", strategyMode);
    const res = await fetch(`${API_BASE}/sessions`, { method: "POST", body: form });
    if (!res.ok) {
      alert("Failed to create session");
      return;
    }
    const data = await res.json();
    setSessionId(data.session_id);
    setLogs((prev) => [`Created session ${data.session_id}`, ...prev]);
  }, [sessionDate, strategyMode]);

  const compute = useCallback(async () => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/compute/v0`, { method: "POST", body: form });
    if (res.ok) {
      const data = await res.json();
      setDecisions(data.decisions || []);
      setLogs((prev) => [`Computed regimes (${data.decisions?.length || 0})`, ...prev]);
    } else {
      alert("Compute failed");
    }
  }, [sessionDate, sessionId]);

  const decisionTable = useMemo(
    () =>
      decisions.map((d) => (
        <tr key={d.underlying}>
          <td>{d.underlying}</td>
          <td>{d.regime}</td>
          <td>{d.confidence}</td>
        </tr>
      )),
    [decisions]
  );

  return (
    <div style={{ fontFamily: "Arial, sans-serif", padding: 24, display: "grid", gap: 16 }}>
      <header>
        <h1>Regime-First EOD v0</h1>
        <p>Ingest UW datasets, build boolean features, classify regimes, and stage next-day plans.</p>
      </header>

      <section style={{ display: "grid", gap: 8, maxWidth: 640 }}>
        <label>
          Session Date (YYYY-MM-DD)
          <input value={sessionDate} onChange={(e) => setSessionDate(e.target.value)} placeholder="2024-01-05" />
        </label>
        <label>
          Strategy Mode
          <select value={strategyMode} onChange={(e) => setStrategyMode(e.target.value)}>
            <option value="INDEX_EOD">INDEX_EOD</option>
            <option value="EQUITY_THU_EOD">EQUITY_THU_EOD</option>
          </select>
        </label>
        <button disabled={!sessionDate} onClick={createSession}>
          Create Session
        </button>
        {sessionId && <div>Session ID: {sessionId}</div>}
      </section>

      <UploadDataset apiBase={API_BASE} sessionId={sessionId} onUploaded={(msg) => setLogs((prev) => [msg, ...prev])} />

      <SessionDashboard sessionId={sessionId} onCompute={compute} decisionTable={decisionTable} />

      <ManualOutcomeLabel apiBase={API_BASE} defaultDate={sessionDate} onSaved={(msg) => setLogs((prev) => [msg, ...prev])} />

      <LogsPanel logs={logs} />
    </div>
  );
}

export default App;
