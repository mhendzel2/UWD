import React from "react";

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
};

const EnsemblePanel: React.FC<Props> = ({ ensembles }) => {
  if (!ensembles.length) {
    return (
      <section style={{ border: "1px solid #ccc", padding: 12 }}>
        <h3>v1 Ensemble</h3>
        <p>No v1 ensemble decisions yet.</p>
      </section>
    );
  }

  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>v1 Ensemble</h3>
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
    </section>
  );
};

export default EnsemblePanel;
