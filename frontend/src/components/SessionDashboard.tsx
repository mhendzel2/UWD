import React from "react";
import UserControls from "./UserControls";

type Props = {
  apiBase: string;
  sessionId: string;
  sessionDate: string;
  onCompute: () => void;
  onComputeEcology: () => void;
  onGenerateBriefs: () => void;
  onComputeV1: () => void;
  decisionTable: React.ReactNode;
};

const SessionDashboard: React.FC<Props> = ({
  apiBase,
  sessionId,
  sessionDate,
  onCompute,
  onComputeEcology,
  onGenerateBriefs,
  onComputeV1,
  decisionTable,
}) => {
  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Session Dashboard</h3>
      {sessionId ? (
        <>
          <p>Session ready. Compute layers are gated by your role capabilities.</p>
          <UserControls
            apiBase={apiBase}
            sessionId={sessionId}
            sessionDate={sessionDate}
            onCompute={onCompute}
            onComputeEcology={onComputeEcology}
            onGenerateBriefs={onGenerateBriefs}
            onComputeV1={onComputeV1}
          />
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
