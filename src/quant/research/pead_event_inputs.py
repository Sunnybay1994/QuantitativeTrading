"""Freeze and inspect first-disclosure event inputs without running an account."""
import argparse
import bisect
import datetime as dt
import json
from pathlib import Path
import time
import tomllib
import uuid

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.research.residual_momentum_inputs import digest, write_json


def _write_progress(output, record):
    """A short Windows reader lock on telemetry must not discard a computed year."""
    temporary = output/'progress.json.tmp'
    write_json(temporary, record)
    for attempt in range(5):
        try:
            temporary.replace(output/'progress.json')
            return True
        except PermissionError:
            if attempt < 4:
                time.sleep(.02 * (attempt + 1))
    # Only progress is optional. Checkpoint/input/final-output failures still
    # propagate; this is never a receipt for a completed year or experiment.
    print(json.dumps({'warning': 'progress_reader_lock', **record}, default=str), flush=True)
    return False


def _code_files():
    package = Path(__file__).resolve().parents[1]
    names = ['research/pead_event_inputs.py', 'research/pead_event_signals.py',
             'research/monthly_sue_context_v2.py', 'research/monthly_sue.py',
             'research/residual_momentum_inputs.py', 'data/sue_input_quality.py',
             'data/financial_pit.py', 'data/financial_clean.py',
             'factors/earnings_surprise.py']
    return {name: package/name for name in names}


def _event_checkpoints(*, output, history, start, end, manifest, builder, progress):
    """Resume complete years only, under identical frozen inputs and code."""
    sources = _code_files()
    plan = {'input_manifest_sha256': digest(manifest), 'start': str(start), 'end': str(end),
            'code_sha256': {name: digest(path) for name, path in sources.items()},
            'polars_version': pl.__version__}
    plan_path = output/'event_plan.json'
    if plan_path.exists():
        if json.loads(plan_path.read_text(encoding='utf-8')) != plan:
            raise ValueError('Event checkpoint inputs/code changed; use a new output')
    else:
        snapshot = output/'code_snapshot'
        snapshot.mkdir(exist_ok=True)
        for name, path in sources.items():
            frozen = snapshot/name
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes(path.read_bytes())
        temporary = output/'event_plan.json.tmp'
        write_json(temporary, plan)
        temporary.replace(plan_path)
    checkpoint_root = output/'years'
    checkpoint_root.mkdir(exist_ok=True)
    completed = []
    for year in range(start.year, end.year + 1):
        checkpoint = checkpoint_root/str(year)
        if checkpoint.exists():
            receipt = json.loads((checkpoint/'summary.json').read_text(encoding='utf-8'))
            if (receipt['plan_sha256'] != digest(plan_path)
                    or receipt['sha256'] != digest(checkpoint/'events.parquet')):
                raise ValueError(f'Event checkpoint identity mismatch: {year}')
            frame = pl.read_parquet(checkpoint/'events.parquet')
            if frame.height != receipt['rows']:
                raise ValueError(f'Event checkpoint row count mismatch: {year}')
            progress({'year': year, 'stage': 'reused_completed_year', 'events': frame.height})
        else:
            # Full history is essential: filtering it to this year would turn
            # old-period revisions into apparently new first disclosures.
            frame = builder(history, start=max(start, dt.date(year, 1, 1)),
                end=min(end, dt.date(year, 12, 31)),
                progress=lambda record, year=year: progress({'year': year, **record}))
            if any(digest(path) != plan['code_sha256'][name] for name, path in sources.items()):
                raise ValueError('Event code changed while computing; retain incomplete scratch')
            scratch = checkpoint_root/f'{year}.{uuid.uuid4().hex}.partial'
            scratch.mkdir()
            frame.write_parquet(scratch/'events.parquet')
            write_json(scratch/'summary.json', {'year': year, 'rows': frame.height,
                'sha256': digest(scratch/'events.parquet'), 'plan_sha256': digest(plan_path),
                'completed_at': dt.datetime.now(dt.timezone.utc)})
            scratch.rename(checkpoint)
            progress({'year': year, 'stage': 'completed_year', 'events': frame.height})
        completed.append(frame)
    return pl.concat(completed).sort('announcement_date', 'symbol')


def freeze(*, config: Path, output: Path, data_root: Path):
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    refresh = Path(spec['data']['refresh_config'])
    settings = tomllib.loads(refresh.read_text(encoding='utf-8'))
    source = data_root/'clean/tushare_financials'/settings['financial_snapshot']/'income.parquet'
    before = digest(source)
    columns = ['symbol', 'ann_date', 'f_ann_date', 'available_date', 'end_date', 'report_type',
               'comp_type', 'update_flag', 'n_income', 'n_income_attr_p', 'source']
    all_income = pl.scan_parquet(source).filter(pl.col('symbol').str.contains(r'^(60|68|00|30)[0-9]{4}\.(SH|SZ)$'))
    frame = all_income.select(columns).collect()
    provenance = all_income.select('symbol', 'end_date', 'available_date',
        'source_observed_on', 'source_file').collect()
    if digest(source) != before:
        raise ValueError('Income snapshot changed during event input freeze')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    (output/'refresh.toml').write_bytes(refresh.read_bytes())
    frame.write_parquet(output/'income.parquet')
    provenance.write_parquet(output/'provenance.parquet')
    sessions = available_sessions(data_root, spec['data']['end'] + dt.timedelta(days=100))
    write_json(output/'sessions.json', sessions)
    result = {'frozen_at': dt.datetime.now(dt.timezone.utc), 'source_file': str(source),
        'source_sha256': before, 'rows': frame.height, 'symbols': frame['symbol'].n_unique(),
        'files': {p.name: digest(p) for p in output.iterdir() if p.is_file()},
        'provider_date_missing': frame['available_date'].null_count(),
        'collector_observed_date_missing': provenance['source_observed_on'].null_count(),
        'collector_dates': [str(d) for d in provenance['source_observed_on'].drop_nulls().unique().sort()],
        'original_vintage_proven': False, 'strategy_validity_evaluated': False}
    write_json(output/'manifest.json', result)
    return result


