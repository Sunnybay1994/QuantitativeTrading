"""Business stages used by the subprocess-isolated nightly research runner."""
import datetime as dt
import hashlib
import json
import shutil
import time
import tomllib
from pathlib import Path

import numpy as np
import polars as pl

from quant.factors.library import load_library
from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date
from quant.research.nightly_gp import maximum_correlation
from quant.research.compute_allocation import allowed,require_allowed,may_enqueue


def dump(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str, allow_nan=False), encoding='utf-8')
    for attempt in range(10):
        try:
            temporary.replace(path)
            return
        except PermissionError as exc:
            # Windows scanners/readers may briefly deny atomic destination replacement.
            # Keep the complete temporary payload and the old destination on failure.
            if getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))


def published_candidate(row: dict, settings: dict) -> bool:
    if not isinstance(row.get('id'), str) or not row['id'].isidentifier() or row['id'].startswith('_'):
        raise ValueError('unsafe factor id')
    if 'library' not in settings:
        return False
    target = Path(settings['library'])/'auto'/f"{row['id']}.toml"
    if not target.exists():
        return False
    previous = tomllib.loads(target.read_text(encoding='utf-8'))
    if any(previous[key] != row[key] for key in ('id', 'expr', 'direction')):
        raise ValueError(f"Published candidate definition collision: {row['id']}")
    return True


def resolve_settings(settings: dict, run: Path) -> dict:
    from quant.data.nightly_genetic_inputs import latest_month_end
    path=run/'effective_settings.json'
    if path.exists():
        result=json.loads(path.read_text(encoding='utf-8'))
    else:
        result=dict(settings)
        day=dt.date.fromisoformat(run.name)
        result['as_of']=latest_month_end(Path(settings['data_root']),day)
        result['training_end']=dt.date(day.year-1,12,31)
        if settings.get('cross_stock_config'):
            result['cross_stock'] = tomllib.loads(Path(settings['cross_stock_config']).read_text(encoding='utf-8'))
            result['training_end'] = result['cross_stock']['training_end']
        if settings.get('predictive_priority_config'):
            if settings.get('cross_stock_config') or settings.get('incremental_residual_config'):
                raise ValueError('A batch cannot combine two registered GP objectives')
            result['predictive_priority'] = tomllib.loads(
                Path(settings['predictive_priority_config']).read_text(encoding='utf-8'))
            result['training_end'] = result['predictive_priority']['training_end']
        if settings.get('incremental_residual_config'):
            if settings.get('cross_stock_config') or settings.get('predictive_priority_config'):
                raise ValueError('A batch cannot combine two registered GP objectives')
            residual = tomllib.loads(Path(settings['incremental_residual_config']).read_text(encoding='utf-8'))
            result['incremental_residual'] = residual.get('residual', {})
            result['incremental_residual']['version'] = residual['version']
            for key in ('q10_predictions', 'q10_score_column', 'ngp_library', 'statistics',
                        'label_column', 'control_columns', 'industry_column'):
                if key in residual.get('residual', {}):
                    result['incremental_residual'][key] = residual['residual'][key]
            result['training_end'] = residual['training_end']
        choices=[]
        for completed in Path(settings['output_root']).glob('monthly/*/summary.json'):
            row=json.loads(completed.read_text(encoding='utf-8'))
            if row.get('completed') and row.get('reference_statistics') and row.get('reference_scorecard'):
                source=Path(row['reference_statistics'])
                known=tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))['run']['as_of']
                if known<=result['as_of']:
                    choices.append((known,str(source),row['reference_scorecard']))
        if choices:
            _,result['reference_statistics'],result['reference_scorecard']=max(choices)
        dump(path,result)
    for field in ('as_of','training_end','history_start'):
        if isinstance(result[field],str):
            result[field]=dt.date.fromisoformat(result[field])
    return result


