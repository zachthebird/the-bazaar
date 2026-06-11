"""The evaluation set: which (ticker, date) decisions to score.

These are EXAMPLE cases, not a curated benchmark. A handful of decisions is
an anecdote, not a backtest (see README). Replace or extend ``DEFAULT_CASES``
with a set that matters to you — ideally dozens of decisions spread across
tickers, sectors, and market regimes (up months and down months), so the
hit-rate isn't just measuring one lucky quarter.

Each date must be a past trading day far enough back that a full holding
window has already elapsed, or the oracle will have no forward prices to
score and the case will be reported as uncovered.
"""

from __future__ import annotations

from typing import List, NamedTuple


class EvalCase(NamedTuple):
    ticker: str
    trade_date: str   # YYYY-MM-DD, a past trading day
    note: str = ""


# A small, deliberately varied starter set. NOT a benchmark — a smoke set.
DEFAULT_CASES: List[EvalCase] = [
    EvalCase("AAPL", "2025-02-03", "large-cap tech"),
    EvalCase("NVDA", "2025-02-03", "semis / AI"),
    EvalCase("JPM", "2025-02-03", "financials"),
    EvalCase("XOM", "2025-02-03", "energy"),
    EvalCase("TSLA", "2025-03-03", "high-vol single name"),
    EvalCase("KO", "2025-03-03", "defensive staple"),
    EvalCase("AMZN", "2025-04-01", "mega-cap retail/cloud"),
    EvalCase("UNH", "2025-04-01", "healthcare"),
]
