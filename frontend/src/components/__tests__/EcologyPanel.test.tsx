import { fireEvent, render, screen } from "@testing-library/react";
import EcologyPanel from "../EcologyPanel";

describe("EcologyPanel", () => {
  it("renders loading state", () => {
    render(<EcologyPanel entries={[]} loading hasSession />);
    expect(screen.getByText(/Loading ecology insights/i)).toBeInTheDocument();
  });

  it("renders error state", () => {
    render(<EcologyPanel entries={[]} error="Oops" hasSession />);
    expect(screen.getByText(/Oops/i)).toBeInTheDocument();
  });

  it("renders empty state", () => {
    render(<EcologyPanel entries={[]} hasSession />);
    expect(screen.getByText(/No ecology state computed yet/i)).toBeInTheDocument();
  });

  it("renders entries and details", () => {
    render(
      <EcologyPanel
        entries={[
          {
            underlying: "SPY",
            ecology_state: {
              volatility_ecology: "calm",
              disagreement_intensity: "low",
              intent_profile: "balanced",
              tail_risk_flag: false,
              drawdown_shock_active: false,
              timing_profile: { label: "neutral" },
              strike_levels: { oi_walls: [{ strike: 5000, total_oi: 1000 }] },
              explanation_bullets: ["Test bullet"],
            },
          },
        ]}
        hasSession
      />
    );
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText(/Test bullet/i)).toBeInTheDocument();
  });

  it("fires retry action", () => {
    const onRetry = vi.fn();
    render(<EcologyPanel entries={[]} error="Err" onRetry={onRetry} hasSession />);
    fireEvent.click(screen.getByText(/Retry fetch/i));
    expect(onRetry).toHaveBeenCalled();
  });
});
