"""Replay the three annual models with shared Top50/100 rules and battery costs."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

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


def run_model_replay(*, predictions: Path, benchmarks: Path, output: Path, data_root: Path) -> dict:
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
    output.mkdir(parents=True, exist_ok=False)
    (output/'model.toml').write_bytes(model_bytes)
    (output/'battery.toml').write_bytes(battery_bytes)
    model_signal_coverage(scores, annual_fits=summary['annual_fits'], model=model,
                          sessions=sessions).write_parquet(output/'model_signal_coverage.parquet')
    return run_cost_plans(settings=settings, plans=plans, sessions=sessions, output=output,
        data_root=data_root, execution_snapshot=snapshot, factor=model['research']['id'], start=walk['test_start'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--benchmarks', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run_model_replay(predictions=args.predictions, benchmarks=args.benchmarks,
                                     output=args.output, data_root=args.data_root)))


if __name__ == '__main__':
    main()
