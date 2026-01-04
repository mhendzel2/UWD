from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.anomalies import robust_center_scale, percentile_rank
from app.anomalies.scoring import _score_candidate, FeatureStat, EventCandidate, compute_anomalies_for_session
from app.db import models
from app.ingest import oi_diff, hot_chains, darkpool_eod, stock_screener_eod


def test_robust_stats_and_percentile():
    center, scale = robust_center_scale([1, 2, 2, 3, 100])
    assert center == 2
    assert scale > 0
    pct = percentile_rank(3, sorted([1, 2, 2, 3, 100]))
    assert 0.5 < pct <= 1.0


def test_reason_codes_deterministic_order():
    stats = {
        (models.RawSource.OI_DIFF, "SPY"): {
            "oi_diff_plain": FeatureStat(center=0.0, scale=1.0, sorted_values=[0.0, 1.0]),
            "volume": FeatureStat(center=1.0, scale=1.0, sorted_values=[1.0, 2.0]),
        }
    }
    cand = EventCandidate(
        source=models.RawSource.OI_DIFF,
        ticker="SPY",
        event_key="event",
        features={"oi_diff_plain": 10.0, "volume": 2.0},
        raw_ref={},
    )
    scored = _score_candidate(cand, stats)
    assert scored.reason_codes[0].startswith("OI change")
    assert "Volume" in " ".join(scored.reason_codes)


def test_duplicate_headers_are_deduped(tmp_path):
    csv_content = "option_symbol,close,close,volume,open_interest,premium,trades\nXYZ250101C00010000,1,2,10,5,1000,3\n"
    csv_file = tmp_path / "dup.csv"
    csv_file.write_text(csv_content)
    parsed = hot_chains.parse_hot_chains(csv_file)
    assert len(set(parsed.headers)) == len(parsed.headers)
    assert any(h.startswith("close_") for h in parsed.headers if h != "close")


def test_anomalies_integration_with_sample_data(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    models.Base.metadata.create_all(engine)
    db = SessionLocal()

    session = models.Session(date=date(2025, 11, 24), strategy_mode=models.StrategyMode.INDEX_EOD)
    db.add(session)
    db.commit()
    db.refresh(session)

    root = Path(__file__).resolve().parents[2]
    samples = [
        (models.RawSource.OI_DIFF, oi_diff.parse_oi_diff, root / "sample_data" / "chain-oi-changes-2025-11-24.csv"),
        (models.RawSource.HOT_CHAINS, hot_chains.parse_hot_chains, root / "sample_data" / "hot-chains-2025-11-24.csv"),
        (models.RawSource.DARKPOOL_EOD, darkpool_eod.parse_darkpool, root / "sample_data" / "dp-eod-report-2025-11-24.csv"),
        (models.RawSource.STOCK_SCREENER, stock_screener_eod.parse_stock_screener, root / "sample_data" / "stock-screener-2025-11-24.csv"),
    ]
    for source, parser, path in samples:
        parsed = parser(Path(path))
        rows = parsed.rows[:50]
        db.add(
            models.RawFile(
                session_id=session.session_id,
                source=source,
                filename=Path(path).name,
                sha256="sample",
                rows=len(rows),
                extras={"rows": rows},
            )
        )
    db.commit()

    result = compute_anomalies_for_session(db, session, lookback_sessions=0)
    assert result["events"], "Expected scored anomalies"
    assert result["rollups"], "Expected ticker rollups"
    first_event = result["events"][0]
    assert first_event.reason_codes
    assert first_event.feature_payload
    db.close()


def test_anomaly_migration_present():
    path = Path(__file__).resolve().parents[2] / "backend" / "app" / "db" / "migrations" / "versions" / "0004_anomalies.py"
    content = path.read_text()
    assert "anomaly_events" in content
    assert "anomaly_ticker_rollups" in content
