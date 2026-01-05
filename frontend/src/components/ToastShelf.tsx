import React from "react";
import { useUserState } from "../state/user";

const ToastShelf: React.FC = () => {
  const { toasts, dismissToast } = useUserState();

  if (!toasts.length) return null;

  return (
    <div className="toastShelf" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast ${toast.tone}`} role="alert">
          <span>{toast.message}</span>
          <button aria-label="Dismiss" onClick={() => dismissToast(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
};

export default ToastShelf;
