import React from "react";
import { StatusTone, tokens } from "../../theme";

type StatusBadgeProps = {
  tone?: StatusTone;
  label: string;
  subdued?: boolean;
};

const StatusBadge: React.FC<StatusBadgeProps> = ({ tone = "neutral", label, subdued = false }) => {
  const color = tokens.status[tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: subdued ? "4px 8px" : "6px 10px",
        borderRadius: tokens.radii.lg,
        background: subdued ? "transparent" : tokens.colors.chip,
        border: `1px solid ${color}`,
        color: tokens.colors.heading,
        fontSize: subdued ? "12px" : "13px",
      }}
      aria-label={label}
    >
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: color,
        }}
      />
      {label}
    </span>
  );
};

export default StatusBadge;
