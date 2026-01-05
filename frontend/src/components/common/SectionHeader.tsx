import React from "react";
import StatusBadge from "./StatusBadge";
import { tokens } from "../../theme";

type SectionHeaderProps = {
  title: string;
  eyebrow?: string;
  statusLabel?: string;
  statusTone?: "success" | "warning" | "danger" | "info" | "neutral";
  actions?: React.ReactNode;
  updatedAt?: number;
};

const SectionHeader: React.FC<SectionHeaderProps> = ({ title, eyebrow, statusLabel, statusTone, actions, updatedAt }) => {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: tokens.spacing.md,
        flexWrap: "wrap",
      }}
    >
      <div>
        {eyebrow && <div style={{ color: tokens.colors.muted, fontSize: 12, textTransform: "uppercase" }}>{eyebrow}</div>}
        <h3 style={{ margin: "4px 0", color: tokens.colors.heading }}>{title}</h3>
        {updatedAt && (
          <div style={{ color: tokens.colors.muted, fontSize: 12 }}>Updated {new Date(updatedAt).toLocaleTimeString()}</div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: tokens.spacing.sm }}>
        {statusLabel && <StatusBadge tone={statusTone} label={statusLabel} subdued />}
        {actions}
      </div>
    </div>
  );
};

export default SectionHeader;
