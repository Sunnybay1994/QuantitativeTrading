"""Budgeted DEAP GP over caller-supplied, already computed training terminals."""
from __future__ import annotations

import ast
import copy
import datetime as dt
import hashlib
import math
import random
import re
from dataclasses import asdict, dataclass, replace
from threading import Lock
from typing import Any

import numpy as np
import polars as pl
from deap import base, gp, tools  # type: ignore[import-untyped]

from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date

# DEAP operators use Python's module RNG. Serialize only these in-process searches
# and restore its state; no files, workers or provider state are involved.
_RNG_LOCK = Lock()
_RESERVED = {'symbol', 'trade_date', 'label', 'label_exit_date', 'validation', 'test'}


@dataclass(frozen=True)
class GeneticSearchConfig:
    training_end: dt.date
    seed: int = 20260913
    population_size: int = 30
    generations: int = 5
    max_unique_evaluations: int = 100
    max_attempts: int = 500
    max_depth: int = 4
    minimum_symbols: int = 100
    minimum_months: int = 48
    minimum_paired_coverage: float = .8
    complexity_penalty: float = .0005
    crossover_probability: float = .7
    mutation_probability: float = .3
    tournament_size: int = 3
    candidate_count: int = 20
    random_baseline: bool = False


class _Fitness(base.Fitness):
    weights = (1.,)


class _Individual(gp.PrimitiveTree):
    def __init__(self, content: Any) -> None:
        super().__init__(content)
        self.fitness = _Fitness()


def _validate(panel: pl.DataFrame, terminals: dict[str, str], cfg: GeneticSearchConfig) -> pl.DataFrame:
    counts = ('population_size', 'max_unique_evaluations', 'max_attempts', 'max_depth',
              'minimum_symbols', 'minimum_months', 'tournament_size', 'candidate_count')
    if (any(type(getattr(cfg, k)) is not int or getattr(cfg, k) < 1 for k in counts)
        or type(cfg.generations) is not int or cfg.generations < 0
        or cfg.max_depth > 12 or cfg.minimum_symbols < 2 or type(cfg.seed) is not int
        or not isinstance(cfg.training_end, dt.date)
        or not math.isfinite(cfg.complexity_penalty) or cfg.complexity_penalty < 0
        or any(not math.isfinite(v) or not 0 <= v <= 1 for v in
               (cfg.crossover_probability, cfg.mutation_probability, cfg.minimum_paired_coverage))):
        raise ValueError('Invalid genetic-search configuration')
    if not terminals:
        raise ValueError('Require named, precomputed dimensionless terminals')
    for name, expr in terminals.items():
        if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]*', name) or name in _RESERVED:
            raise ValueError('Invalid or reserved terminal name')
        tree = ast.parse(expr, mode='eval')
        if any(isinstance(n, ast.Name) and n.id in _RESERVED for n in ast.walk(tree)):
            raise ValueError('Terminal DSL cannot refer to labels or split metadata')
    required = ['symbol', 'trade_date', 'label', 'label_exit_date', *terminals]
    frame = panel.select(required).sort('trade_date', 'symbol')
    if frame.is_empty() or frame.schema['trade_date'] != pl.Date or frame.schema['label_exit_date'] != pl.Date:
        raise ValueError('Require a nonempty monthly panel with Date label boundaries')
    if (frame.select('symbol', 'trade_date', 'label_exit_date').null_count().sum_horizontal().item()
        or frame.select('symbol', 'trade_date').is_duplicated().any()
        or frame.filter((pl.col('trade_date') > cfg.training_end)
                        | (pl.col('label_exit_date') > cfg.training_end)
                        | (pl.col('label_exit_date') <= pl.col('trade_date'))).height):
        raise ValueError('Training data contains duplicate keys or unknown/future labels')
    dates = frame['trade_date'].unique().to_list()
    if len({(d.year, d.month) for d in dates}) != len(dates):
        raise ValueError('Require one signal date per calendar month')
    for name in ['label', *terminals]:
        if not frame.schema[name].is_numeric():
            raise ValueError('Terminals and label must be numeric')
    return frame


def _export(tree: gp.PrimitiveTree, mapping: dict[str, str]) -> str:
    """Render generated nodes as existing DSL, never Python or terminal aliases."""
    def visit(i: int) -> tuple[str, int]:
        node = tree[i]
        if not node.arity:
            return '(' + mapping[node.value] + ')', i + 1
        left, following = visit(i + 1)
        if node.name == 'neg':
            return f'(-{left})', following
        right, following = visit(following)
        return f'({left}{dict(add="+", sub="-", mul="*")[node.name]}{right})', following
    expression, end = visit(0)
    if end != len(tree):
        raise ValueError('Malformed GP tree')
    return expression


