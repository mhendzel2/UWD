import React from "react";
import SectionHeader from "./common/SectionHeader";
import StatusBadge from "./common/StatusBadge";
import LoadingState from "./common/LoadingState";
import { tokens } from "../theme";

type ResourceState = {
  status: "idle" | "loading" | "success" | "error";
  error?: string;
  updatedAt?: number;
};

type Capabilities = {
  canComputeV0: boolean;
  canComputeEcology: boolean;
  canGenerateBriefs: boolean;
  canComputeEnsemble: boolean;
};

type Props = {
  sessionId: string;
  onCompute: () => void;
  onComputeEcology: () => void;
  onGenerateBriefs: () => void;
  onComputeV1: () => void;
  onRefreshRegimes: () => void;
  onRefreshBriefs: () => void;
  onRefreshEnsembles: () => void;
  decisionTable: React.ReactNode;
  regimeState: ResourceState;
  briefState: ResourceState;
  ensembleState: ResourceState;
  capabilityState: ResourceState;
  capabilities: Capabilities;
};

const SessionDashboard: React.FC<Props> = ({
  sessionId,
  onCompute,
  onComputeEcology,
  onGenerateBriefs,
  onComputeV1,
  onRefreshRegimes,
  onRefreshBriefs,
  onRefreshEnsembles,
  decisionTable,
  regimeState,
  briefState,
  ensembleState,
  capabilityState,
  capabilities,
}) => {
  const disabledTooltip = (allowed: boolean) => (allowed ? undefined : "Action requires permission");

  return (
    <section className="panel" aria-label="Session dashboard">
      <SectionHeader
        eyebrow="Controls"
        title="Session Dashboard"
        statusLabel={sessionId ? "Ready" : "No session"}
        statusTone={sessionId ? "success" : "warning"}
        actions={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button onClick={onRefreshRegimes} aria-label="Refresh regimes">
              Refresh regimes
            </button>
            <button onClick={onRefreshBriefs} aria-label="Refresh briefs">
              Refresh briefs
            </button>
            <button onClick={onRefreshEnsembles} aria-label="Refresh ensembles">
              Refresh ensembles
            </button>
          </div>
        }
      />
      {!sessionId && <p> Create a session to begin.</p>}
      {sessionId && (
        <>
          <p style={{ color: tokens.colors.muted }}>Compute actions are gated by capabilities and update cached data.</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }} aria-label="Compute actions">
            <button onClick={onCompute} disabled={!capabilities.canComputeV0} title={disabledTooltip(capabilities.canComputeV0)}>
              Compute v0
            </button>
            <button
              onClick={onComputeEcology}
              disabled={!capabilities.canComputeEcology}
              title={disabledTooltip(capabilities.canComputeEcology)}
            >
              Compute Ecology State
            </button>
            <button
              onClick={onGenerateBriefs}
              disabled={!capabilities.canGenerateBriefs}
              title={disabledTooltip(capabilities.canGenerateBriefs)}
            >
              Generate Daily Briefs
            </button>
            <button
              onClick={onComputeV1}
              disabled={!capabilities.canComputeEnsemble}
              title={disabledTooltip(capabilities.canComputeEnsemble)}
            >
              Compute v1 Ensemble
            </button>
            {capabilityState.status === "loading" && <LoadingState label="Checking permissions…" />}
          </div>
          {capabilityState.status === "error" && (
            <p style={{ color: tokens.colors.muted }}>
              Capability endpoint unavailable; controls are defaulting to permissive mode.
            </p>
          )}

          <div style={{ display: "flex", gap: 12, marginTop: 12, flexWrap: "wrap" }} aria-label="Data freshness badges">
            <StatusBadge
              tone={regimeState.status === "success" ? "success" : regimeState.status === "error" ? "danger" : "info"}
              label={`Regimes ${regimeState.updatedAt ? "updated" : regimeState.status}`}
            />
            <StatusBadge
              tone={briefState.status === "success" ? "success" : briefState.status === "error" ? "danger" : "info"}
              label={`Briefs ${briefState.updatedAt ? "updated" : briefState.status}`}
            />
            <StatusBadge
              tone={ensembleState.status === "success" ? "success" : ensembleState.status === "error" ? "danger" : "info"}
              label={`Ensembles ${ensembleState.updatedAt ? "updated" : ensembleState.status}`}
            />
          </div>

          <table style={{ width: "100%", marginTop: 12 }}>
            <thead>
              <tr>
                <th>Underlying</th>
                <th>Regime</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>{decisionTable}</tbody>
          </table>
        </>
      )}
    </section>
  );
};

export default SessionDashboard;
