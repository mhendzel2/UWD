import React, { useCallback, useMemo, useState } from "react";
import UploadDataset from "./components/UploadDataset";
import SessionDashboard from "./components/SessionDashboard";
import ManualOutcomeLabel from "./components/ManualOutcomeLabel";
import LogsPanel from "./components/LogsPanel";
import DailyBriefsPanel from "./components/DailyBriefsPanel";
import EcologyPanel from "./components/EcologyPanel";
import EnsemblePanel from "./components/EnsemblePanel";

const API_BASE = "http://localhost:8000";

type Decision = { underlying: string; regime: string; confidence: string };
type RegimeRow = { underlying: string; regime_label?: string; confidence_tier?: string; ecology_state?: any; dominant_horizon_hint?: string | null };
type Brief = { brief_type: string; entries: any };
type Ensemble = { underlying: string; ensemble_label: string; ensemble_confidence?: number; horizon_weights?: Record<string, number>; component_votes?: any; stability_metrics?: any };

function App() {
  const [sessionId, setSessionId] = useState<string>("");
  const [sessionDate, setSessionDate] = useState<string>("");
  const [strategyMode, setStrategyMode] = useState<string>("INDEX_EOD");
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [regimes, setRegimes] = useState<RegimeRow[]>([]);
  const [briefs, setBriefs] = useState<Brief[]>([]);
  const [ensembles, setEnsembles] = useState<Ensemble[]>([]);
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
    setDecisions([]);
    setRegimes([]);
    setBriefs([]);
    setEnsembles([]);
    setLogs((prev) => [`Created session ${data.session_id}`, ...prev]);
  }, [sessionDate, strategyMode]);

  const loadRegimes = useCallback(async () => {
    if (!sessionId) return;
    const res = await fetch(`${API_BASE}/sessions/${sessionId}/regimes`);
    if (!res.ok) return;
    const data = await res.json();
    setRegimes(data.regimes || []);
  }, [sessionId]);

  const loadBriefs = useCallback(async () => {
    if (!sessionId) return;
    const res = await fetch(`${API_BASE}/sessions/${sessionId}/briefs`);
    if (!res.ok) return;
    const data = await res.json();
    setBriefs(data.briefs || []);
  }, [sessionId]);

  const loadEnsembles = useCallback(async () => {
    if (!sessionId) return;
    const res = await fetch(`${API_BASE}/sessions/${sessionId}/ensemble`);
    if (!res.ok) return;
    const data = await res.json();
    setEnsembles(data.ensembles || []);
  }, [sessionId]);

  const compute = useCallback(async () => {
    if (!sessionId) {
      alert("Create a session first");
      return;
    }
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/compute/v0`, { method: "POST", body: form });
    if (res.ok) {
      const data = await res.json();
      setDecisions(data.decisions || []);
      setLogs((prev) => [`Computed v0 regimes (${data.decisions?.length || 0})`, ...prev]);
      loadRegimes();
    } else {
      alert("Compute failed");
    }
  }, [sessionDate, sessionId, loadRegimes]);

  const computeEcology = useCallback(async () => {
    if (!sessionId) {
      alert("Create a session first");
      return;
    }
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/compute/ecology_v0`, { method: "POST", body: form });
    if (res.ok) {
      const data = await res.json();
      setLogs((prev) => [`Ecology updated (${data.updated})`, ...prev]);
      loadRegimes();
    } else {
      alert("Ecology compute failed");
    }
  }, [sessionDate, sessionId, loadRegimes]);

  const generateDailyBriefs = useCallback(async () => {
    if (!sessionId) {
      alert("Create a session first");
      return;
    }
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/briefs/generate_v1`, { method: "POST", body: form });
    if (res.ok) {
      const data = await res.json();
      setBriefs(data.briefs || []);
      setLogs((prev) => [`Generated briefs (${data.briefs?.length || 0})`, ...prev]);
    } else {
      alert("Brief generation failed");
    }
  }, [sessionDate, sessionId]);

  const computeV1 = useCallback(async () => {
    if (!sessionId) {
      alert("Create a session first");
      return;
    }
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/compute/v1`, { method: "POST", body: form });
    if (res.ok) {
      const data = await res.json();
      if (data.ensembles) {
        setEnsembles(data.ensembles);
      }
      setLogs((prev) => [`Computed v1 ensemble (${data.ensembles?.length || 0})`, ...prev]);
      loadEnsembles();
    } else {
      alert("v1 compute failed");
    }
  }, [sessionDate, sessionId, loadEnsembles]);

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

  const ecologyEntries = useMemo(() => regimes.filter((r) => r.ecology_state), [regimes]);
  const regimeMap = useMemo(() => {
    const map: Record<string, string> = {};
    regimes.forEach((r) => {
      if (r.underlying && r.regime_label) {
        map[r.underlying] = r.regime_label;
      }
    });
    return map;
  }, [regimes]);

  return (
    <div style={{ fontFamily: "Arial, sans-serif", padding: 24, display: "grid", gap: 16 }}>
      <header>
        <h1>Regime-First EOD v1</h1>
        <p>Discovery briefs, ecology interpretability, and v1 ensemble layered on v0 compatibility.</p>
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

      <SessionDashboard
        sessionId={sessionId}
        onCompute={compute}
        onComputeEcology={computeEcology}
        onGenerateBriefs={generateDailyBriefs}
        onComputeV1={computeV1}
        decisionTable={decisionTable}
      />

      <DailyBriefsPanel briefs={briefs} regimeMap={regimeMap} />
      <EcologyPanel entries={ecologyEntries} />
      <EnsemblePanel ensembles={ensembles} />

      <ManualOutcomeLabel apiBase={API_BASE} defaultDate={sessionDate} onSaved={(msg) => setLogs((prev) => [msg, ...prev])} />

      <LogsPanel logs={logs} />
    </div>
  );
}

export default App;
