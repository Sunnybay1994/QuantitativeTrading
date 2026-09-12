"""Export one saved annual LightGBM fit for quality-checked research forecasts."""
import argparse
import datetime as dt
import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

import polars as pl


def export_annual(*, run: Path, output: Path, forward_start: dt.date,
                  refresh_config: Path = Path('configs/data/refresh.toml'),
                  now: dt.datetime | None = None) -> dict[str, Any]:
    """Copy the completed fit; do not train, select a method or change an account."""
    from lightgbm import Booster

    clock = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    freeze_date = clock.date()
    source = run/'predictions'
    config = tomllib.loads((run/'config.toml').read_text(encoding='utf-8'))
    completed = json.loads((run/'summary.json').read_text(encoding='utf-8'))
    report = json.loads((run/'reports/summary.json').read_text(encoding='utf-8'))
    saved = json.loads((source/'summary.json').read_text(encoding='utf-8'))
    model = tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    battery = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    refresh = tomllib.loads(refresh_config.read_text(encoding='utf-8'))
    if (config['research']['auto_trade'] is not False or model['execution']['auto_trade'] is not False
            or config['model']['method'] != 'lightgbm' or model['models']['methods'] != ['lightgbm']):
        raise ValueError('Require a research-only saved annual LightGBM run')
    if (completed['research_id'] != config['research']['id']
            or model['research']['id'] != completed['research_id']
            or completed['annual_fits'] != saved['annual_fits']
            or completed['prediction_rows'] != saved['prediction_rows']
            or completed['conclusions'] != report['conclusions']):
        raise ValueError('Completed run, prediction and report summaries disagree')
    if not refresh.get('quality', {}).get('enabled', False):
        raise ValueError('Frozen forecasts require enabled local input quality')
    if not freeze_date < forward_start or forward_start <= model['walk_forward']['test_end']:
        raise ValueError('Forward start must follow the actual export date and historical evidence')
    fits = [fit for fit in saved['annual_fits'] if fit['test_year'] == forward_start.year]
    if len(fits) != 1:
        raise ValueError('Require exactly one saved annual fit for the forward year')
    fit = fits[0]
    factors = fit['factors']
    if (not factors or len(factors) != len(set(factors))
            or any(not isinstance(f, str) or not f for f in factors) or not fit.get('refit_close')):
        raise ValueError('Require a trained annual fit with distinct nonempty factors')
    cutoff = dt.date.fromisoformat(fit['refit_close'])
    if (cutoff > freeze_date or cutoff.year != fit['test_year']-1
            or fit['last_known_exit'] > fit['refit_close']
            or fit['training_months'] < config['model']['minimum_training_months']):
        raise ValueError('Annual fit violates its causal training window')
    policy = model['models']['missing_features']
    if (policy != config['model']['missing_features'] or policy != fit['missing_features']
            or model['models']['minimum_signal_stocks'] != config['model']['minimum_signal_stocks']
            or (policy == 'neutral_zero_with_monthly_factor_exclusion'
                and (model['selection']['variant'] != 'size_industry_neutral'
                     or model['models']['maximum_missing_fraction'] != config['model']['maximum_missing_fraction']))):
        raise ValueError('Saved fit and actual annual feature policies disagree')
    predictions = pl.scan_parquet(source/'monthly_predictions.parquet')
    if (predictions.select(pl.len()).collect().item() != saved['prediction_rows']
            or predictions.filter(pl.col('test_year') == fit['test_year']).select(pl.len()).collect().item()
                != fit['prediction_rows'] or fit['prediction_rows'] <= 0):
        raise ValueError('Completed prediction rows do not match the saved annual fit')
    model_path = source/f"lightgbm_{fit['test_year']}.txt"
    booster = Booster(model_file=str(model_path))
    if booster.num_feature() != len(factors):
        raise ValueError('Saved LightGBM feature count differs from the annual factor order')
    statistics = Path(model['research']['statistics_source'])
    roots = model['research'].get('factor_statistics_sources', {})
    directions, statistics_sources = {}, {}
    for factor in factors:
        paths = [Path(p) for p in roots.get(factor, [str(statistics)])]
        if not paths:
            raise ValueError('Each frozen factor requires its saved statistics source')
        definition = json.loads((paths[0]/'factors'/factor/'statistics.json').read_text(encoding='utf-8'))['definition']
        if definition['direction'] not in (-1, 1):
            raise ValueError('Factor direction must be signed')
        directions[factor] = definition['direction']
        statistics_sources[factor] = [str(path.resolve()) for path in paths]
    result = {'research_id': completed['research_id'], 'selected_method': 'lightgbm',
        'selection_rule': 'explicit_saved_annual_fit_no_method_selection',
        'conclusion': 'RESEARCH_ONLY', 'source_conclusion': completed['conclusions']['lightgbm'],
        'auto_trade': False, 'frozen_at': clock.isoformat(), 'freeze_date': str(freeze_date),
        'forward_start': str(forward_start), 'source_run': str(run.resolve()),
        'requires_local_quality': True, 'refresh_config': str(refresh_config.resolve()),
        'test_year': fit['test_year'], 'refit_close': fit['refit_close'],
        'factors': factors, 'factor_directions': directions, 'missing_features': policy,
        'maximum_missing_fraction': model['models'].get('maximum_missing_fraction'),
        'control_policy': 'finite_positive_total_market_value_and_nonempty_industry_l1',
        'lightgbm_parameters': model['models']['lightgbm'],
        'statistics_source': str(statistics.resolve()), 'factor_statistics_sources': statistics_sources,
        'statistics_as_of': str(battery['run']['as_of']),
        'historical_evidence': config['research'].get('historical_evidence', 'retrospective_annual_walk_forward')}
    # A small frozen copy leaves historical replay files and default selections untouched.
    output.mkdir(parents=True, exist_ok=False)
    frozen = output/'predictions'
    frozen.mkdir()
    for name in ('model.toml', 'battery.toml', model_path.name):
        shutil.copyfile(source/name, frozen/name)
    shutil.copyfile(run/'config.toml', output/'source_config.toml')
    (frozen/'summary.json').write_text(json.dumps({'annual_fits': [fit],
        'prediction_rows': fit['prediction_rows']}, indent=2), encoding='utf-8')
    (output/'config.toml').write_text('[research]\npredictions = '+json.dumps(frozen.resolve().as_posix())+
        '\n[selection]\nminimum_training_months = '+str(config['model']['minimum_training_months'])+'\n',
        encoding='utf-8')
    (output/'selection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'report.md').write_text(f"# 年度模型冻结研究入口\n\n来源：{run.resolve()}\n\n"
        f"冻结日期 {freeze_date}；前向开始 {forward_start}；年度 {fit['test_year']}；因子 {len(factors)} 个。\n\n"
        f"沿用已保存 LightGBM，源研究结论 {result['source_conclusion']}；本导出仅 RESEARCH_ONLY。\n\n"
        "使用 quant.research.run_daily_model_forecast --saved-data 或 run_fixed_model_forecast 运行本地质量检查。"
        "历史核对必须 --rehearsal；输入质量错误时保留检查记录并停止预测。\n", encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--forward-start', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--refresh-config', type=Path, default=Path('configs/data/refresh.toml'))
    print(json.dumps(export_annual(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == '__main__':
    main()