def _archive_retired_gp(path: Path, target: Path) -> bool:
    """Keep invalid computation evidence outside both queue and active library."""
    from quant.research.mining_retry import retired_gp_result
    content = tomllib.loads(path.read_text(encoding='utf-8'))
    rows = content.get('factors', [content])
    retired = [row for row in rows if Path(row.get('source_ref','')).name == 'search.json'
               and retired_gp_result(Path(row['source_ref']).parent) is not None]
    if not retired:
        return False
    if len(retired) != len(rows):
        raise ValueError('Mixed valid and retired GP definitions require separate queue files')
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        if target.read_bytes() != path.read_bytes():
            raise ValueError('Retired GP queue archive collision')
        path.unlink()
    else:
        path.rename(target)
    return True


def ingest(settings: dict, run: Path) -> dict:
    queue = Path(settings['queue'])
    processing = queue/'processing'
    processing.mkdir(parents=True, exist_ok=True)
    failures = []
    for path in sorted(queue.glob('*.toml')):
        try:
            # Accept normal single-factor definitions and [[factors]] batch files.
            content = tomllib.loads(path.read_text(encoding='utf-8'))
            rows = content.get('factors', [content])
            if any(not allowed(row,settings) for row in rows):
                continue  # Leave other sessions' unregistered files untouched.
            for row in rows:
                from quant.factors.expressions import required_history
                required_history(row['expr'])
                if row['direction'] not in (-1, 1):
                    raise ValueError('direction must be +1 or -1')
            target = processing/path.name
            if target.exists():
                if target.read_bytes() != path.read_bytes():
                    raise ValueError('queue basename collision')
                path.unlink()
            else:
                path.rename(target)
        except (ValueError, KeyError) as exc:
            failures.append({'file':str(path), 'reason':str(exc)})
    count = 0
    library = run/'candidates'
    library.mkdir(exist_ok=True)
    for path in sorted(processing.glob('*.toml')):
        if _archive_retired_gp(path, processing/'invalid_computation'/f'{run.name}_{path.name}'):
            continue
        content = tomllib.loads(path.read_text(encoding='utf-8'))
        rows = content.get('factors', [content])
        if all(published_candidate(row, settings) for row in rows):
            complete = processing/'completed'
            complete.mkdir(exist_ok=True)
            destination = complete/f'{run.name}_{path.name}'
            if destination.exists():
                if destination.read_bytes() != path.read_bytes():
                    raise ValueError('completed queue basename collision')
                path.unlink()
            else:
                path.rename(destination)
            continue
        for row in rows:
            if not allowed(row,settings):
                continue
            identifier = row['id']
            if not identifier.isidentifier() or identifier.startswith('_'):
                raise ValueError('unsafe factor id')
            if published_candidate(row, settings):
                continue
            (library/f'{identifier}.toml').write_text(''.join(
                f'{k} = {json.dumps(row[k], ensure_ascii=False)}\n'
                for k in ('id', 'expr', 'family', 'direction', 'source_ref')), encoding='utf-8')
            count += 1
    if count:
        load_library(library)
    return {'queued_candidates':count, 'queue_errors':failures}


def preserve_gp_candidates(settings: dict, run: Path, search_result: dict) -> int:
    """Queue GP output even when an older nonempty evaluation is already complete."""
    from quant.research.mining_retry import retired_gp_result
    if retired_gp_result(run/'N2') is not None:
        return 0
    folder = Path(search_result.get('gp_output', str(run/'N2')))/'library'
    queued = 0
    for path in sorted(folder.glob('*.toml')):
        row = tomllib.loads(path.read_text(encoding='utf-8'))
        if not may_enqueue(row,settings):
            continue
        if published_candidate(row, settings):
            continue
        target = Path(settings['queue'])/'processing'/path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            previous = tomllib.loads(target.read_text(encoding='utf-8'))
            if any(previous[key] != row[key] for key in ('id', 'expr', 'direction')):
                raise ValueError('Queued GP definition collision')
            continue
        temporary = target.with_suffix('.toml.tmp')
        temporary.write_bytes(path.read_bytes())
        temporary.replace(target)
        queued += 1
    return queued


