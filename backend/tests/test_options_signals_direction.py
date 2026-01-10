from app.options_signals.direction import infer_trade_direction


def test_trade_direction_at_ask():
    direction, usable = infer_trade_direction(
        price=2.0,
        side=None,
        nbbo_bid=1.9,
        nbbo_ask=2.0,
        ewma_nbbo_bid=None,
        ewma_nbbo_ask=None,
    )
    assert direction == "buyer_initiated"
    assert usable is True


def test_trade_direction_at_bid():
    direction, usable = infer_trade_direction(
        price=1.5,
        side=None,
        nbbo_bid=1.5,
        nbbo_ask=1.6,
        ewma_nbbo_bid=None,
        ewma_nbbo_ask=None,
    )
    assert direction == "seller_initiated"
    assert usable is True


def test_trade_direction_at_mid_unknown():
    direction, usable = infer_trade_direction(
        price=1.55,
        side=None,
        nbbo_bid=1.5,
        nbbo_ask=1.6,
        ewma_nbbo_bid=None,
        ewma_nbbo_ask=None,
        eps=0.0,
        eps2=0.0,
    )
    assert direction == "unknown"
    assert usable is True


def test_trade_direction_missing_quotes():
    direction, usable = infer_trade_direction(
        price=1.55,
        side=None,
        nbbo_bid=None,
        nbbo_ask=None,
        ewma_nbbo_bid=None,
        ewma_nbbo_ask=None,
    )
    assert direction == "unknown"
    assert usable is False
