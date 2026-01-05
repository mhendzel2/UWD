import React from "react";
import "./ErrorState.css";

type ErrorStateProps = {
  message: string;
  onRetry?: () => void;
};

const ErrorState: React.FC<ErrorStateProps> = ({ message, onRetry }) => {
  return (
    <div role="alert" className="errorState">
      <div className="errorMessage">
        <strong>Something went wrong</strong>
        <span>{message}</span>
      </div>
      {onRetry && (
        <button onClick={onRetry} aria-label="Retry action">
          Retry
        </button>
      )}
    </div>
  );
};

export default ErrorState;
