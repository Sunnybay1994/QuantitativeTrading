"""Reproduce the six scanned-announcement resolutions from inspected page headers."""

import datetime as dt
import json
from pathlib import Path

from quant.data.financial_document_periods import document_periods


def resolve_batch(headers: dict, source: dict) -> dict:
    remaining = {row['announcement_id']: row for row in source['unresolved']}
    existing = {(row['symbol'], row['period']) for row in source['requests']}
    requests: set[tuple[str, str]] = set()
    resolutions: list[dict] = []
    for document in headers['documents']:
        aid = document['announcement_id']
        original = remaining[aid]
        for field in ('symbol', 'title', 'announcement_date', 'raw_path'):
            if document[field] != original[field]:
                raise ValueError(f'Header/source mismatch: {aid} {field}')
        result = document_periods(
            title=document['title'], issuer_name=document['issuer_full_name'],
            published=dt.date.fromisoformat(document['announcement_date']), pages=document['pages'])
        if not result['periods'] or result['unconfirmed_evidence']:
            raise ValueError(f'Insufficient header evidence: {aid}')
        periods = sorted(set(original.get('confirmed_periods', [])) | set(result['periods']))
        requests.update((document['symbol'], period) for period in periods)
        resolutions.append({**document, 'periods': periods, 'parsed_headers': result})
        del remaining[aid]
    return {'requests': [{'symbol': symbol, 'period': period}
                         for symbol, period in sorted(requests-existing, key=lambda pair: (pair[1], pair[0]))],
            'unresolved': list(remaining.values()), 'document_resolutions': resolutions,
            'source_summary': headers['source_summary'], 'method': headers['method']}


def main() -> None:
    headers = json.loads(Path('configs/data/financial_document_headers_20260912.json').read_text(encoding='utf-8'))
    source = json.loads(Path(headers['source_summary']).read_text(encoding='utf-8'))
    result = resolve_batch(headers, source)
    output = Path('artifacts/data/financial_six_disclosures_20260912')
    output.mkdir(parents=True, exist_ok=True)
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Resolved {len(result['document_resolutions'])}; requests {len(result['requests'])}; "
          f"unresolved {len(result['unresolved'])}")


if __name__ == '__main__':
    main()
