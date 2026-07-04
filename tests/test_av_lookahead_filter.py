"""The AV fundamentals look-ahead filter must actually run.

_make_api_request returns the payload as a JSON *string*, so a filter guarded
on isinstance(result, dict) silently no-ops and future fiscal periods leak
into historical runs (they survive curr_date filtering).
"""
import json

import pytest

import tradingagents.dataflows.alpha_vantage_common as av
import tradingagents.dataflows.alpha_vantage_fundamentals as avf


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.mark.unit
def test_fundamentals_filter_drops_future_fiscal_periods(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "placeholder")
    body = json.dumps({
        "symbol": "AAPL",
        "annualReports": [
            {"fiscalDateEnding": "2025-12-31"},  # after curr_date -> must drop
            {"fiscalDateEnding": "2023-12-31"},  # before          -> must keep
        ],
    })
    monkeypatch.setattr(av.requests, "get", lambda *a, **k: _FakeResponse(body))
    out = avf.get_balance_sheet("AAPL", curr_date="2024-01-01")
    dates = [r["fiscalDateEnding"] for r in json.loads(out)["annualReports"]]
    assert dates == ["2023-12-31"]
