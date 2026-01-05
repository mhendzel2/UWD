import React, { useEffect } from "react";
import { CapabilityKey, useUserState } from "../state/user";

type Props = {
  apiBase: string;
  sessionId: string;
  sessionDate: string;
  onCompute: () => void;
  onComputeEcology: () => void;
  onGenerateBriefs: () => void;
  onComputeV1: () => void;
};

type Control = {
  key: CapabilityKey;
  label: string;
  handler: () => void;
};

const UserControls: React.FC<Props> = ({
  apiBase,
  sessionId,
  sessionDate,
  onCompute,
  onComputeEcology,
  onGenerateBriefs,
  onComputeV1,
}) => {
  const { token, setToken, capabilityFor, fetchCapabilities, role, pushToast } = useUserState();

  useEffect(() => {
    if (sessionId && token) {
      fetchCapabilities(apiBase, sessionId);
    }
  }, [apiBase, fetchCapabilities, sessionId, token]);

  const refreshCapabilities = () => {
    fetchCapabilities(apiBase, sessionId);
  };

  const controls: Control[] = [
    { key: "compute_v0", label: "Compute v0", handler: onCompute },
    { key: "compute_ecology", label: "Compute Ecology", handler: onComputeEcology },
    { key: "generate_briefs", label: "Generate Daily Briefs", handler: onGenerateBriefs },
    { key: "compute_v1", label: "Compute v1 Ensemble", handler: onComputeV1 },
  ];

  const renderButton = (control: Control) => {
    const cap = capabilityFor(control.key);
    const disabled = !sessionId || !cap.allowed;
    const tooltip = !sessionId ? "Create or load a session first" : cap.reason || "";
    return (
      <button
        key={control.key}
        onClick={control.handler}
        disabled={disabled}
        title={disabled ? tooltip : undefined}
        className="computeButton"
      >
        {control.label}
      </button>
    );
  };

  const handleTokenBlur = (value: string) => {
    if (!value) {
      pushToast({ tone: "error", message: "Auth token cleared. Compute capabilities disabled." });
    }
  };

  return (
    <div className="userControls">
      <div className="authRow">
        <div>
          <div className="eyebrow">Auth context</div>
          <div className="smallMuted">Provide a token to unlock compute operations.</div>
          <div className="tokenRow">
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              onBlur={(e) => handleTokenBlur(e.target.value)}
              placeholder="admin-token / analyst-token / viewer-token"
            />
            <button onClick={refreshCapabilities} disabled={!sessionId}>
              Load capabilities
            </button>
          </div>
          <div className="smallMuted">Role: {role}</div>
          {sessionDate && <div className="smallMuted">Session date: {sessionDate}</div>}
        </div>
        <div className="capsGrid">
          {controls.map((c) => {
            const cap = capabilityFor(c.key);
            return (
              <div key={c.key} className={`capPill ${cap.allowed ? "allowed" : "blocked"}`}>
                <span className="pillLabel">{c.label}</span>
                <span className="pillValue">{cap.allowed ? "allowed" : "blocked"}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="computeRow">{controls.map(renderButton)}</div>
    </div>
  );
};

export default UserControls;
