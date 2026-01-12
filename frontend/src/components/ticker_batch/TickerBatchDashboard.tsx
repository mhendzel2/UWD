import React, { useCallback, useEffect, useMemo, useState } from "react";
import "./TickerBatchDashboard.css";
import { normalizeTicker, parseTickersFromText } from "../../utils/tickerCsv";

type RegimeRow = {
  underlying: string;
  regime_label?: string | null;
  confidence_tier?: string | null;
  dominant_horizon_hint?: string | null;
  ecology_state?: any;
};

type EnsembleRow = {
  underlying: string;
  ensemble_label?: string | null;
  ensemble_confidence?: number | null;
  component_votes?: any;
  stability_metrics?: any;
};

type AnomalyRollup = {
  ticker: string;
  severity_score?: number | null;
  ensemble_score?: number | null;
  reason_codes?: string[];
  feature_payload?: any;
  raw_ref?: any;
  computed_at?: string | null;
};

type AnomalyEvent = {
  source?: string | null;
  ticker: string;
  event_key?: string | null;
  severity_score?: number | null;
  ensemble_score?: number | null;
  reason_codes?: string[];
  feature_payload?: any;
  raw_ref?: any;
  computed_at?: string | null;
};

type OptionsSignalRegistry = { signals?: Array<{ name: string; label: string; enabled: boolean }> };

type OptionsScreenerRow = {
  trade_date: string;
  underlying_symbol: string;
  signal_score?: number | null;
  signal_rank?: number | null;
  sector?: string | null;
  close?: number | null;
  ret_1d?: number | null;
  iv_rank_252?: number | null;
  iv_minus_rv20?: number | null;
  put_call_vol_ratio?: number | null;
  net_premium?: number | null;
};

type SortKey =
  | "ticker"
  | "regime"
  | "ensemble"
  | "ensemble_confidence"
  | "anomaly_severity"
  | "anomaly_ensemble"
  | "os_signal_score"
  | "os_signal_rank";

