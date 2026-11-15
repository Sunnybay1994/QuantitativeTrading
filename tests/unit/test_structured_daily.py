import json

import pytest

from quant.data import structured_daily as daily


@pytest.mark.parametrize("status", ["checked", "partial", "deferred"])
def test_daily_data_receipt_does_not_promote_limited_sources_or_collect_after_yield(
    tmp_path, monkeypatch, status
):
    output = tmp_path / "capture"

    def incremental(**kwargs):
        output.mkdir()
        record = dict(status=status, as_of="2026-11-06", auto_trade=False)
        (output / "summary.json").write_text(json.dumps(record))
        return record

    calls = []

    def futures(**kwargs):
        calls.append(kwargs)
        return dict(status="captured", rows=12, auto_trade=False)

    monkeypatch.setattr(daily, "incremental", incremental)
    monkeypatch.setattr(daily, "futures", futures)
    result = daily.run(config=tmp_path / "config", data_root=tmp_path / "data", output=output)
    assert result["status"] == status
    assert len(calls) == (0 if status == "deferred" else 1)
    assert result["auto_trade"] is False and (output / "pipeline.json").is_file()
    assert len(result["structured_receipt_sha256"]) == 64


def test_quote_failure_is_partial_and_preserves_structured_receipt(tmp_path, monkeypatch):
    def incremental(**kwargs):
        (tmp_path / "summary.json").write_text('{"status":"checked"}')
        return dict(status="checked", as_of="2026-11-06")

    def failed(**kwargs):
        raise ValueError("missing IF quotes")

    monkeypatch.setattr(daily, "incremental", incremental)
    monkeypatch.setattr(daily, "futures", failed)
    result = daily.run(config=tmp_path / "config", data_root=tmp_path / "data", output=tmp_path)
    assert result["status"] == "partial" and result["futures"]["status"] == "failed"
    assert json.loads((tmp_path / "summary.json").read_text())["status"] == "checked"


@pytest.mark.parametrize('timing', [
    {'time_budget_exhausted': True},
    {'time_budget_exhausted': False, 'elapsed_seconds': 900, 'max_run_seconds': 900},
])
def test_runtime_budget_does_not_start_followup_futures_query(tmp_path, monkeypatch, timing):
    record = dict(status='partial', as_of='2026-11-06', **timing)

    def incremental(**kwargs):
        (tmp_path/'summary.json').write_text(json.dumps(record))
        return record

    monkeypatch.setattr(daily, 'incremental', incremental)
    monkeypatch.setattr(daily, 'futures', lambda **kw: pytest.fail('budget already exhausted'))
    result = daily.run(config=tmp_path/'config', data_root=tmp_path/'data', output=tmp_path)
    assert result['status'] == 'partial'
    assert result['futures']['status'] == 'deferred'
    assert json.loads((tmp_path/'summary.json').read_text()) == record


def test_monthly_brief_uses_observed_futures_panel_and_keeps_basis_unknown(tmp_path, monkeypatch):
    from quant.reporting import research_brief as brief

    panel = dict(
        status="observed_quotes",
        basis_status="unknown_no_matching_spot_series",
        rows=[
            dict(
                ts_code="IF2611.CFX",
                trade_date="20261106",
                close=4000.0,
                settle=4001.0,
                vol=1.0,
                oi=2.0,
                native_units="native",
            )
        ],
    )
    monkeypatch.setattr(brief, "futures_facts", lambda month, root: panel)
    facts = brief.collect_facts("2026-11", root=tmp_path)
    assert facts["index_futures"] == panel
    report = brief.render_template(facts)
    assert "IF2611.CFX" in report and "unknown_no_matching_spot_series" in report


def test_cli_exposes_daily_pipeline_without_bypassing_futures_option(monkeypatch):
    from quant import cli

    calls = []
    monkeypatch.setattr(cli, "_delegate", lambda module, args: calls.append((module, args)) or 0)
    assert (
        cli.main(["data", "structured-incremental", "--with-futures", "--output", "isolated"]) == 0
    )
    assert calls == [
        ("quant.data.structured_incremental", ["--with-futures", "--output", "isolated"])
    ]
