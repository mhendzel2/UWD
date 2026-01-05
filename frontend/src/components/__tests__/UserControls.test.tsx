import React from "react";
import { render, screen } from "@testing-library/react";
import UserControls from "../UserControls";
import { CapabilityMap, UserStateProvider } from "../../state/user";

describe("UserControls", () => {
  const noop = () => undefined;

  const renderWithProvider = (capabilities: Partial<CapabilityMap> = {}) =>
    render(
      <UserStateProvider initialCapabilities={capabilities}>
        <UserControls
          apiBase="http://localhost:8000"
          sessionId="session-123"
          sessionDate="2024-01-01"
          onCompute={noop}
          onComputeEcology={noop}
          onGenerateBriefs={noop}
          onComputeV1={noop}
        />
      </UserStateProvider>
    );

  it("disables compute buttons when capability is blocked", () => {
    renderWithProvider({
      compute_v0: { allowed: false, reason: "role blocked" },
      compute_ecology: { allowed: true },
      generate_briefs: { allowed: true },
      compute_v1: { allowed: true },
      compute_anomalies: { allowed: true },
    });

    const button = screen.getByRole("button", { name: /compute v0/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "role blocked");
  });
});
