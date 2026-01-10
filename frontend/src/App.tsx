import React, { useCallback, useMemo, useState, useEffect } from "react";
import UploadDataset from "./components/UploadDataset";
import SessionDashboard from "./components/SessionDashboard";
import ManualOutcomeLabel from "./components/ManualOutcomeLabel";
import LogsPanel from "./components/LogsPanel";
import DailyBriefsPanel from "./components/DailyBriefsPanel";
import EcologyPanel from "./components/EcologyPanel";
import EnsemblePanel from "./components/EnsemblePanel";
import ChartsPanel from "./components/ChartsPanel";
import OutlierDetectionPanel from "./components/OutlierDetectionPanel";
import AnomaliesPanel from "./components/AnomaliesPanel";
import ToastShelf from "./components/ToastShelf";
import OptionsSignalsDashboard from "./components/options_signals/OptionsSignalsDashboard";
import { UserStateProvider, useUserState } from "./state/user";
import { handleAuthFailure } from "./utils/http";
import "./App.css";

const API_BASE = "http://localhost:8000";

type Decision = { underlying: string; regime: string; confidence: string };
type RegimeRow = { underlying: string; regime_label?: string; confidence_tier?: string; ecology_state?: any; dominant_horizon_hint?: string | null };
type Brief = { brief_type: string; entries: any };
type Ensemble = { underlying: string; ensemble_label: string; ensemble_confidence?: number; horizon_weights?: Record<string, number>; component_votes?: any; stability_metrics?: any };

