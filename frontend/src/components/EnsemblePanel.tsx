import React from "react";
import SectionHeader from "./common/SectionHeader";
import LoadingState from "./common/LoadingState";
import EmptyState from "./common/EmptyState";

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
  status?: {
    status: "idle" | "loading" | "success" | "error";
    error?: string;
    updatedAt?: number;
  };
};

const EnsemblePanel: React.FC<Props> = ({ ensembles, status }) => {
  return (
    <section className="panel" aria-label="Ensemble decisions">
      <SectionHeader
        title="v1 Ensemble"
        eyebrow="Decision stability"
        statusLabel={status?.status || "idle"}
        statusTone={status?.status === "error" ? "danger" : status?.status === "success" ? "success" : "info"}
        updatedAt={status?.updatedAt}
      />
      {status?.status === "loading" && <LoadingState label="Loading ensembles…" />}
      {!ensembles.length && status?.status !== "loading" && (
        <EmptyState title="No v1 ensemble decisions yet" description="Compute the v1 ensemble to view results." />
      )}
      {!!ensembles.length && (
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
