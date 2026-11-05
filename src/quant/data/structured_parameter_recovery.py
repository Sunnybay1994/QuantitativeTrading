"""Resume the rejected share_float global suffix using the frozen stock catalog."""
import datetime as dt
import hashlib
import json
from pathlib import Path

from quant.data.structured_event_pages import pages


def load_parameter_recovery(output,receipt,spec,symbol_recovery):
    path=output/'parameter_recovery.json'
    pinned=receipt.get('parameter_recovery_sha256')
    if not path.exists():
        if pinned:
            raise ValueError('Registered parameter recovery file disappeared')
        return None
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if pinned and pinned!=digest:
        raise ValueError('Frozen parameter recovery request changed')
    recovery=json.loads(path.read_text(encoding='utf-8'))
    if (recovery['table']!='share_float' or recovery['auto_trade'] is not False
            or recovery['original_config_sha256']!=receipt['config_sha256']):
        raise ValueError('Parameter recovery must retain the original capture scope')
    if not symbol_recovery or any(recovery[k]!=symbol_recovery[k]
            for k in ('table','catalog_path','catalog_sha256')):
        raise ValueError('Parameter recovery must reuse the frozen acquisition catalog')
    first=dt.date.fromisoformat(recovery['first'])
    last=dt.date.fromisoformat(recovery['last'])
    failed_last=dt.date.fromisoformat(recovery['failed_last'])
    rule=spec['tables']['share_float']
    if (rule['chunk']!='month' or rule.get('symbols') or rule.get('symbols_file')
            or not spec['start']<=first<=failed_last<=last==spec['end']
            or (first!=spec['start'] and first.day!=1)):
        raise ValueError('Parameter recovery is outside the original monthly capture')
    offset=recovery['failed_offset']
    scope=f'share_float/all/{first}/{failed_last}'
    if (not isinstance(offset,int) or not 0<=offset<=100000
            or offset%spec['page_size'] or f'{scope}/{offset}' in receipt['requests']):
        raise ValueError('Parameter recovery must start at the unsaved rejected page')
    evidence=Path(recovery['stopped_summary_path'])
    if hashlib.sha256(evidence.read_bytes()).hexdigest()!=recovery['stopped_summary_sha256']:
        raise ValueError('Original stopped receipt changed')
    original=json.loads(evidence.read_text(encoding='utf-8'))
    if (original['status']!='stopped' or original['config_sha256']!=receipt['config_sha256']
            or any(receipt['requests'].get(k)!=v for k,v in original['requests'].items())):
        raise ValueError('Original saved request records changed')
    for before in range(0,offset,spec['page_size']):
        record=receipt['requests'].get(f'{scope}/{before}')
        if not record or record['rows']!=spec['page_size']:
            raise ValueError('Rejected global window must retain its contiguous saved prefix')
    receipt['parameter_recovery_sha256']=digest
    return {**recovery,'first':first,'last':last,'failed_last':failed_last,
        'stop_before':f'{scope}/{offset}','symbols':symbol_recovery['symbols']}


def parameter_pages(*,table,rule,spec,receipt,client,store,save,recovery):
    """Keep saved global observations first, then exhaust the entire remaining suffix."""
    observed=set()
    for frame,record in pages(table=table,rule=rule,spec=spec,symbol=None,
            first=recovery['first'],last=recovery['failed_last'],receipt=receipt,
            client=client,store=store,save=save,stop_before=recovery['stop_before']):
        observed.update(frame['ts_code'].to_list())
        yield frame,record
    if not observed<=set(recovery['symbols']):
        raise ValueError('Cached global prefix contains codes outside the recovery catalog')
    state={'first':str(recovery['first']),'last':str(recovery['last']),
        'symbols':len(recovery['symbols']),'complete':False,
        'parent_pages':'retained; native row union keeps earliest observation'}
    receipt['parameter_split']=state
    save()
    for symbol in recovery['symbols']:
        yield from pages(table=table,rule=rule,spec=spec,symbol=symbol,
            first=recovery['first'],last=recovery['last'],receipt=receipt,
            client=client,store=store,save=save)
    state['complete']=True
    save()
