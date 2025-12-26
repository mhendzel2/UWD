import React, { useMemo, useState } from "react";

type BriefEntry = Record<string, any>;
type Brief = {
  brief_type: string;
  entries: { items?: any; note?: string } | any;
};

type Props = {
  briefs: Brief[];
  regimeMap?: Record<string, string>;
};

const tabs = [
  { key: "FLOW_SHORT_TERM", label: "Flow Short-Term" },
  { key: "VOL_SELL_PREMIUM", label: "High IV Sell Premium" },
  { key: "VOL_BUY_PREMIUM", label: "Low IV Buy Premium" },
];

const DailyBriefsPanel: React.FC<Props> = ({ briefs, regimeMap = {} }) => {
  const [active, setActive] = useState<string>(tabs[0].key);

  const activeBrief = useMemo(() => briefs.find((b) => b.brief_type === active), [briefs, active]);

  const flowItems = useMemo(() => {
    if (!activeBrief || activeBrief.brief_type !== "FLOW_SHORT_TERM") return { bullish: [], bearish: [] };
    const items = (activeBrief.entries?.items as any) || {};
    return { bullish: items.bullish || [], bearish: items.bearish || [] };
  }, [activeBrief]);

  const renderFlowTable = (entries: BriefEntry[]) => (
    <table style={{ width: "100%", marginTop: 8 }}>
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Bias</th>
          <th>Call Vol</th>
          <th>Put Vol</th>
          <th>Premium Imbalance</th>
          <th>IV Rank</th>
          <th>Regime OK?</th>
          <th>Key Strikes</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e: BriefEntry) => (
          <tr key={`${e.ticker}-${e.bias}`}>
            <td>{e.ticker}</td>
            <td>{e.bias}</td>
            <td>{e.call_volume}</td>
            <td>{e.put_volume}</td>
            <td>{e.premium_imbalance}</td>
            <td>{typeof e.iv_rank === "number" ? e.iv_rank.toFixed(3) : e.iv_rank}</td>
            <td>{regimeMap["SPX"] || regimeMap["SPXW"] || "n/a"}</td>
            <td>
              {(e.strike_levels?.oi_walls || [])
                .slice(0, 2)
                .map((w: any) => `$${w.strike}`)
                .join(", ") || "n/a"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  const renderVolTable = (entries: BriefEntry[]) => (
    <table style={{ width: "100%", marginTop: 8 }}>
      <thead>
        <tr>
          <th>Ticker</th>
          <th>IV Rank</th>
          <th>Implied Move %</th>
          <th>Structures</th>
          <th>Permission</th>
          <th>Key Strikes</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e: BriefEntry) => (
          <tr key={e.ticker}>
            <td>{e.ticker}</td>
            <td>{typeof e.iv_rank === "number" ? e.iv_rank.toFixed(3) : e.iv_rank}</td>
            <td>{e.implied_move_perc}</td>
            <td>{Array.isArray(e.suggested_structures) ? e.suggested_structures.join(", ") : e.suggested_structures}</td>
            <td>{e.requires_regime_permission ? "Yes" : "No"}</td>
            <td>
              {(e.strike_levels?.oi_walls || [])
                .slice(0, 2)
                .map((w: any) => `$${w.strike}`)
                .join(", ") || "n/a"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  const renderContent = () => {
    if (!activeBrief) return <p>No brief loaded.</p>;
    if (activeBrief.brief_type === "FLOW_SHORT_TERM") {
      return (
        <>
          <h4>Bullish</h4>
          {renderFlowTable(flowItems.bullish)}
          <h4 style={{ marginTop: 12 }}>Bearish</h4>
          {flowItems.bearish.length ? renderFlowTable(flowItems.bearish) : <p>No bearish candidates (filtered out).</p>}
          {activeBrief.entries?.note && <p style={{ color: "#555" }}>{activeBrief.entries.note}</p>}
        </>
      );
    }
    const items = (activeBrief.entries?.items as BriefEntry[]) || (activeBrief.entries as BriefEntry[]) || [];
    return (
      <>
        {renderVolTable(items)}
        {activeBrief.entries?.note && <p style={{ color: "#555" }}>{activeBrief.entries.note}</p>}
      </>
    );
  };

  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Daily Briefs</h3>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        {tabs.map((tab) => (
          <button key={tab.key} onClick={() => setActive(tab.key)} disabled={active === tab.key}>
            {tab.label}
          </button>
        ))}
      </div>
      {renderContent()}
    </section>
  );
};

export default DailyBriefsPanel;
