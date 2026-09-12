"""Replay the three annual models with shared Top50/100 rules and battery costs."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Callable

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.research.factor_battery_costs import run_cost_plans
from quant.research.model_training_models import buffered_model_targets


def model_signal_coverage(scores: pl.DataFrame, *, annual_fits: list[dict], model: dict,
                          sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    """Explain missing monthly signals on the actual execution calendar."""
    counts = dict(scores.group_by('trade_date').agg(pl.col('symbol').n_unique()).iter_rows())
    fits = {row['test_year']: row for row in annual_fits}
    walk = model['walk_forward']
    rows = []
    for signal, execution in zip(sessions, sessions[1:]):
        if not walk['test_start'] <= execution <= walk['test_end']:
            continue
        if signal >= walk['test_start'] and signal.month == execution.month:
            continue
        available = counts.get(signal, 0)
        ready = available >= model['models']['minimum_signal_stocks']
        reason = 'available' if ready else fits[execution.year].get(
            'reason', 'insufficient_complete_feature_rows')
        rows.append({'test_year': execution.year, 'signal_date': signal,
                     'execution_date': execution, 'available_stocks': available,
                     'signal_available': ready, 'reason': reason})
    return pl.from_dicts(rows)


def model_target_plans(scores: pl.DataFrame, *, model: dict, sessions: tuple[dt.date, ...]) -> dict:
    portfolio = model['portfolio']
    return {f'{method}_top{top_k}': (f'p4_{method}_top{top_k}', buffered_model_targets(
        scores, method=method, sessions=sessions, start=model['walk_forward']['test_start'],
        end=model['walk_forward']['test_end'], top_k=top_k,
        minimum_symbols=model['models']['minimum_signal_stocks'],
        retention_multiplier=portfolio['retention_rank_multiplier']))
        for method in model['models']['methods']
        for top_k in (portfolio['primary_top_k'], portfolio['sensitivity_top_k'])}


def signal_sell_permission() -> pl.Expr:
    """Signal-close sell permission: upper-limit closes may sell, lower may not."""
    return (pl.col('traded') & pl.col('limits_known') &
        pl.col('close').is_finite() & pl.col('up_limit').is_finite() &
        pl.col('down_limit').is_finite() & (pl.col('down_limit') > 0) &
        (pl.col('up_limit') > pl.col('down_limit')) &
        (pl.col('close') > pl.col('down_limit'))).fill_null(False)


def prepare_constraints(*, config: Path, plans: dict, data_root: Path, output: Path,
                        resume: bool, model_scores: pl.DataFrame | None = None) -> tuple[Callable[[pl.DataFrame, dict], tuple[pl.DataFrame, dict]], str]:
    """Freeze existing PIT controls and benchmark weights for this explicit experiment."""
    from quant.data.equal_weight_index import read_equal_weight_targets
    from quant.data.factor_battery_inputs import read_frozen_battery_universe
    from quant.data.neutralization_inputs import apply_recovered_market_values
    from quant.portfolio.simple_constraints import RelativeConstraintLimits, constrain_account_targets

    content = config.read_text(encoding='utf-8')
    settings = tomllib.loads(content)
    if settings.get('auto_trade') is not False or settings.get('mode') != 'research_only':
        raise ValueError('Constraints require research_only and auto_trade=false')
    names = settings['strategy_names']
    if not names or len(names) != len(set(names)) or not set(names) <= {n for n, _ in plans.values()}:
        raise ValueError('Constraint strategy_names must select existing unique plans')
    dates = sorted({d for name, targets in plans.values() if name in names for d in targets['as_of']})
    universe_dates = set(dates)
    recovery = Path(settings['recovered_size']) if settings.get('recovered_size') else None
    if recovery is not None:
        # This is the explicit artifact overlay, never a read of raw/clean outside quant.data.
        universe_dates.update(pl.read_parquet(recovery, columns=['as_of'])['as_of'])
    universe = read_frozen_battery_universe(statistics=Path(settings['statistics']),
        as_of_dates=sorted(universe_dates), include_tradeability=True)
    directional = settings.get('signal_tradeability') == 'directional_sell_eligible_buy'
    if settings.get('signal_tradeability') not in (None, 'directional_sell_eligible_buy'):
        raise ValueError('Unknown constraint signal_tradeability rule')
    if not directional:
        # Keep the original experiment inputs byte-for-byte comparable on resume.
        universe = universe.drop(['close', 'up_limit', 'down_limit'], strict=False)
    if recovery is not None:
        universe = apply_recovered_market_values(universe=universe, recovery_path=recovery)
    benchmark = read_equal_weight_targets(data_root=data_root, version=settings['benchmark_snapshot'],
        index_name=settings['benchmark'], as_of_dates=dates)
    config_path = output/'constraints_config.toml'
    frames = {'constraints_universe.parquet': universe, 'constraints_benchmark.parquet': benchmark}
    risk_settings = settings.get('held_risk_estimate')
    risk_estimates = None
    if risk_settings:
        from quant.data.held_control_supplements import read_held_risk_estimates
        risk_path = Path(risk_settings['path'])
        # Artifact keys identify the bounded requests; the data reader validates values/evidence.
        keys = pl.read_parquet(risk_path, columns=['as_of', 'symbol'])
        if keys.is_empty():
            raise ValueError('Held risk estimate artifact is empty')
        risk_estimates = pl.concat([read_held_risk_estimates(path=risk_path, as_of=day,
            symbols=keys.filter(pl.col('as_of') == day)['symbol'].to_list())
            for day in sorted(set(keys['as_of']))])
        frames['constraints_held_risk_estimates.parquet'] = risk_estimates
    nominee_settings = settings.get('candidate_selection')
    nominee_scores = None
    if nominee_settings:
        if model_scores is None:
            raise ValueError('Candidate selection requires the actual model score table')
        columns = ['trade_date', 'symbol', nominee_settings['score_column']]
        nominee_scores = pl.read_parquet(nominee_settings['scores']).select(columns).sort('trade_date', 'symbol')
        if not nominee_scores.equals(model_scores.select(columns).sort('trade_date', 'symbol')):
            raise ValueError('Candidate scores differ from the actual model predictions')
        frames['constraints_scores.parquet'] = nominee_scores
        executions = pl.concat([t.select('as_of', 'execution_date') for name, t in plans.values()
            if name in names]).unique()
        frames['constraints_execution_symbols.parquet'] = nominee_scores.select(
            pl.col('trade_date').alias('as_of'), 'symbol').join(executions, on='as_of', how='inner').select(
                'execution_date', 'symbol').unique().sort('execution_date', 'symbol')
    if resume:
        if not config_path.is_file() or config_path.read_text(encoding='utf-8') != content:
            raise ValueError('Resume constraints configuration changed')
        for filename, frame in frames.items():
            if not (output/filename).is_file() or not pl.read_parquet(output/filename).equals(frame):
                raise ValueError(f'Resume constraint inputs changed: {filename}')
    else:
        config_path.write_text(content, encoding='utf-8')
        for filename, frame in frames.items():
            frame.write_parquet(output/filename)

    def transform(batch: pl.DataFrame, state: dict) -> tuple[pl.DataFrame, dict]:
        signal = batch['as_of'][0]
        if batch['strategy'].n_unique() != 1:
            raise ValueError('Mixed strategy constraint batch')
        if batch['strategy'][0] not in names:
            return batch, {'as_of': str(signal), 'feasible': True, 'applied': False, 'failure_reason': None}
        market = universe.filter(pl.col('trade_date') == signal).select(
            pl.col('trade_date').alias('as_of'), pl.col('trade_date').alias('known_at'),
            'symbol', 'industry_l1', 'total_market_value', pl.col('amount20').alias('adv20'),
            pl.col('eligible').alias('can_buy'),
            (signal_sell_permission() if directional else
             pl.col('traded') & pl.col('limits_known') & pl.col('away_from_limits')).alias('can_sell'))
        nominee_info = None
        risk_info: list[dict] = []
        if risk_estimates is not None:
            assert risk_settings is not None
            from quant.portfolio.simple_constraints import apply_suspended_held_risk_estimates
            equity = state['nav'][-1]['equity']
            held_weights = pl.from_dicts([{'as_of': signal, 'symbol': symbol,
                'weight': h['quantity']*h['mark_price']/equity}
                for symbol, h in sorted(state['holdings'].items()) if h['quantity'] > 0],
                schema={'as_of': batch.schema['as_of'], 'symbol': pl.String, 'weight': pl.Float64})
            market, risk_info = apply_suspended_held_risk_estimates(market=market,
                current=held_weights, benchmark=benchmark.filter(pl.col('as_of') == signal),
                estimates=risk_estimates, as_of=signal,
                maximum_staleness_days=risk_settings['maximum_staleness_days'])
        if nominee_settings:
            from quant.portfolio.industry_candidate_selection import select_industry_candidates
            assert nominee_scores is not None
            if state.get('date') != str(signal) or not state.get('nav'):
                raise ValueError('Candidate selection requires the actual signal-close account')
            equity = state['nav'][-1]['equity']
            current = pl.from_dicts([{'as_of': signal, 'symbol': symbol,
                'weight': h['quantity']*h['mark_price']/equity}
                for symbol, h in sorted(state['holdings'].items()) if h['quantity'] > 0],
                schema={'as_of': batch.schema['as_of'], 'symbol': pl.String, 'weight': pl.Float64})
            restricted = [r['symbol'] for r in state.get('restricted_shares', [])
                          if str(r['list_date']) > str(signal) and r['quantity'] > 0]
            market = market.with_columns((pl.col('can_sell') &
                ~pl.col('symbol').is_in(restricted)).alias('can_sell'))
            day_scores = nominee_scores.filter(pl.col('trade_date') == signal).select(
                pl.col('trade_date').alias('as_of'), 'symbol',
                pl.col(nominee_settings['score_column']).alias('score'))
            nominees, nominee_info = select_industry_candidates(scores=day_scores, market=market,
                benchmark=benchmark.filter(pl.col('as_of') == signal), current=current,
                previous=state.get('constraint_nominees', sorted(state['holdings'])),
                top_k=nominee_settings['top_k'], retention_multiplier=nominee_settings['retention_multiplier'],
                minimum_signal_stocks=nominee_settings['minimum_signal_stocks'],
                single_stock_weight=settings['limits']['single_stock_weight'],
                industry_active_band=settings['limits']['industry_active_band'])
            if not nominee_info['feasible']:
                return batch, {'as_of': str(signal), 'applied': True, 'feasible': False,
                    'failure_reason': 'candidate_selection_failed', 'candidate_selection': nominee_info,
                    'held_risk_estimates': risk_info}
            selected = set(nominees['symbol'])
            template = batch.row(0, named=True)
            batch = pl.from_dicts([{**template, 'symbol': symbol,
                'weight': 1/nominee_settings['top_k'] if symbol in selected else 0.}
                for symbol in sorted(selected | set(state['holdings']) | set(batch['symbol']))], schema=batch.schema)
        result, info = constrain_account_targets(targets=batch, state=state, market=market,
            benchmark=benchmark.filter(pl.col('as_of') == signal),
            limits=RelativeConstraintLimits(**settings['limits']), enabled=settings['enabled'],
            sell_only=settings['sell_only'], unknown_industry_policy=settings['unknown_industry_policy'],
            diagnostic_only=True)
        info['applied'] = True
        if settings.get('signal_direction_quantity_lock', False):
            permissions = {r['symbol']: (r['can_buy'], r['can_sell']) for r in market.iter_rows(named=True)}
            info['execution_direction_permissions'] = {symbol: permissions.get(symbol, (False, False))
                for symbol in result['symbol'] if permissions.get(symbol, (False, False)) != (True, True)}
        if risk_info:
            info['held_risk_estimates'] = risk_info
        if nominee_info is not None:
            info['candidate_selection'] = nominee_info
            info['nominee_symbols'] = sorted(nominees['symbol'])
        return result, info

    return transform, content


def run_model_replay(*, predictions: Path, benchmarks: Path, output: Path, data_root: Path,
                     constraints_config: Path | None = None, resume: bool = False) -> dict:
    model_bytes = (predictions/'model.toml').read_bytes()
    model = tomllib.loads(model_bytes.decode('utf-8'))
    battery_bytes = (predictions/'battery.toml').read_bytes()
    settings = tomllib.loads(battery_bytes.decode('utf-8'))
    baseline_settings = tomllib.loads((benchmarks/'battery.toml').read_text(encoding='utf-8'))
    for key in ('portfolio', 'costs', 'universe', 'run', 'data'):
        if settings[key] != baseline_settings[key]:
            raise ValueError(f'Model and benchmark differ in {key}')
    for key in ('initial_cash', 'cost_multipliers'):
        if settings['portfolio'][key] != model['portfolio'][key]:
            raise ValueError(f'Model and battery differ in {key}')
    summary = json.loads((predictions/'summary.json').read_text(encoding='utf-8'))
    walk = model['walk_forward']
    if (sorted(row['test_year'] for row in summary['annual_fits']) != list(range(
            walk['test_start'].year, walk['test_end'].year+1)) or walk['test_end'] != settings['run']['as_of']):
        raise ValueError('Model predictions do not cover the registered years')
    sessions = available_sessions(data_root, walk['test_end']+dt.timedelta(days=40))
    scores = pl.read_parquet(predictions/'monthly_predictions.parquet')
    plans = model_target_plans(scores, model=model, sessions=sessions)
    snapshot = json.loads((benchmarks/'summary.json').read_text(encoding='utf-8'))['execution_snapshot']
    if resume:
        if ((output/'model.toml').read_bytes() != model_bytes
                or (output/'battery.toml').read_bytes() != battery_bytes):
            raise ValueError('Resume model or battery configuration changed')
    else:
        output.mkdir(parents=True, exist_ok=False)
        (output/'model.toml').write_bytes(model_bytes)
        (output/'battery.toml').write_bytes(battery_bytes)
    transform = None
    if constraints_config is not None:
        transform, content = prepare_constraints(config=constraints_config, plans=plans,
            data_root=data_root, output=output, resume=resume, model_scores=scores)
        settings['target_constraints_config'] = content
    elif resume and (output/'constraints_config.toml').exists():
        raise ValueError('Resume cannot omit the original constraints configuration')
    coverage = model_signal_coverage(scores, annual_fits=summary['annual_fits'], model=model, sessions=sessions)
    if resume:
        if not pl.read_parquet(output/'model_signal_coverage.parquet').equals(coverage):
            raise ValueError('Resume model signal coverage changed')
    else:
        coverage.write_parquet(output/'model_signal_coverage.parquet')
    return run_cost_plans(settings=settings, plans=plans, sessions=sessions, output=output,
        data_root=data_root, execution_snapshot=snapshot, factor=model['research']['id'], start=walk['test_start'],
        target_constraints=transform, resume=resume,
        constraint_execution_symbols=(pl.read_parquet(output/'constraints_execution_symbols.parquet')
            if constraints_config is not None and (output/'constraints_execution_symbols.parquet').exists() else None))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--benchmarks', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--constraints-config', type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run_model_replay(predictions=args.predictions, benchmarks=args.benchmarks,
                                     output=args.output, data_root=args.data_root,
                                     constraints_config=args.constraints_config, resume=args.resume)))


if __name__ == '__main__':
    main()
