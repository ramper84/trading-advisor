"""RSI and volatility, computed on read from daily_bars — NO LLM import,
deterministic, matching trending.py's own rule. SMA50/SMA200 and 52-week
hi/lo are NOT computed here — they're already persisted columns on
market_observations, free from yfinance's fast_info (ADR-007). Cheap
enough over a bounded window (a few dozen days) that persisting a separate
table would be premature (ARCHITECTURE.md §7).
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import pstdev
from typing import Optional


@dataclass
class TechnicalIndicators:
    rsi_14: Optional[float]
    volatility: Optional[float]  # population stdev of daily returns over the window, unannualized


def compute_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Standard RSI over the trailing `period` days: average gain divided
    by average loss. A plain moving average of gains/losses, not Wilder's
    smoothing — the well-known, easier-to-audit v1 approximation."""
    if len(closes) < period + 1:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_volatility(closes: list[float]) -> Optional[float]:
    """Population stdev of daily percentage returns over the given window."""
    if len(closes) < 2:
        return None
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]
    if len(returns) < 2:
        return None
    return pstdev(returns)


def compute_technical_indicators(closes: list[float]) -> TechnicalIndicators:
    """closes: daily_bars.close values, oldest first."""
    return TechnicalIndicators(
        rsi_14=compute_rsi(closes),
        volatility=compute_volatility(closes),
    )
