"""Add explicitly recognized PDF periods to the daily disclosure request list."""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.cninfo_announcements import download_document
from quant.data.financial_document_periods import document_periods
from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore


def apply_reviewed_headers(*, disclosures: Path, headers: Path, output: Path) -> dict:
    """Reuse inspected statement headers while preserving the original OCR result."""
    from quant.data.resolve_financial_six_20260912 import resolve_batch

    source = json.loads((disclosures/'summary.json').read_text(encoding='utf-8'))
    reviewed = json.loads(headers.read_text(encoding='utf-8'))
    pending = {row['announcement_id'] for row in source['unresolved']}
    selected = {**reviewed, 'documents': [row for row in reviewed['documents']
                                         if row['announcement_id'] in pending]}
    corrections = resolve_batch(selected, source)
    requests = {(row['symbol'], row['period']) for row in source['requests'] + corrections['requests']}
    result = {**source,
              'requests': [{'symbol': symbol, 'period': period}
                           for symbol, period in sorted(requests, key=lambda pair: (pair[1], pair[0]))],
              'unresolved': corrections['unresolved'],
              'document_resolutions': source.get('document_resolutions', []) + corrections['document_resolutions'],
              'reviewed_headers': reviewed}
    path = output/'summary.json'
    if path.is_file():
        if json.loads(path.read_text(encoding='utf-8')) != result:
            raise ValueError('Reviewed headers or source changed; choose a new output')
        return result
    output.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def issuer_names(symbols: list[str], *, data_root: Path, output: Path) -> dict:
    """Keep exact provider full names; never guess how a stock abbreviation expands."""
    output.mkdir(parents=True, exist_ok=True)
    path = output/'issuer_names.json'
    names = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    client = TushareConnector(config_path=Path('configs/tushare.local.toml'))
    store = RawStore(data_root/'raw')
    for symbol in sorted(set(symbols)-set(names)):
        params = {'ts_code': symbol, 'fields': 'ts_code,name,fullname'}
        try:
            raw = client.query_raw('stock_basic', **params)
        except Exception:
            raise RuntimeError(f'Issuer name query failed: {symbol}') from None
        saved = store.write(source='tushare', table='financial_document_issuer_names', parameters=params, frame=raw)
        if not raw.is_empty() and (raw.height != 1 or raw['ts_code'].to_list() != [symbol]):
            raise ValueError('Issuer metadata response does not match the requested symbol')
        names[symbol] = {'fullname': raw['fullname'].item() if not raw.is_empty() else None,
                         'raw_path': str(saved.data_path)}
        path.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding='utf-8')
        time.sleep(1.05)
    return names


def ocr_pages(pdf: Path, output: Path, *, maximum_pages: int = 400) -> list[dict]:
    renderer, info = shutil.which('pdftoppm'), shutil.which('pdfinfo')
    bundled = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin'
    if not renderer and (bundled/'pdftoppm.exe').is_file():
        renderer = str(bundled/'pdftoppm.exe')
    if not info and (bundled/'pdfinfo.exe').is_file():
        info = str(bundled/'pdfinfo.exe')
    if not renderer or not info:
        raise RuntimeError('Existing Poppler renderer and pdfinfo must be available on PATH')
    details = subprocess.run([info, str(pdf)], capture_output=True, text=True, errors='replace',
                             timeout=60, check=True).stdout
    match = re.search(r'^Pages:\s+(\d+)', details, re.MULTILINE)
    if not match or not 0 < int(match[1]) <= maximum_pages:
        raise ValueError('PDF page count is unavailable or exceeds the configured inspection limit')
    count = int(match[1])
    output.mkdir(parents=True, exist_ok=True)
    path = output/'pages.jsonl'
    pages = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.is_file() else []
    done = {row['page'] for row in pages}
    if len(done) != len(pages) or not done <= set(range(1, count+1)):
        raise ValueError('Invalid saved OCR page numbers')
    if len(done) == count:
        return pages
    images = output/'images'
    images.mkdir(exist_ok=True)
    # Header crop keeps statement names, units, dates and audit scope; footnotes stay out.
    subprocess.run([renderer, '-scale-to-x', '1400', '-scale-to-y', '-1', '-x', '0', '-y', '0',
                    '-W', '1400', '-H', '1000', '-png', str(pdf), str(images/'page')],
                   check=True, capture_output=True, timeout=1800)
    inputs = [{'page': int(image.stem.split('-')[-1]), 'image': str(image.resolve())}
              for image in sorted(images.glob('page-*.png'))
              if int(image.stem.split('-')[-1]) not in done]
    if len(inputs)+len(done) != count:
        raise ValueError('Rendered page count differs from source PDF')
    request = output/'input_pages.json'
    request.write_text(json.dumps(inputs), encoding='utf-8')
    subprocess.run(['powershell.exe', '-NoProfile', '-File', str(Path(__file__).with_name('ocr_financial_pages.ps1')),
                    '-InputJson', str(request.resolve()), '-OutputJsonl', str(path.resolve())],
                   check=True, capture_output=True, timeout=1800)
    pages = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    if len(pages) != count or {row['page'] for row in pages} != set(range(1, count+1)):
        raise ValueError('OCR did not return all inspected pages')
    return pages


