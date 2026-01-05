import { fireEvent, render, screen } from "@testing-library/react";
import DailyBriefsPanel from "../DailyBriefsPanel";

describe("DailyBriefsPanel", () => {
  it("renders loading state", () => {
    render(<DailyBriefsPanel briefs={[]} loading />);
    expect(screen.getByText(/Loading briefs/i)).toBeInTheDocument();
  });

  it("shows error with retry", () => {
    const onRetry = vi.fn();
    render(<DailyBriefsPanel briefs={[]} error="boom" onRetry={onRetry} hasSession />);
    fireEvent.click(screen.getByText(/Retry fetch/i));
    expect(onRetry).toHaveBeenCalled();
  });

  it("shows empty state when no briefs available", () => {
    render(<DailyBriefsPanel briefs={[]} hasSession />);
    expect(screen.getByText(/No brief loaded/i)).toBeInTheDocument();
  });

  it("renders flow entries when present", () => {
    render(
      <DailyBriefsPanel
        briefs={[
          {
            brief_type: "FLOW_SHORT_TERM",
            entries: { items: { bullish: [{ ticker: "SPY", bias: "Bull", call_volume: 10, put_volume: 5 }] } },
          },
        ]}
        regimeMap={{ SPX: "Bull" }}
        hasSession
      />
    );
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getAllByText("Bull").length).toBeGreaterThan(0);
  });
});
