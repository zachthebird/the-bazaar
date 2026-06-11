# Eval / backtest harness

A reproducible way to ask the only question that matters about a trading agent:
**are its calls any better than a coin flip or just buying everything?**

The harness runs the TradingAgents pipeline over a fixed set of past decisions,
maps each decision to a position, and scores it against what the price actually
did next. It is deliberately small and honest: real method, real metrics, and —
until you run it on a real set — **no numbers**.

## What it measures

For each `(ticker, trade_date)` case:

1. The agents produce a 5-tier rating — Buy / Overweight / Hold / Underweight / Sell.
2. That rating becomes a signed position weight: `+1 / +0.5 / 0 / -0.5 / -1`.
3. The oracle fetches the close-to-close forward return over a fixed holding
   window (default 5 trading days), plus the same window's return for a
   benchmark (default SPY), giving raw and benchmark-excess (**alpha**) return.

Aggregated across cases:

| Metric | What it tells you |
| --- | --- |
| **Directional hit-rate** | Of the non-Hold calls, how often the sign was right. 50% is the coin-flip line. Holds are excluded; a flat move counts as a miss. |
| **Signal-weighted return** | Mean per-decision return of a book sized by conviction (`weight × forward return`). Equal-weight, single-period — not a compounded track record. |
| **Signal-weighted alpha** | Same, on benchmark-excess returns. |
| **Buy-and-hold baseline** | Mean forward return of always being fully long. The bar to clear. |
| **Excess over buy-and-hold** | Signal-weighted return minus that baseline. Negative means the agents added nothing. |
| **Rating distribution** | Counts per tier. Exposes the classic degenerate case — an agent that just says "Buy" every time. |
| **Latency / tokens** | Wall-clock per decision; total tokens when the provider reports usage. |

Exact definitions live in [`metrics.py`](metrics.py); the math is unit-tested in
[`test_metrics.py`](test_metrics.py) against synthetic fixtures.

## Run it

Use whatever launches Python 3 on your machine (`python3` on a stock macOS).
`--mock` and the metric tests are 3.9-safe; a real run needs the framework (3.10+).

```bash
# Free smoke test — stubbed ratings, no LLM, no API key, no cost.
# Proves the plumbing + metrics end to end (fetches real prices if online).
python3 -m evals.run --mock

# A real run: needs the framework installed and an LLM key (see ../.env.example).
# Each case is a full multi-agent run — costs tokens and minutes. Start small.
python3 -m evals.run --limit 2
python3 -m evals.run --holding-days 5     # full default set

# Just the metric tests (no dependencies):
python3 evals/test_metrics.py
```

Output goes to `evals/results.json` (full per-case detail, gitignored) and
`evals/RESULTS.md` (the table above). Re-running regenerates both; commit
`RESULTS.md` when you have a real run worth publishing.

Define your own cases in [`cases.py`](cases.py).

## Caveats — read before quoting any number

- **A handful of cases is an anecdote, not a backtest.** Score dozens of
  decisions across tickers and across up *and* down months before drawing
  conclusions; otherwise you're measuring one regime.
- **Point-in-time validity is not enforced here.** The score is only honest if
  the agents saw *only* data available on `trade_date`. This harness measures
  the forward return; it does **not** verify the upstream data tools are
  strictly as-of-date. If they fetch latest-available data, results suffer
  lookahead bias and are invalid. This is the single biggest threat to validity.
- **No transaction costs, slippage, or position limits** are modeled. Returns
  are gross.
- **Survivorship / selection bias**: hand-picked tickers and dates can flatter
  or punish the agents. A real evaluation uses a pre-registered, unbiased set.
- **Research only — not financial, investment, or trading advice.** Nothing here
  is a recommendation, and the position mapping is an illustrative modeling
  choice, not a strategy anyone should trade.

The point of shipping this *before* it has results is to be measurable. The
worst thing a portfolio project can do is claim performance it can't reproduce;
the second worst is to have no way to check at all. This is the way to check.
