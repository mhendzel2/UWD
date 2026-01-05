import React, { useCallback, useEffect, useMemo, useState } from "react";
import "./AnomaliesPanel.css";
import LoadingState from "./common/LoadingState";
import ErrorState from "./common/ErrorState";
import EmptyState from "./common/EmptyState";
import StatusBadge from "./common/StatusBadge";

type Props = {
  apiBase: string;
  sessionId: string;
  sessionDate: string;
  onLog?: (msg: string) => void;
};

type FeatureMetric = {
  value?: number;
  robust_z?: number;
  percentile?: number;
  center?: number;
  scale?: number;
};

type AnomalyEvent = {
  source: string;
  ticker: string;
  event_key: string;
  severity_score: number;
  ensemble_score: number;
  reason_codes: string[];
  feature_payload: Record<string, FeatureMetric>;
  raw_ref?: Record<string, any>;
};

type Rollup = {
  ticker: string;
  severity_score: number;
  ensemble_score: number;
  reason_codes: string[];
  feature_payload?: any;
  raw_ref?: any;
};

const sources = ["ALL", "OI_DIFF", "HOT_CHAINS", "DARKPOOL_EOD", "STOCK_SCREENER"];
const HEAVY_DATASET_THRESHOLD = 500;

const AnomaliesPanel: React.FC<Props> = ({ apiBase, sessionId, sessionDate, onLog }) => {
  const [lookback, setLookback] = useState<string>("30");
  const [minScore, setMinScore] = useState<string>("0.0");
  const [tickerFilter, setTickerFilter] = useState<string>("");
  const [sourceFilter, setSourceFilter] = useState<string>("ALL");
  const [events, setEvents] = useState<AnomalyEvent[]>([]);
  const [rollups, setRollups] = useState<Rollup[]>([]);
  const [selected, setSelected] = useState<AnomalyEvent | null>(null);
  const [fetching, setFetching] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [displayLimit, setDisplayLimit] = useState<number>(300);

  const fetchAnomalies = useCallback(async () => {
    if (!sessionId) return;
    setFetching(true);
    setError("");
    const params = new URLSearchParams();
    if (tickerFilter) params.append("ticker", tickerFilter.trim().toUpperCase());
    if (sourceFilter !== "ALL") params.append("source", sourceFilter);
    if (minScore) params.append("min_score", minScore);
    params.append("limit", "250");

    try {
      const res = await fetch(`${apiBase}/sessions/${sessionId}/anomalies?${params.toString()}`);
      if (!res.ok) {
        throw new Error("Failed to load anomalies");
      }
      const json = await res.json();
      setEvents(json.events || []);
      setRollups(json.rollups || []);
      setDisplayLimit(300);
      if (json.events && json.events.length > 0) {
        setSelected(json.events[0]);
      }
      setLastUpdated(Date.now());
      onLog?.(`Anomalies refreshed (${json.events?.length || 0} events)`);
    } catch (e: any) {
      setError(e?.message || "Failed to load anomalies");
    } finally {
      setFetching(false);
    }
  }, [apiBase, minScore, onLog, sessionId, sourceFilter, tickerFilter]);

  useEffect(() => {
    fetchAnomalies();
  }, [fetchAnomalies, sessionId]);

  const computeAnomalies = useCallback(async () => {
    if (!sessionId) {
      setError("Create or select a session first.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("session_id", sessionId);
      form.append("lookback_sessions", lookback || "30");
      const res = await fetch(`${apiBase}/compute/anomalies_v1`, { method: "POST", body: form });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || "Compute failed");
      }
      const json = await res.json();
      setEvents(json.events || []);
      setRollups(json.rollups || []);
      setSelected(json.events?.[0] ?? null);
      setDisplayLimit(300);
      setLastUpdated(Date.now());
      onLog?.(`Anomalies computed (${json.summary?.total_events || 0} events)`);
    } catch (e: any) {
      setError(e?.message || "Compute failed");
    } finally {
      setLoading(false);
    }
  }, [apiBase, lookback, onLog, sessionId]);

  const summary = useMemo(() => {
    const bySource: Record<string, number> = {};
    events.forEach((e) => {
      bySource[e.source] = (bySource[e.source] || 0) + 1;
    });
    return bySource;
  }, [events]);

  const selectedRollup = useMemo(() => {
    if (!selected) return null;
    return rollups.find((r) => r.ticker === selected.ticker) || null;
  }, [rollups, selected]);

  const featureRows = useMemo(() => {
    if (!selected) return [];
    return Object.entries(selected.feature_payload || {})
      .map(([name, metrics]) => ({
        name,
        z: metrics.robust_z ?? 0,
        pct: metrics.percentile ?? 0,
        value: metrics.value,
      }))
      .sort((a, b) => Math.abs(b.z) - Math.abs(a.z))
      .slice(0, 8);
  }, [selected]);

  const visibleEvents = useMemo(() => events.slice(0, displayLimit), [displayLimit, events]);
  const isTruncated = events.length > displayLimit;
  const isHeavyDataset = events.length > HEAVY_DATASET_THRESHOLD;

  return (
    <section className="anomalyPanel">
      <div className="anomalyHeader">
        <div>
          <div className="eyebrow">Interpretability-first</div>
          <h2 className="title">Anomalies Review Queue</h2>
          <p className="subtitle">Session {sessionDate || "—"} • Median/MAD normalization with per-source context.</p>
        </div>
        <div className="chip">
          <span className="chipLabel">Lookback</span>
          <input value={lookback} onChange={(e) => setLookback(e.target.value)} className="chipInput" />
          <span className="chipSuffix">sessions</span>
        </div>
      </div>

      <div className="controlGrid">
        <label className="control">
          Ticker
          <input value={tickerFilter} onChange={(e) => setTickerFilter(e.target.value)} placeholder="SPY" aria-label="Ticker filter" />
        </label>
        <label className="control">
          Source
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} aria-label="Source filter">
            {sources.map((s) => (
              <option key={s} value={s}>
                {s === "ALL" ? "All sources" : s}
              </option>
            ))}
          </select>
        </label>
        <label className="control">
          Min severity
          <input value={minScore} onChange={(e) => setMinScore(e.target.value)} placeholder="0.3" aria-label="Minimum severity score" />
        </label>
        <div className="control actions">
          <button onClick={fetchAnomalies} className="ghost">
            Refresh
          </button>
          <button onClick={computeAnomalies} disabled={loading || !sessionId}>
            {loading ? "Computing…" : "Compute anomalies"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <StatusBadge tone={loading || fetching ? "info" : "success"} label={loading ? "Computing" : "Live"} />
        {lastUpdated && <span className="subtitle">Updated {new Date(lastUpdated).toLocaleTimeString()}</span>}
        {isHeavyDataset && <StatusBadge tone="warning" label="Large dataset - narrow filters" subdued />}
      </div>

      {error && <ErrorState message={error} onRetry={fetchAnomalies} />}
      {(fetching || loading) && <LoadingState label={loading ? "Computing anomalies…" : "Refreshing anomalies…"} />}

      <div className="summaryRow">
        {Object.entries(summary).map(([src, count]) => (
          <div key={src} className="pill">
            <div className="pillLabel">{src}</div>
            <div className="pillValue">{count}</div>
          </div>
        ))}
        {rollups.slice(0, 3).map((r) => (
          <div key={r.ticker} className="pill highlight">
            <div className="pillLabel">{r.ticker}</div>
            <div className="pillValue">{r.severity_score?.toFixed(2)}</div>
            <div className="pillHint">rollup</div>
          </div>
        ))}
      </div>

      <div className="tableWrap">
        <table className="anomalyTable">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Source</th>
              <th>Severity</th>
              <th>Ensemble</th>
              <th>Reasons</th>
              <th>Event Key</th>
            </tr>
          </thead>
          <tbody>
            {visibleEvents.map((ev) => (
              <tr
                key={`${ev.event_key}-${ev.source}`}
                className={selected?.event_key === ev.event_key ? "selectedRow" : ""}
                onClick={() => setSelected(ev)}
              >
                <td>{ev.ticker}</td>
                <td>{ev.source}</td>
                <td className="numeric">{ev.severity_score?.toFixed(2)}</td>
                <td className="numeric">{ev.ensemble_score?.toFixed(2)}</td>
                <td className="reasonCell">
                  {ev.reason_codes?.slice(0, 3).map((r, idx) => (
                    <span key={idx} className="reasonChip">
                      {r}
                    </span>
                  ))}
                </td>
                <td className="eventKey">{ev.event_key}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!events.length && !fetching && !loading && (
          <EmptyState
            title="No anomalies found"
            description="Broaden your filters or compute anomalies for this session."
            action={
              <button onClick={computeAnomalies} disabled={!sessionId}>
                Compute anomalies
              </button>
            }
          />
        )}
        {isTruncated && (
          <div className="summaryRow" style={{ marginTop: 8 }}>
            <div className="pill highlight">
              <div className="pillLabel">Performance guard</div>
              <div className="pillValue">
                Showing {visibleEvents.length} / {events.length}
              </div>
              <div className="pillHint">Use filters or load all</div>
            </div>
            <button onClick={() => setDisplayLimit(events.length)}>Show all</button>
          </div>
        )}
      </div>

      {selected && (
        <div className="detailDrawer">
          <div className="detailHeader">
            <div>
              <div className="eyebrow">Details</div>
              <h3 className="detailTitle">
                {selected.ticker} • {selected.source}
              </h3>
              <div className="smallMuted">Event {selected.event_key}</div>
            </div>
            <div className="scoreBlock">
              <div className="scoreLabel">Severity</div>
              <div className="scoreValue">{selected.severity_score?.toFixed(2)}</div>
              <div className="scoreHint">Ensemble {selected.ensemble_score?.toFixed(2)}</div>
            </div>
          </div>

          <div className="reasonList">
            {selected.reason_codes?.map((r, idx) => (
              <div key={idx} className="reasonRow">
                <div className="bullet" />
                <span>{r}</span>
              </div>
            ))}
          </div>

          <div className="featureGrid">
            {featureRows.map((f) => (
              <div key={f.name} className="featureCard">
                <div className="featureName">{f.name}</div>
                <div className="featureValue">{f.value ?? "—"}</div>
                <div className="featureMeta">
                  <span>z {f.z.toFixed(2)}</span>
                  <span>pct {(f.pct * 100).toFixed(1)}%</span>
                </div>
              </div>
            ))}
          </div>

          {selectedRollup && (
            <div className="rollupCard">
              <div className="rollupHeader">
                <div>
                  <div className="eyebrow">Ticker rollup</div>
                  <div className="rollupTitle">{selectedRollup.ticker}</div>
                </div>
                <div className="scoreBlock compact">
                  <div className="scoreLabel">Severity</div>
                  <div className="scoreValue">{selectedRollup.severity_score?.toFixed(2)}</div>
                </div>
              </div>
              <div className="rollupReasons">
                {selectedRollup.reason_codes?.map((r, idx) => (
                  <span key={idx} className="reasonChip">
                    {r}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
};

export default AnomaliesPanel;
