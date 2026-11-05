"""Frozen acquisition catalog for the concrete single-day share_float overflow."""
import hashlib
import json
from pathlib import Path


def load_symbol_recovery(output,receipt):
    path=output/'single_day_recovery.json'
    if not path.exists():
        if receipt.get('single_day_recovery_sha256'):
            raise ValueError('Registered single-day recovery file disappeared')
        return None
    payload=path.read_bytes();digest=hashlib.sha256(payload).hexdigest()
    if receipt.get('single_day_recovery_sha256',digest)!=digest:
        raise ValueError('Frozen single-day recovery request changed')
    spec=json.loads(payload)
    if spec['table']!='share_float' or spec['auto_trade'] is not False:
        raise ValueError('Only registered share_float symbol recovery is implemented')
    catalog=Path(spec['catalog_path'])
    if hashlib.sha256(catalog.read_bytes()).hexdigest()!=spec['catalog_sha256']:
        raise ValueError('Frozen single-day recovery catalog changed')
    symbols=json.loads(catalog.read_text(encoding='utf-8'))['symbols']
    if not symbols or any(not isinstance(s,str) or not s for s in symbols) or len(symbols)!=len(set(symbols)):
        raise ValueError('Require a nonempty unique recovery acquisition catalog')
    receipt['single_day_recovery_sha256']=digest
    return {**spec,'symbols':symbols}
