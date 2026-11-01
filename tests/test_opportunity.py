from datetime import datetime, timezone
from decimal import Decimal as D

from oracle_platform.domain import BookLevel, OrderBook, Side
from oracle_platform.opportunity import OutcomeLeg, evaluate_complete_set, evaluate_directional


def _book(token, bids, asks):
    return OrderBook("market-1", token,
                     tuple(BookLevel(D(p), D(q)) for p, q in bids),
                     tuple(BookLevel(D(p), D(q)) for p, q in asks),
                     datetime.now(timezone.utc))


def test_directional_buy_uses_ask_vwap_and_fees():
    book = _book("yes", [("0.49", "20")], [("0.50", "5"), ("0.52", "10")])
    result = evaluate_directional(outcome_probability=D("0.60"), book=book, side=Side.BUY,
                                  quantity=D("5"), fee_rate=D("0.01"), limit_price=D("0.51"))
    assert result.executable
    assert result.average_price == D("0.50")
    assert result.net_edge_per_share == D("0.0950")
    assert result.net_expected_value == D("0.475000")


def test_directional_requires_full_requested_depth():
    book = _book("yes", [("0.49", "20")], [("0.50", "5"), ("0.52", "10")])
    result = evaluate_directional(outcome_probability=D("0.60"), book=book, side=Side.BUY,
                                  quantity=D("6"), fee_rate=D("0"), limit_price=D("0.51"))
    assert not result.executable
    assert result.filled_quantity == D("5")
    assert result.reason == "INSUFFICIENT_FULL_DEPTH"


def test_directional_sell_uses_bid_depth():
    book = _book("yes", [("0.50", "10")], [("0.52", "10")])
    result = evaluate_directional(outcome_probability=D("0.45"), book=book, side=Side.SELL,
                                  quantity=D("2"), fee_rate=D("0.01"), limit_price=D("0.50"))
    assert result.executable
    assert result.net_edge_per_share == D("0.0450")


def test_complete_set_requires_exact_exhaustive_outcome_coverage():
    legs = [
        OutcomeLeg("A", _book("a", [("0.30", "10")], [("0.32", "10")]), D("0")),
        OutcomeLeg("B", _book("b", [("0.28", "10")], [("0.29", "10")]), D("0")),
        OutcomeLeg("C", _book("c", [("0.30", "10")], [("0.31", "10")]), D("0")),
    ]
    result = evaluate_complete_set(market_id="market-1", expected_outcomes=("A", "B", "C"),
                                  legs=legs, quantity=D("2"), outcomes_verified_exhaustive=True,
                                  settlement_rules_verified=True)
    assert result.executable
    assert result.net_profit == D("0.16")
    rejected = evaluate_complete_set(market_id="market-1", expected_outcomes=("A", "B", "C"),
                                     legs=legs[:2], quantity=D("2"), outcomes_verified_exhaustive=True,
                                     settlement_rules_verified=True)
    assert not rejected.executable
    assert rejected.reason == "OUTCOME_COVERAGE_MISMATCH"
