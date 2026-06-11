"""Unit tests for the metric math, on SYNTHETIC fixtures.

Important: the numbers here are hand-made inputs chosen to verify the
arithmetic — they are NOT evaluation results and make no claim about the
agents. Run with:  python3 evals/test_metrics.py  (no dependencies; pytest
also discovers them if you have it installed).
"""

from __future__ import annotations

import os
import sys

# Allow running as a plain script (python evals/test_metrics.py) by putting
# the repo root on the path, not just the evals/ dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.metrics import (
    Outcome, position_weight, directional_hit_rate, signal_weighted_return,
    buy_and_hold_return, rating_distribution, summarize,
)


def _o(rating, raw, alpha=None):
    return Outcome("T", "2025-01-02", rating, raw_return=raw, alpha_return=alpha)


def test_position_weights():
    assert position_weight("Buy") == 1.0
    assert position_weight("Overweight") == 0.5
    assert position_weight("Hold") == 0.0
    assert position_weight("Underweight") == -0.5
    assert position_weight("Sell") == -1.0
    assert position_weight("garbage") == 0.0  # unknown -> no position


def test_hit_rate_excludes_holds_and_flat():
    outs = [
        _o("Buy", 0.05),     # long, up   -> hit
        _o("Sell", -0.03),   # short, down-> hit
        _o("Buy", -0.02),    # long, down -> miss
        _o("Hold", 0.10),    # excluded (no directional bet)
        _o("Sell", 0.0),     # flat -> miss (earned nothing)
    ]
    # 4 directional calls (Hold excluded), 2 hits
    assert directional_hit_rate(outs) == 0.5


def test_hit_rate_none_when_all_hold():
    assert directional_hit_rate([_o("Hold", 0.01), _o("Hold", -0.01)]) is None


def test_signal_weighted_and_baseline():
    outs = [_o("Buy", 0.10), _o("Sell", 0.10), _o("Hold", 0.10)]
    # weights 1, -1, 0 -> (0.10 + -0.10 + 0.0)/3 == 0.0
    assert abs(signal_weighted_return(outs) - 0.0) < 1e-12
    # buy-and-hold is mean raw return regardless of rating == 0.10
    assert abs(buy_and_hold_return(outs) - 0.10) < 1e-12


def test_distribution_counts():
    outs = [_o("Buy", 0.01), _o("Buy", 0.02), _o("Sell", -0.01)]
    dist = rating_distribution(outs)
    assert dist["Buy"] == 2 and dist["Sell"] == 1 and dist["Hold"] == 0


def test_summarize_coverage_and_excess():
    outs = [_o("Buy", 0.04), _o("Underweight", -0.02)]
    s = summarize(outs, n_attempted=4)
    assert s["n_scored"] == 2 and s["n_attempted"] == 4
    assert abs(s["coverage"] - 0.5) < 1e-12
    # swr = (1*0.04 + -0.5*-0.02)/2 = (0.04 + 0.01)/2 = 0.025
    assert abs(s["signal_weighted_return"] - 0.025) < 1e-12
    # bnh = (0.04 + -0.02)/2 = 0.01 ; excess = 0.025 - 0.01 = 0.015
    assert abs(s["excess_over_buy_and_hold"] - 0.015) < 1e-12


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok:", fn.__name__)
    print("\nAll %d metric tests passed (synthetic fixtures)." % len(fns))


if __name__ == "__main__":
    _run()
