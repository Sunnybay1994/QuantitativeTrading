"""Resolve actual daily consumers before choosing incremental factor/minute work.

This is a read-only dependency calculation, not a new admission check. Shadow
execution keeps its own local minute observations and missing-window reporting.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

from quant.data.factor_health_inputs import read_factor_health_selection
from quant.data.refresh import refresh_factor_selection
from quant.factors.library import load_library
from quant.research.candidate_freeze import load_candidate_freeze
from quant.research.factor_intraday import minute_input_names
from quant.research.nightly_gp import expand_expression
from quant.research.run_daily_model_forecast import model_factor_requirements


def resolve_daily_dependencies(*, config: Path, as_of: dt.date) -> dict:
    """Return the factor union consumed by this day's frozen production paths.

    Missing, excluded, changed or unknown required definitions raise rather than
    silently remove a consumer. Future model selections are not used. No factor,
    provider, account or configuration file is written by this function.
    """
    if type(as_of) is not dt.date:
        raise ValueError('Daily dependencies require a date cutoff')
    sources: dict[str, str] = {}

    def record(path: Path) -> bytes:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        key = str(path.resolve())
        if key in sources and sources[key] != digest:
            raise ValueError(f'Daily dependency source changed: {path}')
        sources[key] = digest
        return raw

    settings = tomllib.loads(record(config).decode('utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('Daily dependencies require auto_trade=false')
    refresh_path = Path(settings['refresh_config'])
    refresh = tomllib.loads(record(refresh_path).decode('utf-8'))
    library = Path(refresh['factors']['library'])
    for path in sorted([*library.glob('*.toml'), *(library/'auto').rglob('*.toml')]):
        record(path)
    definitions = {row.id: row for row in load_library(library, refresh_factor_selection(refresh['factors']))}
    selection = Path(settings['model']['selection'])
    model_spec = tomllib.loads(record(selection/'config.toml').decode('utf-8'))
    record(Path(model_spec['research']['predictions'])/'summary.json')
    model = model_factor_requirements(selection=selection, refresh_config=refresh_path, as_of=as_of)
    if model['required_excluded'] or model['required_outside_refresh_selection']:
        raise ValueError('Daily model requirements are outside the configured refresh selection')
    consumers: dict[str, dict] = {'model': {'factor_ids': model['required_factors']}}
    if settings.get('q10'):
        q10 = tomllib.loads(record(Path(settings['q10']['config'])).decode('utf-8'))
        if Path(q10['model']['selection']).resolve() != selection.resolve():
            raise ValueError('Q10 requires the same frozen selection as the daily forecast')
        consumers['q10'] = {'factor_ids': model['required_factors'], 'raw_daily_inputs': True}
    health_path = refresh.get('quality', {}).get('factor_health_config')
    if refresh.get('quality', {}).get('enabled', False) and health_path:
        health = tomllib.loads(record(Path(health_path)).decode('utf-8'))
        scope = health['diagnostics']
        record(Path(scope['selection'])/'annual_selection.parquet')
        schedule = read_factor_health_selection(selection=Path(scope['selection']),
            as_of_dates=[as_of], max_factors=scope['maximum_factors'],
            replacements=health.get('replacements', {}))
        consumers['factor_health'] = {'factor_ids': sorted(schedule['factor_id'].unique().to_list())}
    candidate = settings.get('candidate_forward', {})
    if candidate.get('enabled'):
        root, receipt_path = Path(candidate['search_output']), Path(candidate['receipt'])
        record(receipt_path)
        receipt = load_candidate_freeze(root, receipt_path=receipt_path)
        search = json.loads(record(root/'search.json'))
        mapping = json.loads(record(root/'search_contract.json'))['mapping']
        terminals, direct_minutes = set(), set()
        for row in search['candidates']:
            record(root/'library'/f"{row['factor_id']}.toml")
            expression = row['terminal_expression']
            if expand_expression(expression, mapping) != row['expression']:
                raise ValueError('Frozen candidate terminal expansion changed')
            names = {node.id for node in ast.walk(ast.parse(expression, mode='eval'))
                     if isinstance(node, ast.Name)}
            unknown = {name for name in names if name.startswith('gp_')} - set(mapping)
            if unknown:
                raise ValueError(f'Unknown candidate terminals: {sorted(unknown)}')
            terminals.update(names & set(mapping))
            direct_minutes.update(minute_input_names((row['expression'],)))
        candidate_factors = []
        for terminal in sorted(terminals):
            if not terminal.startswith('gp_'):
                raise ValueError(f'Unexpected candidate terminal: {terminal}')
            factor = terminal[3:]
            if factor not in definitions or definitions[factor].expr != mapping[terminal]:
                raise ValueError(f'Candidate terminal differs from refresh library: {terminal}')
            # Capture reads these published columns directly, so their definition
            # must agree with both the frozen mapping and selected library.
            published = json.loads(record(Path(settings['data_root'])/'factors'/factor/'definition.json'))
            if published.get('id') != factor or published.get('expr') != mapping[terminal]:
                raise ValueError(f'Published candidate terminal differs: {terminal}')
            candidate_factors.append(factor)
        consumers['candidate_forward'] = {'factor_ids': candidate_factors,
            'direct_minute_inputs': sorted(direct_minutes),
            'candidate_count': len(receipt['candidates']),
            'candidate_set_sha256': receipt['candidate_set_sha256']}
        if load_candidate_freeze(root, receipt_path=receipt_path) != receipt:
            raise ValueError('Frozen candidates changed during dependency resolution')
    for name in ('b20', 'b32'):
        if settings.get(name):
            account = tomllib.loads(record(Path(settings[name]['config'])).decode('utf-8'))
            if name == 'b32':
                supported = {'turnover_cv20', 'alpha158_std20', 'alpha158_roc20', 'alpha158_rsv20'}
                used = set(account['universe']['same_effective_pool'])
                used.update(component for row in account['accounts'] for component in row['components'])
                if used - supported:
                    raise ValueError('Unrecognized B32 signal dependency; do not infer daily-only inputs')
            elif account['strategy']['kind'] != 'inverse_volatility':
                raise ValueError('Unrecognized B20 signal dependency; do not infer daily-only inputs')
            consumers[name] = {'factor_ids': [], 'raw_daily_inputs': True}
    required = sorted({factor for item in consumers.values() for factor in item['factor_ids']})
    if set(required) - set(definitions):
        raise ValueError(f'Required consumer factors outside refresh selection: {sorted(set(required)-set(definitions))}')
    minute_factors = {factor: minute_input_names((row.expr,)) for factor, row in definitions.items()
                      if minute_input_names((row.expr,))}
    minutes = {name for factor in required for name in minute_factors.get(factor, ())}
    minutes.update(consumers.get('candidate_forward', {}).get('direct_minute_inputs', []))
    for path, expected in sources.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Daily dependency source changed during resolution: {path}')
    return {'as_of': str(as_of), 'auto_trade': False, 'required_factor_ids': required,
        'required_minute_factor_ids': sorted(set(required) & set(minute_factors)),
        'required_minute_inputs': sorted(minutes),
        'research_only_minute_factor_ids': sorted(set(minute_factors) - set(required)),
        'consumers': consumers, 'sources': sources,
        'shadow': {'enabled': settings.get('forward_tracking', {}).get('enabled', False),
                   'scope': 'saved reference orders: symbol and completed execution_date; local opening windows',
                   'missing_windows': 'remain missing and require review; never suppress account daily refresh'},
        'b16_manual': {'raw_daily_inputs': True,
                       'execution_inputs': 'independent frozen same-day quote packets; not all-market historical minutes'}}
