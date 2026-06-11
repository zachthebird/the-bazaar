"""Pure, dependency-free scoring for the trading-agent eval harness.

Everything in this module is a deterministic function of its inputs — no
network, no LLM, no clock. That is deliberate: the metric math is the part
most worth unit-testing, so it lives apart from the parts that touch the
network (``oracle.py``) and the agents (``run.py``).

The agent emits one of five ratings (see
``tradingagents.agents.utils.rating.RATINGS_5_TIER``). We translate each
rating into a signed position *weight* in [-1, 1], then score those weights
against realized forward returns.

Position mapping (conviction-weighted, long/short):

    Buy +1.0 · Overweight +0.5 · Hold 0.0 · Underweight -0.5 · Sell -1.0

This mapping is a modeling choice, not something the framework dictates.
It is intentionally simple and symmetric so the metrics stay interpretable;
change ``POSITION_WEIGHTS`` if you want a long-only or differently-sized book.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence


# Signed conviction weight per 5-tier rating. Long/short, symmetric.
POSITION_WEIGHTS: Dict[str, float] = {
    "Buy": 1.0,
    "Overweight": 0.5,
    "Hold": 0.0,
    "Underweight": -0.5,
    "Sell": -1.0,
}


def position_weight(rating: str) -> float:
    """Map a 5-tier rating to a signed position weight in [-1, 1].

    Unknown ratings map to 0.0 (treated as no position) rather than raising,
    so a single malformed agent output can't abort a whole batch — but the
    runner records the raw rating too, so degenerate output stays visible.
    """
    return POSITION_WEIGHTS.get(rating, 0.0)


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


class Outcome:
    """One scored case: the agent's weight and the realized forward return.

    ``raw_return`` and ``alpha_return`` are decimals (0.012 == +1.2%).
    ``alpha_return`` is the return in excess of the benchmark over the same
    window; it may be None if no benchmark outcome was available.
    """

    __slots__ = ("ticker", "trade_date", "rating", "weight",
                 "raw_return", "alpha_return", "latency_s", "tokens")

    def __init__(
        self,
        ticker: str,
        trade_date: str,
        rating: str,
        raw_return: float,
        alpha_return: Optional[float] = None,
        latency_s: Optional[float] = None,
        tokens: Optional[int] = None,
    ):
        self.ticker = ticker
        self.trade_date = trade_date
        self.rating = rating
        self.weight = position_weight(rating)
        self.raw_return = raw_return
        self.alpha_return = alpha_return
        self.latency_s = latency_s
        self.tokens = tokens


def _mean(xs: Sequence[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def directional_hit_rate(outcomes: Sequence[Outcome]) -> Optional[float]:
    """Fraction of *directional* calls whose sign matched the realized move.

    Hold (weight 0) makes no directional bet, so it is excluded from the
    denominator. A flat realized return (exactly 0.0) counts as a miss,
    since a directional bet earned nothing. Returns None if the agent made
    no directional calls at all (e.g. it said Hold every time).
    """
    directional = [o for o in outcomes if o.weight != 0.0]
    if not directional:
        return None
    hits = sum(1 for o in directional if _sign(o.weight) == _sign(o.raw_return)
               and o.raw_return != 0.0)
    return hits / len(directional)


def signal_weighted_return(outcomes: Sequence[Outcome]) -> Optional[float]:
    """Mean per-decision return of a book sized by conviction weight.

    Each case contributes ``weight * raw_return``. This is an equal-weight
    average over non-overlapping, single-period decisions — NOT a compounded
    track record, and it ignores transaction costs and slippage. See the
    README caveats before quoting it.
    """
    return _mean([o.weight * o.raw_return for o in outcomes])


def signal_weighted_alpha(outcomes: Sequence[Outcome]) -> Optional[float]:
    """Like ``signal_weighted_return`` but on benchmark-excess (alpha) returns."""
    vals = [o.weight * o.alpha_return for o in outcomes if o.alpha_return is not None]
    return _mean(vals) if vals else None


def buy_and_hold_return(outcomes: Sequence[Outcome]) -> Optional[float]:
    """Baseline: mean forward return of always being fully long every case.

    This is the 'do the agents beat just buying everything' yardstick.
    """
    return _mean([o.raw_return for o in outcomes])


def rating_distribution(outcomes: Sequence[Outcome]) -> Dict[str, int]:
    """Count of each rating. Exposes degenerate behavior (e.g. always 'Buy')."""
    dist: Dict[str, int] = {r: 0 for r in POSITION_WEIGHTS}
    for o in outcomes:
        dist[o.rating] = dist.get(o.rating, 0) + 1
    return dist


def summarize(outcomes: Sequence[Outcome], n_attempted: int) -> Dict[str, object]:
    """Aggregate a list of scored outcomes into a metrics dict.

    ``n_attempted`` is the number of cases the runner tried, so coverage
    (how many produced a usable price outcome) is visible rather than hidden.
    """
    n_scored = len(outcomes)
    hit = directional_hit_rate(outcomes)
    swr = signal_weighted_return(outcomes)
    bnh = buy_and_hold_return(outcomes)
    n_directional = sum(1 for o in outcomes if o.weight != 0.0)
    return {
        "n_attempted": n_attempted,
        "n_scored": n_scored,
        "coverage": (n_scored / n_attempted) if n_attempted else None,
        "n_directional": n_directional,
        "directional_hit_rate": hit,
        "signal_weighted_return": swr,
        "signal_weighted_alpha": signal_weighted_alpha(outcomes),
        "buy_and_hold_return": bnh,
        "excess_over_buy_and_hold": (swr - bnh) if (swr is not None and bnh is not None) else None,
        "rating_distribution": rating_distribution(outcomes),
        "mean_latency_s": _mean([o.latency_s for o in outcomes if o.latency_s is not None]),
        "total_tokens": (sum(o.tokens for o in outcomes if o.tokens is not None)
                         or None),
    }
