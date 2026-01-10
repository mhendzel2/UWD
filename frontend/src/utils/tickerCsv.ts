function parseCsvLine(line: string): string[] {
  // Minimal CSV parser with quote handling.
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (!inQuotes && ch === ",") {
      out.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  out.push(cur);
  return out;
}

export function normalizeTicker(raw: string): string {
  let t = (raw || "").trim();
  t = t.replace(/^['\"]+|['\"]+$/g, "");
  t = t.toUpperCase();
  // Keep common ticker chars (A-Z 0-9 . -)
  t = t.replace(/[^A-Z0-9.\-]/g, "");
  return t;
}

export function parseTickersFromText(text: string): string[] {
  const raw = (text || "").trim();
  if (!raw) return [];

  const lines = raw
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  if (!lines.length) return [];

  // Try CSV-with-header mode.
  const firstCells = parseCsvLine(lines[0]).map((c) => (c || "").trim().toLowerCase());
  const headerCandidates = new Set(["ticker", "tickers", "symbol", "symbols", "underlying", "underlying_symbol"]);
  const headerIndex = firstCells.findIndex((c) => headerCandidates.has(c));

  const tickers: string[] = [];
  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    if (!line) continue;

    // If this line looks like a multi-column CSV, parse it.
    const cells = parseCsvLine(line);
    let candidate = "";

    if (cells.length > 1 || headerIndex >= 0) {
      if (idx === 0 && headerIndex >= 0) continue; // skip header row
      const pick = headerIndex >= 0 ? cells[headerIndex] : cells[0];
      candidate = String(pick ?? "");
    } else {
      candidate = line;
    }

    // Also handle delimiter-separated single line: "AAPL,MSFT,NVDA"
    const splitCandidates = candidate.split(/[\s;|\t]+/).filter(Boolean);
    if (splitCandidates.length > 1) {
      for (const s of splitCandidates) {
        const t = normalizeTicker(s);
        if (t) tickers.push(t);
      }
    } else {
      const t = normalizeTicker(candidate);
      if (t) tickers.push(t);
    }
  }

  // If it's a single-line CSV of tickers, parse that too.
  if (lines.length === 1 && lines[0].includes(",")) {
    const cells = parseCsvLine(lines[0]);
    for (const c of cells) {
      const t = normalizeTicker(c);
      if (t) tickers.push(t);
    }
  }

  // Dedupe preserve order.
  const seen = new Set<string>();
  const deduped: string[] = [];
  for (const t of tickers) {
    if (seen.has(t)) continue;
    seen.add(t);
    deduped.push(t);
  }
  return deduped;
}
