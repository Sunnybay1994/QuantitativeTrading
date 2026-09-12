"""Generate research forecasts with the selected frozen annual model."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from quant.research.factor_battery_evaluation import score_factor_sections
from quant.research.model_training_models import neutral_missing_features, validate_active_features


def model_features(*, universe: pl.DataFrame, values: dict[str, pl.DataFrame],
                   directions: dict[str, int], settings: dict, factors: list[str],
                   variant: str, as_of: dt.date,
                   missing_policy: str = 'common_complete_case_pool_for_all_three_methods',
                   maximum_missing_fraction: float = .3) -> tuple[pl.DataFrame, list[dict]]:
    if universe.filter(pl.col('trade_date') != as_of).height or not factors or len(factors) != len(set(factors)):
        raise ValueError('Require one signal date and distinct model factors')
    impute = missing_policy == 'neutral_zero_with_monthly_factor_exclusion'
    if missing_policy not in {'common_complete_case_pool_for_all_three_methods', 'neutral_zero_with_monthly_factor_exclusion'}:
        raise ValueError('Unknown model missing-feature policy')
    if impute and variant != 'size_industry_neutral':
        raise ValueError('Neutral-zero filling requires neutral scores')
    frames, coverage = [], []
    for factor in factors:
        frame = values[factor]
        if frame.filter(pl.col('trade_date') != as_of).height:
            raise ValueError('Factor values cross the signal date')
        scores = score_factor_sections(universe=universe, values=frame,
            direction=directions[factor], settings=settings)
        scores = scores.select(
            'symbol', 'trade_date', pl.col(variant).alias(factor))
        if not impute:
            scores = scores.filter(pl.col(factor).is_finite())
            coverage.append({'factor': factor, 'eligible_finite_stocks': scores.height})
        frames.append(scores)
    if impute:
        common = neutral_missing_features(pool=universe.filter(pl.col('eligible')).select(
            'symbol', 'trade_date', 'total_market_value', 'industry_l1'),
            frames=frames, factors=factors, maximum_missing_fraction=maximum_missing_fraction,
            minimum_symbols=1, coverage=coverage)
        coverage = [{**row, 'trade_date': str(row['trade_date']),
            'eligible_finite_stocks': row['observed_stocks']} for row in coverage]
        return common, coverage
    common = frames[0]
    for frame in frames[1:]:
        common = common.join(frame, on=['symbol', 'trade_date'], validate='1:1')
    return common.sort('trade_date', 'symbol'), coverage


def fixed_predict(*, features: pl.DataFrame, fit: dict, method: str, source: Path,
                  minimum_symbols: int) -> pl.DataFrame:
    factors = fit['factors']
    output = features.select('symbol', 'trade_date')
    if features.height < minimum_symbols:
        return output.clear().with_columns(pl.lit(None, dtype=pl.Float64).alias('prediction'))
    matrix = features.select(factors).to_numpy()
    if not np.isfinite(matrix).all():
        raise ValueError('Prediction requires complete finite features')
    validate_active_features(features, factors,
        required=fit.get('missing_features') == 'neutral_zero_with_monthly_factor_exclusion')
    flags = [f'__active_{f}' for f in factors]
    mask = features.select(flags).to_numpy().astype(float) if all(f in features.columns for f in flags) else None
    if method == 'lightgbm':
        from lightgbm import Booster

        model = Booster(model_file=str(source/f"lightgbm_{fit['test_year']}.txt"))
        if model.num_feature() != len(factors):
            raise ValueError('Frozen model feature count differs from its fit')
        forecast = model.predict(matrix, num_threads=2)
    elif method == 'equal_z':
        forecast = matrix.mean(axis=1) if mask is None else matrix.sum(axis=1)/mask.sum(axis=1)
    elif method == 'positive_mean_ic':
        weights = np.array([fit['positive_mean_ic_weights'][f] for f in factors])
        if not np.isfinite(weights).all() or (weights <= 0).any() or not np.isclose(weights.sum(), 1.0):
            raise ValueError('Invalid frozen IC weights')
        forecast = matrix @ weights if mask is None else (matrix @ weights)/(mask @ weights)
    else:
        raise ValueError('Unknown frozen method')
    if not np.isfinite(forecast).all():
        raise ValueError('Model produced nonfinite forecasts')
    return output.with_columns(pl.Series('prediction', forecast))


def run_forecast(*, selection: Path, as_of: dt.date, output: Path, data_root: Path,
                 rehearsal: bool = False) -> dict[str, Any]:
    decision = json.loads((selection/'selection.json').read_text(encoding='utf-8'))
    config = tomllib.loads((selection/'config.toml').read_text(encoding='utf-8'))
    if decision['selected_method'] is None or decision['conclusion'] != 'RESEARCH_ONLY' or decision['auto_trade'] is not False:
        raise ValueError('Require a selected research-only method')
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    if as_of > now.date() or (as_of == now.date() and now.hour < 15):
        raise ValueError('Require a completed close')
    if as_of < dt.date.fromisoformat(decision['forward_start']) and not rehearsal:
        raise ValueError('Historical dates require --rehearsal')
    source = Path(config['research']['predictions'])
    model = tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    fits = json.loads((source/'summary.json').read_text(encoding='utf-8'))['annual_fits']
    available = [fit for fit in fits if fit.get('refit_close') and fit['refit_close'] <= str(as_of)]
    if not available:
        raise ValueError('No trained model existed at this signal date')
    fit = max(available, key=lambda row: row['refit_close'])
    if (as_of.year > fit['test_year'] or fit['last_known_exit'] > fit['refit_close']
            or fit['training_months'] < config['selection']['minimum_training_months']):
        raise ValueError('Require a causal annual model with sufficient history; refresh the annual fit')
    statistics = Path(model['research']['statistics_source'])
    from quant.data.model_forward_inputs import read_forward_universe, read_forward_values

    if as_of <= settings['run']['as_of']:
        universe = pl.scan_parquet(statistics/'inputs'/str(as_of.year)/'universe.parquet').filter(
            pl.col('trade_date') == as_of).collect()
    else:
        universe = read_forward_universe(data_root=data_root, settings=settings, as_of=as_of)
    if universe.is_empty():
        raise ValueError('No signal-date universe is available')
    factors = fit['factors']
    values = read_forward_values(data_root=data_root, factors=factors, as_of=as_of)
    roots = model['research'].get('factor_statistics_sources', {})
    directions = {factor: json.loads((Path(roots.get(factor, [str(statistics)])[0])/'factors'/factor/'statistics.json').read_text(
        encoding='utf-8'))['definition']['direction'] for factor in factors}
    features, coverage = model_features(universe=universe, values=values, directions=directions,
        settings=settings, factors=factors, variant=model['selection']['variant'], as_of=as_of,
        missing_policy=model['models'].get('missing_features', 'common_complete_case_pool_for_all_three_methods'),
        maximum_missing_fraction=model['models'].get('maximum_missing_fraction', .3))
    predictions = fixed_predict(features=features, fit=fit, method=decision['selected_method'],
        source=source, minimum_symbols=model['models']['minimum_signal_stocks'])
    result = {'as_of': str(as_of),
        'method': decision['selected_method'], 'rehearsal': rehearsal,
        'conclusion': 'RESEARCH_ONLY', 'auto_trade': False, 'refit_close': fit['refit_close'],
        'eligible_stocks': universe.filter(pl.col('eligible')).height,
        'common_feature_stocks': features.height, 'prediction_stocks': predictions.height,
        'coverage': coverage, 'source_selection': str(selection),
        'action': 'record_research_forecasts' if predictions.height else 'record_missing_inputs_keep_existing_positions'}
    output.mkdir(parents=True, exist_ok=False)
    features.write_parquet(output/'features.parquet')
    predictions.write_parquet(output/'predictions.parquet')
    result['recorded_at'] = dt.datetime.now(now.tzinfo).isoformat()
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 固定模型预测记录', '', f"日期{as_of}；方法{result['method']}；演练={rehearsal}。",
        f"可选股票{result['eligible_stocks']}只，可用模型特征{features.height}只，预测{predictions.height}只。", '',
        '仅作研究预测记录。' if predictions.height else '输入不足：本次不产生新信号，已有持仓保持原处理规则。', '',
        '|因子|有效股票数|', '|---|---:|']
    lines += [f"|{row['factor']}|{row['eligible_finite_stocks']}|" for row in coverage]
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--as-of', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--rehearsal', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run_forecast(selection=args.selection, as_of=args.as_of, output=args.output,
        data_root=args.data_root, rehearsal=args.rehearsal)))


if __name__ == '__main__':
    main()
