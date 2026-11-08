import datetime as dt
import hashlib
import json

import polars as pl
import pytest

from quant.reporting.doctor_worklist import collect, markdown
from quant.reporting.doctor_worklist_20261109 import REQUIRED, RUNS

CLOCK = dt.datetime(2026, 11, 8, 23, tzinfo=dt.timezone(dt.timedelta(hours=8)))


def tree(root):
    (root / "docs/worklists").mkdir(parents=True)
    (root / "docs/worklists/工作清单_20261109.md").write_text("current")
    # The closed pointer must not cause the old worklist to be selected.
    (root / "docs/工作清单_20261102.md").write_text("closed pointer")
    names = {
        "account_portfolio_v1": "account_portfolio_a1_q10_20261108_01",
        "account_portfolio_top15_v1": "account_portfolio_a1_top15_20261108_01",
        "top15_pessimistic_fill_v1": "top15_pessimistic_fill_20261108_01",
        "top15_turnover_budget_v1": "top15_turnover_budget_20261108_01",
    }
    assert set(names.values()) == RUNS
    rows = []
    for experiment, variants in REQUIRED.items():
        run = root / "artifacts/research" / names[experiment]
        run.mkdir(parents=True)
        config = run / "config.toml"
        config.write_text(f'id="{experiment}"\n')
        (run / "report.md").write_text("generated")
        (run / "assessment.json").write_text(
            json.dumps(
                dict(
                    auto_trade=False,
                    rows=[
                        dict(variant=v, cost_multiplier=c, cagr=0.1, max_drawdown=-0.1)
                        for v in variants
                        for c in (0.5, 1.0, 2.0)
                    ],
                    assessments={v: dict(conclusion="REJECTED") for v in variants},
                )
            )
        )
        for variant in variants:
            rows.append(
                dict(
                    experiment_id=experiment,
                    variant=variant,
                    level="strategy",
                    result_time="2026-11-08T16:00:00+08:00",
                    conclusion="REJECTED",
                    run_path=str(run),
                    report_path=str(run / "report.md"),
                    config_path=str(config),
                    config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
                    **{
                        f"{metric}_{cost}": value
                        for metric, value in [("cagr", 0.1), ("mdd", -0.1)]
                        for cost in ("0_5x", "1x", "2x")
                    },
                )
            )
    folder = root / "artifacts/registry"
    folder.mkdir()
    pl.from_dicts(rows).write_parquet(folder / "experiments.parquet")
    return rows


def test_current_worklist_uses_six_new_receipts_not_closed_pointer_or_old_replays(tmp_path):
    rows = tree(tmp_path)
    old = {
        **rows[0],
        "run_path": str(tmp_path / "artifacts/research/old_r1"),
        "result_time": "2026-11-04T12:00:00+08:00",
    }
    pl.from_dicts(rows + [old]).write_parquet(tmp_path / "artifacts/registry/experiments.parquet")
    result = collect(tmp_path, CLOCK)
    assert result["worklist_date"] == "2026-11-09"
    assert len(result["registry"]["verified_results"]) == 6
    assert result["registry"]["missing_required"] == [] and result["registry"]["issues"] == []
    assert (
        result["acceptance_verified"] is False and result["a2"]["formal_status"] == "not_observed"
    )
    assert "2026-11-09" in "\n".join(markdown(result))


@pytest.mark.parametrize("kind", ["config_mutation", "metric_mutation", "future_result"])
def test_invalid_new_results_cannot_count_toward_acceptance(tmp_path, kind):
    rows = tree(tmp_path)
    if kind == "config_mutation":
        from pathlib import Path

        Path(rows[0]["config_path"]).write_text('id="changed"\n')
    elif kind == "metric_mutation":
        rows[0]["cagr_2x"] = 0.9
    else:
        rows[0]["result_time"] = "2026-11-09T01:00:00+08:00"
    pl.from_dicts(rows).write_parquet(tmp_path / "artifacts/registry/experiments.parquet")
    result = collect(tmp_path, CLOCK)
    assert len(result["registry"]["verified_results"]) < 6
    assert result["registry"]["issues"] and result["acceptance_verified"] is False