def resolve(*, disclosures: Path, data_root: Path, output: Path, document_cache: Path) -> dict:
    source = json.loads((disclosures/'summary.json').read_text(encoding='utf-8'))
    if (output/'summary.json').is_file():
        saved = json.loads((output/'summary.json').read_text(encoding='utf-8'))
        if saved['raw_paths'] != source['raw_paths'] or saved['start'] != source['start'] or saved['end'] != source['end']:
            raise ValueError('Completed document resolution has different announcement inputs')
        return saved
    output.mkdir(parents=True, exist_ok=True)
    names = issuer_names([item['symbol'] for item in source['unresolved']], data_root=data_root, output=output)
    raw_rows = pl.read_parquet(source['raw_paths']).to_dicts() if source['raw_paths'] else []
    rows = {str(row['announcementId']): row for row in raw_rows}
    requests = {(row['symbol'], row['period']) for row in source['requests']}
    recognized, excluded, unresolved = [], [], []
    for item in source['unresolved']:
        row = rows.get(item['announcement_id'])
        if row is None or item['reason'] != 'report_period_not_explicit_in_title':
            unresolved.append(item)
            continue
        relative, issuer = str(row.get('adjunctUrl') or ''), str(row.get('secName') or '')
        published = dt.date.fromisoformat(item['announcement_date'])
        preliminary = document_periods(title=item['title'], issuer_name=issuer, published=published, pages=[])
        if preliminary.get('excluded'):
            excluded.append({**item, **preliminary})
            continue
        identifier = item['announcement_id']
        if not re.fullmatch(r'\d+', identifier):
            raise ValueError('Numeric announcement ID required for document capture')
        raw_root = data_root/'raw'/'cninfo'/'financial_disclosure_documents'
        cached = sorted(raw_root.glob(f'date=*/*/{identifier}.pdf'))
        if cached:
            pdf = cached[0]
        else:
            stamp = dt.datetime.now(dt.timezone.utc)
            folder = raw_root/f'date={stamp.astimezone(dt.timezone(dt.timedelta(hours=8))).date()}'/stamp.strftime('%H%M%S%f')
            body = download_document(relative)
            folder.mkdir(parents=True, exist_ok=False)
            pdf = folder/f'{identifier}.pdf'
            with pdf.open('xb') as file:
                file.write(body)
        print(f'Inspecting issuer financial document {identifier}', flush=True)
        try:
            pages = ocr_pages(pdf, document_cache/identifier)
        except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            unresolved.append({**item, 'reason': 'document_text_unavailable', 'detail': str(exc), 'raw_path': str(pdf)})
            continue
        full_name = names[item['symbol']]['fullname']
        parsed = document_periods(title=item['title'], issuer_name=issuer, issuer_full_name=full_name,
                                  published=published, pages=pages)
        if parsed['periods']:
            recognized.append({**item, 'raw_path': str(pdf), 'issuer_full_name': full_name, **parsed})
            requests.update((item['symbol'], period) for period in parsed['periods'])
            if parsed.get('unconfirmed_evidence') or ('一期' in item['title'] and
                    all(period.endswith('-12-31') for period in parsed['periods'])):
                unresolved.append({**item, 'raw_path': str(pdf), 'reason': 'partially_readable_document_periods',
                                   'confirmed_periods': parsed['periods'],
                                   'unconfirmed_evidence': parsed.get('unconfirmed_evidence', [])})
        else:
            unresolved.append({**item, 'raw_path': str(pdf), 'reason': parsed['reason']})
    result = {**source, 'requests': [{'symbol': symbol, 'period': period} for symbol, period in
                                    sorted(requests, key=lambda row: (row[1], row[0]))],
              'document_resolutions': recognized, 'excluded_documents': excluded, 'unresolved': unresolved}
    lines = ['# 财务公告正文期别', '',
             f'识别出期别的文档{len(recognized)}份，备考/模拟文档{len(excluded)}份，待解析{len(unresolved)}份；'
             f'合并标题结果后，共{len(requests)}组公司与报告期请求。', '',
             '|证券|公告原件|已识别期别|依据页|', '|---|---|---|---|']
    for item in recognized:
        pages_used = ', '.join(str(page) for page in sorted({row['page'] for row in item['evidence']}))
        lines.append(f"|{item['symbol']}|[{item['announcement_id']}]({Path(item['raw_path']).resolve().as_posix()})|"
                     f"{', '.join(item['periods'])}|{pages_used}|")
    if unresolved:
        lines += ['', '待解析：', *[f"- {item['symbol']} / {item['announcement_id']}: {item['reason']}" for item in unresolved]]
    lines += ['', '识别范围限定在可确认的发行人报表表头与审计范围；实际数值另从供应商四表获取。', '']
    (output/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disclosures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--document-cache', type=Path, default=Path('artifacts/data/financial_document_ocr_v1'))
    args = parser.parse_args()
    result = resolve(disclosures=args.disclosures, data_root=args.data_root, output=args.output,
                     document_cache=args.document_cache)
    print(json.dumps({'recognized': len(result['document_resolutions']), 'excluded': len(result['excluded_documents']),
                      'unresolved': len(result['unresolved']), 'requests': len(result['requests'])}))


if __name__ == '__main__':
    main()
