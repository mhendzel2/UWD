import React from "react";
import "./panelStates.css";

type Props = {
  message: string;
  hint?: string;
};

const LoadingState: React.FC<Props> = ({ message, hint }) => {
  return (
    <div className="panelState loadingState" role="status" aria-live="polite">
      <div className="spinner" />
      <div>
        <div className="panelStateTitle">{message}</div>
        {hint && <div className="panelStateHint">{hint}</div>}
      </div>
    </div>
  );
};

export default LoadingState;
