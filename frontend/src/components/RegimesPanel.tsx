import React from "react";
import ChartsPanel from "./ChartsPanel";
import EmptyState from "./common/EmptyState";
import ErrorState from "./common/ErrorState";
import LoadingState from "./common/LoadingState";

type RegimeRow = {
  underlying: string;
  regime_label?: string;
  confidence_tier?: string;
};

type Props = {
  regimes: RegimeRow[];
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
  hasSession?: boolean;
};

const RegimesPanel: React.FC<Props> = ({ regimes, loading, error, onRetry, hasSession }) => {
  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Regime Classifications</h3>
      {loading && <LoadingState message="Loading regimes..." hint="Fetching latest classifications for this session." />}
      {!loading && error && <ErrorState message={error} onRetry={onRetry} retryLabel="Retry fetch" />}
      {!loading && !error && !hasSession && <EmptyState message="Create or select a session to view regimes." />}
      {!loading && !error && hasSession && regimes.length === 0 && (
        <EmptyState message="No regime classifications yet." actionLabel="Refresh" onAction={onRetry} />
      )}
      {!loading && !error && regimes.length > 0 && (
        <>
          <ChartsPanel regimes={regimes} />
          <table style={{ width: "100%", marginTop: 12 }}>
            <thead>
              <tr>
                <th>Underlying</th>
                <th>Label</th>
                <th>Confidence Tier</th>
              </tr>
            </thead>
            <tbody>
              {regimes.map((r) => (
                <tr key={r.underlying}>
                  <td>{r.underlying}</td>
                  <td>{r.regime_label || "Unknown"}</td>
                  <td>{r.confidence_tier || "Unknown"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
};

export default RegimesPanel;