def _rank_signature(dates: pl.Series, values: np.ndarray) -> str:
    """Training-cohort ordinal equivalence, including global sign reversal."""
    ranked = pl.DataFrame({'trade_date': dates, 'value': values}).with_columns(
        pl.when(pl.col('value').is_finite()).then(pl.col('value')).alias('value'))
    ranks = ranked.select((2 * pl.col('value').rank('average').over('trade_date')
        - pl.col('value').count().over('trade_date') - 1).alias('rank'))['rank'].to_numpy()
    finite = np.isfinite(ranks)
    centered = np.where(finite, ranks, 0.)
    nonzero = np.flatnonzero(centered)
    if nonzero.size and centered[nonzero[0]] < 0:
        centered = -centered
    # Integer centered ranks avoid signed-zero and floating standardization noise.
    return hashlib.sha256(np.packbits(finite).tobytes() + centered.astype('<i8').tobytes()).hexdigest()


def _run(frame: pl.DataFrame, terminals: dict[str, str], cfg: GeneticSearchConfig,
         *, mode: str, unique_target: int | None = None) -> dict[str, Any]:
    names = sorted(terminals)
    pset = gp.PrimitiveSet('TRAIN', len(names))
    # DEAP ARG names cannot collide with primitive names or terminal columns.
    mapping = {f'ARG{i}': terminals[name] for i, name in enumerate(names)}
    for fn, arity, name in ((np.add, 2, 'add'), (np.subtract, 2, 'sub'),
                            (np.multiply, 2, 'mul'), (np.negative, 1, 'neg')):
        pset.addPrimitive(fn, arity, name=name)
    toolbox = base.Toolbox()
    toolbox.register('expression', gp.genHalfAndHalf, pset=pset, min_=0, max_=min(2, cfg.max_depth))
    toolbox.register('individual', tools.initIterate, _Individual, toolbox.expression)
    toolbox.register('select', tools.selTournament, tournsize=cfg.tournament_size)
    toolbox.register('mate', gp.cxOnePoint)
    toolbox.register('mutation_expression', gp.genGrow, min_=0, max_=min(2, cfg.max_depth))
    toolbox.register('mutate', gp.mutUniform, expr=toolbox.mutation_expression, pset=pset)
    arrays = [frame[name].cast(pl.Float64).to_numpy() for name in names]
    terminal_signatures = {_rank_signature(frame['trade_date'], values): name
                           for name, values in zip(names, arrays, strict=True)}
    labels = frame.select('symbol', 'trade_date', 'label')
    trials: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}
    evaluated: list[dict[str, Any]] = []
    unique_limit = cfg.max_unique_evaluations if unique_target is None else min(unique_target, cfg.max_unique_evaluations)

    def budget_open() -> bool:
        return len(trials) < cfg.max_attempts and len(cache) < unique_limit

    def assess(ind: _Individual, generation: int, operation: str) -> bool:
        expr = _export(ind, mapping)
        key = ast.dump(ast.parse(expr, mode='eval'), include_attributes=False)
        trial: dict[str, Any] = {'attempt': len(trials) + 1, 'generation': generation,
            'operation': operation, 'tree': str(ind), 'expression': expr,
            'terminal_expression': _export(ind, {f'ARG{i}': name for i, name in enumerate(names)}),
            'depth': ind.height, 'complexity': len(ind)}
        if ind.height > cfg.max_depth:
            trials.append({**trial, 'status': 'invalid', 'reason': 'maximum_tree_depth'})
            return False
        if key in cache:
            previous = cache[key]
            trials.append({**trial, 'status': 'duplicate', 'duplicate_of': previous['attempt']})
            if previous['status'] == 'evaluated':
                ind.fitness.values = (previous['fitness'],)
                return True
            return False
        try:
            with np.errstate(all='ignore'):
                values = np.asarray(gp.compile(expr=ind, pset=pset)(*arrays), dtype=float)
            if values.shape != (frame.height,):
                raise ValueError('expression_shape')
            ic = rank_ic_by_date(labels.with_columns(pl.Series('score', values)), score='score', label='label',
                minimum_symbols=cfg.minimum_symbols, minimum_paired_coverage=cfg.minimum_paired_coverage)
            stats = monthly_ic_summary(ic['trade_date'].to_list(), ic['rank_ic'].to_list(), lag=3)
            if stats['months'] < cfg.minimum_months or stats['mean_ic'] is None:
                raise ValueError('insufficient_valid_months_or_constant_expression')
            direction = 1 if stats['mean_ic'] >= 0 else -1
            fitness = abs(stats['mean_ic']) - cfg.complexity_penalty * len(ind)
            trial.update(status='evaluated', direction=direction, fitness=fitness, train=stats,
                         rank_signature=_rank_signature(frame['trade_date'], values),
                         directed_mean_ic=direction * stats['mean_ic'],
                         monthly_ic=[{'trade_date': str(d), 'rank_ic': v}
                                     for d, v in ic.select('trade_date', 'rank_ic').iter_rows()])
            ind.fitness.values = (fitness,)
            evaluated.append(trial)
        except (ValueError, TypeError, OverflowError, FloatingPointError) as exc:
            trial.update(status='invalid', reason=str(exc))
        cache[key] = trial
        trials.append(trial)
        return trial['status'] == 'evaluated'

    population: list[_Individual] = []
    if mode == 'random':
        while budget_open():
            assess(_Individual(gp.genHalfAndHalf(pset=pset, min_=0, max_=cfg.max_depth)), 0, 'random')
    else:
        while len(population) < cfg.population_size and budget_open():
            ind = toolbox.individual()
            if assess(ind, 0, 'initial'):
                population.append(ind)
        for generation in range(1, cfg.generations + 1):
            if not population or not budget_open():
                break
            children = []
            for _ in range(cfg.population_size):
                if not budget_open():
                    break
                ind = copy.deepcopy(toolbox.select(population, 1)[0])
                operations = []
                if random.random() < cfg.crossover_probability:
                    other = copy.deepcopy(toolbox.select(population, 1)[0])
                    ind, _ = toolbox.mate(ind, other)
                    operations.append('crossover')
                if random.random() < cfg.mutation_probability:
                    ind, = toolbox.mutate(ind)
                    operations.append('mutation')
                if assess(ind, generation, '+'.join(operations) or 'reproduction'):
                    children.append(ind)
            population = tools.selBest(population + children, cfg.population_size)
    ranked = sorted(evaluated, key=lambda r: (-r['fitness'], r['complexity'], r['expression']))
    distinct = []
    signatures: dict[str, str] = dict(terminal_signatures)
    for row in ranked:
        signature = row['rank_signature']
        if signature in signatures:
            row['candidate_exclusion'] = 'training_rank_equivalent'
            row['equivalent_to'] = signatures[signature]
        else:
            signatures[signature] = row['expression']
            distinct.append(row)
    candidates = [{k: row[k] for k in ('expression', 'terminal_expression', 'direction', 'fitness', 'complexity', 'depth',
                   'train', 'directed_mean_ic', 'monthly_ic')} for row in distinct[:cfg.candidate_count]]
    return {'candidates': candidates, 'trials': trials, 'summary': {
        'mode': mode, 'attempts': len(trials), 'unique_evaluations': len(cache),
        'valid_evaluations': len(evaluated), 'invalid_attempts': sum(r['status'] == 'invalid' for r in trials),
        'duplicate_attempts': sum(r['status'] == 'duplicate' for r in trials),
        'rank_equivalent_candidates_excluded': len(ranked) - len(distinct),
        'unique_evaluation_target': unique_limit, 'target_reached': len(cache) == unique_limit,
        'training_rows': frame.height, 'training_months': frame['trade_date'].n_unique(),
        'last_signal_date': str(frame['trade_date'].max()), 'last_label_exit': str(frame['label_exit_date'].max()),
        'configuration': {**asdict(cfg), 'training_end': str(cfg.training_end)},
        'fitness_definition': 'abs(mean monthly cross-sectional Spearman RankIC) - complexity_penalty * tree_nodes'}}


def search_genetic(panel: pl.DataFrame, terminals: dict[str, str], config: GeneticSearchConfig) -> dict[str, Any]:
    """Train only on this panel. Caller owns PIT terminal construction and units.

    Returned directions and rankings are training proposals, not admission results.
    Optional random search has the same attempt cap and GP's actual unique-evaluation
    count as its target; any shortfall is explicit. All proposals, including depth
    failures and cached repeats, consume the total attempt budget.
    """
    frame = _validate(panel, terminals, config)
    with _RNG_LOCK:
        previous = random.getstate()
        try:
            random.seed(config.seed)
            result = _run(frame, terminals, config, mode='genetic')
            if config.random_baseline:
                random.seed(config.seed)
                result['random_baseline'] = _run(frame, terminals, replace(config, random_baseline=False),
                    mode='random', unique_target=result['summary']['unique_evaluations'])
            return result
        finally:
            random.setstate(previous)
