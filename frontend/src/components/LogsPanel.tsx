import React from "react";
import { LogEntry, formatLogMessage } from "../utils/logBuffer";
import StatusBadge from "./common/StatusBadge";

type Props = {
  logs: LogEntry[];
  level: "all" | "info" | "warning" | "error";
  onLevelChange: (level: Props["level"]) => void;
  search: string;
  onSearch: (text: string) => void;
  status: "disconnected" | "connecting" | "connected" | "error";
};

const LogsPanel: React.FC<Props> = ({ logs, level, onLevelChange, search, onSearch, status }) => {
  return (
    <section className="panel" aria-label="Real-time logs">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <h3 style={{ margin: 0 }}>Logs</h3>
        <StatusBadge
          tone={status === "connected" ? "success" : status === "error" ? "danger" : "warning"}
          label={`WebSocket ${status}`}
          subdued
        />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <label>
          Level
          <select value={level} onChange={(e) => onLevelChange(e.target.value as Props["level"])} aria-label="Log level filter">
            <option value="all">All</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>
        </label>
        <label>
          Search
          <input value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Filter logs" aria-label="Search logs" />
        </label>
      </div>
      <div style={{ maxHeight: 260, overflowY: "auto", marginTop: 8 }} aria-live="polite">
        {!logs.length && <p style={{ color: "#94a3b8" }}>No log entries yet.</p>}
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
          {logs.map((log, idx) => (
            <li
              key={idx}
              style={{
                padding: "8px 10px",
                borderRadius: 8,
                border: "1px solid rgba(255,255,255,0.08)",
                background: "rgba(255,255,255,0.03)",
                fontFamily: "ui-monospace, SFMono-Regular, SFMono-Regular",
              }}
            >
              {formatLogMessage(log)}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
};

export default LogsPanel;
