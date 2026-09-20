"""GP evolution using the registered predictive-priority batch selector throughout."""
from __future__ import annotations

import ast
import copy
import datetime as dt
import hashlib
import json
import random
from dataclasses import asdict
from pathlib import Path

import polars as pl
from deap import gp

from quant.data.cross_stock_sampling import stock_groups
from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date
from quant.research.gp_predictive_priority import (
    Candidate, GroupIC, MechanismManifest, MechanismTerminal, SelectionRules,
    _expression_details, assess_candidate, rank_candidates,
)

_CORRELATION_METHOD = 'mean_absolute_monthly_spearman_then_max_control'
_SELECTION_METHOD = 'remaining_best_inclusive_0.001_band_rebuilt_after_each_pick_v1'
_DAILY_FINGERPRINT_METHOD = 'sha256_schema_and_key_sorted_polars_row_hashes_v1'


def _write(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _date(value: dt.date | str) -> dt.date:
    return dt.date.fromisoformat(value) if isinstance(value, str) else value


def _daily_input_fingerprint(panel: pl.DataFrame, *, batch_size: int = 65536) -> str:
    """Hash all daily inputs, including warmup rows, without serializing the wide panel.

Canonical columns are hashed in bounded slices. Only keys and eight-byte row
hashes are sorted; the multi-GB wide frame is neither sorted nor converted to
bytes. Column dtypes and Polars version are frozen because hash_rows guarantees
reproducibility only within one Polars version. Row/column order and slice size
do not change the result; duplicate/missing keys are rejected by the caller.
"""
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError('Fingerprint batch size must be a positive integer')
    columns = sorted(panel.columns)
    schema = panel.schema
    metadata = {'method': _DAILY_FINGERPRINT_METHOD, 'polars_version': pl.__version__,
                'rows': panel.height, 'schema': [(name, str(schema[name])) for name in columns],
                'row_hash_seeds': [0, 1, 2, 3]}
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode())
    hashes = [section.hash_rows(seed=0, seed_1=1, seed_2=2, seed_3=3)
              for section in panel.select(columns).iter_slices(n_rows=batch_size)]
    if not hashes:
        return digest.hexdigest()
    keyed = panel.select('trade_date', 'symbol').with_columns(
        pl.concat(hashes).alias('_input_row_hash')).sort('trade_date', 'symbol')
    for section in keyed.select('_input_row_hash').iter_slices(n_rows=batch_size):
        # At most batch_size*8 bytes, with explicit endian order.
        digest.update(section['_input_row_hash'].to_numpy().astype('<u8', copy=False).tobytes())
    return digest.hexdigest()


def _validate_training(panel: pl.DataFrame, labels: pl.DataFrame, config: dict) -> None:
    end = _date(config['training_end'])
    if (labels.is_empty() or panel.is_empty()
            or labels.schema.get('trade_date') != pl.Date
            or labels.schema.get('label_exit_date') != pl.Date
            or panel.schema.get('trade_date') != pl.Date):
        raise ValueError('Predictive search requires dated training signals and label exits')
    if (labels.select('symbol', 'trade_date').is_duplicated().any()
            or panel.select('symbol', 'trade_date').is_duplicated().any()
            or labels.select('symbol', 'trade_date', 'label_exit_date').null_count().sum_horizontal().item()
            or panel.select('symbol', 'trade_date').null_count().sum_horizontal().item()):
        raise ValueError('Training sample has duplicate or missing keys')
    if (labels.filter((pl.col('trade_date') > end) | (pl.col('label_exit_date') > end)
                      | (pl.col('label_exit_date') <= pl.col('trade_date'))).height
            or panel.filter(pl.col('trade_date') > end).height):
        raise ValueError('Training input contains dates or label exits beyond the registered cutoff')
    dates = labels['trade_date'].unique().sort().to_list()
    if (len(dates) != config['training_months']
            or len({(day.year, day.month) for day in dates}) != len(dates)):
        raise ValueError('Require the registered monthly training sample with one signal per month')
    if labels['symbol'].n_unique() != config['sample_groups'] * config['symbols_per_group']:
        raise ValueError('Training stock count differs from registered disjoint groups')
    if labels.join(panel.select('symbol', 'trade_date'), on=['symbol', 'trade_date'], how='anti').height:
        raise ValueError('Training labels have no matching daily signal rows')