def evaluate(settings: dict, run: Path) -> dict:
    from quant.factors.compute import run as compute
    from quant.research.run_factor_pipeline import run_pipeline
    from quant.reporting.experiment_registry import register_run
    from quant.data.nightly_genetic_inputs import require_execution_coverage
    library = run/'candidates'
    library.mkdir(exist_ok=True)
    for path in sorted(library.glob('*.toml')):
        _archive_retired_gp(path, library/'invalid_computation'/path.name)
    gp_result=run/'N2'/'result.json'
    from quant.research.mining_retry import retired_gp_result
    invalid_gp = retired_gp_result(run/'N2') is not None
    gp_output=Path(json.loads(gp_result.read_text(encoding='utf-8')).get('gp_output',str(run/'N2'))) if gp_result.exists() else run/'N2'
    for path in ([] if invalid_gp else sorted((gp_output/'library').glob('*.toml'))):
        if not may_enqueue(tomllib.loads(path.read_text(encoding='utf-8')),settings):
            continue
        if published_candidate(tomllib.loads(path.read_text(encoding='utf-8')), settings):
            continue
        processing=Path(settings['queue'])/'processing'
        processing.mkdir(parents=True,exist_ok=True)
        # Retain unprocessed GP work across nights, even if the battery times out.
        if not (processing/path.name).exists() and not (Path(settings['library'])/'auto'/path.name).exists():
            shutil.copyfile(path,processing/path.name)
        destination = library/path.name
        if destination.exists():
            previous=tomllib.loads(destination.read_text(encoding='utf-8'))
            proposed=tomllib.loads(path.read_text(encoding='utf-8'))
            if any(previous[k]!=proposed[k] for k in ('id','expr','direction')):
                raise ValueError('candidate definition collision')
        else:
            shutil.copyfile(path, destination)
    if not list(library.glob('*.toml')):
        return {'candidates':0, 'evaluated':0, 'reason':'No queued or completed GP candidates'}
    from quant.data.monthly_open_inputs import evaluation_source_identity
    batch_id = hashlib.sha256(str(settings['as_of']).encode()+b''.join(p.read_bytes() for p in sorted(library.glob('*.toml')))
        + evaluation_source_identity(settings)).hexdigest()[:16]
    batch = Path(settings['batch_root'])/batch_id
    batch.mkdir(parents=True, exist_ok=True)
    frozen = batch/'library'
    if not frozen.exists():
        if settings.get('prepare_month_inputs', False):
            from quant.data.nightly_month_inputs import ensure_nightly_month_inputs
            settings = ensure_nightly_month_inputs(settings=settings, as_of=settings['as_of'],
                                                   output=run/'inputs')
        shutil.copytree(library, frozen)
        dump(batch/'settings.json',settings)
    # Finish the oldest interrupted battery before beginning another candidate batch.
    for prior in sorted(Path(settings['batch_root']).iterdir(),key=lambda p:p.stat().st_mtime):
        if not (prior/'library').is_dir():
            continue
        if not (prior/'admission_scorecard.parquet').exists():
            batch=prior
            frozen=batch/'library'
            break
    allocation={k:settings[k] for k in ('compute_allocation','compute_allocation_config') if k in settings}
    if (batch/'settings.json').exists():
        settings=json.loads((batch/'settings.json').read_text(encoding='utf-8'))
        for field in ('as_of','training_end','history_start'):
            settings[field]=dt.date.fromisoformat(settings[field])
    settings.update(allocation)
    definitions = load_library(frozen)
    require_allowed(definitions,settings)
    require_execution_coverage(Path(settings['data_root']),settings['execution_snapshot'],settings['as_of'])
    compute(data_root=Path(settings['data_root']), refresh_config=Path(settings['refresh_config']),
            library=frozen, selected='all', start=settings['history_start'], end=settings['as_of'],
            artifact_root=batch/'compute')
    from quant.research.gp_context_alignment import verify_new_gp_values
    verify_new_gp_values(definitions, data_root=Path(settings['data_root']),
                         output=batch/'gp_context_alignment.json')
    result = run_pipeline(config=Path(settings['battery_config']), library=frozen,
        as_of=settings['as_of'], output=batch/'evaluation', data_root=Path(settings['data_root']),
        execution_snapshot=settings['execution_snapshot'], workers=settings['workers'],
        resume=(batch/'evaluation').exists(), return_benchmark_config=Path(settings['return_benchmark_config']))
    if result['cost_failures'] or result.get('pending_external_runs'):
        raise ValueError(f'Candidate battery unfinished: {result["cost_failures"]}; pending {result.get("pending_external_runs")}')
    register_run(batch/'evaluation')
    return {'candidates':len(definitions), 'evaluated':len(definitions), 'batch':str(batch),'as_of':str(settings['as_of']),
            'scorecard':result['scorecard_path'], 'cost_failures':result['cost_failures']}


