from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from oracle_platform.domain import Side
from oracle_platform.wallet_intelligence import WalletTrade, reconstruct_wallet


def _trade(trade_id, side, price, quantity, fee="0"):
    return WalletTrade(trade_id, "0xabc", "m1", "token1", side, D(price), D(quantity), D(fee),
                       datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=int(trade_id[-1])))


def test_wallet_average_cost_reconstruction_and_pnl():
    trades = [
        _trade("t1", Side.BUY, "0.40", "10", "0.02"),
        _trade("t2", Side.BUY, "0.50", "10", "0.02"),
        _trade("t3", Side.SELL, "0.60", "5", "0.03"),
    ]
    result = reconstruct_wallet(trades, {"token1": D("0.55")},
                                history_complete=True, initial_balances_known=True)
    average_cost = D("9.04") / D("20")
    expected_realised = (D("0.60") - average_cost) * D("5") - D("0.03")
    expected_unrealised = D("0.55") * D("15") - (D("9.04") - average_cost * D("5"))
    assert result.realised_pnl == expected_realised
    assert result.unrealised_pnl == expected_unrealised
    assert result.history_complete is True
    assert result.open_positions["token1"]["quantity"] == D("15")


def test_wallet_unmatched_sell_marks_reconstruction_incomplete():
    result = reconstruct_wallet([_trade("t1", Side.SELL, "0.60", "4")], {})
    assert result.unmatched_sell_count == 1
    assert result.history_complete is False
    assert any("Unmatched sell" in note for note in result.completeness_notes)


def test_missing_open_position_mark_does_not_become_zero_unrealised_pnl():
    result = reconstruct_wallet([_trade("t1", Side.BUY, "0.40", "5")], {},
                                history_complete=True, initial_balances_known=True)
    assert result.unrealised_pnl is None
    assert result.total_pnl is None


def test_unknown_public_trade_fees_withhold_net_pnl_and_skill_metrics():
    trade = WalletTrade(
        "unknown-fee", "0xabc", "m1", "token1", Side.BUY, D("0.4"), D("5"), D("0"),
        datetime(2026, 1, 1, tzinfo=UTC), fee_known=False,
    )
    result = reconstruct_wallet([trade], {"token1": D("0.6")},
                                history_complete=True, initial_balances_known=True)
    assert result.fees_complete is False
    assert result.fees_paid is None
    assert result.realised_pnl is None
    assert result.unrealised_pnl is None
    assert result.total_pnl is None
    assert result.history_complete is False
