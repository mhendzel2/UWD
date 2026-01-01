import React, { useCallback, useEffect, useMemo, useState } from "react";
import "./OutlierDetectionPanel.css";

type Props = {
  apiBase: string;
  sessionId: string;
  sessionDate: string;
  onLog?: (message: string) => void;
};

type AvailableDate = {
  session_id: string;
  date: string;
  oi_file_count: number;
};

type OutlierRow = {
  underlying_symbol: string;
  option_symbol: string;
  oi_diff: number;
  strike?: number | null;
  stock_price?: number | null;
  percentage_of_total?: number | null;
  days_to_earnings?: number | null;
  dte?: number | null;
  sector?: string | null;
  method: string;
  score: number;
};

type OutlierSummary = {
  method: string;
  count: number;
  top_symbol: string;
  max_oi_change: number;
  threshold_info: string;
};

type DistributionStats = {
  count: number;
  mean: number;
  std: number;
  min: number;
  max: number;
  iqr_lower: number;
  iqr_upper: number;
  percentiles: Record<string, number>;
};

type OutlierApiResponse = {
  zscore: { results: OutlierRow[]; summary: OutlierSummary };
  iqr: { results: OutlierRow[]; summary: OutlierSummary };
  preevent: { results: OutlierRow[]; summary: OutlierSummary };
  distribution?: DistributionStats | { error: string };
  unique_symbols: number;
  total_outliers: number;
};

type MethodKey = "zscore" | "iqr" | "preevent";

const methodLabel: Record<MethodKey, string> = {
  zscore: "Z-Score (|z| > threshold)",
  iqr: "IQR (multiplier  IQR)",
  preevent: "Pre-Event (earnings proximity + chain %)",
};

