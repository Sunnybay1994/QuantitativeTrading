"""Fit the registered annual models after every annual factor selection is complete."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.research.model_training_models import common_features, fit_predict, training_panel


def completed_fit_plan(selection: Path, model: dict) -> list[dict]:
    plan = json.loads((selection/'summary.json').read_text(encoding='utf-8'))['annual_selection']
    years = [row['test_year'] for row in plan]
    walk = model['walk_forward']
    if sorted(years) != list(range(walk['test_start'].year, walk['test_end'].year+1)):
        raise ValueError('Require every registered walk-forward year exactly once')
    missing = [row['test_year'] for row in plan if not row['selection_complete']]
    if missing:
        raise ValueError(f'Finish annual factor evidence before model training: {missing}')
    return sorted(plan, key=lambda row: row['test_year'])


def run_predictions(*, selection: Path, output: Path) -> dict:
    model_bytes = (selection/'model.toml').read_bytes()
    model = tomllib.loads(model_bytes.decode('utf-8'))
    plan = completed_fit_plan(selection, model)
    root = Path(model['research']['statistics_source'])
    decisions = pl.read_parquet(selection/'annual_selection.parquet')
    scores, fits = [], []
    output.mkdir(parents=True, exist_ok=False)
    (output/'model.toml').write_bytes(model_bytes)
    (output/'battery.toml').write_bytes((selection/'battery.toml').read_bytes())
    walk = model['walk_forward']
    for index, annual in enumerate(plan):
        year, selected = annual['test_year'], annual['provisional_selected']
        cutoff = dt.date.fromisoformat(annual['refit_close'])
        last = min(walk['test_end'], dt.date.fromisoformat(plan[index+1]['refit_close'])-dt.timedelta(days=1)
                   if index+1 < len(plan) else walk['test_end'])
        if not selected:
            fits.append({'test_year': year, 'factors': [], 'reason': 'no_admitted_factors', 'prediction_rows': 0})
            continue
        features = common_features(statistics=root, factors=selected, variant=model['selection']['variant'],
            start=walk['history_start'], end=last, minimum_symbols=model['models']['minimum_signal_stocks'])
        training = training_panel(features=features, statistics=root, cutoff=cutoff,
                                  minimum_symbols=model['models']['minimum_signal_stocks'])
        if training.is_empty():
            fits.append({'test_year': year, 'factors': selected, 'reason': 'no_complete_training_history',
                         'prediction_rows': 0})
            continue
        prediction = features.filter(pl.col('trade_date') >= cutoff)
        means = dict(decisions.filter((pl.col('test_year') == year) & pl.col('factor').is_in(selected)).select(
            'factor', 'training_mean_ic').rows())
        forecast, metadata, fitted = fit_predict(training=training, prediction=prediction, factors=selected,
            mean_ic=means, cutoff=cutoff, settings=model['models'])
        fitted.booster_.save_model(str(output/f'lightgbm_{year}.txt'))
        scores.append(forecast.with_columns(pl.lit(year).alias('test_year')))
        fits.append({'test_year': year, **metadata})
        print(json.dumps({'test_year': year, 'training_rows': training.height,
                          'prediction_rows': prediction.height}), flush=True)
    combined = pl.concat(scores) if scores else pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date,
        'equal_z': pl.Float64, 'positive_mean_ic': pl.Float64, 'lightgbm': pl.Float64, 'test_year': pl.Int32})
    if combined.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Adjacent annual fits produced overlapping predictions')
    combined.write_parquet(output/'monthly_predictions.parquet')
    summary = {'annual_fits': fits, 'prediction_rows': combined.height,
               'scope': 'fixed annual model predictions; portfolio cost replay and admission follow'}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_predictions(selection=args.selection, output=args.output)))


if __name__ == '__main__':
    main()
