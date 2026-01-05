import React from "react";
import EmptyState from "./common/EmptyState";
import ErrorState from "./common/ErrorState";
import LoadingState from "./common/LoadingState";

type EcologyEntry = {
  underlying: string;
  dominant_horizon_hint?: string | null;
  ecology_state?: any;
};

type Props = {
  entries: EcologyEntry[];
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
  hasSession?: boolean;
};

const EcologyPanel: React.FC<Props> = ({ entries, loading, error, onRetry, hasSession }) => {
  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Market Ecology</h3>
      {loading && <LoadingState message="Loading ecology insights..." hint="Pulling ecology views for current regimes." />}
      {!loading && error && <ErrorState message={error} onRetry={onRetry} retryLabel="Retry fetch" />}
      {!loading && !error && !hasSession && <EmptyState message="Create or select a session to view ecology." />}
      {!loading && !error && hasSession && entries.length === 0 && (
        <EmptyState message="No ecology state computed yet." actionLabel="Refresh" onAction={onRetry} />
      )}
      {!loading && !error && entries.length > 0 && (
        <>
          <table style={{ width: "100%", marginTop: 8 }}>
            <thead>
              <tr>
                <th>Underlying</th>
                <th>Dominant Horizon</th>
                <th>Vol Ecology</th>
                <th>Disagreement</th>
                <th>Intent Profile</th>
                <th>Tail Risk</th>
                <th>Drawdown Shock</th>
                <th>Timing</th>
                <th>Key Strikes</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => {
                const state = e.ecology_state || {};
                const walls = state.strike_levels?.oi_walls || [];
                const wallText = walls.slice(0, 2).map((w: any) => `$${w.strike}`).join(", ");
                return (
                  <tr key={e.underlying}>
                    <td>{e.underlying}</td>
                    <td>{e.dominant_horizon_hint || state.dominant_horizon_hint || "n/a"}</td>
                    <td>{state.volatility_ecology || "n/a"}</td>
                    <td>{state.disagreement_intensity || "n/a"}</td>
                    <td>{state.intent_profile || "n/a"}</td>
                    <td>{state.tail_risk_flag ? "YES" : "no"}</td>
                    <td>{state.drawdown_shock_active ? "active" : "off"}</td>
                    <td>{state.timing_profile?.timing_profile?.label || state.timing_profile?.label || "n/a"}</td>
                    <td>{wallText || "n/a"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ marginTop: 8 }}>
            {entries.map((e) => {
              const state = e.ecology_state || {};
              return (
                <div key={`${e.underlying}-bullets`} style={{ marginBottom: 8 }}>
                  <strong>{e.underlying} notes:</strong>
                  <ul>
                    {(state.explanation_bullets || []).map((b: string) => (
                      <li key={b}>{b}</li>
                    ))}
                    {state.timing_profile?.timing_profile?.label && <li>Timing: {state.timing_profile.timing_profile.label}</li>}
                    {state.strike_levels?.oi_walls && (
                      <li>
                        OI walls:{" "}
                        {state.strike_levels.oi_walls
                          .slice(0, 3)
                          .map((w: any) => `$${w.strike} (oi ${w.total_oi})`)
                          .join(", ")}
                      </li>
                    )}
                  </ul>
                </div>
              );
            })}
          </div>
          {entries[0]?.ecology_state?.market_overlays && (
            <div style={{ marginTop: 12, borderTop: "1px solid #eee", paddingTop: 8 }}>
              <strong>Market Sentiment:</strong>{" "}
              {(() => {
                const m = entries[0].ecology_state.market_overlays.market_sentiment || {};
                return `PCR ${m.put_call_ratio?.toFixed ? m.put_call_ratio.toFixed(2) : m.put_call_ratio || "n/a"}, Net Prem ${m.net_premium?.toFixed ? m.net_premium.toFixed(0) : m.net_premium || 0}`;
              })()}
              <div style={{ marginTop: 4 }}>
                <strong>Sector Flows:</strong>
                <ul>
                  {Object.entries(entries[0].ecology_state.market_overlays.sector_flows || {}).map(([sec, vals]: any) => (
                    <li key={sec}>
                      {sec}: net {vals.net_premium?.toFixed ? vals.net_premium.toFixed(0) : vals.net_premium || 0}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
};

export default EcologyPanel;
