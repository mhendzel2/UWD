import React from "react";

type Props = {
  sessionId: string;
  onCompute: () => void;
  onComputeEcology: () => void;
  onGenerateBriefs: () => void;
  onComputeV1: () => void;
  decisionTable: React.ReactNode;
};

const SessionDashboard: React.FC<Props> = ({ sessionId, onCompute, onComputeEcology, onGenerateBriefs, onComputeV1, decisionTable }) => {
  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Session Dashboard</h3>
      {sessionId ? (
        <>
          <p>Session ready. Compute v0 to classify regimes.</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button onClick={onCompute}>Compute v0</button>
            <button onClick={onComputeEcology}>Compute Ecology State</button>
            <button onClick={onGenerateBriefs}>Generate Daily Briefs</button>
            <button onClick={onComputeV1}>Compute v1 Ensemble</button>
          </div>
          <table style={{ width: "100%", marginTop: 8 }}>
            <thead>
              <tr>
                <th>Underlying</th>
                <th>Regime</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>{decisionTable}</tbody>
          </table>
        </>
      ) : (
        <p>Create a session to begin.</p>
      )}
    </section>
  );
};

export default SessionDashboard;
