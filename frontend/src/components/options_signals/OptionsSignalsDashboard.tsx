import React, { useCallback, useEffect, useMemo, useState } from "react";
import "./OptionsSignalsDashboard.css";

type ScreenerRow = {
  trade_date: string;
  underlying_symbol: string;
  sector?: string;
  close?: number | null;
  ret_1d?: number | null;
  signal_score?: number | null;
  signal_rank?: number | null;
  bullish_flow_score?: number | null;
  bearish_flow_score?: number | null;
  vol_expansion_score?: number | null;
  put_call_vol_ratio?: number | null;
  net_premium?: number | null;
  call_buy_premium?: number | null;
  put_buy_premium?: number | null;
  iv_atm_proxy?: number | null;
  iv_rank_252?: number | null;
  rv_20?: number | null;
  iv_minus_rv20?: number | null;
  news_count?: number | null;
  sentiment_mean?: number | null;
  uoa_contract_count?: number | null;
  uoa_max_volume_z?: number | null;
};

type TimeseriesRow = {
  trade_date: string;
  close?: number | null;
  ret_1d?: number | null;
  iv_atm_proxy?: number | null;
  rv_20?: number | null;
  call_premium?: number | null;
  put_premium?: number | null;
  call_volume?: number | null;
  put_volume?: number | null;
  put_call_vol_ratio?: number | null;
  news_count?: number | null;
  sentiment_mean?: number | null;
  uoa_contract_count?: number | null;
};

type UoaRow = {
  option_chain_id: string;
  expiry_date?: string | null;
  option_type?: string | null;
  strike?: number | null;
  contract_volume?: number | null;
  contract_premium?: number | null;
  iv_last?: number | null;
  delta_last?: number | null;
  uoa_volume_z?: number | null;
  uoa_vo_i?: number | null;
};

type AlertRow = {
  event_ts: string;
  trade_date: string;
  underlying_symbol?: string | null;
  event_type: string;
  severity?: string | null;
  payload?: any;
};

type DataQualityRow = {
  trade_date: string;
  total_trades?: number | null;
  canceled_filtered?: number | null;
  trades_missing_nbbo?: number | null;
  symbols_missing_ohlcv?: number | null;
  symbols_missing_news?: number | null;
  freshness?: Record<string, string | null>;
};

type Registry = { signals?: Array<{ name: string; label: string; enabled: boolean }> };

const DEFAULT_SIGNAL = "BULL_FLOW";

