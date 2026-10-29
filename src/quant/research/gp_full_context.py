"""Evaluate only new GP cross-section subtrees on the complete market grid."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

import polars as pl

from quant.data.gp_context_inputs import FullMarketInputs, KEYS, dump, sha256
from quant.factors.expressions import evaluate_expressions

VERSION = 'full_market_observed_cross_subtrees_v1'
LEGACY = 'sample_cross_section_v1'
PUBLISHED_TERMINALS = 'published_terminal_boundary_v1'
CROSS = {'rank', 'scale', 'ind_neutralize'}


def scope_cross_sections(expression: str) -> str:
    """Make the new operator population explicit in the exported DSL formula.

    Padding and a different warm-up length can introduce non-traded names with
    carried financial values. Only a current positive observed close admits a
    name to these *new* cross sections. Existing library terminal formulas are
    expanded afterwards, so their frozen definitions are not rewritten.
    """
    condition = ast.parse('adj_close > 0', mode='eval').body
    missing = ast.parse('0 / 0', mode='eval').body

    class Scope(ast.NodeTransformer):
        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id in CROSS:
                child = node.args[0]
                scoped = (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                          and child.func.id == 'where' and len(child.args) == 3
                          and ast.dump(child.args[0]) == ast.dump(condition)
                          and ast.dump(child.args[2]) == ast.dump(missing))
                if not scoped:
                    node.args[0] = ast.Call(func=ast.Name(id='where', ctx=ast.Load()),
                                           args=[condition, child, missing], keywords=[])
            return node

    return ast.unparse(Scope().visit(ast.parse(expression, mode='eval')).body)


def expand(expression: str, mapping: dict[str, str]) -> str:
    class Expand(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.parse(mapping[node.id], mode='eval').body if node.id in mapping else node
    return ast.unparse(Expand().visit(ast.parse(expression, mode='eval')).body)


def replace_cross_subtrees(expression: str, materialize) -> str:
    """An outer cross-section node absorbs its entire nested/time-series operand."""
    class Replace(ast.NodeTransformer):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id in CROSS:
                return ast.copy_location(ast.Name(id=materialize(ast.unparse(node)), ctx=ast.Load()), node)
            return self.generic_visit(node)
    return ast.unparse(Replace().visit(ast.parse(expression, mode='eval')).body)


class FullContextEvaluator:
    """Persistent cohort projections; no trial-wide full-market factor battery.

    The frozen subtree/row/storage budgets bound extra work without increasing
    population, generations or resampling failed trials. Budget failures are
    explicit computational failures, not measured zero IC or alpha rejection.
    """

    def __init__(self, panel: pl.DataFrame, mapping: dict[str, str], output: Path,
                 *, identity: dict, maximum_subtrees: int, maximum_disk_mb: int,
                 reader, verify_sources=None):
        self.panel, self.mapping, self.output = panel, mapping, output
        self.terminal_policy = identity.get('terminal_input_policy')
        if self.terminal_policy not in (None,PUBLISHED_TERMINALS):
            raise ValueError('Unknown GP terminal input policy')
        self.reader, self.verify_sources = reader, verify_sources
        self.maximum_subtrees = maximum_subtrees
        self.maximum_bytes = maximum_disk_mb * 1024**2
        output.mkdir(parents=True, exist_ok=True)
        contract = {**identity, 'context_version': VERSION, 'population': 'same_date_observed_positive_adjusted_close',
                    'maximum_subtrees': maximum_subtrees,
                    'maximum_disk_mb': maximum_disk_mb, 'mapping': mapping}
        self.identity = hashlib.sha256(json.dumps(contract, sort_keys=True, default=str).encode()).hexdigest()
        path = output/'contract.json'
        if path.exists() and json.loads(path.read_text(encoding='utf-8')) != json.loads(json.dumps(contract, default=str)):
            raise ValueError('GP calculation context changed; preserve this run and use a new directory')
        if not path.exists():
            dump(path, contract)
        self.registry_path = output/'subtrees.json'
        self.registry = json.loads(self.registry_path.read_text(encoding='utf-8')) if self.registry_path.exists() else {}
        self.keys = panel.select(KEYS)
        self.low, self.high = panel['trade_date'].min(), panel['trade_date'].max()
        self.metrics = {'projection_cache_hits': 0, 'new_subtrees': 0, 'year_evaluations': 0,
                        'context_seconds': 0.0, 'context_budget_failures': 0}

    def _reserve(self, expression: str) -> tuple[str, Path, dict]:
        key = hashlib.sha256((self.identity + ast.dump(ast.parse(expression, mode='eval'))).encode()).hexdigest()
        folder = self.output/key
        if key not in self.registry:
            if len(self.registry) >= self.maximum_subtrees:
                self.metrics['context_budget_failures'] += 1
                raise ValueError('GP_CONTEXT_SUBTREE_BUDGET: trial not evaluated; no sample-scope fallback')
            self.registry[key] = {'expression': expression, 'expanded': expand(expression, self.mapping), 'parts': {}}
            dump(self.registry_path, self.registry)
            self.metrics['new_subtrees'] += 1
        folder.mkdir(exist_ok=True)
        return key, folder, self.registry[key]

    def materialize(self, expression: str) -> tuple[str, pl.DataFrame]:
        if self.verify_sources:
            self.verify_sources()
        key, folder, record = self._reserve(expression)
        name = 'gpcontext_' + key[:20]
        pieces = []
        for year in range(self.low.year, self.high.year + 1):
            low, high = max(self.low, dt.date(year, 1, 1)), min(self.high, dt.date(year, 12, 31))
            wanted = self.keys.filter(pl.col('trade_date').is_between(low, high))
            if wanted.is_empty():
                continue
            path = folder/f'{year}.parquet'
            part = record['parts'].get(str(year))
            if part:
                if sha256(path) != part['sha256']:
                    raise ValueError('Frozen GP cross-section projection changed')
                values = pl.read_parquet(path)
                self.metrics['projection_cache_hits'] += 1
            else:
                from quant.research.slice_budget import checkpoint
                checkpoint()
                began = time.perf_counter()
                full, evaluated_expression, basis = self.reader(expression, record['expanded'], low, high)
                evaluated = evaluate_expressions(full, {'value': evaluated_expression})
                values = wanted.join(evaluated, on=KEYS, how='left', validate='1:1')
                path_tmp = path.with_suffix('.partial.parquet')
                values.write_parquet(path_tmp)
                occupied = sum(p.stat().st_size for p in self.output.glob('*/*.parquet') if p != path_tmp)
                if occupied + path_tmp.stat().st_size > self.maximum_bytes:
                    path_tmp.unlink()
                    self.metrics['context_budget_failures'] += 1
                    raise ValueError('GP_CONTEXT_STORAGE_BUDGET: trial not evaluated; no approximation')
                path_tmp.replace(path)
                elapsed = time.perf_counter() - began
                record['parts'][str(year)] = {'sha256': sha256(path), 'rows': values.height,
                    'basis': basis, 'seconds': elapsed, 'full_rows': full.height}
                dump(self.registry_path, self.registry)
                self.metrics['year_evaluations'] += 1
                self.metrics['context_seconds'] += elapsed
            if (values.height != wanted.height or values.select(KEYS).join(wanted, on=KEYS, how='anti').height
                    or values.select(pl.struct(KEYS).is_duplicated().any()).item()):
                raise ValueError('GP cross-section projection keys differ from frozen sample')
            pieces.append(values)
        return name, pl.concat(pieces).rename({'value': name})

    def evaluate(self, expression: str) -> pl.DataFrame:
        projected = {}

        def materialize(subtree):
            name, values = self.materialize(subtree)
            projected[name] = values
            return name

        # Preserve legacy expansion contracts. New searches use the exact
        # published-terminal boundary also consumed by N3 materialized plans.
        expanded = expand(expression, self.mapping)
        selected = expression if self.terminal_policy == PUBLISHED_TERMINALS else expanded
        rewritten = replace_cross_subtrees(scope_cross_sections(selected), materialize)
        fields = {node.id for node in ast.walk(ast.parse(rewritten, mode='eval')) if isinstance(node, ast.Name)}
        # Published values are authoritative only under the explicit policy.
        usable = set(self.panel.columns) - set(KEYS)
        if self.terminal_policy != PUBLISHED_TERMINALS:
            usable -= set(self.mapping)
        sample = self.panel.select(*KEYS, *sorted(fields & usable))
        for values in projected.values():
            sample = sample.join(values, on=KEYS, how='left', validate='1:1')
        result = evaluate_expressions(sample, {'candidate': rewritten})
        dump(self.output/'metrics.json', self.metrics)
        return result


def build_evaluator(panel: pl.DataFrame, mapping: dict[str, str], settings: dict,
                    output: Path, sample: Path, labels: Path) -> FullContextEvaluator:
    options = settings['genetic']
    if options.get('calculation_context') != VERSION:
        raise ValueError('Unknown full-market GP context version')
    folder = output/'full_context'
    folder.mkdir(exist_ok=True)
    reader = FullMarketInputs(data_root=Path(settings['data_root']), refresh_config=Path(settings['refresh_config']),
        output=folder, start=panel['trade_date'].min(), end=panel['trade_date'].max(), mapping=mapping,
        maximum_rows=options['context_max_rows'], memory_mb=options['context_memory_mb'])
    from quant.data.gp_minute_snapshot import POLICY
    minute_policy = {'minute_input_policy':POLICY} if reader.freeze_minutes else {}
    terminal_policy = ({'terminal_input_policy':options['terminal_input_policy']}
                       if options.get('terminal_input_policy') else {})
    result = FullContextEvaluator(panel, mapping, folder, identity={
        **minute_policy,
        **terminal_policy,
        'sample_sha256': sha256(sample), 'labels_sha256': sha256(labels),
        'refresh_sha256': sha256(reader.config), 'data_root': str(reader.root.resolve()),
        'context_max_rows': options['context_max_rows'], 'context_memory_mb': options['context_memory_mb'],
        'expression_identity': options['expression_identity'],
    }, maximum_subtrees=options['context_max_subtrees'], maximum_disk_mb=options['context_max_disk_mb'],
       reader=reader.read, verify_sources=reader.verify_sources)
    result.inputs = reader
    return result
