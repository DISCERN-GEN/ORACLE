from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from oracle_platform.domain import BookLevel, Forecast, OrderBook, OrderIntent, PaperAccount, Side
from oracle_platform.risk import RiskEngine
from oracle_platform.sessions import PaperSession, SessionState


def _fixtures(age_seconds: int = 0):
    now = datetime.now(UTC)
    book = OrderBook("m1", "yes-token", (BookLevel(D("0.49"), D("20")),),
                     (BookLevel(D("0.50"), D("20")),), now - timedelta(seconds=age_seconds))
    forecast = Forecast("m1", "YES", D("0.60"), D("0.55"), D("0.65"), D("0.8"), "test", "0.1")
    intent = OrderIntent("m1", "yes-token", Side.BUY, D("0.50"), D("2"), "risk-test-123456")
    account = PaperAccount.create(D("1000"))
    return now, book, forecast, intent, account


def test_risk_approves_small_positive_edge_paper_order():
    now, book, forecast, intent, account = _fixtures()
    result = RiskEngine().evaluate_paper(intent, forecast, book, account, D("0.005"), D("0.09"), now)
    assert result.decision.value == "approve"
    assert not result.checks_failed


def test_risk_rejects_negative_net_ev():
    now, book, forecast, intent, account = _fixtures()
    result = RiskEngine().evaluate_paper(intent, forecast, book, account, D("0.005"), D("-0.01"), now)
    assert result.decision.value == "reject"
    assert "positive_net_expected_value" in result.checks_failed


def test_risk_rejects_stale_orderbook():
    now, book, forecast, intent, account = _fixtures(age_seconds=60)
    result = RiskEngine().evaluate_paper(intent, forecast, book, account, D("0.005"), D("0.09"), now)
    assert "fresh_market_data" in result.checks_failed


def test_12_hour_session_transitions_to_completed():
    now = datetime.now(UTC)
    session = PaperSession.start(12, now)
    assert session.state == SessionState.RUNNING
    assert session.refresh(now + timedelta(hours=11, minutes=59)) == SessionState.RUNNING
    assert session.refresh(now + timedelta(hours=12)) == SessionState.COMPLETED


def test_session_duration_is_bounded():
    try:
        PaperSession.start(0)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for zero-hour session")
