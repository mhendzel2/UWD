import { describe, expect, it } from "vitest";
import { parseTickersFromText } from "./tickerCsv";

describe("parseTickersFromText", () => {
  it("extracts tickers from a multi-column screener CSV with symbol header", () => {
    const sample = `symbol,companyName,industry,marketCap,price
SLV,iShares Silver Trust,Asset Management,41623997116,72.38
TSLA,"Tesla, Inc.",Auto - Manufacturers,1433061946226,445.01
INTC,Intel Corporation,Semiconductors,217618744494,45.55
`;

    expect(parseTickersFromText(sample)).toEqual(["SLV", "TSLA", "INTC"]);
  });

  it("handles a single-line comma-separated ticker list", () => {
    expect(parseTickersFromText("aapl, msft, nvda")).toEqual(["AAPL", "MSFT", "NVDA"]);
  });
});
