import React from "react";

type Props = {
  sessionId: string;
  onCompute: () => void;
  decisionTable: React.ReactNode;
};

const SessionDashboard: React.FC<Props> = ({ sessionId, onCompute, decisionTable }) => {
  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Session Dashboard</h3>
      {sessionId ? (
        <>
          <p>Session ready. Compute v0 to classify regimes.</p>
          <button onClick={onCompute}>Compute v0</button>
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
