"""Exercise the actual shared ledger and A2 order outputs in an isolated account."""

import datetime as dt
import hashlib
import json
from types import SimpleNamespace

import polars as pl
import pytest

from quant.data.account_30w_top15_inputs import instruments
from quant.data.etf_corporate_actions import SCHEMA
from quant.execution import account_30w_top15_paper as paper
from tests.unit.test_stock_paper import fixture_inputs


@pytest.fixture
def account(tmp_path, monkeypatch):
    stocks, _, _, _ = fixture_inputs()
    stocks.bars = stocks.bars.with_columns(
        pl.lit(10.0).alias("open"),
        pl.lit(10.1).alias("high"),
        pl.lit(9.9).alias("low"),
        pl.lit(10.0).alias("close"),
    )
    signal = dt.date(2026, 1, 30)
    path = tmp_path / "account.toml"
    path.write_text(
        paper.CONFIG.read_text(encoding="utf-8").replace(
            "inception_date = 2026-11-30", "inception_date = 2026-01-30"
        ),
        encoding="utf-8",
    )
    symbols = stocks.instruments["symbol"].to_list()
    scores = pl.DataFrame(
        dict(
            trade_date=[signal] * len(symbols),
            symbol=symbols,
            prediction=list(map(float, range(len(symbols), 0, -1))),
        )
    )
    monkeypatch.setattr(
        paper,
        "forecast_for",
        lambda *args: scores.with_columns(pl.lit(args[1]).alias("trade_date")),
    )
    monkeypatch.setattr(paper, "read_stock_paper_calendar", lambda *_: stocks.calendar)
    etf_rows = []
    for date in stocks.calendar["date"]:
        for symbol, price in [("512890.SH", 1.5), ("511010.SH", 110.0)]:
            etf_rows.append(
                dict(
                    symbol=symbol,
                    trade_date=date,
                    open=price,
                    high=price + 0.01,
                    low=price - 0.01,
                    close=price,
                    volume=100000000.0,
                    amount=price * 100000000.0,
                    adj_factor=1.0,
                    source="fixture",
                )
            )
    bars = pl.from_dicts(etf_rows)
    etfs = dict(
        bars=bars,
        references=bars.select("symbol", "trade_date", pl.col("close").alias("pre_close")),
        actions=pl.DataFrame(schema=SCHEMA),
        instruments=instruments(),
        splits=[],
    )
    output = tmp_path / "rehearsal" / "account"

    def run(end, **kwargs):
        return paper.run(
            config_path=path,
            output=output,
            end=end,
            stock_reader=lambda *_: stocks,
            etf_reader=lambda *_: etfs,
            **kwargs,
        )

    return path, output, stocks, etfs, run


def test_not_started_does_not_create_future_state(tmp_path):
    output = tmp_path / "formal"
    result = paper.run(
        output=output, end=dt.date(2026, 11, 6), now=dt.datetime(2026, 11, 8, tzinfo=paper.SHANGHAI)
    )
    assert result["status"] == "not_started" and result["inception"] == "2026-11-30"
    assert not output.exists()


def test_first_signal_has_fifteen_limits_and_two_etf_quantities(account):
    _, output, _, _, run = account
    result = run(dt.date(2026, 1, 30))
    assert result["stock_orders"] == 15 and result["etf_orders"] == 2
    orders = pl.read_csv(output / "latest_orders.csv")
    stock = orders.filter(pl.col("asset_type") == "STOCK")
    etfs = orders.filter(pl.col("asset_type") == "ETF")
    assert set(stock["limit_price"]) == {10.1}
    assert etfs["limit_price"].null_count() == 2 and set(etfs["order_type"]) == {"MARKET"}
    assert all(x.endswith("T09:15:00+08:00") for x in orders["planned_submit_at"])
    assert result["equity"] == 300000 and result["rehearsal"]
    receipt = json.loads((output / '2026-01-30/orders_receipt.json').read_bytes())
    for name, digest in receipt['files'].items():
        assert digest == hashlib.sha256((output / '2026-01-30' / name).read_bytes()).hexdigest()
    assert result['orders_sha256'] == receipt['files']['orders.csv']
    assert result['snapshot_sha256'] == receipt['files']['state.json']


def test_actual_mixed_fills_share_cash_and_resume_does_not_rewrite_fills(account):
    _, output, _, _, run = account
    run(dt.date(2026, 1, 30))
    result = run(dt.date(2026, 2, 2))
    assert result["cash"] >= 0 and result["positions"] == 17
    folder = output / "2026-02-02"
    fills = pl.read_csv(folder / "fills.csv")
    assert fills.height == 17 and set(fills["side"]) == {"BUY"}
    state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    assert state["nav"][-1]["reconciliation_unexplained_return"] == pytest.approx(0, abs=1e-10)
    saved = {name: (folder / name).read_bytes() for name in ["fills.csv", "state.json", "nav.csv"]}
    run(dt.date(2026, 2, 2))
    assert all((folder / name).read_bytes() == content for name, content in saved.items())


