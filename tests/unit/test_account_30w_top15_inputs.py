"""A2 input provenance, exact-session quotes and full-history dividend protection."""

import datetime as dt
import hashlib
import json

import polars as pl
import pytest

from quant.data import account_30w_top15_inputs as data
from quant.data.etf_corporate_actions import SCHEMA

DAY = dt.date(2026, 1, 30)


class Connector:
    def __init__(self, missing=False):
        self.calls = []
        self.missing = missing

    def query_raw(self, api, **params):
        self.calls.append((api, params))
        symbol = params["ts_code"]
        if api == "fund_div":
            return pl.DataFrame()
        dates = ["20260129"] if self.missing and symbol == "511010.SH" else ["20260129", "20260130"]
        price = 1.5 if symbol == "512890.SH" else 110.0
        return pl.from_dicts(
            [
                dict(
                    ts_code=symbol,
                    trade_date=day,
                    open=price,
                    high=price + 0.01,
                    low=price - 0.01,
                    close=price,
                    pre_close=price,
                    vol=100000.0,
                    amount=price * 10000.0,
                )
                for day in dates
            ]
        )


@pytest.fixture
def settings(tmp_path):
    terms = tmp_path / "terms.toml"
    terms.write_text("splits=[]\n", encoding="utf-8")
    return dict(
        etf_daily_root=str(tmp_path / "inputs"),
        etf_actions_root=str(tmp_path / "actions"),
        action_terms=str(terms),
        action_sources=str(tmp_path / "sources.json"),
    )


def test_capture_is_exact_dated_immutable_and_reused(settings, tmp_path):
    connector = Connector()
    folder = data.capture(date=DAY, settings=settings, data_root=tmp_path, connector=connector)
    bars, refs, receipt = data.read_capture(folder, date=DAY, now=dt.datetime.now(data.SHANGHAI))
    assert set(bars["symbol"]) == set(data.SYMBOLS) and bars.height == 4 and refs.height == 4
    assert len(connector.calls) == 4 and len(receipt["requests"]) == 4
    assert receipt["requests"]["512890.SH/fund_div/0"]["rows"] == 0
    again = data.capture(date=DAY, settings=settings, data_root=tmp_path, connector=connector)
    assert again == folder and len(connector.calls) == 4
    for item in receipt["requests"].values():
        from pathlib import Path

        assert hashlib.sha256(Path(item["raw_path"]).read_bytes()).hexdigest() == item["sha256"]


def test_stale_etf_quote_never_substitutes_for_exact_session(settings, tmp_path):
    with pytest.raises(ValueError, match="Exact-session ETF quotes missing"):
        data.capture(
            date=DAY, settings=settings, data_root=tmp_path, connector=Connector(missing=True)
        )
    assert not list((tmp_path / "inputs").glob("*/capture_*/summary.json"))


def test_raw_mutation_is_detected_before_reuse(settings, tmp_path):
    folder = data.capture(date=DAY, settings=settings, data_root=tmp_path, connector=Connector())
    receipt = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    from pathlib import Path

    path = Path(next(iter(receipt["requests"].values()))["raw_path"])
    path.write_bytes(b"changed unit-test source")
    with pytest.raises(ValueError, match="raw source changed"):
        data.read_capture(folder, date=DAY, now=dt.datetime.now(data.SHANGHAI))


def test_empty_new_full_history_cannot_erase_known_cash_actions(settings, tmp_path):
    folder = data.capture(date=DAY, settings=settings, data_root=tmp_path, connector=Connector())
    old = tmp_path / "actions" / "old"
    old.mkdir(parents=True)
    event = dict(
        symbol="511010.SH",
        ann_date=dt.date(2025, 1, 1),
        record_date=dt.date(2025, 1, 2),
        ex_date=dt.date(2025, 1, 3),
        pay_date=dt.date(2025, 1, 6),
        share_list_date=None,
        div_cash=0.1,
        share_ratio=0.0,
        adjust_share_price=True,
        action_type="CASH_DIVIDEND",
        source_path="unit-fixture",
        source_sha256="unit-fixture",
        source_url="unit-fixture",
        observed_at="2025-01-07T09:00:00+08:00",
        version="old",
    )
    pl.from_dicts([event], schema=SCHEMA).write_parquet(old / "actions.parquet")
    (old / "sources.json").write_text("[]", encoding="utf-8")
    (old / "terms.toml").write_text("splits=[]", encoding="utf-8")
    summary = dict(
        status="complete",
        symbols=data.SYMBOLS,
        observed_at="2025-01-07T09:00:00+08:00",
        data_sha256=data.sha(old / "actions.parquet"),
        sources_sha256=data.sha(old / "sources.json"),
        terms_sha256=data.sha(old / "terms.toml"),
    )
    (old / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="lost known implementations"):
        data.shared_actions(folder=folder, settings=settings, now=dt.datetime.now(data.SHANGHAI))
    assert len(list((tmp_path / "actions").glob("*/summary.json"))) == 1


