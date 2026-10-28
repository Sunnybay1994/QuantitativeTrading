"""Append missing GP call estimates; never rewrite original ledger records."""
import datetime as dt
import hashlib
import json
from pathlib import Path

from quant.llm.ledger import SHANGHAI, priced_rows
from quant.llm.pricing import DEFAULT_PRICING, load_pricing


def reprice_unpriced(path: Path, *, pricing: Path = DEFAULT_PRICING, execute: bool = False) -> dict:
    snapshot = path.read_bytes()
    rows = priced_rows(path)
    rates = load_pricing(pricing)
    tariff_hash = hashlib.sha256(pricing.read_bytes()).hexdigest()
    adjustments, unresolved = [], []
    for row in rows:
        if row.get('task') != 'gp_hints' or row.get('usd') not in (None, 0):
            continue
        usage = row.get('tokens') or {}
        prompt = usage.get('prompt_tokens') if isinstance(usage, dict) else None
        completion = usage.get('completion_tokens') if isinstance(usage, dict) else None
        if (type(prompt) is not int or type(completion) is not int
                or min(prompt, completion) < 0 or prompt+completion == 0):
            unresolved.append(row['_source_line'])
            continue
        usd = (prompt*rates['input_usd_per_million']
               + completion*rates['output_usd_per_million']) / 1_000_000
        adjustments.append({
            'kind': 'pricing_adjustment', 'task': 'pricing_adjustment',
            'ts': dt.datetime.now(SHANGHAI).isoformat(),
            'source_line': row['_source_line'], 'source_sha256': row['_source_sha256'],
            'original_task': row['task'], 'usd': usd, 'estimated': True,
            'basis': 'frozen_uncached_peak_tariff_estimate_not_provider_invoice',
            'tariff': rates, 'tariff_sha256': tariff_hash,
        })
    if execute and adjustments:
        if path.read_bytes() != snapshot:
            raise RuntimeError('Ledger changed during pricing; inspect and retry')
        block = b'' if snapshot.endswith(b'\n') else b'\n'
        block += ''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in adjustments).encode('utf-8')
        with path.open('ab') as stream:
            stream.write(block)
        assert path.read_bytes().startswith(snapshot)
        priced_rows(path)  # Verify references before reporting success.
    return {'executed': execute, 'adjustments': len(adjustments), 'unresolved_lines': unresolved,
            'estimated_usd_added': sum(r['usd'] for r in adjustments),
            'original_bytes_sha256': hashlib.sha256(snapshot).hexdigest(), 'new_api_calls': 0}
