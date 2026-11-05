"""Previous-month brief from the existing evening task; no additional scheduler."""
import datetime as dt
import hashlib
import json
from pathlib import Path

from quant.llm.ledger import SHANGHAI


def run(*, root=Path('.'), now=None):
    root = Path(root).resolve()
    clock = now or dt.datetime.now(SHANGHAI)
    if clock.tzinfo is None:
        raise ValueError('Require timezone-aware brief execution clock')
    clock = clock.astimezone(SHANGHAI)
    if clock.day != 1 or clock.hour < 21:
        return {'status': 'not_due', 'observed_at': clock.isoformat(), 'auto_trade': False}
    previous_end = clock.date().replace(day=1)-dt.timedelta(days=1)
    month = previous_end.strftime('%Y-%m')
    folder = root / 'artifacts/research/brief'
    receipt_path = folder / f'{month}.scheduler.json'
    if receipt_path.exists():
        saved = json.loads(receipt_path.read_text(encoding='utf-8'))
        if saved.get('status') == 'complete':
            expected = {str(folder/f'{month}{suffix}') for suffix in ('.md','.facts.json','.narrative.json')}
            if (saved.get('month') != month or saved.get('auto_trade') is not False
                    or set(saved.get('products_sha256', {})) != expected):
                raise ValueError('Completed monthly brief receipt identity mismatch')
            for path, digest in saved['products_sha256'].items():
                if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                    raise ValueError('Completed monthly brief product changed')
            return {**saved, 'reused': True}
    from quant.reporting.research_brief import write_brief

    result = write_brief(month, root=root, use_llm=True, notify=False)
    report = Path(result['path'])
    facts = folder / f'{month}.facts.json'
    narrative = folder / f'{month}.narrative.json'
    paths = [report, facts, narrative]
    if not all(path.is_file() for path in paths):
        raise ValueError('Monthly brief products missing')
    call = json.loads(narrative.read_text(encoding='utf-8'))
    machine_facts = json.loads(facts.read_text(encoding='utf-8'))
    facts_digest = hashlib.sha256(json.dumps(machine_facts,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
    complete = (result['narrative'] is True and call.get('status') == 'accepted'
                and call.get('month') == month and call.get('facts_sha256') == facts_digest)
    receipt = {'status': 'complete' if complete else 'incomplete', 'month': month,
        'observed_at': clock.isoformat(), 'report': str(report), 'reused': False,
        'narrative_status': call.get('status'), 'maximum_llm_attempts': 1,
        'products_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        'auto_trade': False, 'notifications': 0,
        'scope': 'Previous completed calendar month; native scheduler event still required for production acceptance.'}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt
