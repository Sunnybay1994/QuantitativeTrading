"""Refresh only company/report-period pairs found in a completed announcement scan."""
import argparse
import datetime as dt
import json
import re
from collections.abc import Callable
from pathlib import Path

import tomllib

from quant.data.collect_financial_disclosures import collect
from quant.data.refresh_financials import TABLES, refresh_quarter
from quant.data.resolve_financial_disclosures import apply_reviewed_headers, resolve


def refresh_daily(*, end: dt.date, config: Path, data_root: Path, artifact_root: Path,
                  lookback_days: int, progress: Callable[[dict],None] | None = None) -> dict:
    if lookback_days < 1:
        raise ValueError('Financial disclosure lookback must be positive')
    disclosures = artifact_root/'data'/f'financial_disclosures_v1_{end:%Y%m%d}'
    if progress is not None:
        progress({'phase':'announcement_scan','completed':0})
    collect(start=end-dt.timedelta(days=lookback_days-1), end=end, data_root=data_root, output=disclosures)
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    version = 'v1'
    if settings.get('financials', {}).get('resolve_documents', False):
        if progress is not None:
            progress({'phase':'resolve_documents','completed':0})
        enriched = artifact_root/'data'/f'financial_disclosures_v2_{end:%Y%m%d}'
        resolve(disclosures=disclosures, data_root=data_root, output=enriched,
                document_cache=artifact_root/'data'/'financial_document_ocr_v1')
        disclosures, version = enriched, 'v2'
        headers = settings['financials'].get('reviewed_headers')
        if headers:
            reviewed = artifact_root/'data'/f'financial_disclosures_v3_{end:%Y%m%d}'
            apply_reviewed_headers(disclosures=disclosures, headers=Path(headers), output=reviewed)
            disclosures, version = reviewed, 'v3'
    return update(disclosures=disclosures, config=config, data_root=data_root,
                  output=artifact_root/'data'/f'financial_updates_{version}_{end:%Y%m%d}',progress=progress)


def update(*, disclosures: Path, config: Path, data_root: Path, output: Path,
           progress: Callable[[dict],None] | None = None) -> dict:
    source = json.loads((disclosures/'summary.json').read_text(encoding='utf-8'))
    requests = source['requests']
    if len({(r['symbol'], r['period']) for r in requests}) != len(requests):
        raise ValueError('Duplicate company/report-period request')
    text = config.read_text(encoding='utf-8')
    settings = tomllib.loads(text)
    base = settings['financial_snapshot']
    pattern = r'(?m)^(financial_snapshot\s*=\s*)[\"\'][^\"\']+[\"\']'
    if len(re.findall(pattern, text)) != 1:
        raise ValueError('One financial snapshot setting required')
    summary_path = output/'summary.json'
    if summary_path.is_file():
        saved = json.loads(summary_path.read_text(encoding='utf-8'))
        if saved['requests'] != requests or saved['financial_snapshot'] != base:
            raise ValueError('Completed update does not match these requests and active snapshot')
        return {**saved, 'message': 'no-op', 'new_rows': 0}
    output.mkdir(parents=True, exist_ok=True)
    request_path = output/'requests.json'
    request = {'base_version': base, 'requests': requests}
    if request_path.exists():
        saved = json.loads(request_path.read_text(encoding='utf-8'))
        if saved['requests'] != requests:
            raise ValueError('Resume the same financial requests or choose a new output')
        base = saved['base_version']
    else:
        request_path.write_text(json.dumps(request, indent=2), encoding='utf-8')
    prefix = output.name
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', prefix):
        raise ValueError('Use a simple unique output directory name')
    periods = sorted({r['period'] for r in requests})
    final = f'{prefix}_{len(periods)-1:03d}' if periods else base
    if settings['financial_snapshot'] not in (base, final):
        raise ValueError('Active financial snapshot changed during this update')
    versions, new_rows, completed_requests = [], 0, 0
    for index, period in enumerate(periods):
        symbols = sorted(r['symbol'] for r in requests if r['period'] == period)
        name = f'{prefix}_{index:03d}'
        def quarter_progress(counts: dict, quarter_number=index+1, before=completed_requests) -> None:
            if progress is not None:
                progress({**counts,'quarter_number':quarter_number,'quarters':len(periods),
                    'completed_requests':before+counts['completed'],
                    'total_requests':len(requests)*len(TABLES)})
        saved_path = data_root/'clean/tushare_financials'/name/'summary.json'
        if saved_path.is_file():
            result = json.loads(saved_path.read_text(encoding='utf-8'))
            if result['base_version'] != base or result['period'] != period or result.get('symbols') != symbols:
                raise ValueError('Financial version does not match the requested batch')
        else:
            result = refresh_quarter(data_root=data_root, base_name=base, name=name,
                symbols=symbols, period=dt.date.fromisoformat(period),
                pause_seconds=60 / settings.get('requests_per_minute', 60),
                **({'progress':quarter_progress} if progress is not None else {}))
        completed_requests += len(symbols)*len(TABLES)
        if progress is not None:
            progress({'phase':'quarter_complete','quarter_number':index+1,'quarters':len(periods),
                      'period':period,'completed_requests':completed_requests,
                      'total_requests':len(requests)*len(TABLES)})
        new_rows += sum(row['clean_rows']-row['base_clean_rows'] for row in result['datasets'].values())
        versions.append(name)
        base = name
    result = {'message': 'updated' if new_rows else 'no-op', 'new_rows': new_rows,
              'financial_snapshot': base, 'requests': requests, 'versions': versions,
              'unresolved_announcements': source['unresolved'],
              'recognized_documents': len(source.get('document_resolutions', [])),
              'excluded_documents': len(source.get('excluded_documents', [])),
              'scope': 'Numeric requests performed; announcement titles do not prove provider revision completeness'}
    if requests:
        config.write_text(re.sub(pattern, lambda m: m[1]+'"'+base+'"', text), encoding='utf-8')
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disclosures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/data/refresh.toml'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(update(disclosures=args.disclosures, config=args.config, data_root=args.data_root,
                            output=args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
