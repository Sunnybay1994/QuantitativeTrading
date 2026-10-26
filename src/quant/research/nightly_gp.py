"""DEAP expression search using the same daily DSL as full-history computation."""
import ast
import copy
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import polars as pl
from deap import base, gp, tools  # type: ignore[import-untyped]
from scipy.stats import rankdata  # type: ignore[import-untyped]

from quant.factors.expressions import _UNARY, _WINDOW, evaluate_expressions
from quant.factors.library import load_library
from quant.research.factor_battery_statistics import monthly_ic_summary, preprocess_cross_section, rank_ic_by_date

_FITNESS_PREPROCESSING = 'battery_raw_mad3_scale1.4826_v1'


def preprocess_training_scores(frame: pl.DataFrame) -> pl.DataFrame:
    """Use the battery's raw score transform before training IC and redundancy."""
    sections = []
    for section in frame.partition_by('trade_date'):
        scores = preprocess_cross_section(
            section['candidate'].to_numpy(), np.zeros(section.height),
            np.full(section.height, '', dtype=object), neutralize=False)
        sections.append(section.with_columns(pl.Series('candidate', scores).fill_nan(None)))
    return pl.concat(sections) if sections else frame


def primitive_set(terminals: list[str]) -> gp.PrimitiveSet:
    """Every DSL operation is available; integer windows are always valid constants."""
    pset = gp.PrimitiveSet('DAILY', 0)
    for terminal in terminals:
        pset.addTerminal(terminal)
    for name, operator in [('add', '+'), ('sub', '-'), ('mul', '*'), ('div', '/'), ('pow', '**')]:
        pset.addPrimitive(lambda a, b, op=operator: f'({a}{op}{b})', 2, name=name)
    for name, operator in [('gt', '>'), ('ge', '>='), ('lt', '<'), ('le', '<='), ('eq', '=='), ('ne', '!=')]:
        pset.addPrimitive(lambda a, b, op=operator: f'(({a}{op}{b})*1.0)', 2, name=name)
    pset.addPrimitive(lambda a: f'(-{a})', 1, name='neg')
    for name in sorted(_UNARY):
        pset.addPrimitive(lambda a, fn=name: f'{fn}({a})', 1, name=name)
    for name in sorted(_WINDOW):
        for window in (5, 20, 60):
            if name in {'ts_corr', 'ts_cov'}:
                pset.addPrimitive(lambda a, b, fn=name, n=window: f'{fn}({a},{b},{n})', 2, name=f'{name}_{window}')
            elif name == 'ts_quantile':
                for probability in (.25, .75):
                    pset.addPrimitive(lambda a, q=probability, n=window: f'ts_quantile({a},{q},{n})', 1,
                                      name=f'quantile_{window}_{int(probability*100)}')
            else:
                pset.addPrimitive(lambda a, fn=name, n=window: f'{fn}({a},{n})', 1, name=f'{name}_{window}')
    pset.addPrimitive(lambda a, b, c: f'where(({a})>0,{b},{c})', 3, name='where')
    pset.addPrimitive(lambda a: f'ind_neutralize({a},industry_l1)', 1, name='ind_neutralize')
    return pset