def test_etfs_do_not_rebalance_at_a_nonquarter_month_end(account):
    _, output, _, _, run = account
    run(dt.date(2026, 1, 30))
    run(dt.date(2026, 2, 2))
    result = run(dt.date(2026, 2, 27))
    state = json.loads((output / "2026-02-27/state.json").read_text(encoding="utf-8"))
    assert result["etf_orders"] == 0 and state["allocation"]["quarterly_allocation"] is False
    assert state["pending_etf_orders"] == []


def test_notify_uses_frozen_signal_orders_once_and_never_a_rehearsal(tmp_path):
    output = tmp_path / "formal"
    folder = output / "2026-11-30"
    folder.mkdir(parents=True)
    orders = pl.DataFrame(
        dict(as_of=["2026-11-30"], execution_date=["2026-12-01"], symbol=["600000.SH"])
    )
    orders.write_csv(folder / "orders.csv")
    (folder / "orders.md").write_text("manual paper orders", encoding="utf-8")
    state = dict(date="2026-11-30", auto_trade=False, shadow=True, rehearsal=False)
    (folder / "state.json").write_text(json.dumps(state))
    (output / 'config.toml').write_bytes(paper.CONFIG.read_bytes())
    paper.publish_order_receipt(output, '2026-11-30',
                                dt.datetime(2026, 11, 30, 21, 30, tzinfo=paper.SHANGHAI))
    calls = []

    def sender(*args):
        calls.append(args)
        return [SimpleNamespace(channel="test", ok=True, detail="platform_accepted")]

    before = paper.notify_due(
        output=output, now=dt.datetime(2026, 11, 30, 21, tzinfo=paper.SHANGHAI), sender=sender
    )
    assert before["status"] == "not_due" and calls == []
    now = dt.datetime(2026, 12, 1, 8, 35, tzinfo=paper.SHANGHAI)
    first = paper.notify_due(output=output, now=now, sender=sender)
    second = paper.notify_due(output=output, now=now, sender=sender)
    assert first == second and len(calls) == 1 and first["transport_accepted"]
    assert first["late"] is False
    assert first['body_sha256'] == hashlib.sha256(calls[0][1].encode('utf-8')).hexdigest()
    (folder / 'orders.md').write_text('different text', encoding='utf-8')
    paper.publish_order_receipt(output, '2026-11-30',
                                dt.datetime(2026, 11, 30, 21, 35, tzinfo=paper.SHANGHAI))
    with pytest.raises(ValueError, match='changed after notification attempt'):
        paper.notify_due(output=output, now=now, sender=sender)
    assert len(calls) == 1
    (output / "manual_rehearsal_notification.json").unlink()
    state["rehearsal"] = True
    (folder / "state.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="not a rehearsal"):
        paper.notify_due(output=output, now=now, sender=sender)


@pytest.mark.parametrize('changed', ['orders.csv', 'orders.md', 'state.json', 'config.toml',
                                     'missing_receipt', 'future_receipt'])
def test_notification_rejects_changed_published_bundle_before_sending(tmp_path, changed):
    output = tmp_path / 'formal'
    folder = output / '2026-11-30'
    folder.mkdir(parents=True)
    (output / 'config.toml').write_bytes(paper.CONFIG.read_bytes())
    pl.DataFrame(dict(as_of=['2026-11-30'], execution_date=['2026-12-01'],
                      symbol=['600000.SH'])).write_csv(folder / 'orders.csv')
    (folder / 'orders.md').write_text('original paper order', encoding='utf-8')
    (folder / 'state.json').write_text(json.dumps(dict(
        date='2026-11-30', auto_trade=False, shadow=True, rehearsal=False)))
    receipt = dict(as_of='2026-11-30', recorded_at='2026-11-30T21:30:00+08:00',
        files={name: hashlib.sha256(
        (folder / name).read_bytes()).hexdigest()
        for name in ['orders.csv', 'orders.md', 'state.json']},
        config_sha256=hashlib.sha256((output / 'config.toml').read_bytes()).hexdigest())
    if changed == 'future_receipt':
        receipt['recorded_at'] = '2026-12-01T09:00:00+08:00'
    if changed != 'missing_receipt':
        (folder / 'orders_receipt.json').write_text(json.dumps(receipt))
    if changed not in ['missing_receipt', 'future_receipt']:
        path = output / changed if changed == 'config.toml' else folder / changed
        original = path.read_bytes()
        path.write_bytes(original.replace(b'600000.SH', b'600001.SH') if changed == 'orders.csv'
                         else original + (b' ' if changed.endswith('.json') else b'\n'))
    calls = []
    with pytest.raises(ValueError, match='published order bundle'):
        paper.notify_due(output=output, now=dt.datetime(2026, 12, 1, 8, 35, tzinfo=paper.SHANGHAI),
                         sender=lambda *args: calls.append(args) or [])
    assert calls == [] and not (output / 'manual_rehearsal_notification.json').exists()


def test_notification_cannot_read_a_snapshot_during_account_write(tmp_path):
    from quant.execution.manual_session_service import instance_lock

    output = tmp_path / 'formal'
    output.mkdir()
    with instance_lock(output / 'writer.lock'), pytest.raises(OSError):
        paper.notify_due(output=output, now=dt.datetime(2026, 12, 1, 8, 35, tzinfo=paper.SHANGHAI),
                         sender=lambda *_: pytest.fail('must not send during account write'))
    assert not (output / 'manual_rehearsal_notification.json').exists()
