from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import get_db
from app.db import models
from app.main import app


def test_options_signals_screener_schema_snapshot():
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    models.Base.metadata.create_all(engine)
    db = SessionLocal()

    trade_date = date(2025, 1, 2)
    db.add(
        models.FeaturesUnderlyingDaily(
            trade_date=trade_date,
            underlying_symbol="AAPL",
            sector="Tech",
            close=150.0,
            ret_1d=0.01,
            put_call_vol_ratio=0.7,
            net_premium=120000,
            call_buy_premium=150000,
            put_buy_premium=30000,
            iv_atm_proxy=0.25,
            iv_rank_252=0.6,
            rv_20=0.2,
            iv_minus_rv20=0.05,
            news_count=4,
            sentiment_mean=0.1,
            uoa_contract_count=2,
            uoa_max_volume_z=3.2,
        )
    )
    db.add(
        models.SignalsUnderlyingDaily(
            trade_date=trade_date,
            underlying_symbol="AAPL",
            signal_name="BULL_FLOW",
            score=2.1,
            rank=1,
            explanation_json={"components": {"z_call_buy_premium_60": 2.0}},
        )
    )
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    resp = client.get("/options-signals/screener?date=2025-01-02&signal=BULL_FLOW")
    assert resp.status_code == 200
    payload = resp.json()
    assert "rows" in payload
    assert payload["rows"]
    row = payload["rows"][0]
    assert set(row.keys()) >= {
        "underlying_symbol",
        "sector",
        "close",
        "ret_1d",
        "signal_score",
        "put_call_vol_ratio",
        "net_premium",
        "iv_atm_proxy",
        "iv_rank_252",
        "rv_20",
        "news_count",
        "uoa_contract_count",
    }
    app.dependency_overrides.clear()