function AppContent() {
  const [activeView, setActiveView] = useState<"regime" | "options">("regime");
  const [sessionId, setSessionId] = useState<string>("");
  const [sessionDate, setSessionDate] = useState<string>("");
  const [strategyMode, setStrategyMode] = useState<string>("INDEX_EOD");
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [regimes, setRegimes] = useState<RegimeRow[]>([]);
  const [briefs, setBriefs] = useState<Brief[]>([]);
  const [ensembles, setEnsembles] = useState<Ensemble[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const { token, pushToast } = useUserState();

  const authHeaders = useMemo<HeadersInit | undefined>(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token]);

  const loadLatestSession = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/sessions/latest`);
      if (res.ok) {
        const data = await res.json();
        setSessionId(data.session_id);
        setSessionDate(data.date);
        setStrategyMode(data.strategy_mode);
        setLogs((prev) => [`Loaded latest session ${data.date}`, ...prev]);
      }
    } catch (e) {
      console.error("Failed to load latest session", e);
    }
  }, []);

  useEffect(() => {
    loadLatestSession();
  }, [loadLatestSession]);

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

  useEffect(() => {
    if (sessionId) {
      loadRegimes();
      loadBriefs();
      loadEnsembles();
    }
  }, [loadBriefs, loadEnsembles, loadRegimes, sessionId]);

  const createSession = useCallback(async () => {
    const form = new FormData();
    form.append("session_date", sessionDate);
    form.append("strategy_mode", strategyMode);
    const res = await fetch(`${API_BASE}/sessions`, { method: "POST", body: form });
    if (!res.ok) {
      pushToast({ tone: "error", message: "Failed to create session" });
      return;
    }
    const data = await res.json();
    setSessionId(data.session_id);
    setDecisions([]);
    setRegimes([]);
    setBriefs([]);
    setEnsembles([]);
    setLogs((prev) => [`Created session ${data.session_id}`, ...prev]);
  }, [pushToast, sessionDate, strategyMode]);

  const ensureAuthToken = useCallback(() => {
    if (!token) {
      pushToast({ tone: "error", message: "Add an auth token to run compute endpoints." });
      return false;
    }
    return true;
  }, [pushToast, token]);

  const compute = useCallback(async () => {
    if (!sessionId) {
      pushToast({ tone: "error", message: "Create a session first" });
      return;
    }
    if (!ensureAuthToken()) return;
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/compute/v0`, { method: "POST", body: form, headers: authHeaders });
    if (await handleAuthFailure(res, pushToast)) return;
    if (res.ok) {
      const data = await res.json();
      setDecisions(data.decisions || []);
      setLogs((prev) => [`Computed v0 regimes (${data.decisions?.length || 0})`, ...prev]);
      loadRegimes();
    } else {
      pushToast({ tone: "error", message: "Compute failed" });
    }
  }, [authHeaders, ensureAuthToken, loadRegimes, pushToast, sessionDate, sessionId]);

  const computeEcology = useCallback(async () => {
    if (!sessionId) {
      pushToast({ tone: "error", message: "Create a session first" });
      return;
    }
    if (!ensureAuthToken()) return;
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/compute/ecology_v0`, { method: "POST", body: form, headers: authHeaders });
    if (await handleAuthFailure(res, pushToast)) return;
    if (res.ok) {
      const data = await res.json();
      setLogs((prev) => [`Ecology updated (${data.updated})`, ...prev]);
      loadRegimes();
    } else {
      pushToast({ tone: "error", message: "Ecology compute failed" });
    }
  }, [authHeaders, ensureAuthToken, loadRegimes, pushToast, sessionDate, sessionId]);

  const generateDailyBriefs = useCallback(async () => {
    if (!sessionId) {
      pushToast({ tone: "error", message: "Create a session first" });
      return;
    }
    if (!ensureAuthToken()) return;
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/briefs/generate_v1`, { method: "POST", body: form, headers: authHeaders });
    if (await handleAuthFailure(res, pushToast)) return;
    if (res.ok) {
      const data = await res.json();
      setBriefs(data.briefs || []);
      setLogs((prev) => [`Generated briefs (${data.briefs?.length || 0})`, ...prev]);
    } else {
      pushToast({ tone: "error", message: "Brief generation failed" });
    }
  }, [authHeaders, ensureAuthToken, pushToast, sessionDate, sessionId]);

  const computeV1 = useCallback(async () => {
    if (!sessionId) {
      pushToast({ tone: "error", message: "Create a session first" });
      return;
    }
    if (!ensureAuthToken()) return;
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("asof_date", sessionDate);
    const res = await fetch(`${API_BASE}/compute/v1`, { method: "POST", body: form, headers: authHeaders });
    if (await handleAuthFailure(res, pushToast)) return;
    if (res.ok) {
      const data = await res.json();
      if (data.ensembles) {
        setEnsembles(data.ensembles);
      }
      setLogs((prev) => [`Computed v1 ensemble (${data.ensembles?.length || 0})`, ...prev]);
      loadEnsembles();
    } else {
      pushToast({ tone: "error", message: "v1 compute failed" });
    }
  }, [authHeaders, ensureAuthToken, loadEnsembles, pushToast, sessionDate, sessionId]);

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

  const handleSessionCreated = (id: string, date: string) => {
    setSessionId(id);
    setSessionDate(date);
    setLogs((prev) => [`Switched to session ${date}`, ...prev]);
  };

  return (
    <div className="appRoot">
      <ToastShelf />
      <header>
        <div className="appHeaderRow">
          <div>
            <h1>{activeView === "regime" ? "Regime-First EOD v1" : "Options Signals Dashboard"}</h1>
            <p>
              {activeView === "regime"
                ? "Discovery briefs, ecology interpretability, and v1 ensemble layered on v0 compatibility."
                : "Feature-engineered leading indicators and ranked opportunities per underlying."}
            </p>
          </div>
          <nav className="appNav">
            <button className={activeView === "regime" ? "active" : ""} onClick={() => setActiveView("regime")}>
              Regime Dashboard
            </button>
            <button className={activeView === "options" ? "active" : ""} onClick={() => setActiveView("options")}>
              Options Signals
            </button>
          </nav>
        </div>
      </header>

      {activeView === "regime" ? (
        <>
          <section className="sessionControls">
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

          <UploadDataset
            apiBase={API_BASE}
            sessionId={sessionId}
            onSessionCreated={handleSessionCreated}
            onUploaded={(msg) => setLogs((prev) => [msg, ...prev])}
          />

          <SessionDashboard
            apiBase={API_BASE}
            sessionId={sessionId}
            sessionDate={sessionDate}
            onCompute={compute}
            onComputeEcology={computeEcology}
            onGenerateBriefs={generateDailyBriefs}
            onComputeV1={computeV1}
            decisionTable={decisionTable}
          />

          <ChartsPanel regimes={regimes} />

          <AnomaliesPanel
            apiBase={API_BASE}
            sessionId={sessionId}
            sessionDate={sessionDate}
            onLog={(msg) => setLogs((prev) => [msg, ...prev])}
          />

          <OutlierDetectionPanel
            apiBase={API_BASE}
            sessionId={sessionId}
            sessionDate={sessionDate}
            onLog={(msg) => setLogs((prev) => [msg, ...prev])}
          />

          <DailyBriefsPanel briefs={briefs} regimeMap={regimeMap} />
          <EcologyPanel entries={ecologyEntries} />
          <EnsemblePanel ensembles={ensembles} />

          <ManualOutcomeLabel apiBase={API_BASE} defaultDate={sessionDate} onSaved={(msg) => setLogs((prev) => [msg, ...prev])} />

          <LogsPanel logs={logs} />
        </>
      ) : (
        <OptionsSignalsDashboard apiBase={API_BASE} />
      )}
    </div>
  );
}

export default function App() {
  return (
    <UserStateProvider>
      <AppContent />
    </UserStateProvider>
  );
}
