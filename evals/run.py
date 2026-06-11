"""Run the trading agents over a fixed set of past decisions and score them.

Two modes:

  --mock   Stub the agent with a deterministic, ticker-seeded rating. No LLM,
           no API key, no cost. Use it to validate the plumbing and the
           metrics end-to-end for free before spending on a real run.

  (real)   Instantiate TradingAgentsGraph and call .propagate() for each case.
           Needs the framework installed and an LLM provider key configured
           (see the repo .env.example). Each case is a full multi-agent run,
           so this costs real tokens and minutes — start with --limit.

The score is written to evals/results.json (full detail) and evals/RESULTS.md
(human-readable table). Nothing here fabricates numbers: with no real run on
record, RESULTS.md stays in its "not yet run" state.

    python3 -m evals.run --mock                # free smoke test
    python3 -m evals.run --limit 2             # 2 real decisions
    python3 -m evals.run --holding-days 5      # full default set, real

(Use whatever launches Python 3 on your machine — `python3` on a stock macOS.
 --mock and the metric tests are 3.9-safe; a real run needs the framework, 3.10+.)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import List, Optional

# Make `tradingagents` importable when run from the repo root, mirroring
# web-ui/backend/main.py. Harmless if the package is already installed.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evals.cases import DEFAULT_CASES, EvalCase
from evals.metrics import Outcome, summarize
from evals import oracle

# The 5-tier vocabulary, imported from the framework when available so the
# eval can never drift from the real rating set. Falls back to a literal copy
# in mock mode on machines without the framework installed.
try:
    from tradingagents.agents.utils.rating import RATINGS_5_TIER
except Exception:  # pragma: no cover - framework not installed (mock-only use)
    RATINGS_5_TIER = ("Buy", "Overweight", "Hold", "Underweight", "Sell")


def _mock_rating(ticker: str, trade_date: str) -> str:
    """Deterministic, ticker+date-seeded rating spanning all five tiers.

    Pseudo-random but reproducible, so a mock run produces a non-degenerate
    distribution that exercises the metrics — it is NOT a prediction.
    """
    h = hashlib.sha256((ticker + trade_date).encode()).hexdigest()
    return RATINGS_5_TIER[int(h, 16) % len(RATINGS_5_TIER)]


class _TokenCounter:
    """Best-effort LangChain callback that accumulates LLM token usage.

    Providers that report usage (e.g. OpenAI) populate it; others leave it at
    zero, in which case the runner reports tokens as unavailable rather than
    guessing. Defensive by design: never raises into the agent run.
    """

    def __init__(self) -> None:
        self.tokens = 0

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: D401
        try:
            out = getattr(response, "llm_output", None) or {}
            # Chat Completions shape: llm_output["token_usage"]["total_tokens"].
            # Responses API shape: llm_output["usage"] with input/output tokens.
            usage = out.get("token_usage") or out.get("usage") or {}
            total = usage.get("total_tokens")
            if total is None:
                total = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
            self.tokens += int(total or 0)
        except Exception:
            pass

    # The framework passes callbacks straight to the LLM client. Only the
    # `on_*` event hooks need to exist as callables; everything else (e.g.
    # raise_error, ignore_llm, run_inline) must fall through to AttributeError
    # so LangChain's getattr-with-default picks the correct boolean defaults.
    def __getattr__(self, name):
        if name.startswith("on_"):
            def _noop(*_a, **_k):
                return None
            return _noop
        raise AttributeError(name)


def _run_one_real(case: EvalCase, args, graph_cache: dict):
    """Run a single real decision, returning (rating, latency_s, tokens)."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    counter = _TokenCounter()
    # One graph per process is fine; rebuild only if analysts changed.
    key = tuple(args.analysts)
    if key not in graph_cache:
        cfg = dict(DEFAULT_CONFIG)
        graph_cache[key] = TradingAgentsGraph(
            selected_analysts=list(args.analysts),
            config=cfg,
            callbacks=[counter],
        )
    graph = graph_cache[key]

    t0 = time.monotonic()
    _state, signal = graph.propagate(case.ticker, case.trade_date)
    latency = time.monotonic() - t0
    return signal, latency, (counter.tokens or None)