def measure_candidate(scored: pl.DataFrame, expression: str, assignments: dict[str, int],
                      controls: list[str], rules: SelectionRules) -> tuple[Candidate, dict]:
    """Measure groups and each frozen control independently, retaining absent measurements.

Control redundancy preserves the original GP metric: for each control compute
mean absolute monthly common-stock Spearman, then take the maximum across
controls. A month requires at least the registered number of finite pairs and
nonconstant ranks. Unlike the legacy helper, an unmeasured control is not omitted.
"""
    groups, diagnostics = [], []
    for group in range(rules.sample_groups):
        symbols = [symbol for symbol, value in assignments.items() if value == group]
        frame = scored.filter(pl.col('symbol').is_in(symbols))
        series = rank_ic_by_date(frame, score='candidate', label='label',
                                minimum_symbols=rules.minimum_symbols_per_month,
                                minimum_paired_coverage=rules.minimum_paired_coverage)
        stats = monthly_ic_summary(series['trade_date'].to_list(), series['rank_ic'].to_list())
        valid = series.filter(pl.col('rank_ic').is_finite())
        groups.append(GroupIC(group, stats['mean_ic'], stats['months'],
                              valid['paired_count'].min() if valid.height else None,
                              valid['paired_coverage'].min() if valid.height else None))
        diagnostics.append({'group': group, **stats})
    correlations, control_statistics = [], []
    for control in controls:
        # Zero coverage threshold retains legacy common-stock correlation semantics;
        # the minimum pair count and nonconstant ranks remain mandatory.
        series = rank_ic_by_date(scored, score='candidate', label=control,
                                minimum_symbols=rules.minimum_symbols_per_month,
                                minimum_paired_coverage=0.)
        valid = series.filter(pl.col('rank_ic').is_finite())
        correlation = float(valid['rank_ic'].abs().mean()) if valid.height else None
        if correlation is not None:
            correlation = min(1., max(0., correlation))
        correlations.append((control, correlation))
        control_statistics.append({'control': control, 'valid_months': valid.height,
                                   'mean_absolute_monthly_spearman': correlation})
    pooled = rank_ic_by_date(scored, score='candidate', label='label',
                            minimum_symbols=rules.minimum_symbols_per_month,
                            minimum_paired_coverage=rules.minimum_paired_coverage)
    train = monthly_ic_summary(pooled['trade_date'].to_list(), pooled['rank_ic'].to_list())
    return Candidate(expression, tuple(groups), tuple(correlations)), {
        'train': train, 'group_statistics': diagnostics, 'control_statistics': control_statistics,
    }


def _candidate(row: dict) -> Candidate:
    saved = row['selection_candidate']
    return Candidate(saved['expression'], tuple(GroupIC(**group) for group in saved['groups']),
                     tuple(tuple(pair) for pair in saved['control_correlations']))


def _rank_rows(rows: list[dict], manifest: MechanismManifest, controls: list[str],
               rules: SelectionRules) -> list[dict]:
    unique = {row['terminal_expression']: row for row in rows if row.get('selection_eligible')}
    result = rank_candidates([_candidate(row) for row in unique.values()], manifest=manifest,
                             control_ids=controls, rules=rules)
    return [unique[row.expression] for row in (*result.selected, *result.eligible_not_selected)]


