"""Bounded P7 source sampling; no forecast mutation or return evaluation."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

import polars as pl
import requests

from quant.data.connectors.cninfo_announcements import announcement_pages, download_document

OUTPUT = Path('artifacts/data/p7_source_check_20260912_01')
RAW = Path('data/raw/cninfo/p7_source_check_20260912_01')
FIELDS = ['ts_code', 'ann_date', 'end_date', 'first_ann_date', 'change_reason', 'update_flag']


def select_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ann-date year strata, then first two repeated-period groups; no polarity ranking."""
    eligible = sorted((r for r in rows if str(r.get('change_reason') or '').strip()),
                      key=lambda r: (r['ann_date'], r['ts_code'], r['end_date'], r['input_path'], r['row_index']))
    selected: list[dict[str, Any]] = []
    for year in ['2017', '2020', '2023', '2025']:
        selected.extend({**r, 'selection': f'year_{year}', 'pair_id': None}
                        for r in [r for r in eligible if r['ann_date'].startswith(year)][:2])
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in eligible:
        group = groups.setdefault((row['ts_code'], row['end_date']), [])
        if not any(r['ann_date'] == row['ann_date'] for r in group):
            group.append(row)
    pairs = sorted((g for g in groups.values() if len(g) > 1),
                   key=lambda g: (g[0]['ann_date'], g[0]['ts_code'], g[0]['end_date']))[:2]
    for i, group in enumerate(pairs, 1):
        selected.extend({**r, 'selection': 'revision_candidate', 'pair_id': f'pair_{i}'} for r in group[:2])
    return [{'sample_id': f'S{i:02}', **r} for i, r in enumerate(selected, 1)]


def freeze() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=False)
    paths = sorted(Path('data/raw/forecast_text_corpus/p7_forecast_512_20260912_01').glob('*.parquet'))
    paths += [Path('data/raw/forecast_text_corpus/p7_forecast_512_retry_20260912_01/forecast_300479.SZ.parquet')]
    scope = set(json.loads(Path('configs/data/p7_forecast_scope_20260912.json').read_text(encoding='utf-8'))['symbols'])
    rows = []
    for path in paths:
        for index, row in enumerate(pl.read_parquet(path).select(pl.col(FIELDS).cast(pl.String)).to_dicts()):
            if row['ts_code'] not in scope:
                raise ValueError('Input outside fixed scope')
            rows.append({**row, 'input_path': str(path), 'row_index': index})
    payload: dict[str, Any] = {'selected_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
               'rule': 'ann_date-year 2017/2020/2023/2025, first two by ann_date/ts_code/end_date; '
                       'first two multi-ann-date issuer/period groups over entire supplied corpus, first two dates each; '
                       'input_path/row_index break exact ties; no outcome or polarity selection',
               'input_rows': len(rows), 'reason_rows': sum(bool((r['change_reason'] or '').strip()) for r in rows),
               'samples': select_samples(rows)}
    (OUTPUT/'selected_samples.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print([(r['sample_id'], r['ts_code'], r['ann_date']) for r in payload['samples']], flush=True)


class StockSession:
    """Limit the existing CNINFO paginator to the selected issuer."""
    def __init__(self, stock: str):
        self.stock = stock

    def post(self, url: str, *, data: dict, **kwargs: Any) -> Any:
        return requests.post(url, data={**data, 'stock': self.stock}, **kwargs)


def fetch() -> None:
    RAW.mkdir(parents=True, exist_ok=False)
    response = requests.get('https://www.cninfo.com.cn/new/data/szse_stock.json', timeout=30)
    response.raise_for_status()
    mapping = response.json()['stockList']
    samples = json.loads((OUTPUT/'selected_samples.json').read_text(encoding='utf-8'))['samples']
    codes = {r['ts_code'].split('.')[0] for r in samples}
    (RAW/'issuer_lookup.json').write_text(json.dumps([r for r in mapping if r['code'] in codes], ensure_ascii=False, indent=2), encoding='utf-8')
    orgs = {r['code']: r['orgId'] for r in mapping}
    results = []
    for sample in samples:
        code = sample['ts_code'].split('.')[0]
        date = dt.datetime.strptime(sample['ann_date'], '%Y%m%d').date()
        folder = RAW/sample['sample_id']
        folder.mkdir()
        result = {'sample_id': sample['sample_id'], 'candidates': []}
        try:
            stock = code+','+orgs[code]
            for number, (params, rows) in enumerate(announcement_pages(date-dt.timedelta(days=2), date+dt.timedelta(days=2), category='', session=StockSession(stock))):
                (folder/f'listing_{number+1}.json').write_text(json.dumps({'params': {**params, 'stock': stock}, 'retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(),'rows':rows}, ensure_ascii=False, indent=2), encoding='utf-8')
                for row in rows:
                    if row.get('secCode') == code and any(t in row.get('announcementTitle','') for t in ['业绩','季度报告','半年度报告']):
                        result['candidates'].append(row)
            for row in result['candidates']:
                path = folder/(str(row['announcementId'])+'.pdf')
                with path.open('xb') as file:
                    file.write(download_document(row['adjunctUrl']))
                row['raw_pdf'] = str(path)
        except Exception as exc:
            result['error'] = type(exc).__name__+': '+str(exc)[:300]
        results.append(result)
        (OUTPUT/'source_candidates.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(sample['sample_id'], len(result['candidates']), result.get('error',''), flush=True)
        time.sleep(0.5)


def extract() -> None:
    # Reuse Codex's already bundled pure-Python parser under Windows Miniforge.
    bundled = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages'
    sys.path.append(str(bundled))
    from pypdf import PdfReader  # type: ignore[import-not-found]  # bundled parser
    results = json.loads((OUTPUT/'source_candidates.json').read_text(encoding='utf-8'))
    documents = []
    for result in results:
        for row in result['candidates']:
            path = RAW/result['sample_id']/(str(row['announcementId'])+'.pdf')
            if not path.exists():
                with path.open('xb') as file:
                    file.write(download_document(row['adjunctUrl']))
            pages = [{'page': i+1, 'text': page.extract_text()} for i, page in enumerate(PdfReader(path).pages)]
            target = OUTPUT/(result['sample_id']+'_'+str(row['announcementId'])+'_pages.json')
            target.write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
            documents.append({'sample_id': result['sample_id'], **row, 'raw_pdf':str(path), 'pages_path':str(target)})
            print(result['sample_id'],row['announcementId'],len(pages),flush=True)
    (OUTPUT/'documents.json').write_text(json.dumps(documents,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('step', choices=['freeze','fetch','extract'])
    args = parser.parse_args()
    {'freeze':freeze,'fetch':fetch,'extract':extract}[args.step]()
