"""Capture frozen GP signals from refreshed local inputs, before their next open.

This records raw signals and the same-day battery universe, not performance or
admission. Saved input rows make later scoring reproducible without reading a
revised historical factor panel. No labels, network calls or shared data writes.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

import polars as pl

from quant.data.daily_factor_health_inputs import read_daily_health_universe
from quant.data.factor_panels import available_sessions, panel_complete, read_factor_inputs
from quant.data.refresh import SHANGHAI
from quant.factors.expressions import evaluate_expressions, required_history
from quant.research.candidate_freeze import load_candidate_freeze
from quant.research.nightly_gp import expand_expression

KEYS = ['symbol', 'trade_date']


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture_window(*, receipt: dict, as_of: dt.date, sessions: tuple[dt.date, ...],
                   now: dt.datetime) -> dict:
    """A missed next-open deadline never becomes independent evidence on retry."""
    if now.tzinfo is None:
        raise ValueError('Capture clock must have a timezone')
    clock = now.astimezone(SHANGHAI)
    freeze_day = dt.date.fromisoformat(receipt['frozen_local_date'])
    lower = dt.date.fromisoformat(receipt['forward_not_before'])
    eligible = [day for day in sessions if day > freeze_day and day >= lower]
    first = min(eligible) if eligible else None
    result = {'first_eligible_session': str(first) if first else None,
              'as_of': str(as_of), 'entry_session': None, 'capture_deadline': None}
    if as_of <= freeze_day or as_of < lower or (first and as_of < first):
        return {**result, 'status': 'pending', 'reason': 'Waiting for first post-freeze exchange session'}
    if as_of not in sessions or first is None:
        raise ValueError('Calendar does not establish an eligible signal session')
    following = [day for day in sessions if day > as_of]
    if not following:
        raise ValueError('Calendar lacks the next exchange session; cannot establish capture deadline')
    entry = min(following)
    deadline = dt.datetime.combine(entry, dt.time(9, 30), SHANGHAI)
    result.update(entry_session=str(entry), capture_deadline=deadline.isoformat())
    if clock < dt.datetime.combine(as_of, dt.time(17), SHANGHAI):
        return {**result, 'status': 'pending', 'reason': 'Daily inputs are not past their completion cutoff'}
    if clock >= deadline:
        return {**result, 'status': 'missed_window', 'reason': 'Next open already reached; no historical backfill as forward evidence'}
    return {**result, 'status': 'ready'}


def read_candidate_inputs(*, search_output: Path, data_root: Path,
                          refresh_config: Path, as_of: dt.date) -> tuple[pl.DataFrame, dict, dict]:
    """Reuse raw terminal values exactly as N2 does; never apply their directions."""
    search = json.loads((search_output/'search.json').read_text(encoding='utf-8'))
    contract = json.loads((search_output/'search_contract.json').read_text(encoding='utf-8'))
    mapping = contract['mapping']
    expressions = {row['factor_id']: row['terminal_expression'] for row in search['candidates']}
    if not expressions or len(expressions) != len(search['candidates']):
        raise ValueError('Require distinct frozen candidate expressions')
    for row in search['candidates']:
        if expand_expression(row['terminal_expression'], mapping) != row['expression']:
            raise ValueError('Frozen terminal expression does not reproduce the exported expression')
    names = {node.id for expr in expressions.values() for node in ast.walk(ast.parse(expr, mode='eval'))
             if isinstance(node, ast.Name)}
    terminals = sorted(names & set(mapping))
    if any(not name.startswith('gp_') for name in terminals):
        raise ValueError('Unexpected GP terminal naming')
    lookback = max(required_history(expr) for expr in expressions.values())
    sessions = available_sessions(data_root, as_of)
    if not sessions or sessions[-1] != as_of or len(sessions) <= lookback:
        raise ValueError('Missing completed session or candidate warmup')
    start = sessions[-lookback-1]
    panel, bars = read_factor_inputs(data_root, refresh_config, start, as_of, sessions)
    sources = {}
    for terminal in terminals:
        factor = terminal[3:]
        definition_path = data_root/'factors'/factor/'definition.json'
        sources[str(definition_path)] = _digest(definition_path)
        definition = json.loads(definition_path.read_text(encoding='utf-8'))
        if definition.get('id') != factor or definition.get('expr') != mapping[terminal]:
            raise ValueError(f'Current terminal differs from frozen expression: {terminal}')
        sections = []
        for year in range(start.year, as_of.year + 1):
            low, high = max(start, dt.date(year, 1, 1)), min(as_of, dt.date(year, 12, 31))
            folder = data_root/'factors'/factor/f'year={year}'
            for filename in ('coverage.json', 'data.parquet'):
                path = folder/filename
                sources[str(path)] = _digest(path)
            if not panel_complete(data_root, factor, year, low, high):
                raise ValueError(f'Missing current or warmup terminal computation: {terminal}')
            frame = pl.scan_parquet(folder/'data.parquet').filter(
                pl.col('trade_date').is_between(low, high)).select(
                    pl.col('ts_code').alias('symbol'), 'trade_date', pl.col('value').alias(terminal)).collect()
            sections.append(frame)
        values = pl.concat(sections)
        if (values.select(KEYS).is_duplicated().any()
                or values.select(KEYS).null_count().sum_horizontal().item()
                or bars.select(KEYS).join(values.select(KEYS), on=KEYS, how='anti').height
                or values.select(KEYS).join(bars.select(KEYS), on=KEYS, how='anti').height):
            raise ValueError(f'Terminal rows do not match observed bars: {terminal}')
        panel = panel.join(values, on=KEYS, how='left', validate='1:1')
    if 'industry_l1' in names:
        # The current publication must be dated as_of; its intervals supply warmup.
        from quant.data.daily_factor_health_inputs import _read_current_industry
        from quant.data.industry_history import attach_industry
        intervals, source = _read_current_industry(data_root, as_of)
        sources[source] = _digest(Path(source))
        panel = attach_industry(panel, intervals)
    fields = sorted(names & set(panel.columns) - set(KEYS))
    panel = panel.select(*KEYS, *fields).with_columns(
        pl.col(name).cast(pl.Float64) for name in fields if name != 'industry_l1')
    if any(_digest(Path(path)) != checksum for path, checksum in sources.items()):
        raise ValueError('Terminal inputs changed during capture')
    return panel, expressions, {'warmup_start': str(start), 'lookback_sessions': lookback,
                                'terminal_count': len(terminals), 'sources': sources}


def run(*, search_output: Path, receipt_path: Path, data_root: Path,
        refresh_config: Path, refresh_evidence: Path, battery_config: Path, as_of: dt.date, output: Path,
        now: dt.datetime | None = None) -> dict:
    """Write one immutable capture in this daily record's own directory."""
    clock = now or dt.datetime.now(dt.timezone.utc)
    receipt = load_candidate_freeze(search_output, receipt_path=receipt_path)
    sessions = available_sessions(data_root, as_of + dt.timedelta(days=45))
    window = capture_window(receipt=receipt, as_of=as_of, sessions=sessions, now=clock)
    result = {**window, 'auto_trade': False, 'candidate_count': len(receipt['candidates']),
              'candidate_set_sha256': receipt['candidate_set_sha256'],
              'independent_forward_capture': False, 'performance_evaluated': False,
              'requires_review': window['status'] == 'missed_window', 'output': str(output),
              'recorded_at_utc': clock.astimezone(dt.timezone.utc).isoformat(),
              'policy': 'Raw signal capture only; no admission or trading; future labels must mature before scoring'}
    if output.exists():
        raise FileExistsError('Use a new candidate forward capture directory')
    output.mkdir(parents=True)
    if window['status'] == 'ready':
        refresh_record = json.loads(refresh_evidence.read_text(encoding='utf-8'))
        if (refresh_record.get('latest_session') != str(as_of)
                or refresh_record.get('intraday_errors', ['missing'])
                or refresh_record.get('input_quality', {}).get('errors', ['missing'])):
            raise ValueError('Candidate capture requires successful same-session refresh evidence')
        refresh_hash, battery_hash = _digest(refresh_config), _digest(battery_config)
        universe = read_daily_health_universe(data_root=data_root, refresh_config=refresh_config,
            battery_config=battery_config, as_of=as_of)
        inputs, expressions, evidence = read_candidate_inputs(search_output=search_output,
            data_root=data_root, refresh_config=refresh_config, as_of=as_of)
        values = evaluate_expressions(inputs, expressions).filter(pl.col('trade_date') == as_of)
        values = universe.select(KEYS).join(values.select(*KEYS, *expressions), on=KEYS, how='left', validate='1:1')
        if refresh_hash != _digest(refresh_config) or battery_hash != _digest(battery_config):
            raise ValueError('Input configuration changed during capture')
        if load_candidate_freeze(search_output, receipt_path=receipt_path) != receipt:
            raise ValueError('Frozen candidate receipt changed during capture')
        for name, frame in [('inputs', inputs), ('values', values), ('universe', universe)]:
            frame.write_parquet(output/f'{name}.parquet')
        shutil.copyfile(refresh_config, output/'refresh_config.toml')
        shutil.copyfile(battery_config, output/'battery_config.toml')
        if (_digest(output/'refresh_config.toml') != refresh_hash
                or _digest(output/'battery_config.toml') != battery_hash):
            raise ValueError('Configuration changed while saving capture inputs')
        (output/'refresh.json').write_text(json.dumps(refresh_record, indent=2), encoding='utf-8')
        (output/'candidate_freeze.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        (output/'terminal_expressions.json').write_text(json.dumps(expressions, indent=2), encoding='utf-8')
        eligible = values.join(universe.filter(pl.col('eligible')).select(KEYS), on=KEYS, how='semi')
        files = {path.name: _digest(path) for path in sorted(output.iterdir())}
        # Check after writing/hashing as well: a long capture must not cross the next open.
        finished = dt.datetime.now(dt.timezone.utc) if now is None else now
        if capture_window(receipt=receipt, as_of=as_of, sessions=sessions, now=finished)['status'] != 'ready':
            raise ValueError('Candidate capture crossed its next-open deadline')
        result.update(status='captured', independent_forward_capture=True,
            captured_at_utc=finished.astimezone(dt.timezone.utc).isoformat(),
            universe_symbols=universe.height, eligible_symbols=eligible.height,
            finite_eligible_counts={name: eligible[name].is_finite().fill_null(False).sum() for name in expressions},
            financial_disclosure_completeness='not_established_by_input_quality',
            unresolved_financial_announcements=refresh_record.get('financials', {}).get('unresolved_announcements'),
            inputs=evidence, files=files)
    temporary = output/'summary.json.tmp'
    temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
    temporary.replace(output/'summary.json')
    return result
