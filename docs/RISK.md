# Risk Notes
- v0 is analysis-only; no broker connectivity or order routing.
- Boolean thresholds are intentionally conservative and logged via `numeric_context`.
- CSV parsers keep all columns; malformed rows are skipped but recorded by row count.
- WebSocket streams are stubbed; rely on REST responses for authoritative outputs.