def run(*, output: Path):
    from quant.research.pead_event_signals import build_financial_events
    inputs = output/'inputs'
    manifest = json.loads((inputs/'manifest.json').read_text(encoding='utf-8'))
    for name, sha in manifest['files'].items():
        if digest(inputs/name) != sha:
            raise ValueError('Frozen event source changed: '+name)
    spec = tomllib.loads((inputs/'config.toml').read_text(encoding='utf-8'))
    if (output/'events.parquet').exists():
        raise ValueError('Financial events already computed; retain them or use a new output')
    reports = 0
    def progress(record):
        nonlocal reports
        reports += 1
        _write_progress(output, record)
        if reports == 1 or reports % 100 == 0 or 'stage' in record:
            print(json.dumps(record, default=str), flush=True)
    events = _event_checkpoints(output=output, history=pl.read_parquet(inputs/'income.parquet'),
        start=spec['data']['start'], end=spec['data']['end'], manifest=inputs/'manifest.json',
        builder=build_financial_events, progress=progress)
    sessions = [dt.date.fromisoformat(d) for d in json.loads((inputs/'sessions.json').read_text())]
    dates = events['announcement_date'].to_list()
    entries, exits = [], []
    for day in dates:
        index = bisect.bisect_right(sessions, day)
        entries.append(sessions[index] if index < len(sessions) else None)
        exit_index = index + spec['event']['holding_sessions_reference']
        exits.append(sessions[exit_index] if exit_index < len(sessions) else None)
    events = events.with_columns(pl.Series('earliest_execution_date', entries, dtype=pl.Date),
        pl.Series('reference_expiry_date', exits, dtype=pl.Date)).with_columns(
        (pl.col('reference_expiry_date') <= spec['data']['end']).fill_null(False).alias('full_horizon_known'))
    if events.filter(pl.col('earliest_execution_date') <= pl.col('announcement_date')).height:
        raise ValueError('An event was mapped to a noncausal entry session')
    events.write_parquet(output/'events.parquet')
    yearly = events.group_by(pl.col('announcement_date').dt.year().alias('year'), 'status').agg(
        pl.len().alias('events'), pl.col('symbol').n_unique().alias('symbols'),
        pl.col('full_horizon_known').sum().alias('events_with_reference_exit')).sort('year', 'status')
    yearly.write_csv(output/'yearly_event_coverage.csv')
    result = {'stage': 'financial_event_inputs_complete', 'auto_trade': False,
        'events': events.height, 'financially_valid_events': events.filter(pl.col('status') == 'VALID').height,
        'status_counts': events.group_by('status').len().sort('status').to_dicts(),
        'yearly_coverage': yearly.to_dicts(), 'financial_snapshot': manifest['source_file'],
        'input_manifest_sha256': digest(inputs/'manifest.json'),
        'events_sha256': digest(output/'events.parquet'),
        'event_plan_sha256': digest(output/'event_plan.json'),
        'code_sha256': json.loads((output/'event_plan.json').read_text())['code_sha256'],
        'completed_at': dt.datetime.now(dt.timezone.utc), 'account_replays': 0,
        'original_vintage_proven': False, 'cost_after_gain_established': False,
        'remaining': spec['remaining']['checks'],
        'limits': ['Financial validity does not imply market eligibility or executable signal',
                   spec['data']['financial_vintage'],
                   'Economic projection is n_income/n_income_attr_p, matching the existing SUE repository reader; not all vendor financial fields',
                   'Entry/expiry dates are reference dates only; blocked exits and orders not simulated']}
    write_json(output/'summary.json', result)
    report = ['# 财报公告事件：历史输入准备', '',
        '本阶段仅校验事件和盈利意外数据，没有收益、账户回放或准入结论。', '',
        '|年份|财务状态|事件数|股票数|参考退出日在截止日前|', '|---:|---|---:|---:|---:|']
    report.extend(f"|{r['year']}|{r['status']}|{r['events']}|{r['symbols']}|{r['events_with_reference_exit']}|"
                  for r in yearly.to_dicts())
    report += ['', '仍需：'+'；'.join(result['remaining']), '', '边界：'+'；'.join(result['limits'])]
    (output/'report.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/pead_event_inputs_20260930.toml'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=('freeze', 'events'), required=True)
    args = parser.parse_args()
    result = (freeze(config=args.config, output=args.output/'inputs', data_root=args.data_root)
              if args.stage == 'freeze' else run(output=args.output))
    print(json.dumps({k: v for k, v in result.items() if k not in ('files', 'yearly_coverage')}, default=str))


if __name__ == '__main__':
    main()