def incremental_statistics(panel: pl.DataFrame, candidate: str, controls: list[str], direction: int) -> dict:
    """Project contemporaneous ranks on admitted ranks; future returns are response only."""
    # Raw-library reference columns belong to the separate correlation calculation.
    panel = panel.select(list(dict.fromkeys(['symbol', 'trade_date', 'label', candidate, *controls])))
    rows = []
    for section in panel.partition_by('trade_date'):
        paired = section.filter(pl.all_horizontal(pl.col(c).is_finite() for c in [candidate, 'label', *controls]))
        if paired.height < max(100, len(controls)+2):
            continue
        ranks = paired.select(pl.col(c).rank('average') for c in [candidate,*controls]).to_numpy()
        ranks = (ranks-ranks.mean(axis=0))/np.maximum(ranks.std(axis=0),1e-12)
        x = np.column_stack([np.ones(paired.height), ranks[:,1:]])
        residual = direction*(ranks[:,0]-x@np.linalg.lstsq(x,ranks[:,0],rcond=None)[0])
        if np.std(residual)<1e-10:
            continue
        scores = paired.select('symbol','trade_date','label').with_columns(pl.Series('residual',residual))
        ic = rank_ic_by_date(scores,score='residual',label='label',minimum_symbols=100,minimum_paired_coverage=.95)
        rows.extend(ic.select('trade_date','rank_ic').to_dicts())
    rows.sort(key=lambda row: row['trade_date'])
    result=monthly_ic_summary([r['trade_date'] for r in rows],[r['rank_ic'] for r in rows],lag=6)
    complete=panel.filter(pl.all_horizontal(pl.col(c).is_finite() for c in [candidate,'label',*controls])).height
    result.update(input_rows=panel.height,complete_control_rows=complete,
                  complete_control_fraction=complete/panel.height if panel.height else 0.)
    return result


def admission_reference(settings: dict) -> dict:
    if 'output_root' not in settings:
        return settings
    for path in sorted((Path(settings['output_root'])/'monthly').glob('*/summary.json'), reverse=True):
        row = json.loads(path.read_text(encoding='utf-8'))
        if row.get('completed') and row.get('as_of') == str(settings['as_of']):
            source, scorecard = row.get('reference_statistics'), row.get('reference_scorecard')
            if source and scorecard and Path(scorecard).is_file():
                known = tomllib.loads((Path(source)/'battery.toml').read_text(encoding='utf-8'))['run']['as_of']
                if str(known) == str(settings['as_of']):
                    return {**settings, 'reference_statistics': source, 'reference_scorecard': scorecard}
    return settings


def candidate_source(identifier: str, source_ref: str) -> str:
    """Classify explicit provenance without treating unknown queued factors as GP."""
    if identifier.startswith('llm_dsl_'):
        return 'weekly_llm'
    if identifier.startswith(('ngp_', 'gp_')):
        return 'nightly_gp'
    if source_ref.startswith('registered_battery:'):
        return 'registered_battery'
    return 'factor_queue'


