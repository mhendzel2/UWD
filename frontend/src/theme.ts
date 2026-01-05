export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral";

export const tokens = {
  colors: {
    background: "#0b1021",
    surface: "#0f172a",
    panel: "#111827",
    border: "#1f2937",
    muted: "#94a3b8",
    text: "#e5e7eb",
    heading: "#f8fafc",
    accent: "#38bdf8",
    accentSecondary: "#a855f7",
    chip: "#1e293b",
  },
  status: {
    success: "#16a34a",
    warning: "#f59e0b",
    danger: "#f43f5e",
    info: "#38bdf8",
    neutral: "#94a3b8",
  },
  radii: {
    sm: "6px",
    md: "10px",
    lg: "14px",
  },
  spacing: {
    xs: "4px",
    sm: "8px",
    md: "12px",
    lg: "16px",
    xl: "24px",
    xxl: "32px",
  },
  shadow: {
    panel: "0 12px 40px rgba(0,0,0,0.24)",
  },
  chartPalette: ["#38bdf8", "#a855f7", "#22c55e", "#f97316", "#f43f5e", "#eab308", "#8b5cf6"],
};

export const srOnly = {
  border: "0",
  clip: "rect(0, 0, 0, 0)",
  height: "1px",
  margin: "-1px",
  overflow: "hidden",
  padding: "0",
  position: "absolute" as const,
  width: "1px",
  whiteSpace: "nowrap" as const,
};

export const capabilityDefaults = {
  canComputeV0: true,
  canComputeEcology: true,
  canGenerateBriefs: true,
  canComputeEnsemble: true,
};