def test_action_observation_offset_is_parsed_and_future_observation_rejected(
    settings, tmp_path, monkeypatch
):
    folder = data.capture(date=DAY, settings=settings, data_root=tmp_path, connector=Connector())
    from pathlib import Path

    version = Path(settings["etf_actions_root"]) / ("account_30w_" + folder.name)
    version.mkdir(parents=True)
    import quant.data.etf_corporate_actions as master

    events = pl.DataFrame(
        {"observed_at": ["2026-11-08T17:54:25.123456+08:00"], "ann_date": [dt.date(2025, 1, 1)]}
    )
    monkeypatch.setattr(master, "load", lambda *args, **kwargs: events)
    now = dt.datetime(2026, 11, 8, 18, tzinfo=data.SHANGHAI)
    result, _ = data.shared_actions(folder=folder, settings=settings, now=now)
    assert result.height == 1
    with pytest.raises(ValueError, match="not yet available"):
        data.shared_actions(folder=folder, settings=settings, now=now - dt.timedelta(hours=1))


def test_first_live_action_publication_refreshes_clock_but_not_fixed_cutoff(settings, tmp_path, monkeypatch):
    from pathlib import Path
    from quant.data import etf_corporate_actions as master
    from quant.execution import account_30w_top15_paper as paper

    folder = data.capture(date=DAY, settings=settings, data_root=tmp_path, connector=Connector())
    before = dt.datetime.now(data.SHANGHAI)
    events = []

    def publish(**kwargs):
        Path(kwargs['output']).mkdir(parents=True)
        events.append(pl.DataFrame({'ann_date': [DAY],
                                    'observed_at': [dt.datetime.now(data.SHANGHAI).isoformat()]}))

    monkeypatch.setattr(master, 'publish', publish)
    monkeypatch.setattr(master, 'load', lambda *a, **kw: events[0])
    monkeypatch.setattr(paper, 'capture', lambda **kw: folder)
    result = paper.etf_inputs({'data': settings}, DAY, before, data_root=tmp_path)
    assert len(events) == 1 and result['actions'].height == 1
    with pytest.raises(ValueError, match='not yet available'):
        data.shared_actions(folder=folder, settings=settings, now=before)


def test_preparation_creates_only_inputs_and_reuses_them(settings, tmp_path, monkeypatch):
    from pathlib import Path
    from quant.data import account_30w_prepare as prepare

    Path(settings['action_sources']).write_text('{}', encoding='utf-8')
    config = tmp_path/'paper.toml'
    config.write_text('[paper]\nauto_trade=false\n[data]\n' + '\n'.join(
        f'{key}={json.dumps(value)}' for key, value in settings.items()), encoding='utf-8')
    monkeypatch.setattr(prepare, 'latest_session', lambda **kw: DAY)
    client = Connector()
    result = prepare.run(config=config, data_root=tmp_path, output=tmp_path/'prep1', end=DAY, connector=client)
    assert result['status'] == 'complete' and result['account_state_changed'] is False
    assert result['quote_rows'] == 4 and result['auto_trade'] is False
    assert not list(tmp_path.rglob('state.json')) and len(client.calls) == 4
    second = prepare.run(config=config, data_root=tmp_path, output=tmp_path/'prep2', end=DAY, connector=client)
    assert second['status'] == 'complete' and second['capture'] == result['capture']
    assert len(client.calls) == 4


def test_preparation_rejects_future_before_output_or_query(settings, tmp_path, monkeypatch):
    from quant.data import account_30w_prepare as prepare

    config = tmp_path/'paper.toml'
    config.write_text('[paper]\nauto_trade=false\n', encoding='utf-8')
    monkeypatch.setattr(prepare, 'latest_session', lambda **kw: pytest.fail('future calendar request'))
    client = Connector()
    with pytest.raises(ValueError, match='completion window'):
        prepare.run(config=config, data_root=tmp_path, output=tmp_path/'future',
                    end=dt.datetime.now(data.SHANGHAI).date()+dt.timedelta(days=1), connector=client)
    assert not (tmp_path/'future').exists() and not client.calls


def test_cli_routes_input_preparation_without_starting_account(monkeypatch):
    from quant import cli

    calls = []
    monkeypatch.setattr(cli, '_delegate', lambda module, args: calls.append((module, args)) or 0)
    assert cli.main(['data', 'account-30w-inputs', '--output', 'fixture']) == 0
    assert calls == [('quant.data.account_30w_prepare', ['--output', 'fixture'])]
