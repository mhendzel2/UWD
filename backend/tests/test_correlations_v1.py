from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analysis.correlations_v1 import compute_and_persist_correlations_v1
from app.db import models


def test_correlations_compute_and_persist_sqlite():
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    models.Base.metadata.create_all(engine)
    db = SessionLocal()

    dates = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)]

    def stock_row(ticker: str, d: date, close: float, net_prem: float) -> dict:
        call_prem = 2_000.0 if net_prem > 0 else 1_000.0
        put_prem = 1_000.0 if net_prem > 0 else 2_000.0
        return {
            "date": str(d),
            "ticker": ticker,
            "close": close,
            "call_volume": 10_000,
            "put_volume": 8_000,
            "call_premium": call_prem,
            "put_premium": put_prem,
            "put_call_ratio": (put_prem / call_prem),
            "call_open_interest": 5_000,
            "put_open_interest": 4_000,
            "marketcap": 1_000_000_000,
            "total_volume": 5_000_000,
            "iv_rank": 0.5,
            "iv30d": 0.30,
            "iv30d_1d": 0.29,
            "issue_type": "Common Stock",
            "is_index": "f",
        }

    def bot_rows(ticker: str, bullish: bool) -> list[dict]:
        # Make sentiment deterministic:
        # - bullish: call@ask (bullish)
        # - bearish: put@ask (bearish)
        return [
            {
                "ticker": ticker,
                "side": "ask",
                "option_type": "call" if bullish else "put",
                "premium": 1_000.0,
                "overpay_score": 1.0,
                "aggressive_score": 0.0,
                "gamma_exposure": 0.0,
            },
            {
                "ticker": ticker,
                "side": "ask",
                "option_type": "call" if bullish else "put",
                "premium": 500.0,
                "overpay_score": 0.0,
                "aggressive_score": 1.0,
                "gamma_exposure": 0.0,
            },
        ]

    # Build 4 sessions with 2 tickers each; AAA up, BBB down.
    sessions: list[models.Session] = []
    for d in dates:
        s = models.Session(date=d, strategy_mode=models.StrategyMode.EQUITY_THU_EOD)
        db.add(s)
        db.commit()
        db.refresh(s)
        sessions.append(s)

        aaa_close = 100 + 5 * (d - dates[0]).days
        bbb_close = 100 - 2 * (d - dates[0]).days

        db.add(
            models.RawFile(
                session_id=s.session_id,
                source=models.RawSource.STOCK_SCREENER,
                filename=f"stock-{d}.csv",
                sha256="x",
                rows=2,
                extras={
                    "rows": [
                        stock_row("AAA", d, float(aaa_close), net_prem=1000.0),
                        stock_row("BBB", d, float(bbb_close), net_prem=-1000.0),
                    ]
                },
            )
        )
        db.add(
            models.RawFile(
                session_id=s.session_id,
                source=models.RawSource.BOT_EOD,
                filename=f"bot-{d}.csv",
                sha256="y",
                rows=4,
                extras={"rows": bot_rows("AAA", bullish=True) + bot_rows("BBB", bullish=False)},
            )
        )
        db.commit()

    # Compute on last session; need horizon=1.
    payload = compute_and_persist_correlations_v1(
        db,
        sessions[-1],
        lookback_sessions=10,
        horizons=(1,),
        method="spearman",
    )

    assert payload["run_id"]
    assert payload["results"]["by_horizon"]["1"]["ss_net_premium_mcap"]["corr"] is not None
    assert payload["results"]["by_horizon"]["1"]["ss_net_premium_mcap"]["corr"] > 0

    runs = db.query(models.CorrelationRun).all()
    assert len(runs) == 1
    assert str(runs[0].session_id) == str(sessions[-1].session_id)
    assert runs[0].results is not None

    db.close()


def test_correlation_migration_present():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "0007_correlations.py"
    )
    content = path.read_text()
    assert "correlation_runs" in content
    assert "uq_correlation_run" in content
