# Eval results

**No real run has been recorded yet.** This file is a placeholder, on purpose —
publishing fabricated performance would defeat the point of the harness.

To populate it with honest numbers:

```bash
python3 -m evals.run --limit 2       # a couple of real decisions, then
python3 -m evals.run                 # the full default case set
```

That regenerates this file with the metrics table (directional hit-rate,
signal-weighted return and alpha, buy-and-hold baseline, rating distribution,
latency/tokens) and writes full per-case detail to `results.json`.

Before quoting any result here, read the caveats in [README.md](README.md) —
especially the point-in-time / lookahead-bias warning. Commit this file only
once it reflects a real run you're willing to defend.
