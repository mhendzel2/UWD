import React from "react";
import "./panelStates.css";

type Props = {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
};

const ErrorState: React.FC<Props> = ({ message, onRetry, retryLabel = "Retry" }) => {
  return (
    <div className="panelState errorState" role="alert">
      <div className="panelStateTitle">Something went wrong</div>
      <div className="panelStateHint">{message}</div>
      {onRetry && (
        <button onClick={onRetry} className="retryButton">
          {retryLabel}
        </button>
      )}
    </div>
  );
};

export default ErrorState;
