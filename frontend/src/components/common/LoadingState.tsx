import React from "react";
import "./LoadingState.css";

type LoadingStateProps = {
  label?: string;
  tone?: "neutral" | "accent";
};

const LoadingState: React.FC<LoadingStateProps> = ({ label = "Loading…", tone = "neutral" }) => {
  return (
    <div className="loadingState" role="status" aria-live="polite">
      <span aria-hidden className={`spinner ${tone}`} />
      <span>{label}</span>
    </div>
  );
};

export default LoadingState;