def expand_expression(expression: str, mapping: dict[str, str]) -> str:
    class Expand(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.parse(mapping[node.id], mode='eval').body if node.id in mapping else node
    return ast.unparse(Expand().visit(ast.parse(expression, mode='eval')).body)


def recovery_diagnostics(output: Path) -> dict:
    log=output/'process.log'
    content=log.read_text(encoding='utf-8',errors='replace') if log.exists() else ''
    result={'observed_native_dtype_failures':content.count('pyo3_runtime.PanicException:'),
            'observed_deap_restore_type_failures':content.count('IndexError: The gp.generate function tried to add'),
            'dtype_repair':'float64 numeric inputs and numeric comparison results',
            'deap_repair':'restore untyped object terminal return types before mutation',
            'checkpoint_preserves':'population, RNG state and evaluated fitness cache'}
    (output/'recovery_diagnostics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def maximum_correlation(frame: pl.DataFrame, score: str, controls: list[str], minimum: int = 100) -> float:
    """Maximum across factors of mean absolute monthly common-stock Spearman."""
    totals=np.zeros(len(controls))
    counts=np.zeros(len(controls))
    for section in frame.partition_by('trade_date'):
        values=section.select(score,*controls).to_numpy()
        values=values[np.isfinite(values[:,0])]
        if len(values)<minimum:
            continue
        x=values[:,1:]
        mask=np.isfinite(x)
        y=np.where(mask,values[:,0,None],np.nan)
        x=np.where(mask,x,np.nan)
        xr=rankdata(x,axis=0,nan_policy='omit')
        yr=rankdata(y,axis=0,nan_policy='omit')
        n=mask.sum(axis=0)
        xc=np.where(mask,xr-np.nansum(xr,axis=0)/np.maximum(n,1),0.)
        yc=np.where(mask,yr-np.nansum(yr,axis=0)/np.maximum(n,1),0.)
        denominator=np.sqrt(np.sum(xc*xc,axis=0)*np.sum(yc*yc,axis=0))
        valid=(n>=minimum)&(denominator>1e-12)
        rho=np.divide(np.sum(xc*yc,axis=0),denominator,out=np.zeros(len(controls)),where=valid)
        totals+=np.where(valid,np.abs(rho),0.)
        counts+=valid
    qualified=counts>0
    return float(np.max(totals[qualified]/counts[qualified])) if qualified.any() else 1.


def search(panel: pl.DataFrame, labels: pl.DataFrame, mapping: dict[str, str], settings: dict,
           output: Path, *, family: str, context_evaluator=None) -> list[dict]:
    if 'predictive_priority' in settings:
        from quant.research.predictive_priority_search import search_predictive
        return search_predictive(panel, labels, mapping, settings, output, family=family)
    from quant.research.gp_expression_identity import (
        LEGACY as LEGACY_IDENTITY, canonical_expression, expression_key)
    from quant.research.gp_full_context import LEGACY as LEGACY_CONTEXT, VERSION as FULL_CONTEXT
    identity_version = settings.get('expression_identity', LEGACY_IDENTITY)
    context_version = settings.get('calculation_context', LEGACY_CONTEXT)
    if context_version not in (LEGACY_CONTEXT, FULL_CONTEXT):
        raise ValueError('Unknown GP calculation context')
    if context_version == FULL_CONTEXT and context_evaluator is None:
        raise ValueError('Full-market GP context requires its frozen evaluator')
    if context_version == LEGACY_CONTEXT and context_evaluator is not None:
        raise ValueError('Cannot apply new context semantics to a legacy run')
    input_identity = context_evaluator.identity if context_evaluator else None
    if identity_version != LEGACY_IDENTITY and input_identity is None:
        # A direct caller may request symmetry de-duplication alone. Its cache
        # still belongs to these values, labels, schema and terminal definitions.
        digest = hashlib.sha256(json.dumps(mapping, sort_keys=True).encode())
        for frame in (panel, labels):
            digest.update(str(frame.schema).encode())
            digest.update(frame.hash_rows(seed=20261004).to_numpy().tobytes())
        input_identity = digest.hexdigest()
    aliases_path = output/'expression_aliases.json'
    aliases = json.loads(aliases_path.read_text(encoding='utf-8')) if aliases_path.exists() else {}
    if any(row.get('input_identity') != input_identity or row.get('expression_identity') != identity_version
           for row in aliases.values()):
        raise ValueError('GP alias/input version changed; use a new run directory')
    random.seed(settings['seed'])
    controls = list(mapping)
    basics: list[str] = [c for c in ('adj_open', 'adj_high', 'adj_low', 'adj_close', 'volume', 'amount',
                          'turnover_rate', 'total_mv', 'circ_mv', 'pe_ttm', 'pb') if c in panel.columns]
    panel=panel.with_columns(pl.col(c).cast(pl.Float64) for c in controls+basics)
    pset = primitive_set(controls + basics)
    favored=settings.get('favored_terminals',[])
    pset.terminals[object].extend([terminal for terminal in list(pset.terminals[object])
                                  if terminal.value in favored]*3)
    class Fitness(base.Fitness):
        weights = (1.,)
    class Individual(gp.PrimitiveTree):
        def __init__(self, content):
            super().__init__(content)
            self.fitness = Fitness()
    toolbox = base.Toolbox()
    toolbox.register('individual', lambda: Individual(gp.genHalfAndHalf(pset=pset, min_=0, max_=2)))
    toolbox.register('select', tools.selTournament, tournsize=3)
    monthly = panel.select('symbol', 'trade_date', *controls).join(labels, on=['symbol', 'trade_date'])
    checkpoint=output/'search_checkpoint.json'
    cached=json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else None
    cache_path=output/'fitness_cache.json'
    records=cached['records'] if cached else (json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else [])
    if any(row.get('calculation_context', LEGACY_CONTEXT) != context_version
           or row.get('expression_identity', LEGACY_IDENTITY) != identity_version
           or row.get('input_identity') != input_identity for row in records):
        raise ValueError('GP calculation/identity/input version changed; use a new run directory')
    if context_evaluator and context_evaluator.verify_sources:
        context_evaluator.verify_sources()
    cross_stock = settings.get('cross_stock')
    assignments = {}
    objective = (settings.get('search_objective')
                 or (cross_stock['version'] if cross_stock else 'pooled_mean_ic_v1'))
    if any(row.get('search_objective', 'pooled_mean_ic_v1') != objective for row in records):
        raise ValueError('GP search objective changed; use a new run directory')
    if cross_stock:
        from quant.research.cross_stock_search import stock_groups
        assignments = stock_groups(labels['symbol'].unique().to_list(), groups=cross_stock['sample_groups'],
            per_group=cross_stock['symbols_per_group'], seed=cross_stock['sample_seed'])
        contract = json.loads(json.dumps({'config': cross_stock, 'assignments': assignments,
            'seed': settings['seed'], 'mapping': mapping}, default=str))
        contract_path = output/'search_contract.json'
        if contract_path.exists():
            if json.loads(contract_path.read_text(encoding='utf-8')) != contract:
                raise ValueError('Frozen cross-stock search contract changed')
        elif cached or records:
            raise ValueError('Cross-stock checkpoint lacks its frozen search contract')
        else:
            temporary = contract_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(contract, indent=2), encoding='utf-8')
            temporary.replace(contract_path)
    if any(row.get('fitness_preprocessing') != _FITNESS_PREPROCESSING for row in records):
        raise ValueError('GP fitness preprocessing changed; preserve this checkpoint and use a new run directory')
    cache={expression_key(r['terminal_expression'], identity_version):r for r in records}
    def assess(ind):
        observed = gp.compile(ind, pset)
        expression = observed
        if context_evaluator:
            from quant.research.gp_full_context import scope_cross_sections
            expression = scope_cross_sections(expression)
        expression = canonical_expression(expression, identity_version)
        key = expression_key(expression, identity_version)
        if identity_version != LEGACY_IDENTITY:
            aliases[observed] = {'canonical_terminal_expression': expression, 'canonical_key': key,
                                 'input_identity': input_identity, 'expression_identity': identity_version}
        if key in cache:
            ind.fitness.values = (cache[key]['fitness'],)
            return
        row = {'expression': canonical_expression(expand_expression(expression, mapping), identity_version),
               'terminal_expression': expression,
               'complexity': len(ind), 'depth': ind.height, 'fitness': -1e9,
               'fitness_preprocessing': _FITNESS_PREPROCESSING, 'search_objective': objective}
        if context_version != LEGACY_CONTEXT or identity_version != LEGACY_IDENTITY:
            row.update(calculation_context=context_version, expression_identity=identity_version,
                       input_identity=input_identity, canonical_key=key)
        try:
            if ind.height > settings['max_depth']:
                raise ValueError('depth exceeded')
            fields=sorted({node.id for node in ast.walk(ast.parse(expression,mode='eval'))
                           if isinstance(node,ast.Name) and node.id in panel.columns}-{'symbol','trade_date'})
            values = (context_evaluator.evaluate(expression) if context_evaluator else
                      evaluate_expressions(panel.select('symbol','trade_date',*fields), {'candidate': expression}))
            scored = monthly.join(values.select('symbol', 'trade_date', 'candidate'), on=['symbol', 'trade_date'])
            scored = preprocess_training_scores(scored)
            series = rank_ic_by_date(scored, score='candidate', label='label', minimum_symbols=100,
                                     minimum_paired_coverage=.8)
            stats = monthly_ic_summary(series['trade_date'].to_list(), series['rank_ic'].to_list())
            if stats['months'] < 48 or stats['mean_ic'] is None:
                raise ValueError('fewer than 48 valid training months')
            corr = maximum_correlation(scored, 'candidate', controls)
            measured = dict(direction=1 if stats['mean_ic'] >= 0 else -1, train=stats, maximum_rank_correlation=corr,
                            fitness=abs(stats['mean_ic']) - settings['complexity_penalty']*len(ind) - .5*corr)
            if cross_stock:
                from quant.research.cross_stock_search import group_fitness
                measured.update(group_fitness(scored, assignments, config=cross_stock, complexity=len(ind),
                                        maximum_correlation=corr))
            row.update(measured)
        except BaseException as exc:
            # Rust's PanicException inherits BaseException; preserve the offending
            # expression as an invalid trial without swallowing interrupts/exits.
            if not isinstance(exc,(ValueError,TypeError,pl.exceptions.PolarsError,OverflowError)) and type(exc).__name__!='PanicException':
                raise
            row['error'] = str(exc)[:500]
            row['error_type']=type(exc).__name__
        cache[key] = row
        records.append(row)
        if len(records)%20==0:
            temporary=cache_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(records),encoding='utf-8')
            temporary.replace(cache_path)
        ind.fitness.values = (row['fitness'],)
    def tuples(value):
        return tuple(tuples(v) for v in value) if isinstance(value,list) else value
    if cached:
        population=[Individual(gp.PrimitiveTree.from_string(tree,pset)) for tree in cached['population']]
        # DEAP infers literal strings as ret=str when deserializing an untyped
        # tree; its primitives use object. Restore that original untyped grammar.
        for individual in population:
            for node in individual:
                if not node.arity:
                    node.ret=object
        random.setstate(tuples(cached['random_state']))
    else:
        population = [toolbox.individual() for _ in range(settings['population_size'])]
    first_generation=cached['generation'] if cached else 0
    for generation in range(first_generation,settings['generations'] + 1):
        for ind in population:
            assess(ind)
        (output/'search_progress.json').write_text(json.dumps({'generation': generation,
            'unique_evaluations': len(records)}, indent=2), encoding='utf-8')
        temporary=checkpoint.with_suffix('.tmp')
        temporary.write_text(json.dumps({'generation':generation,'population':[str(i) for i in population],
            'random_state':random.getstate(),'records':records}),encoding='utf-8')
        temporary.replace(checkpoint)
        if identity_version != LEGACY_IDENTITY:
            from quant.data.gp_context_inputs import dump
            dump(aliases_path, aliases)
        # A timed-out run retains real best-so-far candidates; resume does not resample them.
        (output/'best_so_far.json').write_text(json.dumps(sorted([r for r in records if 'error' not in r],
            key=lambda r:-r['fitness'])[:20],indent=2),encoding='utf-8')
        if generation == settings['generations']:
            break
        from quant.research.slice_budget import checkpoint as slice_checkpoint
        slice_checkpoint()
        children = [copy.deepcopy(i) for i in toolbox.select(population, len(population))]
        for index, ind in enumerate(children):
            if random.random() < .7:
                gp.cxOnePoint(ind, copy.deepcopy(random.choice(population)))
            if random.random() < .3:
                gp.mutUniform(ind, expr=lambda **kw: gp.genGrow(min_=0, max_=2, **kw), pset=pset)
            if ind.height > settings['max_depth']:
                children[index] = copy.deepcopy(random.choice(population))
        population = tools.selBest(population, 10) + children[:len(children)-10]
    unique: dict[str,dict]={}
    for row in sorted([r for r in records if 'error' not in r],key=lambda r:-r['fitness']):
        normalized = canonical_expression(row['expression'], identity_version)
        unique.setdefault(ast.dump(ast.parse(normalized,mode='eval')),row)
    winners = list(unique.values())[:20]
    library = output/'library'
    library.mkdir(exist_ok=True)
    for row in winners:
        row['factor_id'] = 'ngp_' + hashlib.sha256(row['expression'].encode()).hexdigest()[:16]
        definition = dict(id=row['factor_id'], expr=row['expression'], direction=row['direction'],
                          family=f'nightly_{family}', source_ref=str(output/'search.json'))
        (library/f"{row['factor_id']}.toml").write_text(''.join(f'{k} = {json.dumps(v)}\n' for k,v in definition.items()), encoding='utf-8')
    if context_evaluator and winners:
        # Preserve the exact pre-MAD values for the natural N3 computation check.
        # Receipt uses a fresh registry so a full search budget cannot abort N2.
        from quant.data.gp_context_inputs import dump, sha256
        from quant.research.gp_full_context import FullContextEvaluator
        contract = json.loads((context_evaluator.output/'contract.json').read_text(encoding='utf-8'))
        identity = {k: v for k, v in contract.items()
                    if k not in ('context_version', 'population', 'maximum_subtrees',
                                 'maximum_disk_mb', 'mapping')}
        receipt_evaluator = FullContextEvaluator(
            context_evaluator.panel, context_evaluator.mapping, output/'full_context_receipt',
            identity=identity, maximum_subtrees=contract['maximum_subtrees'],
            maximum_disk_mb=contract['maximum_disk_mb'], reader=context_evaluator.reader,
            verify_sources=context_evaluator.verify_sources)
        saved_values, kept = [], []
        for row in winners:
            # Receipt must match N3's compute of definition.expr (library expression),
            # not the opaque grammar terminal that may still name mapped gp_* shortcuts.
            try:
                values = receipt_evaluator.evaluate(row['expression'])
            except ValueError as exc:
                message = str(exc)
                if 'GP_CONTEXT_SUBTREE_BUDGET' not in message and 'GP_CONTEXT_STORAGE_BUDGET' not in message:
                    raise
                (library/f"{row['factor_id']}.toml").unlink(missing_ok=True)
                continue
            except (pl.exceptions.PolarsError, OverflowError):
                (library/f"{row['factor_id']}.toml").unlink(missing_ok=True)
                continue
            saved_values.append(monthly.select('symbol', 'trade_date').join(
                values, on=['symbol', 'trade_date'], how='left', validate='1:1').with_columns(
                    pl.lit(row['factor_id']).alias('factor')))
            kept.append(row)
        winners = kept
        if saved_values:
            values_path = output/'training_candidate_values.parquet'
            temporary = values_path.with_suffix('.partial.parquet')
            pl.concat(saved_values).write_parquet(temporary)
            temporary.replace(values_path)
            dump(output/'training_values_manifest.json', {
                'calculation_context': context_version, 'expression_identity': identity_version,
                'input_identity': input_identity, 'values_sha256': sha256(values_path),
                'labels_sha256': sha256(output/'monthly_sample.parquet'),
                'directions': {row['factor_id']: row['direction'] for row in winners},
                'expressions': {row['factor_id']: row['expression'] for row in winners}})
    (output/'search.json').write_text(json.dumps({'candidates': winners, 'trials': records}, indent=2), encoding='utf-8')
    return winners


