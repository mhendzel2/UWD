import React from "react";
import { tokens } from "../../theme";

type ErrorStateProps = {
  message: string;
  onRetry?: () => void;
};

const ErrorState: React.FC<ErrorStateProps> = ({ message, onRetry }) => {
  return (
    <div
      role="alert"
      style={{
        background: "rgba(244,63,94,0.12)",
        border: `1px solid ${tokens.status.danger}`,
        color: tokens.colors.heading,
        padding: tokens.spacing.md,
        borderRadius: tokens.radii.md,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: tokens.spacing.md,
      }}
    >
      <div>
        <strong style={{ display: "block" }}>Something went wrong</strong>
        <span style={{ color: tokens.colors.muted }}>{message}</span>
      </div>
      {onRetry && (
        <button style={{ padding: "8px 12px" }} onClick={onRetry} aria-label="Retry action">
          Retry
        </button>
      )}
    </div>
  );
};

export default ErrorState;
