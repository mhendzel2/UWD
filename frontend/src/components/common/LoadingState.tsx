import React from "react";
import { tokens } from "../../theme";

type LoadingStateProps = {
  label?: string;
  tone?: "neutral" | "accent";
};

const LoadingState: React.FC<LoadingStateProps> = ({ label = "Loading…", tone = "neutral" }) => {
  const color = tone === "accent" ? tokens.colors.accent : tokens.status.info;
  return (
    <div
      style={{
        padding: tokens.spacing.md,
        border: `1px dashed ${tokens.colors.border}`,
        borderRadius: tokens.radii.md,
        display: "inline-flex",
        alignItems: "center",
        gap: tokens.spacing.sm,
        color: tokens.colors.text,
      }}
      role="status"
      aria-live="polite"
    >
      <span
        aria-hidden
        style={{
          width: 16,
          height: 16,
          borderRadius: "50%",
          border: `3px solid ${color}`,
          borderRightColor: "transparent",
          animation: "spin 1s linear infinite",
        }}
      />
      <span>{label}</span>
      <style>
        {`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}
      </style>
    </div>
  );
};

export default LoadingState;
