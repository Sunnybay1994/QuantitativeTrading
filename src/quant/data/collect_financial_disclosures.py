"""Map dated public report announcements to bounded financial refresh requests."""
import argparse
import datetime as dt
import json
import re
import time
import unicodedata
from pathlib import Path

import polars as pl

from quant.data.connectors.cninfo_announcements import AnnouncementSetChanged, announcement_pages
from quant.data.storage import RawStore

REPORT = re.compile(r'(20\d{2})年?(年度|年|半年度|半年|第?[一二三四1234]季度)(?:报告|报)')
FINANCIAL = re.compile(r'年度报告|季度报告|半年报告|年报|财务报表|财务报告')


def report_requests(rows: list[dict], *, start: dt.date, end: dt.date) -> dict:
    requests, unresolved = [], []
    for row in rows:
        title = re.sub(r'\s+', '', unicodedata.normalize('NFKC', re.sub(
            r'<[^>]*>', '', str(row.get('announcementTitle') or ''))))
        code = str(row.get('secCode') or '')
        if not FINANCIAL.search(title) or not re.fullmatch(r'[036]\d{5}', code):
            continue
        if re.search(r'业绩说明会|投资者.*接待|工作规程|管理制度', title):
            continue
        try:
            published = dt.datetime.fromtimestamp(int(row['announcementTime']) / 1000,
                tz=dt.timezone(dt.timedelta(hours=8))).date()
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            published = None
        matches = REPORT.findall(title)
        matches += [(year, f'{int(month)//3}季度') for year, month in re.findall(
            r'(20\d{2})年1月?(?:-|至|—|~)(3|6|9|12)月', title)]
        item = {'symbol': code + ('.SH' if code.startswith('6') else '.SZ'),
                'announcement_id': str(row['announcementId']), 'title': title,
                'announcement_date': str(published) if published else None}
        if published is None or not start <= published <= end:
            unresolved.append({**item, 'reason': 'missing_or_out_of_window_publication_date'})
            continue
        if not matches:
            unresolved.append({**item, 'reason': 'report_period_not_explicit_in_title'})
            continue
        for year, kind in sorted(set(matches)):
            quarter = (4 if kind in ('年度', '年') else 2 if kind in ('半年度', '半年') else
                       {'一': 1, '二': 2, '三': 3, '四': 4, '1': 1, '2': 2, '3': 3, '4': 4}[kind[-3]])
            month, day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[quarter]
            period = dt.date(int(year), month, day)
            if period > published:
                unresolved.append({**item, 'reason': 'report_period_after_publication'})
                continue
            requests.append({**item, 'period': str(period)})
    grouped = sorted({(row['symbol'], row['period']) for row in requests}, key=lambda row: (row[1], row[0]))
    return {'requests': [{'symbol': symbol, 'period': period} for symbol, period in grouped],
            'announcements': requests, 'unresolved': unresolved}


def collect(*, start: dt.date, end: dt.date, data_root: Path, output: Path) -> dict:
    if start > end:
        raise ValueError('Disclosure start must not exceed end')
    if (output/'summary.json').is_file():
        saved = json.loads((output/'summary.json').read_text(encoding='utf-8'))
        if saved['start'] != str(start) or saved['end'] != str(end):
            raise ValueError('Completed disclosure scan has a different date window')
        return saved
    output.mkdir(parents=True, exist_ok=True)
    rows, paths = [], []
    store = RawStore(data_root/'raw')
    # All announcements in this bounded date window include first disclosures and corrections.
    day = start
    while day <= end:
        # Cache only a fully paged day. A changing day never contaminates the next attempt.
        day_path = output/'days'/f'{day}.json'
        if day_path.is_file():
            saved_day = json.loads(day_path.read_text(encoding='utf-8'))
            if saved_day['day'] != str(day):
                raise ValueError('Saved disclosure day differs from the requested date')
            day_paths = saved_day['raw_paths']
            day_rows = [row for path in day_paths for row in pl.read_parquet(path).to_dicts()]
        else:
            for attempt in range(3):
                day_rows, day_paths = [], []
                try:
                    # The observed API wraps page 101 to page 1; keep daily windows bounded.
                    for parameters, page in announcement_pages(day, day, category=''):
                        raw = store.write(source='cninfo', table='financial_disclosure_candidates',
                            parameters=parameters, frame=pl.from_dicts(page, infer_schema_length=None) if page else pl.DataFrame())
                        day_paths.append(str(raw.data_path))
                        day_rows.extend(page)
                    break
                except AnnouncementSetChanged:
                    if attempt == 2:
                        raise
                    time.sleep(2*(attempt+1))
            day_path.parent.mkdir(exist_ok=True)
            day_path.write_text(json.dumps({'day': str(day), 'raw_paths': day_paths,
                'source_rows': len(day_rows), 'captured_at': dt.datetime.now(dt.timezone.utc).isoformat()},
                indent=2), encoding='utf-8')
        paths.extend(day_paths)
        rows.extend(day_rows)
        day += dt.timedelta(days=1)
    result = {'start': str(start), 'end': str(end), 'source_rows': len(rows), 'raw_paths': paths,
              **report_requests(rows, start=start, end=end)}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='start', required=True, type=dt.date.fromisoformat)
    parser.add_argument('--to', dest='end', required=True, type=dt.date.fromisoformat)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(start=args.start, end=args.end, data_root=args.data_root, output=args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
