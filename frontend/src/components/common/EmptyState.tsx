import React from "react";
import { tokens } from "../../theme";

type EmptyStateProps = {
  title: string;
  description?: string;
  action?: React.ReactNode;
};

const EmptyState: React.FC<EmptyStateProps> = ({ title, description, action }) => (
  <div
    style={{
      border: `1px dashed ${tokens.colors.border}`,
      borderRadius: tokens.radii.md,
      padding: tokens.spacing.lg,
      color: tokens.colors.muted,
      textAlign: "center",
    }}
  >
    <h4 style={{ margin: 0, color: tokens.colors.heading }}>{title}</h4>
    {description && <p style={{ marginTop: 4 }}>{description}</p>}
    {action && <div style={{ marginTop: tokens.spacing.sm }}>{action}</div>}
  </div>
);

export default EmptyState;