def admit(settings: dict, run: Path) -> dict:
    from quant.data.nightly_genetic_inputs import read_raw_monthly,admitted_controls
    evaluation = json.loads((run/'N3'/'result.json').read_text(encoding='utf-8'))
    if not evaluation.get('evaluated'):
        return {'admitted':0,'rejected':0,'reason':'No completed candidate battery'}
    batch = Path(evaluation['batch'])
    allocation={k:settings[k] for k in ('compute_allocation','compute_allocation_config') if k in settings}
    if (batch/'settings.json').exists():
        settings=json.loads((batch/'settings.json').read_text(encoding='utf-8'))
        for field in ('as_of','training_end','history_start'):
            settings[field]=dt.date.fromisoformat(settings[field])
    settings.update(allocation)
    # Only a completed reference at the identical cutoff can replace a stale
    # reference. A later month would leak future outcomes into this admission.
    settings = admission_reference(settings)
    definitions = {d.id:d for d in load_library(batch/'library')}
    require_allowed(definitions.values(),settings)
    library = load_library(Path(settings['library']))
    reference_ids = [d.id for d in library if d.id not in definitions]
    checkpoint = run/'N4'/'admission_progress.json'
    progress = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else None
    if progress is not None:
        if progress['batch'] != str(batch) or progress['candidates'] != list(definitions):
            raise ValueError('Admission checkpoint inputs changed; retain the original batch')
        reference_ids = progress['reference_ids']
    reference_scorecard = pl.read_parquet(settings['reference_scorecard'])
    reference_date=tomllib.loads((Path(settings['reference_statistics'])/'battery.toml').read_text(encoding='utf-8'))['run']['as_of']
    if reference_date<settings['as_of']:
        raise ValueError(f'ADMITTED controls end {reference_date}, required {settings["as_of"]}; complete monthly full-library battery before retry')
    controls,admitted=admitted_controls(Path(settings['reference_statistics']),reference_scorecard)
    if progress is None:
        progress = {'batch':str(batch), 'candidates':list(definitions),
                    'reference_ids':reference_ids, 'admitted_controls':admitted, 'rows':[]}
        dump(checkpoint, progress)
    elif set(progress['admitted_controls']) != set(admitted):
        raise ValueError('Admission checkpoint controls changed; retain the original batch')
    else:
        admitted = progress['admitted_controls']
    scorecard = pl.read_parquet(evaluation['scorecard'])
    panel = read_raw_monthly(data_root=Path(settings['data_root']),
        statistics=batch/'evaluation'/'statistics', factors=reference_ids,
        start=settings['history_start'],end=settings['as_of'])
    panel = panel.filter(pl.col('label_exit_date') <= settings['as_of']).join(controls,on=['symbol','trade_date'],how='left',validate='1:1')
    rows = progress['rows']
    completed = {row['factor'] for row in rows}
    if len(completed) != len(rows) or not completed <= set(definitions):
        raise ValueError('Invalid completed admission candidates')
    destination = Path(settings['library'])/'auto'
    destination.mkdir(exist_ok=True)
    seasonality_controls=None
    if any(d.family == 'return_seasonality_calendar_y2_5_v1' for d in definitions.values()):
        paths=sorted((batch/'compute'/'seasonality_controls').glob('year=*.parquet'))
        if not paths:
            raise ValueError('Seasonality N3 long-term control receipt missing')
        seasonality_controls=pl.concat([pl.read_parquet(path) for path in paths])
    turnover_controls = None
    if any(d.family == 'turnover_reference_adjusted_price_v1' for d in definitions.values()):
        from quant.data.factor_control_receipts import pending_control_start
        from quant.factors.turnover_reference import CONTROLS as turnover_columns
        paths = []
        for year in range(settings['history_start'].year, settings['as_of'].year+1):
            path = batch/'compute/turnover_reference_controls'/f'year={year}.parquet'
            if pending_control_start(path, start=max(settings['history_start'], dt.date(year, 1, 1)),
                    end=min(settings['as_of'], dt.date(year, 12, 31)), columns=turnover_columns) is not None:
                raise ValueError('Turnover-reference N3 matched control receipt missing or incomplete')
            paths.append(path)
        turnover_controls = pl.concat([pl.read_parquet(path) for path in paths])
    industry_controls = None
    if any(d.family == 'industry_return_information_v1' for d in definitions.values()):
        from quant.data.factor_control_receipts import pending_control_start
        from quant.factors.industry_information import CONTROL
        paths = []
        for year in range(settings['history_start'].year,settings['as_of'].year+1):
            path = batch/'compute/industry_information_controls'/f'year={year}.parquet'
            if pending_control_start(path,start=max(settings['history_start'],dt.date(year,1,1)),
                    end=min(settings['as_of'],dt.date(year,12,31)),columns=(CONTROL,)) is not None:
                raise ValueError('Industry-information N3 matched control receipt missing or incomplete')
            paths.append(path)
        industry_controls = pl.concat([pl.read_parquet(path) for path in paths])
    comovement_controls = None
    if any(d.family == 'liquidity_comovement_logchange_60m_v1' for d in definitions.values()):
        from quant.data.factor_control_receipts import pending_control_start
        from quant.factors.liquidity_comovement import CONTROLS as comovement_columns
        paths = []
        for year in range(settings['history_start'].year, settings['as_of'].year+1):
            path = batch/'compute/liquidity_comovement_controls'/f'year={year}.parquet'
            if pending_control_start(path, start=max(settings['history_start'],dt.date(year,1,1)),
                    end=min(settings['as_of'],dt.date(year,12,31)),columns=comovement_columns) is not None:
                raise ValueError('Liquidity co-movement N3 matched control receipt missing or incomplete')
            paths.append(path)
        comovement_controls = pl.concat([pl.read_parquet(path) for path in paths])
    for identifier, definition in definitions.items():
        if identifier in completed:
            continue
        from quant.research.slice_budget import checkpoint as slice_checkpoint
        slice_checkpoint()
        variants=scorecard.filter(pl.col('factor')==identifier).sort('factor_admitted',descending=True)
        variant=variants['variant'][0]
        values=pl.read_parquet(batch/'evaluation'/'statistics'/'factors'/identifier/'monthly_scores.parquet').select(
            'symbol','trade_date',pl.col(variant).alias('candidate'))
        scored=panel.join(values,on=['symbol','trade_date'],how='left',validate='1:1')
        incremental = incremental_statistics(scored,'candidate',admitted,1)
        from quant.research.n4_correlation import admission_correlation
        corr = admission_correlation(scored, 'candidate', reference_ids,
            engine=settings.get('n4_correlation_engine', 'legacy'), legacy=maximum_correlation)
        battery_pass = bool(variants['factor_admitted'][0])
        passed = (battery_pass and incremental['months']>=96 and
                  incremental['newey_west_t'] is not None and incremental['newey_west_t']>=2.5 and corr<.6)
        family_result = {}
        if definition.family == 'liquidity_comovement_logchange_60m_v1':
            from quant.research.liquidity_comovement_controls import check_liquidity_comovement_controls
            controlled = scored.join(comovement_controls,on=['symbol','trade_date'],how='left',validate='1:1')
            family_result = check_liquidity_comovement_controls(controlled,admitted,incremental_statistics,
                identifier=identifier,variant=variant)
            passed = passed and family_result['passed']
        if definition.family == 'price_delay_hou_moskowitz_2005_v1':
            # Fixed whole-family controls, evaluated within the original N4.
            # Neutral scores retain the original battery's size/industry adjustment.
            from quant.research.price_delay_controls import check_price_delay_controls
            neutral = pl.read_parquet(batch/'evaluation'/'statistics'/'factors'/identifier/'monthly_scores.parquet').select(
                'symbol', 'trade_date', pl.col('size_industry_neutral').alias('candidate'))
            family_result = check_price_delay_controls(panel.join(neutral, on=['symbol','trade_date'],
                how='left', validate='1:1'), admitted, incremental_statistics)
            passed = passed and family_result['passed']
        if definition.family == 'return_seasonality_calendar_y2_5_v1':
            from quant.research.seasonality_controls import check_seasonality_controls
            neutral=pl.read_parquet(batch/'evaluation'/'statistics'/'factors'/identifier/'monthly_scores.parquet').select(
                'symbol','trade_date',pl.col('size_industry_neutral').alias('candidate'))
            controlled=panel.join(neutral,on=['symbol','trade_date'],how='left',validate='1:1').join(
                seasonality_controls,on=['symbol','trade_date'],how='left',validate='1:1')
            family_result=check_seasonality_controls(controlled,admitted,incremental_statistics)
            passed=passed and family_result['passed']
        if definition.family == 'statement_event_reaction_v1':
            from quant.research.statement_event_controls import check_statement_controls
            neutral = pl.read_parquet(batch/'evaluation'/'statistics'/'factors'/identifier/'monthly_scores.parquet').select(
                'symbol', 'trade_date', pl.col('size_industry_neutral').alias('candidate'))
            family_result = check_statement_controls(panel.join(neutral, on=['symbol', 'trade_date'],
                how='left', validate='1:1'), admitted, incremental_statistics)
            passed = passed and family_result['passed']
        if definition.family == 'turnover_reference_adjusted_price_v1':
            from quant.research.turnover_reference_controls import check_turnover_reference_controls
            neutral = pl.read_parquet(batch/'evaluation/statistics/factors'/identifier/'monthly_scores.parquet').select(
                'symbol', 'trade_date', pl.col('size_industry_neutral').alias('candidate'))
            controlled = panel.join(neutral, on=['symbol', 'trade_date'], how='left', validate='1:1').join(
                turnover_controls, on=['symbol', 'trade_date'], how='left', validate='1:1')
            family_result = check_turnover_reference_controls(controlled, admitted, incremental_statistics)
            passed = passed and family_result['passed']
        if definition.family == 'industry_return_information_v1':
            from quant.research.industry_information_controls import check_industry_information_controls
            raw = pl.read_parquet(batch/'evaluation/statistics/factors'/identifier/'monthly_scores.parquet').select(
                'symbol','trade_date',pl.col('raw').alias('candidate'),
                pl.col('size_industry_neutral').alias('industry_neutral'))
            controlled = panel.join(raw,on=['symbol','trade_date'],how='left',validate='1:1').join(
                industry_controls,on=['symbol','trade_date'],how='left',validate='1:1')
            family_result = check_industry_information_controls(controlled,admitted,incremental_statistics,identifier)
            passed = passed and family_result['passed']
        if definition.family == 'sue_family_v1':
            from quant.research.sue_family_controls import check_sue_family_controls
            neutral = pl.read_parquet(batch/'evaluation'/'statistics'/'factors'/identifier/'monthly_scores.parquet').select(
                'symbol', 'trade_date', pl.col('size_industry_neutral').alias('candidate'))
            family_result = check_sue_family_controls(
                panel.join(neutral, on=['symbol', 'trade_date'], how='left', validate='1:1'),
                admitted, incremental_statistics)
            passed = passed and family_result['passed']
        source = candidate_source(identifier, definition.source_ref)
        rows.append({'factor':identifier,'variant':variant,'battery_pass':battery_pass,'incremental_months':incremental['months'],
                     'incremental_nw_t':incremental['newey_west_t'],'maximum_rank_correlation':corr,
                     'complete_control_fraction':incremental['complete_control_fraction'],
                     'factor_admitted':passed,'source':source, **({'family_controls': family_result} if family_result else {})})
        if passed:
            text = (batch/'library'/f'{identifier}.toml').read_text(encoding='utf-8')+f'source = "{source}"\n'
            target = destination/f'{identifier}.toml'
            if target.exists() and target.read_text(encoding='utf-8') != text:
                raise ValueError('admitted factor definition conflict')
            target.write_text(text,encoding='utf-8')
        dump(checkpoint, progress)
    result = pl.from_dicts(rows)
    result.write_parquet(run/'N4'/'admission_scorecard.parquet')
    rejected = Path(settings['rejected_root'])
    rejected.mkdir(parents=True,exist_ok=True)
    result.filter(~pl.col('factor_admitted')).write_parquet(rejected/f'{run.name}_{batch.name}.parquet')
    # Queued definitions are complete only after the actual battery and admission decision.
    processing = Path(settings['queue'])/'processing'
    complete = processing/'completed'
    complete.mkdir(exist_ok=True)
    for path in processing.glob('*.toml'):
        content=tomllib.loads(path.read_text(encoding='utf-8'))
        if all(row['id'] in definitions or published_candidate(row, settings)
               for row in content.get('factors',[content])):
            target=complete/f'{run.name}_{path.name}'
            if not target.exists():
                path.rename(target)
    result.write_parquet(batch/'admission_scorecard.parquet')
    return {'admitted':sum(r['factor_admitted'] for r in rows),'rejected':sum(not r['factor_admitted'] for r in rows),
            'admitted_controls':len(admitted),'reference_factors':len(reference_ids),
            'admitted_factors':[r for r in rows if r['factor_admitted']],
            'admission_scorecard':str(run/'N4'/'admission_scorecard.parquet')}


def monthly_models(settings: dict, run: Path) -> dict:
    from quant.research.nightly_monthly import run_monthly
    return run_monthly(settings,run)
