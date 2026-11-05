"""Preserve a successful limited-permission sample without claiming full coverage."""
import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl

from quant.data.structured_events import normalize


def publish_report_trial(*,permissions,data_root=Path('data')):
    probe=json.loads(permissions.read_text(encoding='utf-8'))['tables']['report_rc']
    raw=Path(probe['raw_path'])
    if hashlib.sha256(raw.read_bytes()).hexdigest()!=probe['sha256']:
        raise ValueError('Immutable permission sample changed')
    metadata=json.loads(raw.with_suffix('.json').read_text(encoding='utf-8'))
    if metadata['checksum_sha256']!=probe['sha256']:
        raise ValueError('Permission sample metadata changed')
    # checked_at precedes the request; raw fetched_at is the actual observation.
    observed=max(dt.datetime.fromisoformat(metadata['fetched_at']),dt.datetime.fromisoformat(probe['checked_at']))
    frame=normalize(pl.read_parquet(raw),table='report_rc',
        rule={'date_field':'report_date','announcement_field':'report_date'},
        observed_at=observed.isoformat(),raw_path=str(raw))
    destination=data_root/'clean/report_rc/snapshot=structured_probe_trial_20261105'
    record={'status':'limited_permission_sample','rows':frame.height,
        'first_date':str(frame['source_announcement_date'].min()),'last_date':str(frame['source_announcement_date'].max()),
        'raw_path':str(raw),'raw_sha256':probe['sha256'],'observed_at':observed.isoformat(),
        'parameters':probe['parameters'],'historical_full_coverage':False,'counts_toward_D1_full_tables':False,
        'consumer':'sue_family_v1 source intake: analyst expectations, descriptive sample only; no factor evaluation',
        'units':'op_rt/op_pr/tp/np native 10000 CNY, eps CNY/share; ratios retain native fields',
        'source_document':'https://tushare.pro/document/2?doc_id=292',
        'permission_boundary':'One successful sample does not prove 8000-point bulk access; documented 2000-point trial is ten calls/day. No extra calls or paid permission.',
        'new_api_calls':0,'auto_trade':False}
    if destination.exists():
        if json.loads((destination/'summary.json').read_text(encoding='utf-8'))!=record:
            raise ValueError('Refuse to replace a published limited sample')
        return record
    staging=destination.with_name(destination.name+'.staging')
    staging.mkdir(parents=True,exist_ok=False)
    frame.write_parquet(staging/'data.parquet')
    (staging/'summary.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    staging.rename(destination)
    return record
