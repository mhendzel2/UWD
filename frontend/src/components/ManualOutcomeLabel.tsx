import React, { useState } from "react";

type Props = {
  apiBase: string;
  defaultDate: string;
  onSaved: (msg: string) => void;
};

const ManualOutcomeLabel: React.FC<Props> = ({ apiBase, defaultDate, onSaved }) => {
  const [tradeDate, setTradeDate] = useState<string>(defaultDate);
  const [underlying, setUnderlying] = useState<string>("");
  const [label, setLabel] = useState<string>("PIN_RANGE");
  const [notes, setNotes] = useState<string>("");

  const submit = async () => {
    const form = new FormData();
    form.append("trade_date", tradeDate);
    form.append("underlying", underlying);
    form.append("realized_label_manual", label);
    form.append("notes", notes);
    const res = await fetch(`${apiBase}/outcomes`, { method: "POST", body: form });
    if (res.ok) {
      const data = await res.json();
      onSaved(`Saved outcome ${data.outcome_id}`);
    } else {
      onSaved("Outcome save failed");
    }
  };

  return (
    <section className="panel" aria-label="Manual outcome label">
      <h3>Manual Outcome Label</h3>
      <div style={{ display: "grid", gap: 6, maxWidth: 360 }}>
        <input placeholder="Trade Date" value={tradeDate} onChange={(e) => setTradeDate(e.target.value)} aria-label="Trade date" />
        <input
          placeholder="Underlying (e.g., SPX)"
          value={underlying}
          onChange={(e) => setUnderlying(e.target.value)}
          aria-label="Underlying ticker"
        />
        <select value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Outcome label">
          <option value="PIN_RANGE">PIN_RANGE</option>
          <option value="TREND">TREND</option>
          <option value="MIXED">MIXED</option>
        </select>
        <textarea placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} aria-label="Notes" />
        <button onClick={submit} aria-label="Save outcome">
          Save Outcome
        </button>
      </div>
    </section>
  );
};

export default ManualOutcomeLabel;
