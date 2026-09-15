"""Retrain a research model with the registered calendar monthly input repair."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.model_forward_inputs import read_model_monthly_values
from quant.research.factor_battery_evaluation import score_factor_sections
from quant.research.model_training_models import common_features, training_panel


def replacement_factors(original: list[str], replacements: dict[str, str]) -> list[str]:
    if not replacements or set(replacements)-set(original):
        raise ValueError('Replacements must refer to existing selected factors')
    result = [replacements.get(factor, factor) for factor in original]
    if len(result) != len(set(result)):
        raise ValueError('Replacement factors must remain unique')
    return result


def run_model(*, config_path: Path, output: Path, data_root: Path) -> dict:
    from lightgbm import LGBMRegressor

    contents = config_path.read_bytes()
    config = tomllib.loads(contents.decode('utf-8'))
    research, settings = config['research'], config['model']
    if research['auto_trade'] is not False or settings['method'] != 'lightgbm':
        raise ValueError('Require the registered research LightGBM model')
    source = Path(research['source_predictions'])
    model_text = (source/'model.toml').read_text(encoding='utf-8')
    original = tomllib.loads(model_text)
    battery = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    fits = json.loads((source/'summary.json').read_text(encoding='utf-8'))['annual_fits']
    matches = [row for row in fits if row['test_year'] == settings['test_year']]
    if len(matches) != 1 or matches[0]['refit_close'] != str(settings['training_cutoff']):
        raise ValueError('Require the same source annual cutoff')
    old_fit = matches[0]
    factors = replacement_factors(old_fit['factors'], config['replacements'])
    statistics = Path(original['research']['statistics_source'])
    roots = [Path(path) for path in config['inputs']['calendar_statistics']]
    for root in roots:
        other = tomllib.loads((root/'battery.toml').read_text(encoding='utf-8'))
        if any(other[key] != battery[key] for key in ('preprocessing', 'universe', 'variants')):
            raise ValueError('Replacement scores must use the source preprocessing and universe rules')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(contents)
    calendar_root = output/'calendar_scores'
    year = settings['test_year']
    dates = pl.scan_parquet(statistics/'inputs'/str(year)/'monthly_labels.parquet').select(
        'trade_date').unique().sort('trade_date').collect()['trade_date'].to_list()
    universe = pl.scan_parquet(statistics/'inputs'/str(year)/'universe.parquet').filter(
        pl.col('trade_date').is_in(dates)).collect()
    for factor in config['replacements'].values():
        definition = json.loads((roots[0]/'factors'/factor/'statistics.json').read_text(encoding='utf-8'))['definition']
        values = read_model_monthly_values(data_root=data_root, factor=factor, dates=dates)
        scores = score_factor_sections(universe=universe, values=values, direction=definition['direction'], settings=battery)
        folder = calendar_root/'factors'/factor
        folder.mkdir(parents=True)
        scores.write_parquet(folder/'monthly_scores.parquet')
    sources = {factor: [*roots, calendar_root] for factor in config['replacements'].values()}
    features = common_features(statistics=statistics, factors=factors, variant=original['selection']['variant'],
        start=settings['training_start'], end=battery['run']['as_of'], minimum_symbols=settings['minimum_signal_stocks'],
        statistics_sources=sources)
    train = training_panel(features=features, statistics=statistics, cutoff=settings['training_cutoff'],
                           minimum_symbols=settings['minimum_signal_stocks'])
    if train['trade_date'].n_unique() < settings['minimum_training_months']:
        raise ValueError('Insufficient complete training history after replacement')
    regressor = LGBMRegressor(**original['models']['lightgbm'])
    regressor.fit(train.select(factors).to_numpy(), train['label_rebalance'].to_numpy())
    prediction = features.filter(pl.col('trade_date') >= settings['training_cutoff'])
    forecast = regressor.booster_.predict(prediction.select(factors).to_numpy())
    folder = output/'predictions'
    folder.mkdir()
    regressor.booster_.save_model(str(folder/f'lightgbm_{year}.txt'))
    result = prediction.select('symbol', 'trade_date').with_columns(
        pl.Series('lightgbm', forecast), pl.lit(year).alias('test_year'))
    result.write_parquet(folder/'monthly_predictions.parquet')
    fit = {'test_year': year, 'factors': factors, 'training_rows': train.height,
        'training_months': train['trade_date'].n_unique(), 'last_known_exit': str(train['exit_date_rebalance'].max()),
        'refit_close': str(settings['training_cutoff']), 'prediction_rows': result.height}
    (folder/'summary.json').write_text(json.dumps({'annual_fits': [fit], 'prediction_rows': result.height}, indent=2), encoding='utf-8')
    model_text = model_text.replace(original['research']['id'], research['id']).replace(
        'methods = ["equal_z", "positive_mean_ic", "lightgbm"]', 'methods = ["lightgbm"]').replace(
        f"test_start = {original['walk_forward']['test_start']}", f'test_start = {year}-01-01')
    model_text = model_text.replace(json.dumps(original['research']['hypothesis']), json.dumps(research['hypothesis'])).replace(
        json.dumps(original['research']['historical_evidence']), json.dumps(research['historical_evidence'])).replace(
        json.dumps(original['selection']['candidate_library']), json.dumps(settings['factor_selection']))
    model_text += '\n[research.factor_statistics_sources]\n' + '\n'.join(
        f'{factor} = {json.dumps([str(root) for root in paths])}' for factor, paths in sources.items())+'\n'
    parsed = tomllib.loads(model_text)
    if parsed['models']['methods'] != ['lightgbm'] or parsed['walk_forward']['test_start'] != dt.date(year, 1, 1):
        raise ValueError('Source model format changed; update the calendar model configuration writer')
    (folder/'model.toml').write_text(model_text, encoding='utf-8')
    (folder/'battery.toml').write_bytes((source/'battery.toml').read_bytes())
    selected = output/'selection'
    selected.mkdir()
    selection_text = f'[research]\npredictions = {json.dumps(str(folder))}\n[selection]\nminimum_training_months = {settings["minimum_training_months"]}\n'
    (selected/'config.toml').write_text(selection_text, encoding='utf-8')
    (selected/'selection.json').write_text(json.dumps({'research_id': research['id'], 'selected_method': 'lightgbm',
        'conclusion': 'RESEARCH_ONLY', 'auto_trade': False, 'forward_start': str(config['forward']['start']),
        'method_source': research['source_selection'], 'selection_rule': 'inherit_frozen_method_no_reselection'}), encoding='utf-8')
    coverage = result.group_by('trade_date').len().sort('trade_date')
    coverage.write_csv(output/'historical_prediction_coverage.csv')
    summary = {'research_id': research['id'], 'conclusion': 'RESEARCH_ONLY', **fit,
               'historical_prediction_signals': coverage.height, 'replacements': config['replacements']}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--replay-trained', type=Path, help='Compare an already trained version to the same-year source')
    args = parser.parse_args()
    result = (replay_pair(config_path=args.config, trained=args.replay_trained, output=args.output, data_root=args.data_root)
              if args.replay_trained else run_model(config_path=args.config, output=args.output, data_root=args.data_root))
    print(json.dumps(result))


def replay_pair(*, config_path: Path, trained: Path, output: Path, data_root: Path) -> dict:
    from quant.research.run_multifactor_replay import run_model_replay

    if config_path.read_bytes() != (trained/'config.toml').read_bytes():
        raise ValueError('Replay requires the same registered training configuration')
    config = tomllib.loads(config_path.read_text(encoding='utf-8'))
    source = Path(config['research']['source_predictions'])
    year = config['model']['test_year']
    model_text = (source/'model.toml').read_text(encoding='utf-8')
    original = tomllib.loads(model_text)
    model_text = model_text.replace('methods = ["equal_z", "positive_mean_ic", "lightgbm"]',
        'methods = ["lightgbm"]').replace(f"test_start = {original['walk_forward']['test_start']}",
        f'test_start = {year}-01-01')
    baseline_model = tomllib.loads(model_text)
    if baseline_model['walk_forward']['test_start'] != dt.date(year, 1, 1) or baseline_model['models']['methods'] != ['lightgbm']:
        raise ValueError('Baseline model configuration did not preserve the comparison window')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config_path.read_bytes())
    baseline = output/'baseline_predictions'
    baseline.mkdir()
    (baseline/'model.toml').write_text(model_text, encoding='utf-8')
    (baseline/'battery.toml').write_bytes((source/'battery.toml').read_bytes())
    forecasts = pl.read_parquet(source/'monthly_predictions.parquet').filter(pl.col('test_year') == year)
    forecasts.write_parquet(baseline/'monthly_predictions.parquet')
    fits = json.loads((source/'summary.json').read_text(encoding='utf-8'))['annual_fits']
    (baseline/'summary.json').write_text(json.dumps({'annual_fits': [f for f in fits if f['test_year'] == year],
        'prediction_rows': forecasts.height}), encoding='utf-8')
    rows = []
    for name, predictions in [('original', baseline), ('calendar80', trained/'predictions')]:
        print(f'Replaying {name} for {year}', flush=True)
        result = run_model_replay(predictions=predictions, benchmarks=Path(original['research']['stock_benchmarks']),
            output=output/name, data_root=data_root)
        rows += [{'model': name, **row} for row in result['rows']]
    summary = {'conclusion': 'RESEARCH_ONLY', 'purpose': 'same_year_input_repair_diagnostic', 'rows': rows}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    lines = ['# 月度输入修复：同年回放', '',
        '|模型|组合|成本|总收益|最大回撤|年化单边换手|', '|---|---|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"|{row['model']}|{row['variant']}|{row['cost_multiplier']}×|{row['total_return']:.3%}|"
                     f"{row['max_drawdown']:.3%}|{row['annualized_one_way_turnover']:.2f}|")
    lines += ['', '相同起始现金、2026年区间和费用；短期回放只检查修复影响，不用于策略准入。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    main()
