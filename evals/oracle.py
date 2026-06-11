"""Realized forward-return oracle for the eval harness.

Given a (ticker, trade_date), this fetches the close-to-close return over a
fixed holding window *after* the decision date, plus the same window's return
for a benchmark, so we can report both raw and benchmark-excess (alpha) return.

This is intentionally a small, self-contained reimplementation rather than a
call into ``TradingAgentsGraph._fetch_returns`` (a private method): the oracle
is the ground truth the whole eval rests on, so it should be readable and
testable on its own. The logic mirrors the framework's approach (yfinance,
close-to-close, weekend/holiday buffer) so the two stay consistent.

NOTE ON VALIDITY: this measures what the price did *after* trade_date. It does
NOT verify that the agent only saw data up to trade_date — that point-in-time
guarantee has to come from the framework's data tools. See evals/README.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple, Optional


class Return(NamedTuple):
    raw: Optional[float]            # decimal, e.g. 0.012 == +1.2%
    alpha: Optional[float]          # raw minus benchmark return over same window
    actual_holding_days: Optional[int]


def realized_return(
    ticker: str,
    trade_date: str,
    holding_days: int = 5,
    benchmark: str = "SPY",
) -> Return:
    """Close-to-close forward return for ``ticker`` over ``holding_days``.

    Returns ``Return(None, None, None)`` when price data is unavailable
    (date too recent, ticker delisted, or a network error) so the caller can
    skip the case and report it as uncovered rather than crashing the batch.

    Buys close on ``trade_date`` (or the next trading day) and sells at the
    close ``holding_days`` trading days later. ``alpha`` subtracts the
    benchmark's return over the identical bar range.
    """
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "evals.oracle needs yfinance: pip install yfinance"
        ) from e

    try:
        start = datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError("trade_date must be YYYY-MM-DD, got %r" % trade_date) from e

    # Pad the window so holding_days *trading* days are available despite
    # weekends/holidays, mirroring the framework's buffer.
    end_str = (start + timedelta(days=holding_days + 7)).strftime("%Y-%m-%d")

    try:
        stock = yf.Ticker(ticker).history(start=trade_date, end=end_str)
        bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)
    except Exception:
        return Return(None, None, None)

    if len(stock) < 2:
        return Return(None, None, None)

    days = min(holding_days, len(stock) - 1)
    raw = float(
        (stock["Close"].iloc[days] - stock["Close"].iloc[0]) / stock["Close"].iloc[0]
    )

    # Alpha only if the benchmark covers the SAME horizon. If the benchmark
    # returned fewer bars, computing excess over a shorter window would be
    # apples-to-oranges, so we report no alpha rather than a misleading one.
    alpha: Optional[float] = None
    if len(bench) - 1 >= days:
        bench_ret = float(
            (bench["Close"].iloc[days] - bench["Close"].iloc[0])
            / bench["Close"].iloc[0]
        )
        alpha = raw - bench_ret

    return Return(raw, alpha, days)