const OutlierDetectionPanel: React.FC<Props> = ({ apiBase, sessionId, sessionDate, onLog }) => {
  const [availableDates, setAvailableDates] = useState<AvailableDate[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string>("");
  const [selectedMethod, setSelectedMethod] = useState<MethodKey>("zscore");

  const [zscoreThreshold, setZscoreThreshold] = useState<string>("3");
  const [iqrMultiplier, setIqrMultiplier] = useState<string>("1.5");
  const [earningsDays, setEarningsDays] = useState<string>("14");
  const [chainPct, setChainPct] = useState<string>("0.2");

  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [data, setData] = useState<OutlierApiResponse | null>(null);

  const loadAvailableDates = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/analysis/outliers/available-dates`);
      if (!res.ok) return;
      const json = await res.json();
      setAvailableDates(json.available_dates || []);
    } catch {
      // ignore
    }
  }, [apiBase]);

  useEffect(() => {
    loadAvailableDates();
  }, [loadAvailableDates]);

  useEffect(() => {
    if (sessionId) setSelectedSessionId(sessionId);
  }, [sessionId]);

  const runDetection = useCallback(async () => {
    if (!selectedSessionId) {
      setError("Select a session with OI data");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("session_id", selectedSessionId);
      form.append("zscore_threshold", zscoreThreshold);
      form.append("iqr_multiplier", iqrMultiplier);
      form.append("earnings_days", earningsDays);
      form.append("chain_pct", chainPct);

      const res = await fetch(`${apiBase}/analysis/outliers/detect`, { method: "POST", body: form });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || "Outlier detection failed");
      }
      const json = (await res.json()) as OutlierApiResponse;
      setData(json);
      onLog?.(`Outliers computed for session ${selectedSessionId}`);
    } catch (e: any) {
      setError(e?.message || "Outlier detection failed");
    } finally {
      setLoading(false);
    }
  }, [apiBase, chainPct, earningsDays, iqrMultiplier, onLog, selectedSessionId, zscoreThreshold]);

  const summary = useMemo(() => {
    if (!data) return null;
    return {
      zscore: data.zscore.summary,
      iqr: data.iqr.summary,
      preevent: data.preevent.summary,
      unique_symbols: data.unique_symbols,
      total_outliers: data.total_outliers,
    };
  }, [data]);

  const activeResults = useMemo(() => {
    if (!data) return [];
    if (selectedMethod === "zscore") return data.zscore.results;
    if (selectedMethod === "iqr") return data.iqr.results;
    return data.preevent.results;
  }, [data, selectedMethod]);

  const activeSummary = useMemo(() => {
    if (!data) return null;
    if (selectedMethod === "zscore") return data.zscore.summary;
    if (selectedMethod === "iqr") return data.iqr.summary;
    return data.preevent.summary;
  }, [data, selectedMethod]);

  return (
    <section className="outlierPanel">
      <div className="outlierHeader">
        <h2 className="outlierTitle">Options OI Outlier Detection</h2>
        <div className="smallMuted">Session date: {sessionDate || ""}</div>
      </div>

      <div className="grid2">
        <label className="gridLabel">
          Select session with OI data
          <select value={selectedSessionId} onChange={(e) => setSelectedSessionId(e.target.value)}>
            <option value="">-- select --</option>
            {availableDates.map((d) => (
              <option key={d.session_id} value={d.session_id}>
                {d.date} (OI files: {d.oi_file_count})
              </option>
            ))}
          </select>
        </label>

        <div className="methodBox">
          <div className="methodButtons">
            <button onClick={() => setSelectedMethod("zscore")} disabled={selectedMethod === "zscore"}>
              Z-Score
            </button>
            <button onClick={() => setSelectedMethod("iqr")} disabled={selectedMethod === "iqr"}>
              IQR
            </button>
            <button onClick={() => setSelectedMethod("preevent")} disabled={selectedMethod === "preevent"}>
              Pre-Event
            </button>
          </div>
          <div className="smallMuted">{methodLabel[selectedMethod]}</div>
        </div>
      </div>

      <div className="grid4">
        <label className="gridLabel">
          Z-Score threshold
          <input value={zscoreThreshold} onChange={(e) => setZscoreThreshold(e.target.value)} placeholder="3" />
        </label>
        <label className="gridLabel">
          IQR multiplier
          <input value={iqrMultiplier} onChange={(e) => setIqrMultiplier(e.target.value)} placeholder="1.5" />
        </label>
        <label className="gridLabel">
          Days to earnings (&lt;)
          <input value={earningsDays} onChange={(e) => setEarningsDays(e.target.value)} placeholder="14" />
        </label>
        <label className="gridLabel">
          % of chain (&gt;)
          <input value={chainPct} onChange={(e) => setChainPct(e.target.value)} placeholder="0.2" />
        </label>
      </div>

      <div className="row">
        <button onClick={runDetection} disabled={loading || !selectedSessionId}>
          {loading ? "Running" : "Run Outlier Detection"}
        </button>
        {error && <div className="error">{error}</div>}
      </div>

      {summary && (
        <div className="summaryGrid">
          <div className="card">
            <div className="cardTitle">Z-Score</div>
            <div>Count: {summary.zscore.count}</div>
            <div>Top: {summary.zscore.top_symbol}</div>
            <div>Max: {summary.zscore.max_oi_change}</div>
          </div>
          <div className="card">
            <div className="cardTitle">IQR</div>
            <div>Count: {summary.iqr.count}</div>
            <div>Top: {summary.iqr.top_symbol}</div>
            <div>Max: {summary.iqr.max_oi_change}</div>
          </div>
          <div className="card">
            <div className="cardTitle">Pre-Event</div>
            <div>Count: {summary.preevent.count}</div>
            <div>Top: {summary.preevent.top_symbol}</div>
            <div>Max: {summary.preevent.max_oi_change}</div>
          </div>
          <div className="summaryFooter">Unique symbols: {summary.unique_symbols}  Total outliers returned: {summary.total_outliers}</div>
        </div>
      )}

      {activeSummary && (
        <div className="thresholdCard">
          <div className="cardTitle">{activeSummary.method} thresholds</div>
          <div>{activeSummary.threshold_info}</div>
        </div>
      )}

      {activeResults.length > 0 && (
        <div className="tableWrap">
          <table className="table">
            <thead>
              <tr>
                <th className="thLeft">Underlying</th>
                <th className="thLeft">Option</th>
                <th className="thRight">OI Δ</th>
                <th className="thRight">Score</th>
                <th className="thRight">DTE</th>
                <th className="thRight">DaysE</th>
                <th className="thRight">% Chain</th>
              </tr>
            </thead>
            <tbody>
              {activeResults.map((r, idx) => (
                <tr key={`${r.underlying_symbol}-${r.option_symbol}-${idx}`}>
                  <td className="td">{r.underlying_symbol}</td>
                  <td className="td">{r.option_symbol}</td>
                  <td className="tdRight">{r.oi_diff}</td>
                  <td className="tdRight">{r.score}</td>
                  <td className="tdRight">{r.dte ?? ""}</td>
                  <td className="tdRight">{r.days_to_earnings ?? ""}</td>
                  <td className="tdRight">{r.percentage_of_total ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && activeResults.length === 0 && <div className="noResults">No results for this method.</div>}
    </section>
  );
};

export default OutlierDetectionPanel;