def search_predictive(panel: pl.DataFrame, labels: pl.DataFrame, mapping: dict[str, str],
                      settings: dict, output: Path, *, family: str) -> list[dict]:
    """Use one deterministic ranking rule for tournaments, elitism and exports.

Controls are measurement columns only and never enter the GP grammar. Rejected
individuals cannot be parents or elites. If a whole generation is ineligible,
the next registered generation samples afresh; it adds no generations or seeds.
No scalar DEAP fitness is assigned or used. A checkpoint resumes its population,
RNG, records and selection trace under an identical frozen search contract.
"""
    from quant.research import nightly_gp as engine

    config = settings['predictive_priority']
    rules = SelectionRules.from_config(config)
    if settings.get('cross_stock'):
        raise ValueError('Predictive priority cannot share a legacy cross-stock objective')
    raw_manifest = settings.get('mechanism_manifest')
    if not isinstance(raw_manifest, dict):
        raise ValueError('Predictive search requires an explicit mechanism manifest')
    manifest = MechanismManifest(tuple(MechanismTerminal(**row)
                                       for row in raw_manifest.get('terminals', [])))
    controls = settings.get('frozen_control_ids')
    if not isinstance(controls, (list, tuple)):
        raise ValueError('Predictive search requires frozen admitted control IDs')
    controls = list(controls)
    rank_candidates([], manifest=manifest, control_ids=controls, rules=rules)
    if set(controls) & set(mapping):
        raise ValueError('Frozen controls must be distinct measurement columns, not GP terminals')
    if any(row.terminal_id not in mapping for row in manifest.terminals):
        raise ValueError('Declared mechanism terminal is missing from the frozen GP mapping')
    for field in ('population_size', 'generations', 'max_depth', 'seed'):
        if settings.get(field) != config[field]:
            raise ValueError(f'Predictive search differs from registered setting: {field}')
    if type(config['population_size']) is not int or config['population_size'] < 2:
        raise ValueError('Predictive population requires at least two individuals')
    if type(config['generations']) is not int or config['generations'] < 0:
        raise ValueError('Invalid registered generation count')
    required = set(mapping) | set(controls)
    if required - set(panel.columns):
        raise ValueError('Training panel lacks frozen terminals or admitted control columns')
    if required & {'symbol', 'trade_date', 'label', 'label_exit_date', 'candidate', 'industry_l1'}:
        raise ValueError('Terminals or controls overlap reserved training columns')
    _validate_training(panel, labels, config)
    daily_fingerprint = _daily_input_fingerprint(panel)
    assignments = stock_groups(labels['symbol'].unique().to_list(), groups=rules.sample_groups,
                               per_group=config['symbols_per_group'], seed=config['sample_seed'])
    basics = [name for name in ('adj_open', 'adj_high', 'adj_low', 'adj_close', 'volume', 'amount',
                                'turnover_rate', 'total_mv', 'circ_mv', 'pe_ttm', 'pb')
              if name in panel.columns and name not in controls and name not in mapping]
    panel = panel.with_columns(pl.col(name).cast(pl.Float64) for name in [*mapping, *controls, *basics])
    monthly = panel.select('symbol', 'trade_date', *controls).join(
        labels, on=['symbol', 'trade_date'], validate='1:1')
    contract = json.loads(json.dumps({
        'objective': config['version'], 'config': config, 'mapping': mapping,
        'mechanism_manifest': {'terminals': [asdict(row) for row in sorted(
            manifest.terminals, key=lambda row: row.terminal_id)]},
        'mechanism_manifest_sha256': manifest.sha256, 'frozen_control_ids': controls,
        'assignments': assignments, 'seed': settings['seed'], 'basic_terminals': basics,
        'favored_terminals': settings.get('favored_terminals', []),
        'fitness_preprocessing': engine._FITNESS_PREPROCESSING,
        'correlation_method': _CORRELATION_METHOD, 'selection_method': _SELECTION_METHOD,
        'daily_input_fingerprint_method': _DAILY_FINGERPRINT_METHOD,
        'daily_input_sha256': daily_fingerprint,
        'monthly_measurement_sha256': hashlib.sha256(
            monthly.sort('trade_date', 'symbol').hash_rows(seed=0).to_numpy().tobytes()).hexdigest(),
    }, default=str))
    checkpoint, cache_path = output/'search_checkpoint.json', output/'fitness_cache.json'
    contract_path = output/'search_contract.json'
    if contract_path.exists():
        if json.loads(contract_path.read_text(encoding='utf-8')) != contract:
            raise ValueError('Frozen predictive search contract changed; use a new run directory')
    elif checkpoint.exists() or cache_path.exists():
        raise ValueError('Predictive checkpoint lacks its frozen search contract')
    else:
        _write(contract_path, contract)
    saved = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else None
    records = saved['records'] if saved else []
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding='utf-8'))
        overlap = min(len(records), len(cached))
        if records[:overlap] != cached[:overlap]:
            raise ValueError('Predictive checkpoint and fitness cache records disagree')
        if len(cached) > len(records):
            records = cached
    if any(row.get('search_objective') != config['version']
           or row.get('fitness_preprocessing') != engine._FITNESS_PREPROCESSING for row in records):
        raise ValueError('Predictive checkpoint objective or preprocessing changed')
    if len({row['terminal_expression'] for row in records}) != len(records):
        raise ValueError('Predictive checkpoint contains duplicate expression records')
    cache = {row['terminal_expression']: row for row in records}
    pset = engine.primitive_set([*mapping, *basics])
    favored = settings.get('favored_terminals', [])
    pset.terminals[object].extend([node for node in list(pset.terminals[object])
                                  if node.value in favored] * 3)
    random.seed(settings['seed'])

    def individual():
        return gp.PrimitiveTree(gp.genHalfAndHalf(pset=pset, min_=0, max_=2))

    def expression(tree):
        return gp.compile(tree, pset)

    def assess(tree):
        formula = expression(tree)
        if formula in cache:
            return
        row = {'expression': engine.expand_expression(formula, mapping),
               'terminal_expression': formula, 'complexity': len(tree), 'depth': tree.height,
               'search_objective': config['version'],
               'fitness_preprocessing': engine._FITNESS_PREPROCESSING,
               'selection_eligible': False}
        try:
            if tree.height > rules.max_depth:
                raise ValueError('depth exceeded')
            names, node_count, depth = _expression_details(formula)
            if node_count != len(tree) or depth != tree.height:
                raise ValueError('Exported expression node count or depth differs from GP tree')
            if not names & {item.terminal_id for item in manifest.terminals}:
                row['selection_reasons'] = ['required_mechanism_not_referenced']
                raise ValueError('required_mechanism_not_referenced')
            fields = sorted({node.id for node in ast.walk(ast.parse(formula, mode='eval'))
                             if isinstance(node, ast.Name) and node.id in panel.columns}
                            - {'symbol', 'trade_date'})
            if set(fields) & set(controls):
                raise ValueError('Admitted control column appeared in GP expression')
            values = engine.evaluate_expressions(panel.select('symbol', 'trade_date', *fields),
                                                 {'candidate': formula})
            scored = monthly.join(values.select('symbol', 'trade_date', 'candidate'),
                                  on=['symbol', 'trade_date'], validate='1:1')
            scored = engine.preprocess_training_scores(scored)
            candidate, measured = measure_candidate(scored, formula, assignments, controls, rules)
            assessment = assess_candidate(candidate, manifest=manifest, control_ids=controls,
                                          rules=rules)
            row.update(measured, selection_candidate=json.loads(json.dumps(asdict(candidate))),
                       selection_eligible=assessment.eligible, direction=assessment.direction,
                       selection_primary=assessment.primary,
                       maximum_rank_correlation=assessment.secondary,
                       mechanism_terminals=list(assessment.mechanism_terminals),
                       selection_reasons=list(assessment.reasons))
            if not assessment.eligible:
                row['error'] = '; '.join(assessment.reasons)
                row['error_type'] = 'SelectionRejected'
        except BaseException as exc:
            if (not isinstance(exc, (ValueError, TypeError, pl.exceptions.PolarsError, OverflowError))
                    and type(exc).__name__ != 'PanicException'):
                raise
            row.update(error=str(exc)[:500], error_type=type(exc).__name__)
        records.append(row)
        cache[formula] = row
        if len(records) % 20 == 0:
            _write(cache_path, records)

    def tuples(value):
        return tuple(tuples(item) for item in value) if isinstance(value, list) else value

    if saved:
        population = [gp.PrimitiveTree.from_string(tree, pset) for tree in saved['population']]
        for tree in population:
            for node in tree:
                if not node.arity:
                    node.ret = object
        random.setstate(tuples(saved['random_state']))
    else:
        population = [individual() for _ in range(config['population_size'])]
    trace = saved.get('selection_trace', []) if saved else []
    first = saved['generation'] if saved else 0
    for generation in range(first, config['generations'] + 1):
        for tree in population:
            assess(tree)
        ranked = _rank_rows(records, manifest, controls, rules)
        _write(output/'search_progress.json', {'generation': generation,
               'unique_evaluations': len(records), 'eligible_evaluations': len(ranked),
               'search_objective': config['version']})
        _write(cache_path, records)
        _write(checkpoint, {'generation': generation, 'population': [str(tree) for tree in population],
                           'random_state': random.getstate(), 'records': records,
                           'selection_trace': trace})
        _write(output/'best_so_far.json', ranked[:rules.maximum_candidates])
        if generation == config['generations']:
            break
        from quant.research.slice_budget import checkpoint as slice_checkpoint
        slice_checkpoint()
        eligible = [tree for tree in population if cache[expression(tree)].get('selection_eligible')]
        if not eligible:
            trace.append({'generation': generation, 'eligible_population': 0,
                          'action': 'fresh_population_within_registered_generations'})
            population = [individual() for _ in range(config['population_size'])]
            continue
        by_expression = {expression(tree): tree for tree in eligible}
        ordered = _rank_rows([cache[name] for name in by_expression], manifest, controls, rules)
        elite_count = min(10, len(population) - 1)
        elites = [copy.deepcopy(by_expression[row['terminal_expression']])
                  for row in ordered[:elite_count]]
        parents = []
        for _ in range(len(population) - len(elites)):
            aspirants = [random.choice(eligible) for _ in range(3)]
            winner = _rank_rows([cache[expression(tree)] for tree in aspirants],
                                manifest, controls, rules)[0]
            parents.append(by_expression[winner['terminal_expression']])
        trace.append({'generation': generation, 'eligible_population': len(eligible),
                      'elites': [expression(tree) for tree in elites],
                      'tournament_winners': [expression(tree) for tree in parents]})
        children = []
        for parent in parents:
            child = copy.deepcopy(parent)
            if random.random() < .7:
                gp.cxOnePoint(child, copy.deepcopy(random.choice(eligible)))
            if random.random() < .3:
                gp.mutUniform(child, expr=lambda **kw: gp.genGrow(min_=0, max_=2, **kw), pset=pset)
            children.append(child if child.height <= rules.max_depth else copy.deepcopy(parent))
        population = elites + children

    unique = {}
    for row in _rank_rows(records, manifest, controls, rules):
        unique.setdefault(ast.dump(ast.parse(row['expression'], mode='eval')), row)
    winners = [dict(row) for row in list(unique.values())[:rules.maximum_candidates]]
    library = output/'library'
    library.mkdir(exist_ok=True)
    for row in winners:
        row['factor_id'] = 'ngp_' + hashlib.sha256(row['expression'].encode()).hexdigest()[:16]
        definition = {'id': row['factor_id'], 'expr': row['expression'], 'direction': row['direction'],
                      'family': f'nightly_{family}', 'source_ref': str(output/'search.json')}
        (library/f"{row['factor_id']}.toml").write_text(''.join(
            f'{key} = {json.dumps(value)}\n' for key, value in definition.items()), encoding='utf-8')
    _write(output/'search.json', {'candidates': winners, 'trials': records, 'selection_trace': trace,
                                 'correlation_method': _CORRELATION_METHOD,
                                 'selection_method': _SELECTION_METHOD})
    if winners:
        from quant.research.candidate_freeze import freeze_completed_search
        freeze_completed_search(output)
    return winners
