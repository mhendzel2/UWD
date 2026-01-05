import { fireEvent, render, screen } from "@testing-library/react";
import RegimesPanel from "../RegimesPanel";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  PieChart: ({ children }: any) => <div>{children}</div>,
  Pie: ({ children }: any) => <div>{children}</div>,
  Cell: () => <div />,
  Tooltip: () => <div />,
  BarChart: ({ children }: any) => <div>{children}</div>,
  Bar: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  CartesianGrid: () => <div />,
  Legend: () => <div />,
}));

describe("RegimesPanel", () => {
  it("renders loading state", () => {
    render(<RegimesPanel regimes={[]} loading hasSession />);
    expect(screen.getByText(/Loading regimes/i)).toBeInTheDocument();
  });

  it("renders error with retry", () => {
    const onRetry = vi.fn();
    render(<RegimesPanel regimes={[]} error="Failed to fetch" onRetry={onRetry} hasSession />);
    fireEvent.click(screen.getByText(/Retry fetch/i));
    expect(onRetry).toHaveBeenCalled();
  });

  it("renders table rows when regimes exist", () => {
    render(
      <RegimesPanel
        regimes={[
          { underlying: "SPY", regime_label: "Bull", confidence_tier: "HIGH" },
          { underlying: "QQQ", regime_label: "Neutral", confidence_tier: "MEDIUM" },
        ]}
        hasSession
      />
    );
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("QQQ")).toBeInTheDocument();
  });

  it("shows empty message when no session is present", () => {
    render(<RegimesPanel regimes={[]} />);
    expect(screen.getByText(/Create or select a session/i)).toBeInTheDocument();
  });
});
