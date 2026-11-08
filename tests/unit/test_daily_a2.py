"""A2 reaches the existing CLI/daily flow without changing primary accounts."""

import datetime as dt

import pytest

from quant.execution import account_30w_top15_paper as paper
from quant.research import run_daily_observation as daily
from tests.unit import test_daily_pair_month

case = test_daily_pair_month.case


@pytest.mark.parametrize("status", ["complete", "failed"])
def test_daily_passes_same_day_forecast_and_preserves_independent_account_status(
    case, monkeypatch, status
):
    args, roots = case
    config = args["config"]
    config.write_text(
        config.read_text(encoding="utf-8")
        + '\n[account_30w_top15]\nconfig="registered-a2"\noutput="isolated-a2"\n',
        encoding="utf-8",
    )
    calls = []

    def observe(spec, **kwargs):
        calls.append((spec, kwargs))
        return dict(status=status, as_of="2026-11-30", auto_trade=False)

    monkeypatch.setattr(paper, "observe_from_daily", observe)
    result = daily.run(**args)
    assert result["status"] == "complete"
    assert result["observation_accounts"]["account_30w_top15"]["status"] == status
    assert calls == [
        (
            {"config": "registered-a2", "output": "isolated-a2"},
            dict(
                end=dt.date(2026, 11, 30),
                data_root=roots["data"],
                forecast=args["output"] / "model/forecast",
            ),
        )
    ]


def test_cli_delegates_registered_a2_command(monkeypatch):
    import sys
    from quant import cli

    calls = []
    monkeypatch.setattr(sys, "argv", ["quant", "paper", "account-30w-top15", "--to", "2026-11-06"])
    monkeypatch.setattr(cli, "_delegate", lambda module, args: calls.append((module, args)) or 0)
    assert cli.main() == 0
    assert calls == [("quant.execution.account_30w_top15_paper", ["--to", "2026-11-06"])]