def run(args) -> dict:
    cases: List[EvalCase] = list(DEFAULT_CASES)
    if args.limit:
        cases = cases[: args.limit]

    outcomes: List[Outcome] = []
    graph_cache: dict = {}
    print("Scoring %d case(s) — mode: %s, holding_days=%d"
          % (len(cases), "MOCK" if args.mock else "REAL", args.holding_days))

    for i, case in enumerate(cases, 1):
        try:
            if args.mock:
                rating = _mock_rating(case.ticker, case.trade_date)
                latency: Optional[float] = None
                tokens: Optional[int] = None
            else:
                rating, latency, tokens = _run_one_real(case, args, graph_cache)
        except Exception as e:
            print("  [%d/%d] %s %s — agent run FAILED: %s"
                  % (i, len(cases), case.ticker, case.trade_date, e))
            continue

        ret = oracle.realized_return(
            case.ticker, case.trade_date,
            holding_days=args.holding_days, benchmark=args.benchmark,
        )
        if ret.raw is None:
            print("  [%d/%d] %s %s — rating=%s, no forward prices (uncovered)"
                  % (i, len(cases), case.ticker, case.trade_date, rating))
            continue

        # A clamped (short) window means the date is too recent to score over
        # the full horizon. Treat it as uncovered rather than averaging a
        # 2-day hold in alongside genuine full-window holds.
        if ret.actual_holding_days is not None and ret.actual_holding_days < args.holding_days:
            print("  [%d/%d] %s %s — rating=%s, only %d/%d trading days available (uncovered)"
                  % (i, len(cases), case.ticker, case.trade_date, rating,
                     ret.actual_holding_days, args.holding_days))
            continue

        outcomes.append(Outcome(
            ticker=case.ticker, trade_date=case.trade_date, rating=rating,
            raw_return=ret.raw, alpha_return=ret.alpha,
            latency_s=latency, tokens=tokens,
        ))
        print("  [%d/%d] %s %s — rating=%s, fwd=%+.2f%%%s"
              % (i, len(cases), case.ticker, case.trade_date, rating,
                 ret.raw * 100,
                 "" if ret.alpha is None else " (alpha %+.2f%%)" % (ret.alpha * 100)))

    metrics = summarize(outcomes, n_attempted=len(cases))
    report = {
        "meta": {
            "mode": "mock" if args.mock else "real",
            "holding_days": args.holding_days,
            "benchmark": args.benchmark,
            "analysts": list(args.analysts),
            "llm_provider": os.environ.get("TRADINGAGENTS_LLM_PROVIDER", "(config default)"),
            "deep_think_llm": os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", "(config default)"),
        },
        "metrics": metrics,
        "cases": [
            {
                "ticker": o.ticker, "trade_date": o.trade_date, "rating": o.rating,
                "weight": o.weight, "raw_return": o.raw_return,
                "alpha_return": o.alpha_return, "latency_s": o.latency_s,
                "tokens": o.tokens,
            }
            for o in outcomes
        ],
    }
    return report


def _pct(x) -> str:
    return "n/a" if x is None else "%+.2f%%" % (x * 100)


def _num(x, fmt="%.3f") -> str:
    return "n/a" if x is None else fmt % x


def write_reports(report: dict, out_dir: str) -> None:
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(report, f, indent=2)

    m, meta = report["metrics"], report["meta"]
    dist = m["rating_distribution"]
    lines = [
        "# Eval results",
        "",
        "> %s run · %d cases attempted · holding window %d trading days · benchmark %s"
        % (meta["mode"].upper(), m["n_attempted"], meta["holding_days"], meta["benchmark"]),
        "> provider: %s · deep model: %s" % (meta["llm_provider"], meta["deep_think_llm"]),
        "",
        ("**This is a %s run.** " % meta["mode"].upper())
        + ("Ratings are stubbed, not real agent decisions — the numbers below only "
           "prove the harness computes correctly. Run without --mock for real results."
           if meta["mode"] == "mock" else
           "Read the caveats in evals/README.md before quoting any number — small "
           "samples are anecdotes, and validity depends on point-in-time data."),
        "",
        "| Metric | Value |",
        "| --- | --- |",
        "| Cases scored (coverage) | %d / %d (%s) |" % (
            m["n_scored"], m["n_attempted"], _pct(m["coverage"])),
        "| Directional calls | %d |" % m["n_directional"],
        "| Directional hit-rate | %s |" % (
            "n/a" if m["directional_hit_rate"] is None else "%.0f%%" % (m["directional_hit_rate"] * 100)),
        "| Signal-weighted return (per decision) | %s |" % _pct(m["signal_weighted_return"]),
        "| Signal-weighted alpha (vs %s) | %s |" % (meta["benchmark"], _pct(m["signal_weighted_alpha"])),
        "| Buy-and-hold baseline (per decision) | %s |" % _pct(m["buy_and_hold_return"]),
        "| Excess over buy-and-hold | %s |" % _pct(m["excess_over_buy_and_hold"]),
        "| Mean latency / decision | %s |" % (
            "n/a" if m["mean_latency_s"] is None else "%.1fs" % m["mean_latency_s"]),
        "| Total tokens | %s |" % ("n/a" if m["total_tokens"] is None else str(m["total_tokens"])),
        "",
        "Rating distribution: " + ", ".join("%s %d" % (r, dist[r]) for r in dist),
        "",
        "_Generated by `python -m evals.run`. Definitions and caveats: evals/README.md._",
    ]
    with open(os.path.join(out_dir, "RESULTS.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Backtest/eval harness for the trading agents.")
    p.add_argument("--mock", action="store_true",
                   help="Stub the agent (no LLM/key/cost). For plumbing + metrics checks.")
    p.add_argument("--limit", type=int, default=0, help="Only run the first N cases.")
    p.add_argument("--holding-days", type=int, default=5,
                   help="Forward holding window in trading days (default 5).")
    p.add_argument("--benchmark", default="SPY", help="Alpha benchmark ticker (default SPY).")
    p.add_argument("--analysts", nargs="+",
                   default=["market", "social", "news", "fundamentals"],
                   help="Which analyst agents to include in a real run.")
    p.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)),
                   help="Directory to write results.json / RESULTS.md.")
    args = p.parse_args(argv)

    report = run(args)
    write_reports(report, args.out)
    m = report["metrics"]
    print("\nDone. Scored %d/%d cases. Wrote results.json + RESULTS.md to %s"
          % (m["n_scored"], m["n_attempted"], args.out))
    if m["n_scored"] == 0:
        print("No cases were scored — check network/yfinance access and that the "
              "case dates are old enough to have forward prices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