def select_family(groups: dict[str, list[str]], coverage: dict[str, int], seed: int,
                  frozen: dict | None = None) -> dict:
    """Rotate preferences, using only families with the unchanged training coverage."""
    families = list(groups)
    requested = families[seed % len(families)]
    available = {name: sum(coverage.get(c, 0) >= 72 for c in columns)
                 for name, columns in groups.items()}
    if frozen is not None:
        family = frozen['family']
        favored = frozen.get('favored_terminals', groups.get(family, []))
        if family not in groups or any(c not in coverage for c in favored):
            raise ValueError('Frozen GP family terminals changed or disappeared')
        return {'requested_family':frozen.get('requested_family', family), 'family':family,
                'family_selection_reason':frozen.get('family_selection_reason', 'frozen_checkpoint'),
                'favored_terminals':favored, 'available_family_terminals':available,
                'family_terminals_with_72_months':sum(coverage[c] >= 72 for c in favored)}
    ordered = families[seed % len(families):] + families[:seed % len(families)]
    family = next((name for name in ordered if available[name]), requested)
    reason = ('preferred_family_available' if available[requested] else
              'preferred_family_insufficient_history' if available[family] else 'no_family_has_required_history')
    return {'requested_family':requested, 'family':family, 'family_selection_reason':reason,
            'favored_terminals':groups[family], 'available_family_terminals':available,
            'family_terminals_with_72_months':available[family]}


