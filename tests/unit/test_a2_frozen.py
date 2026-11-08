import datetime as dt
import hashlib
import json
import time

import pytest

from quant.execution import account_30w_top15_frozen as frozen
from quant.execution import account_30w_top15_paper as paper
from tests.unit import test_account_30w_top15_paper

account = test_account_30w_top15_paper.account
DAY = dt.date(2026, 1, 30)


def setup_frozen(account, tmp_path, monkeypatch):
    config, output, stocks, etfs, _ = account
    forecast = tmp_path / "model/forecast"
    forecast.mkdir(parents=True)
    (forecast / "summary.json").write_text(
        json.dumps(dict(as_of=str(DAY), recorded_at=dt.datetime.now(dt.timezone.utc).isoformat()))
    )
    (forecast / "predictions.parquet").write_bytes(b"fixture copied forecast")
    (forecast.parent / "summary.json").write_text("{}")
    monkeypatch.setattr(frozen, "read_stock_paper_calendar", lambda *_: stocks.calendar)
    monkeypatch.setattr(
        frozen,
        "sources",
        lambda *args: {str(config): hashlib.sha256(config.read_bytes()).hexdigest()},
    )
    monkeypatch.setattr(frozen, "cached_etfs", lambda *_: (etfs, []))
    monkeypatch.setattr(frozen, "offline_stocks", lambda *_: stocks)
    monkeypatch.setattr(
        paper, "etf_inputs", lambda *args, **kwargs: pytest.fail("Provider collection forbidden")
    )
    return dict(
        spec=dict(config=str(config), output=str(output)),
        end=DAY,
        data_root=tmp_path / "data",
        output=tmp_path / "frozen",
        deadline=time.monotonic() + 60,
        forecast=forecast,
    ), output


def test_frozen_readers_generate_original_seventeen_orders_without_collection(
    account, tmp_path, monkeypatch
):
    args, output = setup_frozen(account, tmp_path, monkeypatch)
    result = frozen.run(**args)
    assert result["stock_orders"] == 15 and result["etf_orders"] == 2 and result["rehearsal"]
    assert (args["output"] / "calendar.parquet").is_file()
    assert (output / str(DAY) / "state.json").is_file()


def test_account_changed_during_freeze_never_publishes(account, tmp_path, monkeypatch):
    args, output = setup_frozen(account, tmp_path, monkeypatch)
    stocks = account[2]

    def concurrent(*_):
        state = output / "2026-01-29/state.json"
        state.parent.mkdir(parents=True)
        state.write_text('{"date":"2026-01-29"}')
        return stocks

    monkeypatch.setattr(frozen, "offline_stocks", concurrent)
    with pytest.raises(ValueError, match="advanced during freeze"):
        frozen.run(**args)
    assert not (output / str(DAY) / "state.json").exists()


def test_risk_controls_changed_after_freeze_never_publish(account, tmp_path, monkeypatch):
    args, output = setup_frozen(account, tmp_path, monkeypatch)
    stocks = account[2]

    def change(*_):
        output.mkdir(parents=True)
        (output / "controls.json").write_text('{"halt":true,"sell_only":false}')
        return stocks

    monkeypatch.setattr(frozen, "offline_stocks", change)
    with pytest.raises(ValueError, match="controls changed"):
        frozen.run(**args)
    assert not (output / str(DAY) / "state.json").exists()


@pytest.mark.parametrize("reason", ["writer", "expired"])
def test_unsafe_or_expired_preparation_stops_before_collection(
    account, tmp_path, monkeypatch, reason
):
    args, output = setup_frozen(account, tmp_path, monkeypatch)
    monkeypatch.setattr(
        frozen, "read_stock_paper_calendar", lambda *_: pytest.fail("Must stop before reads")
    )
    if reason == "writer":
        args["account_writer"] = True
    else:
        args["deadline"] = time.monotonic() - 1
    with pytest.raises((ValueError, TimeoutError)):
        frozen.run(**args)
    assert not output.exists()


def test_missing_etf_capture_fails_without_provider_client(tmp_path):
    with pytest.raises(ValueError, match="collection prohibited"):
        frozen.cached_etfs(
            dict(data=dict(etf_daily_root=str(tmp_path))), DAY, dt.datetime.now(dt.timezone.utc)
        )


def test_combined_fallback_keeps_a2_not_started_separate_from_primary(tmp_path,monkeypatch):
    from quant.execution import paper_order_fallback as fallback
    from tests.unit.test_paper_order_fallback import setup_account
    _,state,_,_,config=setup_account(tmp_path)
    with config.open('a') as stream:
        stream.write('[account_30w_top15]\nconfig='+json.dumps(paper.CONFIG.resolve().as_posix())+
            '\noutput='+json.dumps((tmp_path/'a2').as_posix())+'\n')
    monkeypatch.setattr(fallback,'freeze_account',lambda **kwargs:dict(_account_snapshot=
        dict(path=str(state),sha256=hashlib.sha256(state.read_bytes()).hexdigest())))
    monkeypatch.setattr(fallback.q10_paper,'run',lambda **kwargs:dict(as_of='2026-11-06',reference_orders=0))
    result=fallback.run(config=config,end=dt.date(2026,11,6),output=tmp_path/'receipt')
    assert result['status']=='complete'
    assert result['observation_accounts']['account_30w_top15']['status']=='not_started'
    assert not (tmp_path/'a2').exists()
