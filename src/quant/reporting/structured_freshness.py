"""Read-only D2 freshness: event age, checked coverage and permission are distinct."""
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.structured_availability import due_dates, sessions


def build_status(*, data_root=Path('data'), config=Path('configs/data/structured_sources.toml'),
                 as_of=None, now=None, receipt_root=None):
    clock = now or dt.datetime.now(dt.timezone.utc)
    as_of = as_of or clock.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    root = Path(data_root)
    spec = tomllib.loads(Path(config).read_text(encoding='utf-8'))
    calendar = sessions(root)
    receipt_root = Path(receipt_root) if receipt_root else root.resolve().parent/'artifacts/data/structured_incremental'
    attempts = []
    for path in receipt_root.glob('*/summary.json'):
        item = json.loads(path.read_text(encoding='utf-8'))
        stamp = item.get('finished_at', item.get('observed_at'))
        if stamp and dt.datetime.fromisoformat(stamp) <= clock:
            attempts.append((stamp, item.get('tables', {})))
    rows = []
    for table, rule in spec['tables'].items():
        snapshots = sorted((root/'clean'/table).glob('snapshot=*/summary.json'))
        latest, total, today_ids = None, 0, set()
        records = []
        for p in snapshots:
            record = json.loads(p.read_text(encoding='utf-8'))
            records.append(record)
            files = list(p.parent.glob('year=*/data.parquet'))+list(p.parent.glob('data.parquet'))
            for file in files:
                schema = pl.scan_parquet(file).collect_schema()
                if rule['date_field'] not in schema:
                    continue
                day = pl.col(rule['date_field']).cast(pl.String).str.strip_chars().str.replace_all('-', '').str.to_date('%Y%m%d')
                scan = pl.scan_parquet(file).filter((day <= as_of) & (pl.col('available_at') <= clock))
                stats = scan.select(
                    day.max().alias('latest'), (day == as_of).sum().alias('today'), pl.len().alias('rows')).collect().row(0, named=True)
                latest = max([v for v in (latest, stats['latest']) if v is not None], default=None)
                today_ids.update(scan.filter(day == as_of).select('source_row_id').collect()['source_row_id'])
                total += stats['rows']
        runs = sorted((r for r in records if r.get('checked_at') and
                       dt.datetime.fromisoformat(r['checked_at']) <= clock), key=lambda r: r['checked_at'])
        checked = runs[-1] if runs else {}
        due = due_dates(as_of, clock, rule, calendar, 1)
        expected = due[-1] if due else None
        covered = checked.get('checked_through')
        lag = sum(1 for d in calendar if covered < str(d) <= str(expected)) if covered and expected else None
        status = ('permission_limited' if rule.get('permission') == 'limited_trial' else
                  'not_captured' if not snapshots else
                  checked.get('status', 'historical_only'))
        if status in {'captured', 'checked_empty'} and covered and expected and covered < str(expected):
            status = 'stale_check'
        recent = sorted((stamp, tables[table]) for stamp, tables in attempts if table in tables)
        attempt_at, attempt = recent[-1] if recent else (None, {})
        if (attempt.get('status') in {'error', 'partial_budget', 'deferred', 'rate_limited', 'permission_denied'} and
                (not checked.get('checked_at') or attempt_at >= checked['checked_at'])):
            status = attempt['status']
        actual_checked_days = set()
        local = dt.timezone(dt.timedelta(hours=8))
        for stamp, states in attempts:
            item = states.get(table, {})
            if item.get('status') not in {'captured', 'checked_empty'}:
                continue
            run_day = dt.datetime.fromisoformat(stamp).astimezone(local).date()
            observed_days = {dt.datetime.fromisoformat(request['observed_at']).astimezone(local).date()
                             for request in item.get('requests', {}).values()}
            if run_day in observed_days:
                actual_checked_days.add(run_day)
        trailing = list(reversed([day for day in calendar if day <= as_of]))
        consecutive = 0
        for day in trailing:
            if day not in actual_checked_days:
                break
            consecutive += 1
        rows.append({'table': table, 'status': status, 'latest_date': str(latest) if latest else None,
            'rows_on_as_of': len(today_ids), 'observed_rows_in_versions': total,
            'event_age_calendar_days': (as_of-latest).days if latest else None,
            'expected_through': str(expected) if expected else None,
            'checked_through': covered, 'checked_at': checked.get('checked_at'),
            'last_attempt_status': attempt.get('status'), 'last_attempt_at': attempt_at,
            'consecutive_real_checked_trading_days': consecutive,
            'check_lag_sessions': lag, 'scope': rule['scope'],
            'availability_rule': rule['availability'], 'historical_vintage_verified': False})
    lagged = [r for r in rows if r['check_lag_sessions'] is not None]
    return {'as_of': str(as_of), 'observed_at': clock.isoformat(), 'tables': rows,
        'most_lagged_table': max(lagged, key=lambda r: r['check_lag_sessions'])['table'] if lagged else None,
        'five_real_trading_days_verified': all(r['consecutive_real_checked_trading_days'] >= 5 for r in rows),
        'auto_trade': False}


def render_lines(status):
    return [f"{r['table']}: {r['status']}; latest={r['latest_date']}; today_rows={r['rows_on_as_of']}; "
            f"checked={r['checked_through']}; lag_sessions={r['check_lag_sessions']}; {r['scope']}"
            for r in status['tables']]
