import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant.reporting.doctor import _mining

SH=ZoneInfo('Asia/Shanghai')
NOW=dt.datetime(2026,11,6,1,45,tzinfo=SH)


def batch(root: Path,name,day,**fields):
    folder=root/name/day
    folder.mkdir(parents=True)
    payload={'steps':{step:{'ok':True} for step in ('N1','N2','N3','N4','N5')},**fields}
    (folder/'summary.json').write_text(json.dumps(payload),encoding='utf-8')
    return folder/'summary.json'


def test_resumed_frozen_batch_uses_actual_completion_not_snapshot_directory(tmp_path):
    batch(tmp_path,'batch_000079','2026-11-01',finished_at='2026-11-01T08:00:00')
    path=batch(tmp_path,'batch_000080','2026-10-31',finished_at='2026-11-05T11:27:02.498824')
    before=path.read_bytes()
    value=_mining(tmp_path,NOW.date(),observed_at=NOW)
    assert value['last_completed_batch']=='batch_000080'
    assert value['last_completed_on']=='2026-11-05' and value['days_since_completed']==1
    assert value['last_completed_snapshot_date']=='2026-10-31'
    assert value['completion_date_source']=='finished_at' and path.read_bytes()==before


def test_completion_timestamp_is_converted_to_local_date(tmp_path):
    batch(tmp_path,'batch_000080','2026-10-31',finished_at='2026-11-04T18:00:00+00:00')
    value=_mining(tmp_path,NOW.date(),observed_at=NOW)
    assert value['last_completed_on']=='2026-11-05' and value['days_since_completed']==1


@pytest.mark.parametrize('stamp',['invalid',None,'2026-11-06T02:00:00+08:00','2026-11-07T00:00:00'])
def test_invalid_or_future_completion_cannot_refresh_batch_age(tmp_path,stamp):
    batch(tmp_path,'batch_000079','2026-10-31',finished_at='2026-10-31T08:00:00')
    batch(tmp_path,'batch_000080','2026-11-05',finished_at=stamp)
    value=_mining(tmp_path,NOW.date(),observed_at=NOW)
    assert value['last_completed_batch']=='batch_000079' and value['days_since_completed']==6


def test_legacy_summary_date_remains_supported_and_unfinished_batch_is_not_completion(tmp_path):
    batch(tmp_path,'batch_000079','2026-10-31')
    batch(tmp_path,'batch_000080','2026-11-05',finished_at='2026-11-05T11:27:02',
        steps={'N1':{'ok':True}})
    value=_mining(tmp_path,NOW.date(),observed_at=NOW)
    assert value['last_completed_batch']=='batch_000079' and value['days_since_completed']==6
    assert value['completion_date_source']=='legacy_snapshot_date'
