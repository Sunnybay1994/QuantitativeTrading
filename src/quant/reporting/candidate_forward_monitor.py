"""Score immutable candidate captures only after their monthly labels mature."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

import polars as pl

from quant.data.model_forecast_labels import monthly_schedule
from quant.data.refresh import SHANGHAI
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.research.candidate_forward import capture_window
from quant.research.candidate_freeze import load_candidate_freeze
from quant.research.factor_battery_evaluation import score_factor_sections
from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date
from quant.research.factor_labels import build_next_rebalance_open_labels

KEYS = ['symbol', 'trade_date']
REQUIRED_FILES = {'inputs.parquet', 'values.parquet', 'universe.parquet', 'refresh_config.toml',
                  'battery_config.toml', 'refresh.json', 'candidate_freeze.json', 'terminal_expressions.json'}
COPIED_FILES = REQUIRED_FILES - {'inputs.parquet', 'terminal_expressions.json'}
LABEL_SCHEMA = {'symbol': pl.String, 'trade_date': pl.Date, 'execution_date_rebalance': pl.Date,
                'exit_date_rebalance': pl.Date, 'label_rebalance': pl.Float64}
IC_SCHEMA = {'factor': pl.String, 'variant': pl.String, 'trade_date': pl.Date,
             'execution_date_rebalance': pl.Date, 'exit_date_rebalance': pl.Date,
             'signal_count': pl.UInt32, 'paired_count': pl.UInt32, 'paired_coverage': pl.Float64,
             'rank_ic': pl.Float64, 'status': pl.String, 'capture': pl.String}
ERRORS = (OSError, ValueError, TypeError, KeyError, pl.exceptions.PolarsError)


def _now() -> dt.datetime:
    return dt.datetime.now(SHANGHAI)


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def _stamp(value: str) -> dt.datetime:
    stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Capture timestamp must include its timezone')
    return stamp


def _discover(roots: list[Path], current: Path | None) -> list[Path]:
    if not roots or any(not Path(root).is_dir() for root in roots):
        raise ValueError('Require nonempty existing capture roots; a missing folder is not pending evidence')
    paths = set()
    for root in roots:
        paths.update(path.resolve() for path in Path(root).glob('**/candidate_forward/summary.json'))
        if Path(root).name == 'candidate_forward' and (Path(root)/'summary.json').is_file():
            paths.add((Path(root)/'summary.json').resolve())
    if current is not None:
        path = Path(current) if Path(current).name == 'summary.json' else Path(current)/'summary.json'
        if path.is_file():
            paths.add(path.resolve())
    return sorted(paths)


def _check_keys(frame: pl.DataFrame, day: dt.date) -> None:
    if (not set(KEYS) <= set(frame.columns) or frame.schema['trade_date'] != pl.Date
            or frame.schema['symbol'] != pl.String or frame.is_empty()
            or frame.select(KEYS).null_count().sum_horizontal().item()
            or frame.filter(pl.col('trade_date') != day).height
            or frame.select(KEYS).is_duplicated().any()):
        raise ValueError('Capture requires unique nonempty same-day symbol/date keys')


def _load_capture(path: Path, receipt: dict, known_through: dt.date) -> dict | None:
    before = _digest(path)
    record = _json(path)
    if record.get('candidate_set_sha256') != receipt['candidate_set_sha256']:
        return None
    if record.get('status') != 'captured':
        return None
    if record.get('independent_forward_capture') is not True or record.get('auto_trade') is not False:
        raise ValueError('Capture is not an independent non-trading record')
    day = dt.date.fromisoformat(record['as_of'])
    if day > known_through:
        return None
    files = record.get('files', {})
    if not isinstance(files, dict) or not REQUIRED_FILES <= set(files):
        raise ValueError('Capture is missing its complete file hash manifest')
    for name, checksum in files.items():
        if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
            raise ValueError('Capture manifest must contain local file names')
        source = path.parent/name
        if not source.resolve().is_relative_to(path.parent.resolve()) or _digest(source) != checksum:
            raise ValueError(f'Capture file hash differs: {name}')
    if _json(path.parent/'candidate_freeze.json') != receipt:
        raise ValueError('Capture receipt differs from the current frozen candidate set')
    if record.get('candidate_count') != len(receipt['candidates']):
        raise ValueError('Capture candidate count differs from frozen candidates')
    captured = _stamp(record['captured_at_utc'])
    recorded = _stamp(record['recorded_at_utc'])
    if not _stamp(receipt['frozen_at_utc']) <= recorded <= captured:
        raise ValueError('Capture timestamps precede the freeze or run backwards')
    if captured > _now():
        raise ValueError('Capture timestamp is in the future')
    refresh = _json(path.parent/'refresh.json')
    if (refresh.get('latest_session') != str(day) or refresh.get('intraday_errors', ['missing'])
            or refresh.get('input_quality', {}).get('errors', ['missing'])):
        raise ValueError('Capture lacks successful same-session input refresh evidence')
    values = pl.read_parquet(path.parent/'values.parquet')
    universe = pl.read_parquet(path.parent/'universe.parquet')
    for frame in (values, universe):
        _check_keys(frame, day)
    factors = {row['id'] for row in receipt['candidates']}
    if set(values.columns) != set(KEYS) | factors:
        raise ValueError('Captured value columns differ from frozen candidates')
    if (not {'eligible', 'total_market_value', 'industry_l1'} <= set(universe.columns)
            or universe.schema['eligible'] != pl.Boolean or universe['eligible'].null_count()
            or not values.select(KEYS).sort(KEYS).equals(universe.select(KEYS).sort(KEYS))):
        raise ValueError('Captured universe and values must retain identical observed keys')
    settings = tomllib.loads((path.parent/'battery_config.toml').read_text(encoding='utf-8'))
    if (set(settings['variants']) != {'raw', 'size_industry_neutral'} or len(settings['variants']) != 2
            or type(settings['minimum_symbols']) is not int or settings['minimum_symbols'] < 2
            or not 0 < settings['minimum_paired_coverage'] <= 1
            or type(settings['monthly_newey_west_lag']) is not int or settings['monthly_newey_west_lag'] < 0):
        raise ValueError('Invalid saved battery scoring settings')
    if settings.get('monthly_label') != 'next_open_to_next_monthly_rebalance_open':
        raise ValueError('Unsupported saved monthly label convention')
    if settings.get('portfolio', {}).get('rebalance', 'month_end_signal_next_open_execution') != 'month_end_signal_next_open_execution':
        raise ValueError('Unsupported saved portfolio rebalance convention')
    if _digest(path) != before or any(_digest(path.parent/name) != value for name, value in files.items()):
        raise ValueError('Capture changed while being read')
    return {'path': path, 'record': record, 'day': day, 'captured': captured,
            'values': values, 'universe': universe, 'settings': settings,
            'source_hashes': {'summary.json': before, **files}}


def _measurement(settings: dict) -> dict:
    return {name: settings[name] for name in ('variants', 'preprocessing', 'universe', 'monthly_label',
            'minimum_symbols', 'minimum_paired_coverage', 'monthly_newey_west_lag')}


def _calendar(data_root: Path, start: dt.date, known_through: dt.date) -> tuple[pl.DataFrame, tuple[dt.date, ...], dict]:
    paths = [data_root/f'clean/trade_calendar/market={market}/data.parquet' for market in ('SH', 'SZ')]
    hashes = {str(path): _digest(path) for path in paths}
    calendar = read_stock_paper_calendar(data_root).filter(
        pl.col('date').is_between(start, known_through + dt.timedelta(days=100)))
    if not {'date', 'market', 'is_open'} <= set(calendar.columns):
        raise ValueError('Missing calendar fields')
    if set(calendar['market']) != {'SH', 'SZ'} or calendar.select('market', 'date').is_duplicated().any():
        raise ValueError('Require unique SH/SZ calendar rows')
    through = min(calendar.filter(pl.col('market') == market)['date'].max() for market in ('SH', 'SZ'))
    calendar = calendar.filter(pl.col('date') <= through)
    expected = (through - start).days + 1
    for market in ('SH', 'SZ'):
        part = calendar.filter(pl.col('market') == market)
        if part.height != expected or part['date'].null_count() or part['is_open'].null_count():
            raise ValueError('Calendar has a missing day; no schedule may bridge that gap')
    if calendar.group_by('date').agg(pl.col('is_open').n_unique().alias('states')).filter(pl.col('states') != 1).height:
        raise ValueError('SH/SZ exchange calendars disagree')
    if any(_digest(Path(path)) != checksum for path, checksum in hashes.items()):
        raise ValueError('Calendar changed while being read')
    sessions = tuple(calendar.filter(pl.col('is_open'))['date'].unique().sort().to_list())
    return calendar, sessions, hashes


def _select(captures: list[dict], sessions: tuple[dt.date, ...], receipt: dict,
            errors: list[dict]) -> tuple[list[dict], list[dict]]:
    by_day: dict[dt.date, list[dict]] = {}
    for capture in captures:
        try:
            window = capture_window(receipt=receipt, as_of=capture['day'], sessions=sessions, now=capture['captured'])
            if (window['status'] != 'ready' or capture['record'].get('entry_session') != window['entry_session']
                    or _stamp(capture['record']['capture_deadline']) != _stamp(window['capture_deadline'])):
                raise ValueError('Capture was not completed in the verified next-open window')
            by_day.setdefault(capture['day'], []).append(capture)
        except ERRORS as exc:
            errors.append({'source': str(capture['path']), 'error': f'{type(exc).__name__}: {exc}'})
    chosen, duplicates = [], []
    for day, items in sorted(by_day.items()):
        ordered = sorted(items, key=lambda item: (item['captured'], str(item['path'])))
        first = ordered[0]
        tied = [item for item in ordered if item['captured'] == first['captured']]
        if any(not item['values'].select(sorted(item['values'].columns)).sort(KEYS).equals(
                       first['values'].select(sorted(first['values'].columns)).sort(KEYS))
               or not item['universe'].select(sorted(item['universe'].columns)).sort(KEYS).equals(
                       first['universe'].select(sorted(first['universe'].columns)).sort(KEYS))
               or item['settings'] != first['settings'] for item in tied[1:]):
            errors.append({'source': [str(item['path']) for item in tied],
                           'error': f'Conflicting complete captures at the earliest identical timestamp: {day}'})
            continue
        chosen.append(first)
        duplicates.extend({'source': str(item['path']), 'selected': str(first['path']),
                           'reason': 'Earliest complete capture per signal date; no value-based candidate deduplication'}
                          for item in ordered[1:])
    consistent = []
    baseline = None
    for capture in chosen:
        try:
            measurement = _measurement(capture['settings'])
            if baseline is None:
                baseline = measurement
            if measurement != baseline:
                raise ValueError('Saved measurement differs from earliest complete capture')
            consistent.append(capture)
        except ERRORS as exc:
            errors.append({'source': str(capture['path']), 'error': f'{type(exc).__name__}: {exc}'})
    return consistent, duplicates


def _bar_sources(data_root: Path, config: Path, dates: tuple[dt.date, dt.date]) -> list[Path]:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    paths = set()
    for year in {day.year for day in dates}:
        paths.update((data_root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']/
                      f'bar_1d/asset=stock/year={year}').glob('*.parquet'))
    for day in dates:
        folder = data_root/f'clean/tushare_incremental/date={day}'
        if all((folder/f'{name}.parquet').is_file() for name in ('bar_1d', 'daily_basic', 'adjust_factor')):
            paths.add(folder/'bar_1d.parquet')
    return sorted(paths)


def _labels(capture: dict, sessions: tuple[dt.date, ...], schedule: tuple[dt.date, dt.date],
            known_through: dt.date, data_root: Path) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    entry, exit_day = schedule
    if exit_day > known_through:
        raise ValueError('Cannot read future monthly label prices')
    config = capture['path'].parent/'refresh_config.toml'
    if _digest(config) != capture['source_hashes']['refresh_config.toml']:
        raise ValueError('Saved label input configuration changed')
    paths = _bar_sources(data_root, config, schedule)
    hashes = {str(path): _digest(path) for path in paths}
    cohort = capture['universe'].filter(pl.col('eligible')).select(KEYS)
    parts = []
    for day in schedule:
        frame = read_stock_data(data_root=data_root, config=config, table='bar_1d', start=day, end=day)
        if frame.is_empty():
            raise ValueError(f'Entire execution-session price input missing: {day}')
        parts.append(frame.filter(pl.col('symbol').is_in(cohort['symbol'].to_list())))
    bars = pl.concat(parts)
    if bars.filter(~pl.col('trade_date').is_in(schedule) | (pl.col('trade_date') > known_through)).height:
        raise ValueError('Label reader returned prices outside the exact observable execution dates')
    if (_digest(config) != capture['source_hashes']['refresh_config.toml']
            or any(_digest(Path(path)) != checksum for path, checksum in hashes.items())):
        raise ValueError('Label price inputs changed while being read')
    if cohort.is_empty():
        return pl.DataFrame(schema=LABEL_SCHEMA), bars, hashes
    next_signal = sessions[sessions.index(exit_day)-1]
    keys = pl.concat([cohort, cohort.with_columns(pl.lit(next_signal).alias('trade_date'))])
    labels = build_next_rebalance_open_labels(factor_values=keys, bars=bars, sessions=sessions)
    return labels.filter(pl.col('trade_date') == capture['day']).select(list(LABEL_SCHEMA)), bars, hashes


def _save_capture(capture: dict, output: Path) -> Path:
    folder = output/'calculation_inputs'/str(capture['day'])
    folder.mkdir(parents=True)
    for name in sorted(COPIED_FILES | {'summary.json'}):
        target = folder/name
        shutil.copyfile(capture['path'].parent/name, target)
        if _digest(target) != capture['source_hashes'][name]:
            raise ValueError('Capture changed while preserving calculation inputs')
    return folder


def _score(capture: dict, labels: pl.DataFrame, receipt: dict,
           schedule: tuple[dt.date, dt.date]) -> tuple[list[dict], pl.DataFrame]:
    rows, saved_scores = [], []
    for candidate in receipt['candidates']:
        values = capture['values'].select(*KEYS, pl.col(candidate['id']).alias('value'))
        scores = score_factor_sections(universe=capture['universe'], values=values,
            direction=candidate['direction'], settings=capture['settings'])
        saved_scores.append(scores.with_columns(pl.lit(candidate['id']).alias('factor')))
        joined = scores.join(labels.select(*KEYS, 'label_rebalance'), on=KEYS, how='left', validate='1:1')
        for variant in capture['settings']['variants']:
            stats = rank_ic_by_date(joined, score=variant, label='label_rebalance',
                minimum_symbols=capture['settings']['minimum_symbols'],
                minimum_paired_coverage=capture['settings']['minimum_paired_coverage'])
            stat = stats.row(0, named=True) if stats.height else {
                'trade_date': capture['day'], 'signal_count': 0, 'paired_count': 0,
                'paired_coverage': 0., 'rank_ic': None}
            rows.append({'factor': candidate['id'], 'variant': variant, **stat,
                         'execution_date_rebalance': schedule[0], 'exit_date_rebalance': schedule[1],
                         'status': 'scored' if stat['rank_ic'] is not None else 'insufficient_pairs',
                         'capture': str(capture['path'])})
    return rows, pl.concat(saved_scores)


def run(*, search_output: Path, receipt_path: Path, roots: list[Path], known_through: dt.date,
        output: Path, data_root: Path, current: Path | None = None) -> dict:
    """Select the earliest complete capture per date, then score matured month ends.

    Later same-day captures never replace earlier values based on their results.
    Equal earliest timestamps with conflicting values/controls/settings reject that
    date. Individual corrupt inputs are reported without interrupting old accounts.
    Current factor panels are never read, and no capture is reconstructed here.
    """
    output.mkdir(parents=True, exist_ok=False)
    errors: list[dict] = []
    result = {'known_through': str(known_through), 'status': 'pending', 'auto_trade': False,
              'requires_review': False, 'candidate_count': 0, 'scored_months': 0,
              'matured_months': 0, 'valid_ic_observations': 0, 'captures': [], 'duplicates': [],
              'series': [], 'errors': errors, 'conclusion': 'RESEARCH_ONLY',
              'admission_changed': False, 'cost_adjusted_strategy_returns_computed': False,
              'policy': 'Earliest complete capture per signal date; monthly IC only; no historical signal reconstruction',
              'output': str(output), 'source_hashes': {}}
    rows, label_frames = [], []
    try:
        clock = _now()
        if (type(known_through) is not dt.date or known_through > clock.date()
                or (known_through == clock.date() and clock.hour < 15)):
            raise ValueError('Require a completed scoring close')
        receipt = load_candidate_freeze(search_output, receipt_path=receipt_path)
        result.update(candidate_count=len(receipt['candidates']), candidate_set_sha256=receipt['candidate_set_sha256'])
        result['source_hashes'][str(receipt_path)] = _digest(receipt_path)
        (output/'candidate_freeze.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        captures = []
        for path in _discover(roots, current):
            try:
                capture = _load_capture(path, receipt, known_through)
                if capture:
                    captures.append(capture)
            except ERRORS as exc:
                errors.append({'source': str(path), 'error': f'{type(exc).__name__}: {exc}'})
        result['complete_capture_records'] = len(captures)
        if captures:
            calendar, sessions, hashes = _calendar(data_root, min(c['day'] for c in captures), known_through)
            calendar.write_parquet(output/'calendar.parquet')
            result['source_hashes'].update(hashes)
            chosen, result['duplicates'] = _select(captures, sessions, receipt, errors)
            for capture in chosen:
                record = {'as_of': str(capture['day']), 'source': str(capture['path']),
                          'captured_at_utc': capture['record']['captured_at_utc'],
                          'source_hashes': capture['source_hashes'],
                          'status': 'not_month_end_or_calendar_incomplete'}
                result['captures'].append(record)
                try:
                    schedule = monthly_schedule(sessions, capture['day'])
                    if schedule is None:
                        continue
                    record.update(entry_session=str(schedule[0]), exit_session=str(schedule[1]))
                    if schedule[1] > known_through:
                        record['status'] = 'awaiting_realized_return'
                        continue
                    folder = _save_capture(capture, output)
                    labels, bars, hashes = _labels(capture, sessions, schedule, known_through, data_root)
                    result['source_hashes'].update(hashes)
                    bars.write_parquet(folder/'label_prices.parquet')
                    labels.write_parquet(folder/'labels.parquet')
                    scored, scores = _score(capture, labels, receipt, schedule)
                    scores.write_parquet(folder/'scores.parquet')
                    rows.extend(scored)
                    label_frames.append(labels)
                    record.update(status='scored', calculation_inputs=str(folder))
                except ERRORS as exc:
                    record['status'] = 'input_error'
                    errors.append({'source': str(capture['path']), 'error': f'{type(exc).__name__}: {exc}'})
            for candidate in receipt['candidates']:
                for variant in ('raw', 'size_industry_neutral'):
                    subset = sorted([r for r in rows if r['factor'] == candidate['id'] and r['variant'] == variant],
                                    key=lambda r: r['trade_date'])
                    summary = monthly_ic_summary([r['trade_date'] for r in subset], [r['rank_ic'] for r in subset],
                                                 lag=chosen[0]['settings']['monthly_newey_west_lag'] if chosen else 6)
                    result['series'].append({'factor': candidate['id'], 'variant': variant, **summary})
        if load_candidate_freeze(search_output, receipt_path=receipt_path) != receipt:
            raise ValueError('Candidate receipt changed during scoring')
    except ERRORS as exc:
        errors.append({'source': str(search_output), 'error': f'{type(exc).__name__}: {exc}'})
    result.update(matured_months=len({r['trade_date'] for r in rows}),
                  scored_months=len({r['trade_date'] for r in rows if r['rank_ic'] is not None}),
                  valid_ic_observations=sum(r['rank_ic'] is not None for r in rows),
                  requires_review=bool(errors))
    result['status'] = ('partial' if rows else 'failed') if errors else ('observed' if rows else 'pending')
    result['reason'] = ('输入损坏、冲突或缺失，详见错误记录。' if errors else
                        '已评分成熟月末信号；样本不足不表示准入。' if rows else '尚无完整且已到期的月末前向信号。')
    table = pl.from_dicts(rows, schema=IC_SCHEMA) if rows else pl.DataFrame(schema=IC_SCHEMA)
    table.write_csv(output/'monthly_ic.csv')
    labels = pl.concat(label_frames) if label_frames else pl.DataFrame(schema=LABEL_SCHEMA)
    labels.write_parquet(output/'labels.parquet')
    result['calculation_files'] = {path.relative_to(output).as_posix(): _digest(path)
                                   for path in sorted(output.rglob('*')) if path.is_file()}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str,
                                                allow_nan=False), encoding='utf-8')
    lines = ['# 冻结候选前向月度观察', '', f'已知价格截止：{known_through}；状态：{result["status"]}。',
             f'候选数：{result["candidate_count"]}；成熟月份：{result["matured_months"]}；有效评分月份：{result["scored_months"]}。', '',
             '月末信号使用下一开盘至次月末下一开盘的复权收益。仅使用最早完整事前捕获，缺失价格保持空值。',
             '分别按捕获时电池设置计算 raw / size_industry_neutral 的 RankIC；候选方向固定。',
             '这是小样本研究观察，不构成因子准入、独立数据验证或收益保证；不计算成本后策略收益。', '',
             '|候选|变体|有效月数|平均 IC|', '|---|---|---:|---:|']
    lines.extend(f'|{row["factor"]}|{row["variant"]}|{row["months"]}|{row["mean_ic"]}|' for row in result['series'])
    if errors:
        lines += ['', '输入问题：'] + [f'- {row["error"]}' for row in errors]
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result
