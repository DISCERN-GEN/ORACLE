from datetime import datetime, timezone
from decimal import Decimal as D

from oracle_platform.domain import BookLevel, OrderBook, OrderIntent, PaperAccount, Side
from oracle_platform.paper_broker import PaperBroker


def test_buy_fills_only_visible_asks_at_or_below_limit():
    now = datetime.now(timezone.utc)
    book = OrderBook("m1", "yes-token",
                     bids=(BookLevel(D("0.49"), D("20")),),
                     asks=(BookLevel(D("0.50"), D("3")), BookLevel(D("0.52"), D("10"))),
                     captured_at=now)
    account = PaperAccount.create(D("100"))
    intent = OrderIntent("m1", "yes-token", Side.BUY, D("0.51"), D("5"), "idempotency-12345")
    result = PaperBroker().execute(intent, book, account, D("0.01"), True)
    assert result.status == "PARTIALLY_FILLED"
    assert result.filled_quantity == D("3")
    assert result.remaining_quantity == D("2")
    assert result.average_price == D("0.50")
    assert result.fee_total == D("0.0150")
    assert account.positions["yes-token"] == D("3")
    assert account.cash == D("98.4850")


def test_unverified_fee_schedule_cannot_fill():
    now = datetime.now(timezone.utc)
    book = OrderBook("m1", "yes-token", (), (BookLevel(D("0.5"), D("10")),), now)
    account = PaperAccount.create(D("100"))
    intent = OrderIntent("m1", "yes-token", Side.BUY, D("0.5"), D("2"), "idempotency-12346")
    result = PaperBroker().execute(intent, book, account, D("0"), False)
    assert result.status == "REJECTED"
    assert result.reason == "FEE_SCHEDULE_UNVERIFIED"
    assert account.cash == D("100")


def test_no_crossing_depth_remains_unfilled():
    now = datetime.now(timezone.utc)
    book = OrderBook("m1", "yes-token", (), (BookLevel(D("0.6"), D("10")),), now)
    account = PaperAccount.create(D("100"))
    intent = OrderIntent("m1", "yes-token", Side.BUY, D("0.5"), D("2"), "idempotency-12347")
    result = PaperBroker().execute(intent, book, account, D("0"), True)
    assert result.status == "UNFILLED"
    assert account.cash == D("100")


def test_sell_releases_original_cost_basis_from_market_exposure():
    now = datetime.now(timezone.utc)
    buy_book = OrderBook("m1", "yes-token", (), (BookLevel(D("0.50"), D("10")),), now)
    account = PaperAccount.create(D("100"))
    buy = OrderIntent("m1", "yes-token", Side.BUY, D("0.50"), D("3"), "buy-1234567890")
    broker = PaperBroker()
    result = broker.execute(buy, buy_book, account, D("0.01"), True)
    assert result.status == "FILLED"
    assert account.market_exposure["m1"] == D("1.5150")

    sell_book = OrderBook("m1", "yes-token", (BookLevel(D("0.70"), D("10")),), (), now)
    sell = OrderIntent("m1", "yes-token", Side.SELL, D("0.70"), D("1"), "sell-1234567890")
    result = broker.execute(sell, sell_book, account, D("0.01"), True)
    assert result.status == "FILLED"
    assert account.positions["yes-token"] == D("2")
    assert account.market_exposure["m1"] == D("1.01000")


def test_broker_rejects_below_minimum_or_invalid_tick():
    now = datetime.now(timezone.utc)
    book = OrderBook("m1", "yes-token", (), (BookLevel(D("0.5"), D("10")),), now,
                     tick_size=D("0.05"), min_order_size=D("2"))
    account = PaperAccount.create(D("100"))
    too_small = OrderIntent("m1", "yes-token", Side.BUY, D("0.5"), D("1"), "small-1234567890")
    assert PaperBroker().execute(too_small, book, account, D("0"), True).reason == "BELOW_VENUE_MINIMUM_SIZE"
    bad_tick = OrderIntent("m1", "yes-token", Side.BUY, D("0.51"), D("2"), "tick-1234567890")
    assert PaperBroker().execute(bad_tick, book, account, D("0"), True).reason == "INVALID_TICK_SIZE"
