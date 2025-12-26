# Decisions
- v0 uses deterministic boolean rules only (no ML, no tuning).
- Imports store raw rows in JSONB to keep all columns replayable.
- Regime classification is per-underlying per-day; plans are derived from the regime only.
- v1 adds persistence metrics (OI/hot chains/intent, regime switch rate, range/volume context) and a conservative ensemble built from three micro-classifiers; v0 artifacts remain unchanged in their own rows.
- Horizon weights are constrained (floor 0.2, max weekly delta 0.05) and only updated after ≥12 labeled Fridays using EWMA accuracy with extra penalty for false TREND_RISK on PIN_RANGE; no threshold optimization or ML.
- Daily Briefs are discovery-only and explicitly marked as candidates requiring regime permission; no execution instructions are produced.
- Ecology state is an interpretability layer translating existing booleans into dominant horizon, volatility ecology, disagreement, and tail-risk flags that inform plan modifiers (confidence adjust, permission gating, sizing caps) without adding alpha.
