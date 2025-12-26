import React from "react";

type EcologyEntry = {
  underlying: string;
  dominant_horizon_hint?: string | null;
  ecology_state?: any;
};

type Props = {
  entries: EcologyEntry[];
};

const EcologyPanel: React.FC<Props> = ({ entries }) => {
  if (!entries.length) {
    return (
      <section style={{ border: "1px solid #ccc", padding: 12 }}>
        <h3>Market Ecology</h3>
        <p>No ecology state computed yet.</p>
      </section>
    );
  }
  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Market Ecology</h3>
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
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => {
            const state = e.ecology_state || {};
            return (
              <tr key={e.underlying}>
                <td>{e.underlying}</td>
                <td>{e.dominant_horizon_hint || state.dominant_horizon_hint || "n/a"}</td>
                <td>{state.volatility_ecology || "n/a"}</td>
                <td>{state.disagreement_intensity || "n/a"}</td>
                <td>{state.intent_profile || "n/a"}</td>
                <td>{state.tail_risk_flag ? "YES" : "no"}</td>
                <td>{state.drawdown_shock_active ? "active" : "off"}</td>
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
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
};

export default EcologyPanel;
