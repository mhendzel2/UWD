import { fireEvent, render, screen } from "@testing-library/react";
import EnsemblePanel from "../EnsemblePanel";

describe("EnsemblePanel", () => {
  it("renders loading state", () => {
    render(<EnsemblePanel ensembles={[]} loading hasSession />);
    expect(screen.getByText(/Loading v1 ensemble/i)).toBeInTheDocument();
  });

  it("renders error state", () => {
    render(<EnsemblePanel ensembles={[]} error="Failed" hasSession />);
    expect(screen.getByText(/Failed/i)).toBeInTheDocument();
  });

  it("renders empty state", () => {
    render(<EnsemblePanel ensembles={[]} hasSession />);
    expect(screen.getByText(/No v1 ensemble decisions yet/i)).toBeInTheDocument();
  });

  it("renders data table", () => {
    render(
      <EnsemblePanel
        ensembles={[
          { underlying: "SPY", ensemble_label: "Bull", ensemble_confidence: 0.9, horizon_weights: { d1: 0.5 } },
        ]}
        hasSession
      />
    );
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("Bull")).toBeInTheDocument();
  });

  it("triggers retry action", () => {
    const onRetry = vi.fn();
    render(<EnsemblePanel ensembles={[]} error="Failed" onRetry={onRetry} hasSession />);
    fireEvent.click(screen.getByText(/Retry fetch/i));
    expect(onRetry).toHaveBeenCalled();
  });
});
