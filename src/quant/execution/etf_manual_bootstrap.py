"""Freeze the manual ETF study and initialize cash; never infer or submit fills."""
import argparse
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quant.execution.manual_session_service import instance_lock


def save_once(path, payload):
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != payload:
            raise ValueError(f'Preserve existing evidence: {path}')
        return
    with path.open('x', encoding='utf-8') as stream:
        stream.write(text)


def initialize(config, output, calendar):
    raw = config.read_bytes()
    cfg = tomllib.loads(raw.decode('utf-8'))
    if (cfg['auto_trade'] is not False or cfg['capital'] != 100000
            or cfg['classification'] != 'RESEARCH_ONLY'
            or cfg['cost_multipliers'] != [0.5, 1.0, 2.0]
            or (cfg['main_delay_seconds'], cfg['shadow_delay_seconds']) != (120, 60)):
        raise ValueError('Invalid frozen research controls')
    days = sorted(set(calendar.filter(pl.col('is_open'))['date'].to_list()))
    signal, execution = cfg['first_signal_date'], cfg['first_execution_date']
    following = next(day for day in days if day > signal)
    if signal not in days or following != execution or signal.month == execution.month:
        raise ValueError('Require actual month end and immediate next exchange session')
    if not cfg['initialization_date'] < signal:
        raise ValueError('Freeze before the first signal')
    output.mkdir(parents=True, exist_ok=True)
    with instance_lock(output / 'bootstrap.lock'):
        frozen = output / 'config.toml'
        if frozen.exists() and frozen.read_bytes() != raw:
            raise ValueError('Frozen configuration changed')
        if not frozen.exists():
            with frozen.open('xb') as stream:
                stream.write(raw)
        for delay in (120, 60):
            for cost in cfg['cost_multipliers']:
                folder = output / f'delay_{delay}/cost_{cost:g}'
                folder.mkdir(parents=True, exist_ok=True)
                save_once(folder / 'opening.json', dict(
                    date=str(cfg['initialization_date']), cash=100000.0, holdings={},
                    receivables=[], restricted_shares=[], imported_events={},
                    last_event_timestamp=None,
                    valuation=dict(date=str(cfg['initialization_date']), equity=100000.0,
                                   unit_nav=1.0),
                    auto_trade=False, classification='RESEARCH_ONLY',
                    cost_multiplier=cost, delay_seconds=delay))
        result = dict(config_sha256=hashlib.sha256(raw).hexdigest(),
                      initialized_cash_per_scenario=100000,
                      first_signal=str(signal), first_execution=str(execution),
                      main_delay_seconds=120, shadow_delay_seconds=60,
                      fills_enabled=False, fills=0, auto_trade=False,
                      classification='RESEARCH_ONLY',
                      outstanding=['post-submission quote capture and execution adapter',
                                   'partial-fill fee and sequential cash validation',
                                   'daily automation and end-to-end execution acceptance'])
        save_once(output / 'bootstrap.json', result)
    return result


def coverage(data_root, targets, output, symbols):
    dates = sorted(set(pl.read_parquet(targets)['execution_date'].to_list()))
    rows, hashes = [], {'targets': hashlib.sha256(targets.read_bytes()).hexdigest()}
    for symbol in symbols:
        path = data_root / f'clean/bar_intraday/freq=1m/source=tdx/symbol={symbol}/data.parquet'
        if not path.exists():
            frame = None
        else:
            hashes[symbol] = hashlib.sha256(path.read_bytes()).hexdigest()
            frame = pl.read_parquet(path)
        for date in dates:
            for delay in (60, 120):
                at = dt.datetime.combine(date, dt.time(9, 30), ZoneInfo('Asia/Shanghai'))
                at += dt.timedelta(seconds=delay)
                count = 0 if frame is None else frame.filter(pl.col('bar_start') == at).height
                rows.append(dict(symbol=symbol, date=str(date), delay_seconds=delay,
                                 rows=count, unique_bar=count == 1))
    output.mkdir(parents=True, exist_ok=False)
    pl.DataFrame(rows).write_csv(output / 'coverage.csv')
    save_once(output / 'sources.json', hashes)
    save_once(output / 'summary.json', dict(required_dates=len(dates),
              matched_rows=sum(r['unique_bar'] for r in rows), required_rows=len(rows),
              limitation='Presence only; not executable quote, depth or complete-history proof.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/b16_manual_forward_v1.toml'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/paper/b16_manual_v1'))
    parser.add_argument('--coverage-output', type=Path)
    args = parser.parse_args()
    calendar = pl.read_parquet('data/clean/trade_calendar/market=SH/data.parquet')
    result = initialize(args.config, args.output, calendar)
    if args.coverage_output:
        coverage(Path('data'), Path('artifacts/research/etf_allocation_attribution_20260922_03/dynamic_1/targets.parquet'),
                 args.coverage_output, tomllib.loads(args.config.read_text(encoding='utf-8'))['symbols'])
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
