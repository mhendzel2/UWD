from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models
from app.options_signals.pipeline import (
    compute_contract_aggregates,
    compute_underlying_aggregates,
    compute_underlying_features,
    ingest_opt_trades,
    upsert_news_sentiment,
    upsert_ohlcv_daily,
)


def _write_trades_csv(path: Path) -> None:
    df = pd.DataFrame(
        [
            {
                "executed_at": "2025-01-02T14:30:00Z",
                "underlying_symbol": "AAPL",
                "option_chain_id": "AAPL-2025-01-17-C-150",
                "side": "ask",
                "strike": 150,
                "option_type": "call",
                "expiry": "1/17/2025",
                "underlying_price": 148.0,
                "nbbo_bid": 1.9,
                "nbbo_ask": 2.0,
                "ewma_nbbo_bid": 0.0,
                "ewma_nbbo_ask": 0.0,
                "price": 2.0,
                "size": 10,
                "premium": 2000,
                "volume": 10,
                "open_interest": 100,
                "implied_volatility": 0.25,
                "delta": 0.55,
                "theta": -0.01,
                "gamma": 0.02,
                "vega": 0.1,
                "rho": 0.01,
                "theo": 1.95,
                "sector": "Tech",
                "exchange": "CBOE",
                "report_flags": "OK",
                "canceled": False,
                "upstream_condition_detail": "",
                "equity_type": "EQ",
            },
            {
                "executed_at": "2025-01-02T15:00:00Z",
                "underlying_symbol": "AAPL",
                "option_chain_id": "AAPL-2025-01-17-P-145",
                "side": "bid",
                "strike": 145,
                "option_type": "put",
                "expiry": "2025-01-17",
                "underlying_price": 148.0,
                "nbbo_bid": 1.4,
                "nbbo_ask": 1.5,
                "ewma_nbbo_bid": 0.0,
                "ewma_nbbo_ask": 0.0,
                "price": 1.4,
                "size": 5,
                "premium": 700,
                "volume": 5,
                "open_interest": 80,
                "implied_volatility": 0.3,
                "delta": -0.45,
                "theta": -0.02,
                "gamma": 0.03,
                "vega": 0.12,
                "rho": -0.01,
                "theo": 1.45,
                "sector": "Tech",
                "exchange": "CBOE",
                "report_flags": "OK",
                "canceled": False,
                "upstream_condition_detail": "",
                "equity_type": "EQ",
            },
        ]
    )
    df.to_csv(path, index=False)


def test_options_signals_etl_integration(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    models.Base.metadata.create_all(engine)
    db = SessionLocal()

    trade_date = date(2025, 1, 2)
    trades_path = tmp_path / "trades.csv"
    _write_trades_csv(trades_path)

    ingest_opt_trades(db, trade_date=trade_date, trades_path=str(trades_path))

    ohlcv = pd.DataFrame(
        [
            {
                "trade_date": trade_date.isoformat(),
                "underlying_symbol": "AAPL",
                "open": 147.5,
                "high": 150.0,
                "low": 146.8,
                "close": 149.0,
                "adj_close": 149.0,
                "volume": 1000000,
            }
        ]
    )
    upsert_ohlcv_daily(db, ohlcv)

    news = pd.DataFrame(
        [
            {
                "trade_date": trade_date.isoformat(),
                "underlying_symbol": "AAPL",
                "article_count_24h": 5,
                "sentiment_mean": 0.1,
                "sentiment_std": 0.2,
                "sentiment_abs_mean": 0.1,
                "source_count": 3,
                "news_missing": False,
            }
        ]
    )
    upsert_news_sentiment(db, news)

    compute_contract_aggregates(db, trade_date=trade_date)
    compute_underlying_aggregates(db, trade_date=trade_date)
    compute_underlying_features(db, trade_date=trade_date)

    agg_row = db.query(models.OptAggUnderlyingDaily).filter_by(trade_date=trade_date, underlying_symbol="AAPL").first()
    assert agg_row is not None
    assert float(agg_row.call_volume) == 10
    assert float(agg_row.put_volume) == 5

    feat_row = db.query(models.FeaturesUnderlyingDaily).filter_by(trade_date=trade_date, underlying_symbol="AAPL").first()
    assert feat_row is not None
    assert feat_row.news_count == 5
    assert float(feat_row.call_premium) == 2000

    db.close()
