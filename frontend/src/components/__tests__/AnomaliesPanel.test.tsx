import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import AnomaliesPanel from "../AnomaliesPanel";

describe("AnomaliesPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading state while fetching anomalies", async () => {
    let resolveFetch: any;
    vi.spyOn(global, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve;
        }) as any
    );

    render(<AnomaliesPanel apiBase="/api" sessionId="sess" sessionDate="2024-01-01" />);
    expect(screen.getByText(/Loading anomalies/i)).toBeInTheDocument();

    resolveFetch({ ok: true, json: async () => ({ events: [], rollups: [] }) });
    await waitFor(() => expect(screen.getByText(/No anomalies found/i)).toBeInTheDocument());
  });

  it("renders error state and retries fetch", async () => {
    const fetchMock = vi
      .spyOn(global, "fetch")
      .mockResolvedValueOnce({ ok: false, text: async () => "", json: async () => ({}) } as any)
      .mockResolvedValue({ ok: true, json: async () => ({ events: [], rollups: [] }) } as any);

    render(<AnomaliesPanel apiBase="/api" sessionId="sess" sessionDate="2024-01-01" />);

    await waitFor(() => expect(screen.getByText(/Failed to load anomalies/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Retry fetch/i));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("renders events when fetch succeeds", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        events: [
          {
            source: "OI_DIFF",
            ticker: "SPY",
            event_key: "key-1",
            severity_score: 0.9,
            ensemble_score: 0.5,
            reason_codes: ["OI"],
            feature_payload: {},
          },
        ],
        rollups: [],
      }),
    } as any);

    render(<AnomaliesPanel apiBase="/api" sessionId="sess" sessionDate="2024-01-01" />);

    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());
    expect(screen.getAllByText("OI_DIFF").length).toBeGreaterThan(0);
  });
});
