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
           output: Path, *, family: str) -> list[dict]:
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
    if any(row.get('fitness_preprocessing') != _FITNESS_PREPROCESSING for row in records):
        raise ValueError('GP fitness preprocessing changed; preserve this checkpoint and use a new run directory')
    cache={r['terminal_expression']:r for r in records}
    def assess(ind):
        expression = gp.compile(ind, pset)
        if expression in cache:
            ind.fitness.values = (cache[expression]['fitness'],)
            return
        row = {'expression': expand_expression(expression, mapping), 'terminal_expression': expression,
               'complexity': len(ind), 'depth': ind.height, 'fitness': -1e9,
               'fitness_preprocessing': _FITNESS_PREPROCESSING}
        try:
            if ind.height > settings['max_depth']:
                raise ValueError('depth exceeded')
            fields=sorted({node.id for node in ast.walk(ast.parse(expression,mode='eval'))
                           if isinstance(node,ast.Name) and node.id in panel.columns}-{'symbol','trade_date'})
            values = evaluate_expressions(panel.select('symbol','trade_date',*fields), {'candidate': expression})
            scored = monthly.join(values.select('symbol', 'trade_date', 'candidate'), on=['symbol', 'trade_date'])
            scored = preprocess_training_scores(scored)
            series = rank_ic_by_date(scored, score='candidate', label='label', minimum_symbols=100,
                                     minimum_paired_coverage=.8)
            stats = monthly_ic_summary(series['trade_date'].to_list(), series['rank_ic'].to_list())
            if stats['months'] < 48 or stats['mean_ic'] is None:
                raise ValueError('fewer than 48 valid training months')
            corr = maximum_correlation(scored, 'candidate', controls)
            row.update(direction=1 if stats['mean_ic'] >= 0 else -1, train=stats, maximum_rank_correlation=corr,
                       fitness=abs(stats['mean_ic']) - settings['complexity_penalty']*len(ind) - .5*corr)
        except BaseException as exc:
            # Rust's PanicException inherits BaseException; preserve the offending
            # expression as an invalid trial without swallowing interrupts/exits.
            if not isinstance(exc,(ValueError,TypeError,pl.exceptions.PolarsError,OverflowError)) and type(exc).__name__!='PanicException':
                raise
            row['error'] = str(exc)[:500]
            row['error_type']=type(exc).__name__
        cache[expression] = row
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
        # A timed-out run retains real best-so-far candidates; resume does not resample them.
        (output/'best_so_far.json').write_text(json.dumps(sorted([r for r in records if 'error' not in r],
            key=lambda r:-r['fitness'])[:20],indent=2),encoding='utf-8')
        if generation == settings['generations']:
            break
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
        unique.setdefault(ast.dump(ast.parse(row['expression'],mode='eval')),row)
    winners = list(unique.values())[:20]
    library = output/'library'
    library.mkdir(exist_ok=True)
    for row in winners:
        row['factor_id'] = 'ngp_' + hashlib.sha256(row['expression'].encode()).hexdigest()[:16]
        definition = dict(id=row['factor_id'], expr=row['expression'], direction=row['direction'],
                          family=f'nightly_{family}', source_ref=str(output/'search.json'))
        (library/f"{row['factor_id']}.toml").write_text(''.join(f'{k} = {json.dumps(v)}\n' for k,v in definition.items()), encoding='utf-8')
    (output/'search.json').write_text(json.dumps({'candidates': winners, 'trials': records}, indent=2), encoding='utf-8')
    return winners


def run(settings: dict, output: Path) -> dict:
    from quant.data.nightly_genetic_inputs import read_training_sample
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
        mapping_path.write_text(json.dumps(mapping,indent=2),encoding='utf-8')
    end = settings['training_end']
    sample,monthly_sample=output/'daily_sample.parquet',output/'monthly_sample.parquet'
    if sample.exists() and monthly_sample.exists():
        panel,labels=pl.read_parquet(sample),pl.read_parquet(monthly_sample)
    else:
        panel, labels = read_training_sample(data_root=Path(settings['data_root']),
            refresh_config=Path(settings['refresh_config']), statistics=[Path(p) for p in settings['statistics']],
            factors=[d.id for d in definitions], end=end, symbols=300, months=72)
        temporary=sample.with_suffix('.partial.parquet')
        panel.write_parquet(temporary)
        temporary.replace(sample)
        labels.write_parquet(monthly_sample)
    search_day=dt.date.fromisoformat(output.parent.name)
    family = ('price_volume','financial','minute','mixed')[search_day.toordinal()%4]
    search_settings=dict(settings['genetic'])
    search_settings['seed']+=search_day.toordinal()
    keywords={'price_volume':('alpha','price','liquidity','momentum'),
              'financial':('financial','pit','value','quality'),
              'minute':('minute','intraday'), 'mixed':('',)}[family]
    search_settings['favored_terminals']=[f'gp_{d.id}' for d in definitions if any(k in d.family for k in keywords)]
    monthly=panel.select('symbol','trade_date',*mapping).join(labels.select('symbol','trade_date'),on=['symbol','trade_date'])
    coverage=monthly.group_by('trade_date').agg(pl.col(c).is_finite().sum().alias(c) for c in mapping).select(
        (pl.col(c)>=100).sum().alias(c) for c in mapping).to_dicts()[0]
    input_summary={'sample_symbols':labels['symbol'].n_unique(),'sample_months':labels['trade_date'].n_unique(),
                   'family':family,'terminal_count':len(mapping),
                   'sample_first_signal':str(labels['trade_date'].min()),
                   'sample_last_signal':str(labels['trade_date'].max()),
                   'last_label_exit':str(labels['label_exit_date'].max()),'training_end':str(end),
                   'finite_terminal_months':coverage,'family_terminals_with_72_months':sum(
                       coverage[c]>=72 for c in search_settings['favored_terminals'])}
    (output/'input_summary.json').write_text(json.dumps(input_summary,indent=2),encoding='utf-8')
    if labels['trade_date'].n_unique()!=72 or not input_summary['family_terminals_with_72_months']:
        raise ValueError(f'{family} has no terminal with 72 months and 100 finite stocks; see input_summary.json')
    winners = search(panel, labels, mapping, search_settings, output, family=family)
    return {'candidates':len(winners), 'terminal_count':len(mapping), 'family':family,
            'sample_symbols':labels['symbol'].n_unique(), 'sample_months':labels['trade_date'].n_unique(),
            'recovery_diagnostics':diagnostics}
