import React from "react";

type Props = {
  logs: string[];
};

const LogsPanel: React.FC<Props> = ({ logs }) => {
  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Logs</h3>
      <ul>
        {logs.map((log, idx) => (
          <li key={idx}>{log}</li>
        ))}
      </ul>
    </section>
  );
};

export default LogsPanel;
