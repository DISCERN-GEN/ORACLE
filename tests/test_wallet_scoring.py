from datetime import datetime, timezone
from decimal import Decimal as D

from oracle_platform.domain import Side
from oracle_platform.wallet_intelligence import WalletTrade, reconstruct_wallet
from oracle_platform.wallet_scoring import score_wallet


def test_incomplete_wallet_is_never_labelled_verified():
    trade = WalletTrade("t1", "0xabc", "m1", "tok1", Side.BUY, D("0.4"), D("2"), D("0"), datetime.now(timezone.utc))
    reconstruction = reconstruct_wallet([trade])
    result = score_wallet(reconstruction)
    assert result.evidence_status == "provisional_unverified"
    assert result.components["out_of_sample_skill"] is None
    assert result.confidence < D("0.2")


def test_missing_metrics_are_not_zero_filled_or_claimed_as_skill():
    reconstruction = reconstruct_wallet([])
    result = score_wallet(reconstruction)
    assert result.evidence_status == "insufficient_data"
    assert result.components["risk_adjusted_return"] is None
    assert result.components["closing_line_value"] is None
    assert "unscored" in " ".join(result.warnings)


def test_consistency_uses_explicit_resolved_position_results_not_matched_sell_rate():
    trade = WalletTrade("t1", "0xabc", "m1", "tok1", Side.BUY, D("0.4"), D("2"), D("0"), datetime.now(timezone.utc))
    reconstruction = reconstruct_wallet([trade])
    missing = score_wallet(reconstruction, resolved_positions=20)
    assert missing.components["consistency"] is None

    supplied = score_wallet(reconstruction, resolved_positions=20, resolved_position_wins=18)
    assert supplied.components["consistency"] is not None
    assert supplied.sample_size == 20
    assert supplied.observed_weight > missing.observed_weight