def run(settings: dict, output: Path) -> dict:
    if settings.get('predictive_priority'):
        from quant.research.predictive_priority_inputs import run_predictive
        return run_predictive(settings, output)
    from quant.data.nightly_genetic_inputs import read_training_sample
    if settings.get('genetic', {}).get('calculation_context'):
        # Pin the refresh source before making the sample, not after a possible
        # interruption/daily refresh. The saved pointer is also used by context.
        folder = output/'full_context'
        folder.mkdir(exist_ok=True)
        config = folder/'refresh.toml'
        if not config.exists():
            config.write_bytes(Path(settings['refresh_config']).read_bytes())
        settings = {**settings, 'refresh_config': str(config)}
    definitions = load_library(Path(settings['library']))
    diagnostics=recovery_diagnostics(output)
    # All raw-library terminals remain in every night's grammar and redundancy controls.
    mapping = {f'gp_{d.id}': d.expr for d in definitions}
    mapping_path=output/'terminal_mapping.json'
    if mapping_path.exists():
        previous=json.loads(mapping_path.read_text(encoding='utf-8'))
        if any(mapping.get(name)!=expr for name,expr in previous.items()):
            raise ValueError('A frozen GP terminal definition changed or disappeared')
        mapping=previous
        definitions=[d for d in definitions if f'gp_{d.id}' in mapping]
    else:
        temporary = mapping_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(mapping,indent=2),encoding='utf-8')
        temporary.replace(mapping_path)
    end = settings['training_end']
    cross_stock = json.loads(json.dumps(settings['cross_stock'], default=str)) if settings.get('cross_stock') else None
    sample,monthly_sample=output/'daily_sample.parquet',output/'monthly_sample.parquet'
    if sample.exists() and monthly_sample.exists():
        panel,labels=pl.read_parquet(sample),pl.read_parquet(monthly_sample)
    else:
        panel, labels = read_training_sample(data_root=Path(settings['data_root']),
            refresh_config=Path(settings['refresh_config']), statistics=[Path(p) for p in settings['statistics']],
            factors=[d.id for d in definitions], end=end, symbols=300, months=72,
            **({'cross_stock': cross_stock} if cross_stock else {}))
        temporary=sample.with_suffix('.partial.parquet')
        panel.write_parquet(temporary)
        temporary.replace(sample)
        temporary = monthly_sample.with_suffix('.partial.parquet')
        labels.write_parquet(temporary)
        temporary.replace(monthly_sample)
    search_day=dt.date.fromisoformat(output.parent.name)
    search_settings=dict(settings['genetic'])
    if cross_stock:
        for field in ('population_size', 'generations', 'max_depth', 'complexity_penalty'):
            if search_settings[field] != cross_stock[field]:
                raise ValueError(f'Cross-stock preregistration differs: {field}')
        search_settings['cross_stock'] = cross_stock
    search_settings['seed']+=search_day.toordinal()
    keywords={'price_volume':('alpha','price','liquidity','momentum'),
              'financial':('financial','pit','value','quality'),
              'minute':('minute','intraday'), 'mixed':('',)}
    groups = {family:[f'gp_{d.id}' for d in definitions if any(k in d.family for k in terms)]
              for family, terms in keywords.items()}
    monthly=panel.select('symbol','trade_date',*mapping).join(labels.select('symbol','trade_date'),on=['symbol','trade_date'])
    coverage=monthly.group_by('trade_date').agg(pl.col(c).is_finite().sum().alias(c) for c in mapping).select(
        (pl.col(c)>=100).sum().alias(c) for c in mapping).to_dicts()[0]
    summary_path = output/'input_summary.json'
    has_checkpoint = any((output/name).exists() for name in ('search_checkpoint.json', 'fitness_cache.json'))
    if has_checkpoint and not summary_path.exists():
        raise ValueError('GP checkpoint has no frozen input summary; cannot safely select its family')
    frozen = json.loads(summary_path.read_text(encoding='utf-8')) if has_checkpoint else None
    if frozen:
        from quant.research.gp_full_context import LEGACY as legacy_context
        from quant.research.gp_expression_identity import LEGACY as legacy_identity
        for key, default in [('calculation_context', legacy_context), ('expression_identity', legacy_identity)]:
            if frozen.get(key, default) != search_settings.get(key, default):
                raise ValueError('Frozen GP calculation/identity version changed; preserve the old batch')
    selection = select_family(groups, coverage, search_settings['seed'], frozen)
    family = selection['family']
    search_settings['favored_terminals'] = selection['favored_terminals']
    from quant.research.gp_hints import apply_soft_constraints, latest_hint, load_hint
    hint_path = latest_hint()
    hint = load_hint(hint_path)
    search_settings = apply_soft_constraints(search_settings, hint)
    input_summary={'sample_symbols':labels['symbol'].n_unique(),'sample_months':labels['trade_date'].n_unique(),
                   **selection,'terminal_count':len(mapping),
                   'sample_first_signal':str(labels['trade_date'].min()),
                   'sample_last_signal':str(labels['trade_date'].max()),
                   'last_label_exit':str(labels['label_exit_date'].max()),'training_end':str(end),
                   'finite_terminal_months':coverage,
                   'gp_hints_path': str(hint_path) if hint_path else None,
                   'gp_hints': search_settings.get('gp_hints')}
    # Version fields are opt-in on a newly frozen config. Missing fields preserve
    # legacy sampling/cache behavior, including recovery of batches 64--67.
    for key in ('calculation_context', 'expression_identity', 'context_max_subtrees',
                'context_max_rows', 'context_memory_mb', 'context_max_disk_mb'):
        if key in search_settings:
            input_summary[key] = search_settings[key]
    if cross_stock:
        from quant.research.cross_stock_search import stock_groups
        input_summary['cross_stock'] = cross_stock
        input_summary['stock_groups'] = stock_groups(labels['symbol'].unique().to_list(),
            groups=cross_stock['sample_groups'], per_group=cross_stock['symbols_per_group'],
            seed=cross_stock['sample_seed'])
    temporary = summary_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(input_summary,indent=2),encoding='utf-8')
    temporary.replace(summary_path)
    if labels['trade_date'].n_unique()!=72 or not input_summary['family_terminals_with_72_months']:
        raise ValueError(f'{family} has no terminal with 72 months and 100 finite stocks; see input_summary.json')
    context_options = {}
    if search_settings.get('calculation_context'):
        from quant.research.gp_full_context import build_evaluator
        evaluator = build_evaluator(panel, mapping, settings, output, sample, monthly_sample)
        context_options['context_evaluator'] = evaluator
        input_summary['input_identity'] = evaluator.identity
        from quant.data.gp_context_inputs import dump
        dump(summary_path, input_summary)
    residual_cfg = settings.get('incremental_residual')
    search_labels = labels
    if residual_cfg:
        from quant.research.gp_residual_labels import apply_residual_search_labels
        # Search uses residual labels; N3/N4 keep original saved monthly_sample.parquet.
        search_labels = apply_residual_search_labels(
            labels=labels, panel=panel, residual_cfg=residual_cfg, output=output/'residual')
        search_settings = {**search_settings, 'search_objective': residual_cfg.get('version', 'incremental_residual_ic_v1')}
        input_summary['search_objective'] = search_settings['search_objective']
        input_summary['residual_controls'] = list(residual_cfg.get('control_columns', []))
        dump_summary = summary_path.with_suffix('.tmp')
        dump_summary.write_text(json.dumps(input_summary, indent=2), encoding='utf-8')
        dump_summary.replace(summary_path)
    winners = search(panel, search_labels, mapping, search_settings, output, family=family, **context_options)
    return {'candidates':len(winners), 'terminal_count':len(mapping), 'family':family,
            'sample_symbols':labels['symbol'].n_unique(), 'sample_months':labels['trade_date'].n_unique(),
            'search_objective': search_settings.get('cross_stock', {}).get('version')
                or search_settings.get('search_objective', 'pooled_mean_ic_v1'),
            'recovery_diagnostics':diagnostics}
