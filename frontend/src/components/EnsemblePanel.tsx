import React from "react";
import EmptyState from "./common/EmptyState";
import ErrorState from "./common/ErrorState";
import LoadingState from "./common/LoadingState";

type Ensemble = {
  underlying: string;
  ensemble_label: string;
  ensemble_confidence?: number;
  horizon_weights?: Record<string, number>;
  component_votes?: Record<string, any>;
  stability_metrics?: Record<string, any>;
};

type Props = {
  ensembles: Ensemble[];
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
  hasSession?: boolean;
};

const EnsemblePanel: React.FC<Props> = ({ ensembles, loading, error, onRetry, hasSession }) => {
  const showEmpty = !loading && !error && ensembles.length === 0 && hasSession;

  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>v1 Ensemble</h3>
      {loading && <LoadingState message="Loading v1 ensemble decisions..." />}
      {!loading && error && <ErrorState message={error} onRetry={onRetry} retryLabel="Retry fetch" />}
      {!loading && !error && !hasSession && <EmptyState message="Create or select a session to view ensembles." />}
      {showEmpty && <EmptyState message="No v1 ensemble decisions yet." actionLabel="Refresh" onAction={onRetry} />}
      {!loading && !error && ensembles.length > 0 && (
        <table style={{ width: "100%", marginTop: 8 }}>
          <thead>
            <tr>
              <th>Underlying</th>
              <th>Label</th>
              <th>Confidence</th>
              <th>Horizon Weights</th>
              <th>Components</th>
              <th>Stability</th>
            </tr>
          </thead>
          <tbody>
            {ensembles.map((e) => (
              <tr key={e.underlying}>
                <td>{e.underlying}</td>
                <td>{e.ensemble_label}</td>
                <td>{typeof e.ensemble_confidence === "number" ? e.ensemble_confidence.toFixed(3) : e.ensemble_confidence}</td>
                <td>
                  {e.horizon_weights
                    ? Object.entries(e.horizon_weights)
                        .map(([k, v]) => `${k}:${Number(v).toFixed(2)}`)
                        .join(" / ")
                    : "n/a"}
                </td>
                <td>
                  {e.component_votes
                    ? Object.entries(e.component_votes)
                        .map(([k, v]: any) => `${k}:${v.label}(${Number(v.confidence || 0).toFixed(2)})`)
                        .join(" | ")
                    : "n/a"}
                </td>
                <td>
                  {e.stability_metrics
                    ? Object.entries(e.stability_metrics)
                        .map(([k, v]) => `${k}:${v ?? "na"}`)
                        .join(" | ")
                    : "n/a"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
};

export default EnsemblePanel;