function Sparkline({ values }: { values: Array<number | null | undefined> }) {
  const clean = values.filter((v) => typeof v === "number") as number[];
  if (clean.length < 2) {
    return <div className="osSparklineEmpty">No data</div>;
  }
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;
  const points = clean.map((v, idx) => {
    const x = (idx / (clean.length - 1)) * 100;
    const y = 30 - ((v - min) / range) * 30;
    return `${x},${y}`;
  });
  return (
    <svg className="osSparkline" viewBox="0 0 100 40" preserveAspectRatio="none">
      <polyline points={points.join(" ")} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export default function OptionsSignalsDashboard({ apiBase }: { apiBase: string }) {
  const today = new Date().toISOString().slice(0, 10);
  const [asOfDate, setAsOfDate] = useState(today);
  const [signal, setSignal] = useState(DEFAULT_SIGNAL);
  const [sector, setSector] = useState("");
  const [minLiquidity, setMinLiquidity] = useState("");
  const [alertsOnly, setAlertsOnly] = useState(false);
  const [activePanel, setActivePanel] = useState<"screener" | "symbol" | "alerts" | "quality">("screener");
  const [registry, setRegistry] = useState<Registry>({});

  const [screenerRows, setScreenerRows] = useState<ScreenerRow[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [timeseriesRows, setTimeseriesRows] = useState<TimeseriesRow[]>([]);
  const [uoaRows, setUoaRows] = useState<UoaRow[]>([]);
  const [alertRows, setAlertRows] = useState<AlertRow[]>([]);
  const [alertLogRows, setAlertLogRows] = useState<AlertRow[]>([]);
  const [qualityRows, setQualityRows] = useState<DataQualityRow[]>([]);

  useEffect(() => {
    fetch(`${apiBase}/options-signals/registry/signals`)
      .then((res) => res.json())
      .then((data) => setRegistry(data))
      .catch(() => setRegistry({}));
  }, [apiBase]);

  const loadScreener = useCallback(() => {
    const params = new URLSearchParams();
    params.set("date", asOfDate);
    params.set("signal", signal);
    if (sector) params.set("sector", sector);
    if (minLiquidity) params.set("min_liquidity", minLiquidity);
    if (alertsOnly) params.set("alerts_only", "true");
    fetch(`${apiBase}/options-signals/screener?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => setScreenerRows(data.rows || []))
      .catch(() => setScreenerRows([]));
  }, [apiBase, alertsOnly, asOfDate, minLiquidity, sector, signal]);

  const loadQuality = useCallback(() => {
    const params = new URLSearchParams();
    params.set("from", asOfDate);
    params.set("to", asOfDate);
    fetch(`${apiBase}/options-signals/data-quality?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => setQualityRows(data.rows || []))
      .catch(() => setQualityRows([]));
  }, [apiBase, asOfDate]);

  const loadAlertsLog = useCallback(() => {
    const params = new URLSearchParams();
    params.set("from", asOfDate);
    params.set("to", asOfDate);
    fetch(`${apiBase}/options-signals/alerts?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => setAlertLogRows(data.rows || []))
      .catch(() => setAlertLogRows([]));
  }, [apiBase, asOfDate]);

  useEffect(() => {
    loadScreener();
    loadQuality();
    loadAlertsLog();
  }, [loadAlertsLog, loadQuality, loadScreener]);

  const loadSymbol = useCallback(
    (symbol: string) => {
      const params = new URLSearchParams();
      params.set("from", asOfDate);
      params.set("to", asOfDate);
      fetch(`${apiBase}/options-signals/symbol/${symbol}/timeseries?${params.toString()}`)
        .then((res) => res.json())
        .then((data) => setTimeseriesRows(data.rows || []))
        .catch(() => setTimeseriesRows([]));
      fetch(`${apiBase}/options-signals/symbol/${symbol}/uoa?date=${asOfDate}`)
        .then((res) => res.json())
        .then((data) => setUoaRows(data.rows || []))
        .catch(() => setUoaRows([]));
      fetch(`${apiBase}/options-signals/symbol/${symbol}/alerts?${params.toString()}`)
        .then((res) => res.json())
        .then((data) => setAlertRows(data.rows || []))
        .catch(() => setAlertRows([]));
    },
    [apiBase, asOfDate]
  );

  const handleSelect = (symbol: string) => {
    setSelectedSymbol(symbol);
    loadSymbol(symbol);
    setActivePanel("symbol");
  };

  const signalOptions = useMemo(() => {
    const options = registry.signals || [];
    if (!options.length) {
      return [{ name: DEFAULT_SIGNAL, label: "Bullish Flow Signal", enabled: true }];
    }
    return options;
  }, [registry.signals]);

  const timeseriesValues = useMemo(() => timeseriesRows.map((row) => row.close ?? null), [timeseriesRows]);
  const volValues = useMemo(() => timeseriesRows.map((row) => row.iv_atm_proxy ?? null), [timeseriesRows]);

  return (
    <div className="osRoot">
      <header className="osHero">
        <div>
          <p className="osEyebrow">Options Signals</p>
          <h1>Flow intelligence, engineered for daily action.</h1>
          <p className="osSubhead">Ranked opportunities, unusual activity, and contextual alerts from your daily trade ingest.</p>
        </div>
        <div className="osHeroBadge">
          <div>
            <span>As of</span>
            <strong>{asOfDate}</strong>
          </div>
          <div>
            <span>Signal</span>
            <strong>{signal}</strong>
          </div>
        </div>
      </header>

      <section className="osFilters">
        <label>
          Date
          <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
        </label>
        <label>
          Signal
          <select value={signal} onChange={(e) => setSignal(e.target.value)}>
            {signalOptions.map((opt) => (
              <option key={opt.name} value={opt.name} disabled={!opt.enabled}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sector
          <input value={sector} onChange={(e) => setSector(e.target.value)} placeholder="Tech, Health, ETF..." />
        </label>
        <label>
          Min Liquidity
          <input value={minLiquidity} onChange={(e) => setMinLiquidity(e.target.value)} placeholder="5000" />
        </label>
        <label className="osToggle">
          <input type="checkbox" checked={alertsOnly} onChange={(e) => setAlertsOnly(e.target.checked)} />
          Show only alerts
        </label>
        <button onClick={loadScreener}>Refresh Screener</button>
      </section>

      <section className="osTabs">
        <button className={activePanel === "screener" ? "active" : ""} onClick={() => setActivePanel("screener")}>
          Screener
        </button>
        <button className={activePanel === "symbol" ? "active" : ""} onClick={() => setActivePanel("symbol")}>
          Symbol Detail
        </button>
        <button className={activePanel === "alerts" ? "active" : ""} onClick={() => setActivePanel("alerts")}>
          Alerts Log
        </button>
        <button className={activePanel === "quality" ? "active" : ""} onClick={() => setActivePanel("quality")}>
          Data Quality
        </button>
      </section>

      <section className="osGrid">
        {activePanel === "screener" && (
          <div className="osCard osScreener">
          <div className="osCardHeader">
            <h2>Screener</h2>
            <span>Ranked symbols for {signal}</span>
          </div>
          <div className="osTableWrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Sector</th>
                  <th>Close</th>
                  <th>Ret 1D</th>
                  <th>Score</th>
                  <th>Put/Call</th>
                  <th>Net Premium</th>
                  <th>IV</th>
                  <th>IV Rank</th>
                  <th>RV20</th>
                  <th>News</th>
                  <th>UOA</th>
                </tr>
              </thead>
              <tbody>
                {screenerRows.map((row) => (
                  <tr key={row.underlying_symbol} onClick={() => handleSelect(row.underlying_symbol)}>
                    <td className="osSymbol">{row.underlying_symbol}</td>
                    <td>{row.sector || "—"}</td>
                    <td>{row.close?.toFixed(2) ?? "—"}</td>
                    <td className={row.ret_1d && row.ret_1d > 0 ? "osPositive" : "osNegative"}>
                      {row.ret_1d !== null && row.ret_1d !== undefined ? (row.ret_1d * 100).toFixed(2) + "%" : "—"}
                    </td>
                    <td>{row.signal_score?.toFixed(2) ?? "—"}</td>
                    <td>{row.put_call_vol_ratio?.toFixed(2) ?? "—"}</td>
                    <td>{row.net_premium?.toFixed(0) ?? "—"}</td>
                    <td>{row.iv_atm_proxy?.toFixed(2) ?? "—"}</td>
                    <td>{row.iv_rank_252?.toFixed(2) ?? "—"}</td>
                    <td>{row.rv_20?.toFixed(2) ?? "—"}</td>
                    <td>{row.news_count ?? 0}</td>
                    <td>{row.uoa_contract_count ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        )}

        {activePanel === "symbol" && (
          <div className="osCard osDetail">
          <div className="osCardHeader">
            <h2>Symbol Drill-down</h2>
            <span>{selectedSymbol ? selectedSymbol : "Select a symbol in the screener"}</span>
          </div>
          <div className="osDetailGrid">
            <div>
              <h3>Price</h3>
              <Sparkline values={timeseriesValues} />
              <p className="osMetricLine">
                Last Close <strong>{timeseriesRows.at(-1)?.close?.toFixed(2) ?? "—"}</strong>
              </p>
            </div>
            <div>
              <h3>IV vs RV</h3>
              <Sparkline values={volValues} />
              <p className="osMetricLine">
                IV Proxy <strong>{timeseriesRows.at(-1)?.iv_atm_proxy?.toFixed(2) ?? "—"}</strong>
              </p>
            </div>
            <div>
              <h3>Flow Mix</h3>
              <p className="osMetricLine">Call Premium: {timeseriesRows.at(-1)?.call_premium?.toFixed(0) ?? "—"}</p>
              <p className="osMetricLine">Put Premium: {timeseriesRows.at(-1)?.put_premium?.toFixed(0) ?? "—"}</p>
              <p className="osMetricLine">Put/Call Ratio: {timeseriesRows.at(-1)?.put_call_vol_ratio?.toFixed(2) ?? "—"}</p>
            </div>
            <div>
              <h3>Sentiment</h3>
              <p className="osMetricLine">News Count: {timeseriesRows.at(-1)?.news_count ?? "—"}</p>
              <p className="osMetricLine">Sentiment: {timeseriesRows.at(-1)?.sentiment_mean?.toFixed(2) ?? "—"}</p>
              <p className="osMetricLine">UOA Count: {timeseriesRows.at(-1)?.uoa_contract_count ?? "—"}</p>
            </div>
          </div>

          <div className="osTablesSplit">
            <div>
              <h3>Top UOA Contracts</h3>
              <table>
                <thead>
                  <tr>
                    <th>Strike</th>
                    <th>Expiry</th>
                    <th>Type</th>
                    <th>Vol</th>
                    <th>Premium</th>
                    <th>IV</th>
                    <th>Delta</th>
                    <th>UOA Z</th>
                  </tr>
                </thead>
                <tbody>
                  {uoaRows.map((row) => (
                    <tr key={row.option_chain_id}>
                      <td>{row.strike?.toFixed(2) ?? "—"}</td>
                      <td>{row.expiry_date ?? "—"}</td>
                      <td>{row.option_type?.toUpperCase() ?? "—"}</td>
                      <td>{row.contract_volume?.toFixed(0) ?? "—"}</td>
                      <td>{row.contract_premium?.toFixed(0) ?? "—"}</td>
                      <td>{row.iv_last?.toFixed(2) ?? "—"}</td>
                      <td>{row.delta_last?.toFixed(2) ?? "—"}</td>
                      <td>{row.uoa_volume_z?.toFixed(2) ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <h3>Alerts</h3>
              <div className="osAlerts">
                {alertRows.map((row, idx) => (
                  <div key={`${row.event_ts}-${idx}`} className={`osAlert ${row.severity || "medium"}`}>
                    <div>
                      <strong>{row.event_type}</strong>
                      <span>{row.trade_date}</span>
                    </div>
                    <p>{row.payload?.summary || "Thresholds met. Review payload for details."}</p>
                  </div>
                ))}
                {!alertRows.length && <div className="osAlertEmpty">No alerts for this symbol.</div>}
              </div>
            </div>
          </div>
        </div>
        )}

        {activePanel === "alerts" && (
          <div className="osCard osAlertsLog">
          <div className="osCardHeader">
            <h2>Alerts & Event Log</h2>
            <span>All triggered events for {asOfDate}</span>
          </div>
          <div className="osAlertLog">
            {alertLogRows.map((row, idx) => (
              <div key={`${row.event_ts}-${idx}`} className={`osAlert ${row.severity || "medium"}`}>
                <div>
                  <strong>{row.event_type}</strong>
                  <span>{row.underlying_symbol}</span>
                </div>
                <p>{row.payload?.summary || "Thresholds met. Review payload for details."}</p>
              </div>
            ))}
            {!alertLogRows.length && <div className="osAlertEmpty">No alerts on this date.</div>}
          </div>
        </div>
        )}

        {activePanel === "quality" && (
          <div className="osCard osQuality">
          <div className="osCardHeader">
            <h2>Data Quality</h2>
            <span>Daily freshness and missing data</span>
          </div>
          <div className="osQualityGrid">
            {qualityRows.map((row) => (
              <div key={row.trade_date} className="osQualityRow">
                <div>
                  <h4>{row.trade_date}</h4>
                  <p>Total Trades: {row.total_trades ?? 0}</p>
                  <p>Canceled Filtered: {row.canceled_filtered ?? 0}</p>
                  <p>Missing NBBO: {row.trades_missing_nbbo ?? 0}</p>
                </div>
                <div>
                  <p>Symbols Missing OHLCV: {row.symbols_missing_ohlcv ?? 0}</p>
                  <p>Symbols Missing News: {row.symbols_missing_news ?? 0}</p>
                  <p>Freshness: {row.freshness?.opt_trades_raw || "—"}</p>
                </div>
              </div>
            ))}
            {!qualityRows.length && <div className="osQualityRow">No data quality rows.</div>}
          </div>
        </div>
        )}
      </section>
    </div>
  );
}
