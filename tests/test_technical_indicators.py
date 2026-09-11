from app.analysis.technical_indicators import (
    compute_rsi,
    compute_technical_indicators,
    compute_volatility,
)


def test_compute_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 16)]  # strictly increasing, 15 points
    assert compute_rsi(closes, period=14) == 100.0


def test_compute_rsi_all_losses_is_0():
    closes = [float(i) for i in range(15, 0, -1)]  # strictly decreasing
    assert compute_rsi(closes, period=14) == 0.0


def test_compute_rsi_insufficient_data_returns_none():
    assert compute_rsi([1.0, 2.0, 3.0], period=14) is None


def test_compute_rsi_mixed_movement_is_between_0_and_100():
    closes = [100, 102, 101, 105, 103, 107, 106, 110, 108, 112, 111, 115, 113, 117, 116]
    rsi = compute_rsi([float(c) for c in closes], period=14)
    assert rsi is not None
    assert 0.0 < rsi < 100.0


def test_compute_volatility_zero_for_constant_prices():
    assert compute_volatility([100.0, 100.0, 100.0]) == 0.0


def test_compute_volatility_insufficient_data_returns_none():
    assert compute_volatility([100.0]) is None


def test_compute_volatility_positive_for_varying_prices():
    vol = compute_volatility([100.0, 105.0, 98.0, 110.0, 95.0])
    assert vol is not None
    assert vol > 0.0


def test_compute_technical_indicators_bundles_both():
    closes = [float(100 + i) for i in range(20)]
    result = compute_technical_indicators(closes)
    assert result.rsi_14 == 100.0  # strictly increasing
    assert result.volatility is not None
