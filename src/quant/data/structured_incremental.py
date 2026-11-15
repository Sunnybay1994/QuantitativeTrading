"""D2 bounded date-shard refresh, immutable raw pages and versioned publications."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import tomllib
import time

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore, publish_directory
from quant.data.realtime_store import atomic_json
from quant.data.structured_event_pages import pages
from quant.data.structured_native_rows import split_native_rows
from quant.data.structured_availability import due_dates, normalize_increment, sessions, SH


class RequestBudget(RuntimeError):
    pass


class RuntimeBudget(RequestBudget):
    """Stop at a safe page boundary without losing an in-flight raw response."""


class DayClient:
    """Reuse existing page recovery while querying exact *announcement* days."""
    def __init__(self, client, rule, budget, state, receipt, save, data_root, now, yield_check, total):
        self.client, self.rule, self.budget = client, rule, budget
        self.state, self.receipt, self.save = state, receipt, save
        self.data_root, self.now, self.yield_check = data_root, now, yield_check
        self.total = total

    def query_raw(self, table, **params):
        self.yield_check()
        if params['start_date'] != params['end_date']:
            raise ValueError('Incremental requests must be exact date shards')
        if self.budget['used'] >= self.budget['limit'] or self.total['used'] >= self.total['limit']:
            raise RequestBudget('Bounded request budget reached; resume this receipt')
        max_day = self.rule.get('max_requests_per_day')
        if max_day:
            day = self.now().astimezone(SH).date()
            # A request intent is durable before transport, including failed calls.
            intents = self.data_root/'raw/tushare'/table/'request_intents'/str(day)
            intents.mkdir(parents=True, exist_ok=True)
            import uuid
            external = 0
            prior_times = []
            for intent in intents.glob('*.json'):
                item = json.loads(intent.read_text(encoding='utf-8'))
                if item.get('at'):
                    prior_times.append(dt.datetime.fromisoformat(item['at']))
            metadata_files = [p for date in (day-dt.timedelta(days=1), day)
                              for p in (self.data_root/'raw/tushare'/table/f'date={date}').glob('*.json')]
            for metadata in metadata_files:
                record = json.loads(metadata.read_text(encoding='utf-8'))
                fetched = dt.datetime.fromisoformat(record['fetched_at'])
                if (fetched.astimezone(SH).date() == day and
                        record.get('parameters', {}).get('consumer') != self.receipt.get('source_id')):
                    external += 1
                    prior_times.append(fetched)
            if len(list(intents.glob('*.json')))+external >= max_day:
                raise RequestBudget('Trial daily request budget reached')
            if prior_times:
                earliest = max(prior_times)+dt.timedelta(seconds=self.rule.get('minimum_interval_seconds', 0))
                while self.now() < earliest:
                    self.yield_check()
                    time.sleep(min(5., (earliest-self.now()).total_seconds()))
            atomic_json(intents/(uuid.uuid4().hex+'.json'), {'at': self.now().isoformat(), 'api': table})
        self.budget['used'] += 1
        self.total['used'] += 1
        self.state['attempted_calls'] = self.state.get('attempted_calls', 0)+1
        self.save()
        day = params.pop('start_date')
        params.pop('end_date')
        return self.client.query_raw(table, **{self.rule['query_date_parameter']: day, **params})


def _known_ids(data_root, table, rule, first, last):
    ids = set()
    root = Path(data_root)/'clean'/table
    for metadata in root.glob('snapshot=*/summary.json'):
        files = list(metadata.parent.glob('year=*/data.parquet'))+list(metadata.parent.glob('data.parquet'))
        for p in files:
            schema = pl.scan_parquet(p).collect_schema()
            if rule['date_field'] not in schema or 'source_row_id' not in schema:
                continue
            date = pl.col(rule['date_field']).cast(pl.String).str.strip_chars().str.replace_all('-', '')
            rows = pl.scan_parquet(p).filter(date.is_between(
                pl.lit(first.strftime('%Y%m%d')), pl.lit(last.strftime('%Y%m%d'))))
            ids.update(rows.select('source_row_id').collect()['source_row_id'])
    return ids


def _yield_check(data_root):
    from quant.core.capital_window import reason, CapitalPathPause
    why = reason(data_root=data_root)
    if why:
        raise CapitalPathPause(why)


def request_dates(data_root, table, rule, spec, as_of, clock, calendar):
    overlap = rule.get('lookback_calendar_days', spec['lookback_calendar_days'])
    dates = due_dates(as_of, clock, rule, calendar, overlap)
    checked = []
    for p in (Path(data_root)/'clean'/table).glob('snapshot=d2_*/summary.json'):
        record = json.loads(p.read_text(encoding='utf-8'))
        if record.get('status') in {'captured', 'checked_empty'} and record.get('checked_through'):
            checked.append(dt.date.fromisoformat(record['checked_through']))
    if not dates or not checked or max(checked) >= dates[0]-dt.timedelta(days=1):
        return dates
    gap = (dates[-1]-max(checked)).days
    if gap > spec.get('max_catchup_calendar_days', 31):
        raise RequestBudget('Missed interval exceeds bounded catchup; require explicit date-window recovery')
    extra = due_dates(as_of, clock, rule, calendar, gap+overlap)
    return sorted(set(dates) | {day for day in extra if day > max(checked)})


def _run(*, config=Path('configs/data/structured_sources.toml'), data_root=Path('data'),
        output, as_of=None, connector=None, resume=False, tables=None, now=None, yield_check=None,
        seed_receipt=None, monotonic=None):
    config, data_root, output = Path(config), Path(data_root), Path(output)
    clock = now or (lambda: dt.datetime.now(dt.timezone.utc))
    as_of = as_of or clock().astimezone(SH).date()
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    limit = spec.get('max_run_seconds', 900)
    if type(limit) not in (int, float) or not math.isfinite(limit) or limit <= 0:
        raise ValueError('max_run_seconds must be finite and positive')
    timer = monotonic or time.monotonic
    started = timer()
    if spec['auto_trade'] is not False:
        raise ValueError('auto_trade must remain false')
    selected = list(tables or spec['tables'])
    if not selected or not set(selected) <= set(spec['tables']):
        raise ValueError('Unknown or empty structured table selection')
    if output.exists() and not resume:
        raise FileExistsError('Explicit resume required')
    output.mkdir(parents=True, exist_ok=True)
    path = output/'summary.json'
    receipt = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'tables': {}}
    digest = hashlib.sha256(config.read_bytes()).hexdigest()
    frozen = {'config_sha256': digest, 'as_of': str(as_of), 'selected_tables': selected,
              'source_id': spec['id']}
    if any(key in receipt and receipt[key] != value for key, value in frozen.items()):
        raise ValueError('Changed immutable incremental request')
    receipt.update(frozen, status='running', auto_trade=False, observed_at=clock().isoformat(),
                   max_run_seconds=limit, time_budget_exhausted=False,
                   runtime_limit_policy='cooperative_before_requests_pages_publication; in-flight raw retained')
    if seed_receipt and not receipt['tables']:
        seed = json.loads(Path(seed_receipt).read_text(encoding='utf-8'))
        if seed['as_of'] != str(as_of):
            raise ValueError('Raw page reuse must retain the original as_of')
        receipt['seed_receipt'] = str(seed_receipt)
        receipt['seed_sha256'] = hashlib.sha256(Path(seed_receipt).read_bytes()).hexdigest()
        for name in selected:
            old = seed['tables'].get(name, {})
            receipt['tables'][name] = {'requests': old.get('requests', {}), 'attempted_calls': 0}
    if not (output/'config.toml').exists():
        (output/'config.toml').write_bytes(config.read_bytes())
    def save():
        receipt['elapsed_seconds'] = max(0., timer()-started)
        atomic_json(path, receipt)

    def finish_budget(exc):
        receipt.update(status='partial', reason=str(exc), time_budget_exhausted=True,
                       finished_at=clock().isoformat())
        save()
        return receipt

    save()
    calendar = sessions(data_root)
    cooperate = yield_check or (lambda: _yield_check(data_root))

    def check():
        cooperate()
        if timer()-started >= limit:
            raise RuntimeBudget('Runtime budget exhausted; resume saved raw in this receipt')

    client = connector or TushareConnector()
    store = RawStore(data_root/'raw')
    total = {'used': 0, 'limit': spec['max_requests_per_run']}
    for table in selected:
        try:
            check()
        except RuntimeBudget as exc:
            return finish_budget(exc)
        except Exception as exc:
            from quant.core.capital_window import CapitalPathPause
            if not isinstance(exc, CapitalPathPause):
                raise
            receipt.update(status='deferred', reason=str(exc))
            save()
            return receipt
        if receipt['tables'].get(table, {}).get('published'):
            continue
        rule = spec['tables'][table]
        state = receipt['tables'].setdefault(table, {'requests': {}, 'attempted_calls': 0})
        state.update(status='running', scope=rule['scope'], permission=rule.get('permission', 'standard'))
        try:
            dates = request_dates(data_root, table, rule, spec, as_of, clock(), calendar)
        except RequestBudget as exc:
            state.update(status='partial_budget', error=str(exc), error_type=type(exc).__name__)
            save()
            continue
        state.update(requested_dates=list(map(str, dates)), updated_at=clock().isoformat())
        save()
        budget = {'used': 0, 'limit': min(spec['max_requests_per_run'], rule.get('max_requests_per_run', 300))}
        wrapped = DayClient(client, rule, budget, state, receipt, save, data_root, clock, check, total)
        frames, quarantined, empty = [], 0, 0
        try:
            for day in dates:
                for symbol in rule.get('symbols', [None]):
                    found = 0
                    for frame, record in pages(table=rule['api'], rule=rule, spec=spec, symbol=symbol,
                            first=day, last=day, receipt=state, client=wrapped, store=store, save=save):
                        check()
                        frame, rejected = split_native_rows(table, frame)
                        quarantined += rejected.height
                        if not frame.is_empty():
                            frames.append(normalize_increment(frame, table=table, rule=rule,
                                observed_at=record['observed_at'], raw_path=record['raw_path'], calendar=calendar))
                            found += frame.height
                    if not found:
                        empty += 1
            if not dates:
                state.update(status='not_due', rows=0, new_rows=0)
                save()
                continue
            full = pl.concat(frames, how='diagonal_relaxed').unique('source_row_id', keep='first') if frames else pl.DataFrame()
            known = _known_ids(data_root, table, rule, dates[0], dates[-1]) if not full.is_empty() else set()
            new_rows = sum(row not in known for row in full['source_row_id']) if not full.is_empty() else 0
            status = ('permission_limited' if rule.get('permission') == 'limited_trial' else
                      'missing_daily_rows' if rule['cadence'] == 'daily' and empty else
                      'checked_empty' if full.is_empty() else 'captured')
            staging = output/f'publish_{table}'
            destination = data_root/'clean'/table/f'snapshot=d2_{output.name}'
            staging.mkdir(exist_ok=True)
            if not full.is_empty():
                full.write_parquet(staging/'data.parquet')
            summary = {'status': status, 'rows': full.height, 'new_rows': new_rows,
                'latest_date': str(full['source_announcement_date'].max()) if not full.is_empty() else None,
                'checked_through': str(dates[-1]), 'checked_at': clock().isoformat(),
                'dates': list(map(str, dates)), 'scope': rule['scope'], 'units': rule['units'],
                'revision_keys': rule['revision_keys'],
                'revision_identity': rule.get('revision_identity', 'configured_native_entity_with_content_versions'),
                'permission': rule.get('permission', 'standard'), 'quarantined_rows': quarantined,
                'source_receipt': str(path), 'historical_vintage_verified': False, 'auto_trade': False}
            atomic_json(staging/'summary.json', summary)
            check()
            destination.parent.mkdir(parents=True, exist_ok=True)
            publish_directory(staging, destination, staging_root=output, destination_root=data_root/'clean'/table)
            state.update(summary, published=str(destination))
        except Exception as exc:
            from quant.core.capital_window import CapitalPathPause
            text = str(exc)
            source_status = ('rate_limited' if '频率超限' in text or '每分钟' in text else
                             'permission_denied' if '权限' in text or '积分' in text else 'error')
            state.update(status='deferred' if isinstance(exc, CapitalPathPause) else
                         'partial_budget' if isinstance(exc, RequestBudget) else 'error',
                         error_type=type(exc).__name__, error=str(exc), updated_at=clock().isoformat())
            if not isinstance(exc, (CapitalPathPause, RequestBudget)):
                state['status'] = source_status
            if isinstance(exc, RuntimeBudget):
                return finish_budget(exc)
            if isinstance(exc, CapitalPathPause):
                receipt.update(status='deferred', reason=str(exc))
                save()
                return receipt
        save()
    good = {'captured', 'checked_empty', 'not_due'}
    receipt['status'] = 'checked' if all(s['status'] in good for s in receipt['tables'].values()) else 'partial'
    receipt['finished_at'] = clock().isoformat()
    save()
    return receipt


def run(*, data_root=Path('data'), **kwargs):
    from quant.data.realtime import single_writer
    with single_writer(Path(data_root)/'clean/structured_incremental/writer.lock'):
        return _run(data_root=data_root, **kwargs)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/data/structured_sources.toml'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--as-of', type=dt.date.fromisoformat)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--with-futures', action='store_true', help='Also capture IF/IC/IM monthly-panel quotes')
    args = parser.parse_args()
    operation = run
    if args.with_futures:
        from quant.data.structured_daily import run as operation
    result = operation(config=args.config, data_root=args.data_root, output=args.output,
                 as_of=args.as_of, resume=args.resume)
    print(json.dumps(result, default=str))
    if result['status'] != 'checked':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
