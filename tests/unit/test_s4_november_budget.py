import datetime as dt
from pathlib import Path
import tomllib
from types import SimpleNamespace

import pytest

from quant.data.events_v0_budget import task_budget_usd
from quant.data.events_v0 import _task_spend
from quant.data import events_v0_budget as budget
from quant.llm.ledger import append,SHANGHAI


def test_november_cap_uses_actual_billing_month_in_shanghai():
    utc=dt.timezone.utc
    assert task_budget_usd(dt.datetime(2026,10,31,15,59,tzinfo=utc))==5.
    assert task_budget_usd(dt.datetime(2026,10,31,16,tzinfo=utc))==2.
    assert task_budget_usd(dt.datetime(2026,11,30,15,59,tzinfo=utc))==2.
    assert task_budget_usd(dt.datetime(2026,11,30,16,tzinfo=utc))==5.
    config=tomllib.loads(Path('configs/research/event_family_v1.toml').read_text(encoding='utf-8'))
    assert config['month_budget_overrides_usd']['2026-11']==2.


def test_reservation_enforces_november_two_dollar_cap_even_for_legacy_five_dollar_callers(tmp_path,monkeypatch):
    now=dt.datetime(2026,11,5,tzinfo=SHANGHAI)
    monkeypatch.setattr(budget,'dt',SimpleNamespace(datetime=SimpleNamespace(now=lambda tz:now)))
    append({'task':'event_extract','usd':1.99},tmp_path,now=now)
    with pytest.raises(budget.EventBudgetExhausted):
        budget.complete_with_budget(lambda *a:pytest.fail('must not make a paid call'),[],{},
            ledger_root=tmp_path,announcement_id='fixture',spend=_task_spend,
            record=lambda *a:None,limit=5.)
