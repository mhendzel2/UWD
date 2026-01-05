import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import UploadDataset from "./components/UploadDataset";
import SessionDashboard from "./components/SessionDashboard";
import ManualOutcomeLabel from "./components/ManualOutcomeLabel";
import LogsPanel from "./components/LogsPanel";
import DailyBriefsPanel from "./components/DailyBriefsPanel";
import EcologyPanel from "./components/EcologyPanel";
import EnsemblePanel from "./components/EnsemblePanel";
import ChartsPanel from "./components/ChartsPanel";
import OutlierDetectionPanel from "./components/OutlierDetectionPanel";
import AnomaliesPanel from "./components/AnomaliesPanel1";
import LoadingState from "./components/common/LoadingState";
import ErrorState from "./components/common/ErrorState";
import { capabilityDefaults } from "./theme";
import { LOG_BUFFER_LIMIT, LogEntry, LogLevel, appendLog } from "./utils/logBuffer";
import "./App.css";

const API_BASE = "http://localhost:8000";
const CACHE_TTL = 60_000;

type Decision = { underlying: string; regime: string; confidence: string };
type RegimeRow = { underlying: string; regime_label?: string; confidence_tier?: string; ecology_state?: any; dominant_horizon_hint?: string | null };
type Brief = { brief_type: string; entries: any; status?: string; updated_at?: string };
type Ensemble = { underlying: string; ensemble_label: string; ensemble_confidence?: number; horizon_weights?: Record<string, number>; component_votes?: any; stability_metrics?: any };

type ResourceState = {
  status: "idle" | "loading" | "success" | "error";
  error?: string;
  updatedAt?: number;
};

type Capabilities = {
  canComputeV0: boolean;
  canComputeEcology: boolean;
  canGenerateBriefs: boolean;
  canComputeEnsemble: boolean;
};

type LogConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

