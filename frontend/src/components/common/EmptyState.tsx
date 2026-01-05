import React from "react";
import "./panelStates.css";

type Props = {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
};

const EmptyState: React.FC<Props> = ({ message, actionLabel, onAction }) => {
  return (
    <div className="panelState emptyState">
      <div className="panelStateTitle">{message}</div>
      {actionLabel && onAction && (
        <button onClick={onAction} className="retryButton">
          {actionLabel}
        </button>
      )}
    </div>
  );
};

export default EmptyState;