function toCsv(rows: Array<Record<string, any>>, columns: string[]): string {
  const esc = (v: any) => {
    const s = v === null || v === undefined ? "" : String(v);
    if (/[\r\n\",]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const header = columns.map(esc).join(",");
  const body = rows.map((r) => columns.map((c) => esc(r[c])).join(",")).join("\n");
  return `${header}\n${body}\n`;
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function TickerBatchDashboard({
  apiBase,
  sessionId,
  sessionDate,
}: {
  apiBase: string;
  sessionId: string;
  sessionDate: string;
}) {
  const [fileName, setFileName] = useState<string>("");
  const [rawInput, setRawInput] = useState<string>("");
  const [tickers, setTickers] = useState<string[]>([]);

  const [devPath, setDevPath] = useState<string>("C:\\Users\\mjhen\\Downloads\\screener-results (1).csv");
  const [devPathStatus, setDevPathStatus] = useState<string>("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const [regimes, setRegimes] = useState<RegimeRow[]>([]);
  const [ensembles, setEnsembles] = useState<EnsembleRow[]>([]);
  const [anomalyRollups, setAnomalyRollups] = useState<AnomalyRollup[]>([]);

  const [autoLoadSessionData, setAutoLoadSessionData] = useState<boolean>(true);
  const [autoLoadOptionsSignals, setAutoLoadOptionsSignals] = useState<boolean>(true);

  const [selectedTicker, setSelectedTicker] = useState<string>("");
  const [selectedTickerEvents, setSelectedTickerEvents] = useState<AnomalyEvent[]>([]);

  const today = new Date().toISOString().slice(0, 10);
  const [optionsDate, setOptionsDate] = useState<string>(sessionDate || today);
  const [optionsRegistry, setOptionsRegistry] = useState<OptionsSignalRegistry>({});
  const [optionsSignal, setOptionsSignal] = useState<string>("BULL_FLOW");
  const [optionsRows, setOptionsRows] = useState<OptionsScreenerRow[]>([]);

  const [sortKey, setSortKey] = useState<SortKey>("anomaly_severity");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    setTickers(parseTickersFromText(rawInput));
  }, [rawInput]);

  useEffect(() => {
    setOptionsDate(sessionDate || today);
  }, [sessionDate, today]);

  const onFile = useCallback(async (file: File | null) => {
    if (!file) return;
    setFileName(file.name);
    const text = await file.text();
    setRawInput(text);
  }, []);

  const loadFromDevPath = useCallback(async () => {
    setDevPathStatus("");
    if (!devPath.trim()) return;

    try {
      const params = new URLSearchParams();
      params.set("path", devPath.trim());
      const res = await fetch(`${apiBase}/dev/local-file-text?${params.toString()}`);
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || "Dev path load failed");
      }
      const json = await res.json();
      setRawInput(String(json.text || ""));
      setFileName(String(json.path || devPath.trim()));
      setDevPathStatus(`Loaded ${json.bytes ?? ""} bytes`);
    } catch (e: any) {
      setDevPathStatus(e?.message || "Dev path load failed");
    }
  }, [apiBase, devPath]);

  const loadSessionData = useCallback(async () => {
    if (!sessionId) {
      setError("Create or load a session first (top of the app).");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const [rRes, eRes, aRes] = await Promise.all([
        fetch(`${apiBase}/sessions/${sessionId}/regimes`),
        fetch(`${apiBase}/sessions/${sessionId}/ensemble`),
        fetch(`${apiBase}/sessions/${sessionId}/anomalies`),
      ]);

      if (!rRes.ok) throw new Error("Failed to load regimes");
      if (!eRes.ok) throw new Error("Failed to load ensembles");
      if (!aRes.ok) throw new Error("Failed to load anomalies/rollups");

      const regimesJson = await rRes.json();
      const ensemblesJson = await eRes.json();
      const anomaliesJson = await aRes.json();

      setRegimes(regimesJson.regimes || []);
      setEnsembles(ensemblesJson.ensembles || []);
      setAnomalyRollups(anomaliesJson.rollups || []);
    } catch (e: any) {
      setError(e?.message || "Failed to load session data");
    } finally {
      setLoading(false);
    }
  }, [apiBase, sessionId]);

  useEffect(() => {
    // Load options signal registry (safe even without a session)
    fetch(`${apiBase}/options-signals/registry/signals`)
      .then((res) => res.json())
      .then((data) => setOptionsRegistry(data))
      .catch(() => setOptionsRegistry({}));
  }, [apiBase]);

  useEffect(() => {
    // Auto-default to latest available options-signals date if sessionDate is not set.
    if (sessionDate) return;
    fetch(`${apiBase}/options-signals/latest-date`)
      .then((res) => res.json())
      .then((data) => {
        const d = String(data?.date || "").trim();
        if (d) setOptionsDate(d);
      })
      .catch(() => {
        // ignore
      });
  }, [apiBase, sessionDate]);

  const loadOptionsSignals = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("date", optionsDate);
      params.set("signal", optionsSignal);
      const res = await fetch(`${apiBase}/options-signals/screener?${params.toString()}`);
      if (!res.ok) throw new Error("Failed to load options signals screener");
      const json = await res.json();
      setOptionsRows(json.rows || []);
    } catch (e: any) {
      setError(e?.message || "Failed to load options signals");
      setOptionsRows([]);
    } finally {
      setLoading(false);
    }
  }, [apiBase, optionsDate, optionsSignal]);

  useEffect(() => {
    if (!autoLoadSessionData) return;
    if (!sessionId) return;
    loadSessionData();
  }, [autoLoadSessionData, loadSessionData, sessionId]);

  useEffect(() => {
    if (!autoLoadOptionsSignals) return;
    // Safe: options screener is GET-only.
    loadOptionsSignals();
  }, [autoLoadOptionsSignals, loadOptionsSignals]);

  const loadSelectedTickerEvents = useCallback(
    async (ticker: string) => {
      if (!sessionId || !ticker) return;
      try {
        const params = new URLSearchParams();
        params.set("ticker", ticker);
        params.set("limit", "50");
        const res = await fetch(`${apiBase}/sessions/${sessionId}/anomalies?${params.toString()}`);
        if (!res.ok) {
          setSelectedTickerEvents([]);
          return;
        }
        const json = await res.json();
        setSelectedTickerEvents(json.events || []);
      } catch {
        setSelectedTickerEvents([]);
      }
    },
    [apiBase, sessionId]
  );

  const regimeByUnderlying = useMemo(() => {
    const map = new Map<string, RegimeRow>();
    for (const r of regimes) {
      if (!r?.underlying) continue;
      map.set(String(r.underlying).toUpperCase(), r);
    }
    return map;
  }, [regimes]);

  const ensembleByUnderlying = useMemo(() => {
    const map = new Map<string, EnsembleRow>();
    for (const e of ensembles) {
      if (!e?.underlying) continue;
      map.set(String(e.underlying).toUpperCase(), e);
    }
    return map;
  }, [ensembles]);

  const rollupByTicker = useMemo(() => {
    const map = new Map<string, AnomalyRollup>();
    for (const r of anomalyRollups) {
      if (!r?.ticker) continue;
      map.set(String(r.ticker).toUpperCase(), r);
    }
    return map;
  }, [anomalyRollups]);

  const optionsByTicker = useMemo(() => {
    const map = new Map<string, OptionsScreenerRow>();
    for (const row of optionsRows) {
      const t = normalizeTicker(row.underlying_symbol);
      if (!t) continue;
      map.set(t, row);
    }
    return map;
  }, [optionsRows]);

  const combinedRows = useMemo(() => {
    return tickers.map((t) => {
      const regime = regimeByUnderlying.get(t);
      const ensemble = ensembleByUnderlying.get(t);
      const rollup = rollupByTicker.get(t);
      const os = optionsByTicker.get(t);

      const anomalySeverity = rollup?.severity_score ?? null;
      const ensembleConf = ensemble?.ensemble_confidence ?? null;
      const osSignalScore = os?.signal_score ?? null;
      const osSignalRank = os?.signal_rank ?? null;

      return {
        ticker: t,
        regime_label: regime?.regime_label ?? null,
        confidence_tier: regime?.confidence_tier ?? null,
        dominant_horizon_hint: regime?.dominant_horizon_hint ?? null,
        ensemble_label: ensemble?.ensemble_label ?? null,
        ensemble_confidence: ensembleConf,
        anomaly_severity: anomalySeverity,
        anomaly_ensemble: rollup?.ensemble_score ?? null,
        anomaly_reason_codes: (rollup?.reason_codes || []).slice(0, 4).join("; ") || null,
        os_signal_score: osSignalScore,
        os_signal_rank: osSignalRank,
        os_sector: os?.sector ?? null,
      };
    });
  }, [tickers, regimeByUnderlying, ensembleByUnderlying, rollupByTicker, optionsByTicker]);

  const sortedRows = useMemo(() => {
    const rows = [...combinedRows];
    const dir = sortDir === "asc" ? 1 : -1;
    const cmpNum = (a: any, b: any) => {
      const av = a === null || a === undefined ? -Infinity : Number(a);
      const bv = b === null || b === undefined ? -Infinity : Number(b);
      if (av === bv) return 0;
      return av < bv ? -1 : 1;
    };
    const cmpStr = (a: any, b: any) => String(a || "").localeCompare(String(b || ""));

    rows.sort((ra, rb) => {
      switch (sortKey) {
        case "ticker":
          return dir * cmpStr(ra.ticker, rb.ticker);
        case "regime":
          return dir * cmpStr(ra.regime_label, rb.regime_label);
        case "ensemble":
          return dir * cmpStr(ra.ensemble_label, rb.ensemble_label);
        case "ensemble_confidence":
          return dir * cmpNum(ra.ensemble_confidence, rb.ensemble_confidence);
        case "anomaly_ensemble":
          return dir * cmpNum(ra.anomaly_ensemble, rb.anomaly_ensemble);
        case "os_signal_score":
          return dir * cmpNum(ra.os_signal_score, rb.os_signal_score);
        case "os_signal_rank":
          return dir * cmpNum(ra.os_signal_rank, rb.os_signal_rank);
        case "anomaly_severity":
        default:
          return dir * cmpNum(ra.anomaly_severity, rb.anomaly_severity);
      }
    });
    return rows;
  }, [combinedRows, sortDir, sortKey]);

  const stats = useMemo(() => {
    const n = tickers.length;
    const withRegime = combinedRows.filter((r) => r.regime_label).length;
    const withEnsemble = combinedRows.filter((r) => r.ensemble_label).length;
    const withAnomaly = combinedRows.filter((r) => typeof r.anomaly_severity === "number").length;
    const withOptions = combinedRows.filter((r) => typeof r.os_signal_score === "number").length;

    const top = [...combinedRows]
      .filter((r) => typeof r.anomaly_severity === "number")
      .sort((a, b) => Number(b.anomaly_severity) - Number(a.anomaly_severity))
      .slice(0, 5)
      .map((r) => `${r.ticker} (${Number(r.anomaly_severity).toFixed(3)})`)
      .join(", ");

    return { n, withRegime, withEnsemble, withAnomaly, withOptions, top };
  }, [combinedRows, tickers.length]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDir(key === "ticker" ? "asc" : "desc");
  };

  const optionsSignalOptions = useMemo(() => {
    const opts = optionsRegistry.signals || [];
    if (!opts.length) return [{ name: "BULL_FLOW", label: "Bullish Flow Signal", enabled: true }];
    return opts;
  }, [optionsRegistry.signals]);

  const exportSummary = useCallback(() => {
    const cols = [
      "ticker",
      "regime_label",
      "confidence_tier",
      "dominant_horizon_hint",
      "ensemble_label",
      "ensemble_confidence",
      "anomaly_severity",
      "anomaly_ensemble",
      "anomaly_reason_codes",
      "os_signal_score",
      "os_signal_rank",
      "os_sector",
    ];
    const csv = toCsv(sortedRows, cols);
    downloadText(`ticker_batch_summary_${sessionDate || today}.csv`, csv);
  }, [sessionDate, sortedRows, today]);

  const onSelectTicker = useCallback(
    (t: string) => {
      setSelectedTicker(t);
      loadSelectedTickerEvents(t);
    },
    [loadSelectedTickerEvents]
  );

  const badgeForAnomaly = (score: number | null) => {
    if (score === null || score === undefined) return <span className="tbBadge">n/a</span>;
    if (score >= 0.8) return <span className="tbBadge bad">high</span>;
    if (score >= 0.5) return <span className="tbBadge warn">med</span>;
    return <span className="tbBadge good">low</span>;
  };

  return (
    <section className="tbRoot">
      <div className="tbHeader">
        <div>
          <h2>Ticker Batch Analysis</h2>
          <div className="tbMuted">
            Upload a CSV of tickers, then pull regime/ensemble/anomaly rollups (and optional options-signal ranks) for the current session.
          </div>
        </div>
        <div className="tbRow">
          <div className="tbMuted">Session</div>
          <div className="tbMono">{sessionId ? `${sessionDate} / ${sessionId}` : "(none)"}</div>
        </div>
      </div>

      <div className="tbGrid2">
        <div className="tbCard">
          <div className="tbRow">
            <label>
              Upload tickers CSV
              <input
                type="file"
                accept={".csv,text/csv"}
                onChange={(e) => onFile(e.target.files?.[0] || null)}
              />
            </label>
            <div className="tbMuted">{fileName ? `Loaded: ${fileName}` : ""}</div>
          </div>

          {import.meta.env.DEV && (
            <div className="tbRow tbMt10">
              <label className="tbWideLabel">
                Dev-only: load by file path (requires backend flag)
                <input
                  value={devPath}
                  onChange={(e) => setDevPath(e.target.value)}
                  placeholder="C:\\Users\\...\\file.csv"
                />
              </label>
              <div className="tbActions">
                <button onClick={loadFromDevPath}>
                  Load from path
                </button>
              </div>
              {devPathStatus && <div className="tbMuted">{devPathStatus}</div>}
            </div>
          )}

          <div className="tbRow tbMt10">
            <label className="tbWideLabel">
              Or paste tickers / CSV
              <textarea
                value={rawInput}
                onChange={(e) => setRawInput(e.target.value)}
                placeholder={"Example:\nAAPL\nMSFT\nNVDA\n\nOr CSV with header:\nticker\nSPY\nQQQ"}
              />
            </label>
          </div>

          <div className="tbActions">
            <button className="primary" onClick={loadSessionData} disabled={loading || !sessionId}>
              {loading ? "Loading…" : "Load Session Metrics"}
            </button>
            <button onClick={exportSummary} disabled={!sortedRows.length}>
              Export Summary CSV
            </button>
            <button
              onClick={() => {
                setRawInput("");
                setFileName("");
                setSelectedTicker("");
                setSelectedTickerEvents([]);
              }}
              disabled={!rawInput && !fileName}
            >
              Clear
            </button>
          </div>

          <div className="tbRow tbMt10">
            <label>
              Auto-load session metrics
              <input
                type="checkbox"
                checked={autoLoadSessionData}
                onChange={(e) => setAutoLoadSessionData(e.target.checked)}
                title="Automatically refresh regimes/ensemble/anomalies for the current session"
              />
            </label>
            <label>
              Auto-load options screener
              <input
                type="checkbox"
                checked={autoLoadOptionsSignals}
                onChange={(e) => setAutoLoadOptionsSignals(e.target.checked)}
                title="Automatically refresh the options-signals screener for the selected date/signal"
              />
            </label>
          </div>

          {error && <div className="tbError tbMt8">{error}</div>}

          <div className="tbStats">
            <div className="tbStat">
              <div className="tbStatLabel">Tickers loaded</div>
              <div className="tbStatValue">{stats.n}</div>
            </div>
            <div className="tbStat">
              <div className="tbStatLabel">With regimes</div>
              <div className="tbStatValue">{stats.withRegime}</div>
            </div>
            <div className="tbStat">
              <div className="tbStatLabel">With ensembles</div>
              <div className="tbStatValue">{stats.withEnsemble}</div>
            </div>
            <div className="tbStat">
              <div className="tbStatLabel">With anomaly rollups</div>
              <div className="tbStatValue">{stats.withAnomaly}</div>
            </div>
          </div>

          {stats.top && <div className="tbMuted tbMt10">Top anomaly tickers: {stats.top}</div>}
        </div>

        <div className="tbCard">
          <div className="tbRow">
            <label>
              Options Signals date
              <input type="date" value={optionsDate} onChange={(e) => setOptionsDate(e.target.value)} />
            </label>
            <label>
              Options signal
              <select value={optionsSignal} onChange={(e) => setOptionsSignal(e.target.value)}>
                {optionsSignalOptions.map((opt) => (
                  <option key={opt.name} value={opt.name} disabled={!opt.enabled}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="tbActions">
              <button onClick={loadOptionsSignals} disabled={loading}>
                {loading ? "Loading…" : "Load Options Screener"}
              </button>
            </div>
          </div>
          <div className="tbMuted tbMt8">
            This pulls the daily screener and maps results onto your uploaded tickers.
          </div>
          <div className="tbStats">
            <div className="tbStat">
              <div className="tbStatLabel">With options-signal rows</div>
              <div className="tbStatValue">{stats.withOptions}</div>
            </div>
            <div className="tbStat">
              <div className="tbStatLabel">Screener rows loaded</div>
              <div className="tbStatValue">{optionsRows.length}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="tbTableWrap">
        <table className="tbTable">
          <thead>
            <tr>
              <th onClick={() => toggleSort("ticker")}>Ticker</th>
              <th onClick={() => toggleSort("regime")}>Regime</th>
              <th>Conf</th>
              <th onClick={() => toggleSort("ensemble")}>Ensemble</th>
              <th onClick={() => toggleSort("ensemble_confidence")}>Ens. Conf</th>
              <th onClick={() => toggleSort("anomaly_severity")}>Anomaly</th>
              <th onClick={() => toggleSort("anomaly_ensemble")}>Ens Score</th>
              <th>Reasons</th>
              <th onClick={() => toggleSort("os_signal_score")}>OS Score</th>
              <th onClick={() => toggleSort("os_signal_rank")}>OS Rank</th>
              <th>Sector</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((r) => (
              <tr key={r.ticker} className={selectedTicker === r.ticker ? "tbSelectedRow" : ""}>
                <td>
                  <button
                    className="tbTickerButton"
                    onClick={() => onSelectTicker(r.ticker)}
                    title="View anomaly event details"
                  >
                    {r.ticker}
                  </button>
                </td>
                <td>{r.regime_label || ""}</td>
                <td>{r.confidence_tier || ""}</td>
                <td>{r.ensemble_label || ""}</td>
                <td>{typeof r.ensemble_confidence === "number" ? r.ensemble_confidence.toFixed(3) : ""}</td>
                <td>
                  {badgeForAnomaly(typeof r.anomaly_severity === "number" ? r.anomaly_severity : null)}{" "}
                  {typeof r.anomaly_severity === "number" ? r.anomaly_severity.toFixed(3) : ""}
                </td>
                <td>{typeof r.anomaly_ensemble === "number" ? r.anomaly_ensemble.toFixed(3) : ""}</td>
                <td className="tbMono">{r.anomaly_reason_codes || ""}</td>
                <td>{typeof r.os_signal_score === "number" ? r.os_signal_score.toFixed(3) : ""}</td>
                <td>{typeof r.os_signal_rank === "number" ? r.os_signal_rank : ""}</td>
                <td>{r.os_sector || ""}</td>
              </tr>
            ))}
            {!sortedRows.length && (
              <tr>
                <td colSpan={11} className="tbMuted">
                  Upload/paste tickers to populate the table.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selectedTicker && (
        <div className="tbDetails">
          <div className="tbDetailsHeader">
            <div>
              <strong>{selectedTicker}</strong>
              <div className="tbMuted">Top anomaly events for this ticker (session-scoped). If empty, run Compute anomalies first.</div>
            </div>
            <div className="tbActions">
              <button onClick={() => loadSelectedTickerEvents(selectedTicker)} disabled={!sessionId}>
                Refresh events
              </button>
              <button
                onClick={() => {
                  setSelectedTicker("");
                  setSelectedTickerEvents([]);
                }}
              >
                Close
              </button>
            </div>
          </div>

          <div className="tbTableWrap">
            <table className="tbTable">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Severity</th>
                  <th>Ens Score</th>
                  <th>Reasons</th>
                  <th>Computed</th>
                </tr>
              </thead>
              <tbody>
                {selectedTickerEvents.map((ev, i) => (
                  <tr key={`${ev.ticker}-${ev.event_key || i}`}
                  >
                    <td>{ev.source || ""}</td>
                    <td>{typeof ev.severity_score === "number" ? ev.severity_score.toFixed(3) : ""}</td>
                    <td>{typeof ev.ensemble_score === "number" ? ev.ensemble_score.toFixed(3) : ""}</td>
                    <td className="tbMono">{(ev.reason_codes || []).slice(0, 6).join("; ")}</td>
                    <td className="tbMono">{ev.computed_at || ""}</td>
                  </tr>
                ))}
                {!selectedTickerEvents.length && (
                  <tr>
                    <td colSpan={5} className="tbMuted">
                      No anomaly events returned.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