function App() {
  const [sessionId, setSessionId] = useState<string>("");
  const [sessionDate, setSessionDate] = useState<string>("");
  const [strategyMode, setStrategyMode] = useState<string>("INDEX_EOD");
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [regimes, setRegimes] = useState<RegimeRow[]>([]);
  const [briefs, setBriefs] = useState<Brief[]>([]);
  const [ensembles, setEnsembles] = useState<Ensemble[]>([]);
  const [regimeState, setRegimeState] = useState<ResourceState>({ status: "idle" });
  const [briefState, setBriefState] = useState<ResourceState>({ status: "idle" });
  const [ensembleState, setEnsembleState] = useState<ResourceState>({ status: "idle" });
  const [capabilityState, setCapabilityState] = useState<ResourceState>({ status: "idle" });
  const [capabilities, setCapabilities] = useState<Capabilities>(capabilityDefaults);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logLevelFilter, setLogLevelFilter] = useState<LogLevel | "all">("all");
  const [logSearch, setLogSearch] = useState<string>("");
  const [logStatus, setLogStatus] = useState<LogConnectionStatus>("disconnected");
  const reconnectTimer = useRef<number | null>(null);
  const regimeUpdatedAt = useRef<number | null>(null);
  const briefUpdatedAt = useRef<number | null>(null);
  const ensembleUpdatedAt = useRef<number | null>(null);
  const capabilityUpdatedAt = useRef<number | null>(null);

  const pushLog = useCallback((message: string, level: LogLevel = "info") => {
    setLogs((prev) => appendLog(prev, { message, level, timestamp: Date.now() }));
  }, []);

  const shouldSkip = (updatedAt?: number | null) => !!updatedAt && Date.now() - updatedAt < CACHE_TTL;

  const loadLatestSession = useCallback(async () => {
    setRegimeState({ status: "loading" });
    try {
      const res = await fetch(`${API_BASE}/sessions/latest`);
      if (!res.ok) {
        throw new Error("Unable to load latest session");
      }
      const data = await res.json();
      setSessionId(data.session_id);
      setSessionDate(data.date);
      setStrategyMode(data.strategy_mode);
      pushLog(`Loaded latest session ${data.date}`);
    } catch (e: any) {
      setRegimeState({ status: "error", error: e?.message || "Failed to load latest session" });
      pushLog("Latest session lookup failed", "warning");
    }
  }, [pushLog]);

  const fetchCapabilities = useCallback(
    async (id: string) => {
      if (!id) return;
      if (shouldSkip(capabilityUpdatedAt.current)) return;
      setCapabilityState({ status: "loading" });
      try {
        const res = await fetch(`${API_BASE}/sessions/${id}/capabilities`);
        if (!res.ok) throw new Error("Capability endpoint unavailable");
        const data = await res.json();
        setCapabilities({ ...capabilityDefaults, ...data.capabilities });
        const updatedAt = Date.now();
        capabilityUpdatedAt.current = updatedAt;
        setCapabilityState({ status: "success", updatedAt });
      } catch (e: any) {
        setCapabilities(capabilityDefaults);
        const updatedAt = Date.now();
        capabilityUpdatedAt.current = updatedAt;
        setCapabilityState({ status: "error", error: e?.message || "Capability lookup failed", updatedAt });
        pushLog("Capabilities defaulted (endpoint unavailable)", "warning");
      }
    },
    [pushLog]
  );

  const loadRegimes = useCallback(
    async (force = false) => {
      if (!sessionId) return;
      if (!force && shouldSkip(regimeUpdatedAt.current)) return;
      setRegimeState({ status: "loading" });
      try {
        const res = await fetch(`${API_BASE}/sessions/${sessionId}/regimes`);
        if (!res.ok) throw new Error("Failed to load regimes");
        const data = await res.json();
        setRegimes(data.regimes || []);
        const updatedAt = Date.now();
        regimeUpdatedAt.current = updatedAt;
        setRegimeState({ status: "success", updatedAt });
      } catch (e: any) {
        setRegimeState({ status: "error", error: e?.message || "Failed to load regimes" });
      }
    },
    [sessionId]
  );

  const loadBriefs = useCallback(
    async (force = false) => {
      if (!sessionId) return;
      if (!force && shouldSkip(briefUpdatedAt.current)) return;
      setBriefState({ status: "loading" });
      try {
        const res = await fetch(`${API_BASE}/sessions/${sessionId}/briefs`);
        if (!res.ok) throw new Error("Failed to load briefs");
        const data = await res.json();
        setBriefs(data.briefs || []);
        const updatedAt = Date.now();
        briefUpdatedAt.current = updatedAt;
        setBriefState({ status: "success", updatedAt });
      } catch (e: any) {
        setBriefState({ status: "error", error: e?.message || "Failed to load briefs" });
      }
    },
    [sessionId]
  );

  const loadEnsembles = useCallback(
    async (force = false) => {
      if (!sessionId) return;
      if (!force && shouldSkip(ensembleUpdatedAt.current)) return;
      setEnsembleState({ status: "loading" });
      try {
        const res = await fetch(`${API_BASE}/sessions/${sessionId}/ensemble`);
        if (!res.ok) throw new Error("Failed to load ensembles");
        const data = await res.json();
        setEnsembles(data.ensembles || []);
        const updatedAt = Date.now();
        ensembleUpdatedAt.current = updatedAt;
        setEnsembleState({ status: "success", updatedAt });
      } catch (e: any) {
        setEnsembleState({ status: "error", error: e?.message || "Failed to load ensembles" });
      }
    },
    [sessionId]
  );

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
    setRegimeState({ status: "idle" });
    setBriefState({ status: "idle" });
    setEnsembleState({ status: "idle" });
    regimeUpdatedAt.current = null;
    briefUpdatedAt.current = null;
    ensembleUpdatedAt.current = null;
    capabilityUpdatedAt.current = null;
    pushLog(`Created session ${data.session_id}`);
  }, [pushLog, sessionDate, strategyMode]);

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
      pushLog(`Computed v0 regimes (${data.decisions?.length || 0})`);
      loadRegimes(true);
    } else {
      alert("Compute failed");
      pushLog("Compute v0 failed", "error");
    }
  }, [loadRegimes, pushLog, sessionDate, sessionId]);

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
      pushLog(`Ecology updated (${data.updated})`);
      loadRegimes(true);
    } else {
      alert("Ecology compute failed");
      pushLog("Ecology compute failed", "error");
    }
  }, [loadRegimes, pushLog, sessionDate, sessionId]);

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
      pushLog(`Generated briefs (${data.briefs?.length || 0})`);
      const updatedAt = Date.now();
      briefUpdatedAt.current = updatedAt;
      setBriefState({ status: "success", updatedAt });
    } else {
      alert("Brief generation failed");
      pushLog("Brief generation failed", "error");
    }
  }, [pushLog, sessionDate, sessionId]);

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
      pushLog(`Computed v1 ensemble (${data.ensembles?.length || 0})`);
      const updatedAt = Date.now();
      ensembleUpdatedAt.current = updatedAt;
      setEnsembleState({ status: "success", updatedAt });
      loadEnsembles(true);
    } else {
      alert("v1 compute failed");
      pushLog("v1 compute failed", "error");
    }
  }, [loadEnsembles, pushLog, sessionDate, sessionId]);

  useEffect(() => {
    loadLatestSession();
  }, [loadLatestSession]);

  useEffect(() => {
    if (sessionId) {
      loadRegimes(true);
      loadBriefs(true);
      loadEnsembles(true);
      fetchCapabilities(sessionId);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setLogStatus("disconnected");
      return;
    }
    const wsUrl = API_BASE.replace(/^http/, "ws") + "/ws/logs";
    let socket: WebSocket | null = null;

    const connect = () => {
      setLogStatus("connecting");
      socket = new WebSocket(wsUrl);
      socket.onopen = () => setLogStatus("connected");
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const entry = payload.message || payload.detail || event.data;
          pushLog(entry, (payload.level as LogLevel) || "info");
        } catch {
          pushLog(event.data, "info");
        }
      };
      socket.onerror = () => setLogStatus("error");
      socket.onclose = () => {
        setLogStatus("error");
        if (reconnectTimer.current) {
          window.clearTimeout(reconnectTimer.current);
        }
        reconnectTimer.current = window.setTimeout(() => connect(), 3000);
      };
    };

    connect();
    return () => {
      if (reconnectTimer.current) {
        window.clearTimeout(reconnectTimer.current);
      }
      socket?.close();
    };
  }, [pushLog, sessionId]);

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

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      if (logLevelFilter !== "all" && log.level && log.level !== logLevelFilter) return false;
      if (logSearch && !log.message.toLowerCase().includes(logSearch.toLowerCase())) return false;
      return true;
    });
  }, [logLevelFilter, logSearch, logs]);

  const handleSessionCreated = (id: string, date: string) => {
    setSessionId(id);
    setSessionDate(date);
    regimeUpdatedAt.current = null;
    briefUpdatedAt.current = null;
    ensembleUpdatedAt.current = null;
    capabilityUpdatedAt.current = null;
    pushLog(`Switched to session ${date}`);
  };

  return (
    <div className="appRoot">
      <header>
        <div>
          <p className="sr-only">Regime-first dashboard</p>
          <h1>Regime-First EOD v1</h1>
          <p>Discovery briefs, ecology interpretability, and v1 ensemble layered on v0 compatibility.</p>
        </div>
        <div aria-live="polite" style={{ color: "#94a3b8" }}>
          Logs buffered to {LOG_BUFFER_LIMIT} entries.
        </div>
      </header>

      <section className="sessionControls" aria-label="Session configuration">
        <label>
          Session Date (YYYY-MM-DD)
          <input
            value={sessionDate}
            onChange={(e) => setSessionDate(e.target.value)}
            placeholder="2024-01-05"
            aria-label="Session date in YYYY-MM-DD format"
          />
        </label>
        <label>
          Strategy Mode
          <select value={strategyMode} onChange={(e) => setStrategyMode(e.target.value)} aria-label="Strategy mode">
            <option value="INDEX_EOD">INDEX_EOD</option>
            <option value="EQUITY_THU_EOD">EQUITY_THU_EOD</option>
          </select>
        </label>
        <button disabled={!sessionDate} onClick={createSession} aria-label="Create new session">
          Create Session
        </button>
        {sessionId && <div aria-live="polite">Session ID: {sessionId}</div>}
      </section>

      {regimeState.status === "loading" && <LoadingState label="Loading latest session…" tone="accent" />}
      {regimeState.status === "error" && (
        <ErrorState message={regimeState.error || "Unable to load session"} onRetry={() => loadLatestSession()} />
      )}

      <div className="gridTwo">
        <UploadDataset
          apiBase={API_BASE}
          sessionId={sessionId}
          onSessionCreated={handleSessionCreated}
          onUploaded={(msg) => pushLog(msg)}
        />

        <SessionDashboard
          sessionId={sessionId}
          onCompute={compute}
          onComputeEcology={computeEcology}
          onGenerateBriefs={generateDailyBriefs}
          onComputeV1={computeV1}
          decisionTable={decisionTable}
          regimeState={regimeState}
          briefState={briefState}
          ensembleState={ensembleState}
          onRefreshRegimes={() => loadRegimes(true)}
          onRefreshBriefs={() => loadBriefs(true)}
          onRefreshEnsembles={() => loadEnsembles(true)}
          capabilities={capabilities}
          capabilityState={capabilityState}
        />
      </div>

      <ChartsPanel regimes={regimes} />

      <div className="gridTwo">
        <AnomaliesPanel
          apiBase={API_BASE}
          sessionId={sessionId}
          sessionDate={sessionDate}
          onLog={(msg) => pushLog(msg)}
        />

        <OutlierDetectionPanel
          apiBase={API_BASE}
          sessionId={sessionId}
          sessionDate={sessionDate}
          onLog={(msg) => pushLog(msg)}
        />
      </div>

      <div className="gridTwo">
        <DailyBriefsPanel briefs={briefs} regimeMap={regimeMap} status={briefState} />
        <EcologyPanel entries={ecologyEntries} status={regimeState} />
      </div>
      <div className="gridTwo">
        <EnsemblePanel ensembles={ensembles} status={ensembleState} />
        <ManualOutcomeLabel apiBase={API_BASE} defaultDate={sessionDate} onSaved={(msg) => pushLog(msg)} />
      </div>

      <LogsPanel
        logs={filteredLogs}
        onLevelChange={setLogLevelFilter}
        level={logLevelFilter}
        search={logSearch}
        onSearch={setLogSearch}
        status={logStatus}
      />
    </div>
  );
}

export default App;
