# Decisions
- v0 uses deterministic boolean rules only (no ML, no tuning).
- Imports store raw rows in JSONB to keep all columns replayable.
- Regime classification is per-underlying per-day; plans are derived from the regime only.
