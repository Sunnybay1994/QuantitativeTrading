"""Keep the published-terminal boundary used by full-context GP training.

Expanding a previously ranked library factor is not a floating-point identity:
a different rolling prefix can move a tiny residual across a zero tie. The
exported formula stays unchanged; its verified library subexpressions use the
same published observations as N2. New cross sections retain N2's full-market
reader and observed-bar population rule.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import polars as pl

from quant.data.gp_context_inputs import FullMarketInputs, KEYS, dump, sha256
from quant.factors.expressions import evaluate_expressions
from quant.research.gp_expression_identity import LEGACY, canonical_expression
from quant.research.gp_full_context import VERSION, expand, replace_cross_subtrees, scope_cross_sections


def materialized_plans(definitions: list) -> dict:
    """Only route definitions with an explicit, verifiable N2 context receipt."""
    sources, plans = {}, {}
    for definition in definitions:
        source = Path(definition.source_ref)
        if source.name != 'search.json' or not source.is_file():
            continue
        if source not in sources:
            sources[source] = json.loads(source.read_text(encoding='utf-8'))
        row = next((r for r in sources[source].get('candidates', [])
                    if r.get('factor_id') == definition.id and r.get('calculation_context') == VERSION), None)
        if row is None:
            continue
        mapping = json.loads((source.parent/'terminal_mapping.json').read_text(encoding='utf-8'))
        terminal = scope_cross_sections(row['terminal_expression'])
        identity = row.get('expression_identity', LEGACY)
        expanded = canonical_expression(expand(terminal, mapping), identity)
        if (row['expression'] != definition.expr or row['direction'] != definition.direction
                or ast.dump(ast.parse(expanded, mode='eval')) != ast.dump(ast.parse(
                    canonical_expression(definition.expr, identity), mode='eval'))):
            raise ValueError('GP materialized terminal mapping differs from frozen definition')
        plans[definition.id] = {'source': source, 'mapping': mapping, 'terminal': terminal}
    return plans


def evaluate_materialized(panel: pl.DataFrame, plans: dict, *, data_root: Path,
                          refresh_config: Path, artifact_root: Path) -> pl.DataFrame:
    """Evaluate verified GP plans on a full padded grid, without changing N2."""
    output = panel.select(KEYS)
    low, high = panel['trade_date'].min(), panel['trade_date'].max()
    selection = hashlib.sha256('\n'.join(sorted(plans)).encode()).hexdigest()[:16]
    folder = artifact_root/'gp_materialized'/f'{low}_{high}'/selection
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder/'sources.json'
    prior = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    sources, stamps = {}, {}

    def track(path):
        key = str(path.resolve())
        if key in sources:
            return
        digest = sha256(path) if path.exists() else None
        if key in prior and prior[key] != digest:
            raise ValueError(f'GP materialized source changed: {path}')
        sources[key] = digest
        stamps[key] = (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None

    for index, source in enumerate(dict.fromkeys(p['source'] for p in plans.values())):
        group = {name: p for name, p in plans.items() if p['source'] == source}
        mapping = next(iter(group.values()))['mapping']
        track(source)
        track(source.parent/'terminal_mapping.json')
        track(refresh_config)
        projections, reader = {}, None

        def materialize(expression):
            nonlocal reader
            if expression not in projections:
                if reader is None:
                    context_folder = folder/f'cross_{index}'
                    context_folder.mkdir(exist_ok=True)
                    reader = FullMarketInputs(data_root=data_root, refresh_config=refresh_config,
                        output=context_folder, start=low, end=high, mapping=mapping,
                        maximum_rows=6_000_000, memory_mb=256)
                full, evaluated, _ = reader.read(expression, expand(expression, mapping), low, high)
                name = f'gpcontext_materialized_{len(projections)}'
                values = evaluate_expressions(full, {name: evaluated})
                projections[expression] = (name, values)
            return projections[expression][0]

        expressions = {name: replace_cross_subtrees(plan['terminal'], materialize)
                       for name, plan in group.items()}
        names = {n.id for expr in expressions.values() for n in ast.walk(ast.parse(expr, mode='eval'))
                 if isinstance(n, ast.Name)}
        sample = panel.select(*KEYS, *sorted(names & set(panel.columns) - set(KEYS) - set(mapping)))
        for name in sorted(names & mapping.keys()):
            definition_path = data_root/'factors'/name.removeprefix('gp_')/'definition.json'
            track(definition_path)
            saved = json.loads(definition_path.read_text(encoding='utf-8'))
            if ast.dump(ast.parse(saved['expr'], mode='eval')) != ast.dump(ast.parse(mapping[name], mode='eval')):
                raise ValueError(f'GP published terminal definition changed: {name}')
            paths = [definition_path.parent/f'year={year}'/'data.parquet'
                     for year in range(low.year, high.year + 1)]
            for path in paths:
                track(path)
            available = [p for p in paths if p.exists()]
            if available:
                values = pl.scan_parquet(available).filter(pl.col('trade_date').is_between(low, high)).select(
                    pl.col('ts_code').alias('symbol'), 'trade_date', pl.col('value').cast(pl.Float64).alias(name)).collect()
                sample = sample.join(values, on=KEYS, how='left', validate='1:1')
            else:
                # Match N2's explicit unavailable-year observation, never zero-fill.
                sample = sample.with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
        for _, values in projections.values():
            sample = sample.join(values, on=KEYS, how='left', validate='1:1')
        values = evaluate_expressions(sample, expressions)
        output = output.join(values, on=KEYS, how='left', validate='1:1')
        if reader is not None:
            reader.verify_sources()
    for key, before in stamps.items():
        path = Path(key)
        after = (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None
        if after != before:
            raise ValueError(f'GP materialized source changed during evaluation: {key}')
    if prior and prior != sources:
        raise ValueError('GP materialized source inventory changed')
    dump(manifest_path, sources)
    return output
