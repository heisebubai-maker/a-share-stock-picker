"""Versioned, explainable heuristic; only uses bars through requested date."""
from math import isfinite
from statistics import mean, pstdev

VERSION = "trend-v1"


def evaluate(bars):
    if len(bars) < 21:
        return None
    latest = bars[-1]
    if latest["is_st"] or latest["suspended"]:
        return None
    prices = [b["close"] for b in bars[-21:]]
    if any(not isfinite(p) or p <= 0 for p in prices):
        return None
    amount = mean(b["amount"] for b in bars[-20:])
    if not isfinite(amount) or amount < 1e8:
        return None
    momentum = (prices[-1] / prices[0] - 1) * 100
    trend = (prices[-1] / mean(prices[-20:]) - 1) * 100
    volatility = pstdev([(b / a - 1) * 100 for a, b in zip(prices, prices[1:])])
    clamp = lambda value: max(0, min(1, value))
    factors = dict(momentum=round(40 * clamp((momentum + 10) / 20), 2),
                   trend=round(30 * clamp((trend + 5) / 10), 2),
                   stability=round(20 * clamp(1 - volatility / 5), 2),
                   liquidity=round(10 * clamp(amount / 5e8), 2))
    return dict(code=latest["code"], name=latest["name"], close=prices[-1],
                score=round(sum(factors.values()), 2), factors=factors,
                momentum_pct=round(momentum, 2), volatility_pct=round(volatility, 2))
