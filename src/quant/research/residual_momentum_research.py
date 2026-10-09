"""Fixed literature family through the existing battery's monthly statistical stage."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.factors.residual_momentum import compute_residual_momentum, SIGNAL_COLUMNS
from quant.research.factor_battery_evaluation import evaluate_factor_year, summarize_factor_statistics
from quant.research.factor_battery_screen import screen_statistics
from quant.research.factor_battery_statistics import monthly_ic_summary
from quant.research.residual_momentum_inputs import digest, freeze_inputs, write_json


def verify_inputs(inputs: Path) -> dict:
    manifest = json.loads((inputs/'input_manifest.json').read_text(encoding='utf-8'))
    if digest(inputs/'config.toml') != manifest['config_sha256']:
        raise ValueError('Frozen research configuration changed')
    for name, sha in manifest['projected_files'].items():
        if digest(inputs/name) != sha:
            raise ValueError('Frozen monthly input changed: ' + name)
    return manifest


def signals(output: Path) -> dict:
    inputs = output/'inputs'
    manifest = verify_inputs(inputs)
    spec = tomllib.loads((inputs/'config.toml').read_text(encoding='utf-8'))
    if (output/'signals.parquet').exists():
        raise ValueError('Signals already exist; reuse statistics or use a new experiment directory')
    monthly = compute_residual_momentum(pl.read_parquet(inputs/'monthly_returns.parquet'),
        pl.read_parquet(inputs/'monthly_factors.parquet'),
        month_ends=tuple(dt.date.fromisoformat(day) for day in manifest['month_ends']),
        risk_free_monthly=spec['signal']['risk_free_monthly'])
    monthly = monthly.filter(pl.col('trade_date').is_between(spec['data']['start'], spec['data']['as_of']))
    monthly.write_parquet(output/'signals.parquet')
    monthly.group_by('trade_date').agg(
        pl.len().alias('historical_symbols'),
        *[pl.col(name).count().alias(name) for name in SIGNAL_COLUMNS]
    ).sort('trade_date').write_parquet(output/'signal_coverage.parquet')
    result = {'rows': monthly.height, 'months': monthly['trade_date'].n_unique(),
        'source_config_sha256': manifest['config_sha256'], 'signal_sha256': digest(output/'signals.parquet'),
        'columns': list(SIGNAL_COLUMNS), 'created_at': dt.datetime.now(dt.timezone.utc),
        'code_sha256': {str(p): digest(p) for p in (
            Path('src/quant/factors/residual_momentum.py'), Path(__file__),
            Path('src/quant/research/residual_momentum_inputs.py'))},
        'status_counts': monthly.group_by('regression_status').len().to_dicts(),
        'evaluation_scope': 'monthly signals only; not continuous account or admission'}
    write_json(output/'signal_summary.json', result)
    return result


def masked_labels(path: Path, *, sessions, as_of, dates):
    frame = pl.scan_parquet(path).filter(pl.col('trade_date').is_in(dates)).collect().rename({'ts_code': 'symbol'})
    return frame.with_columns(*[
        pl.when(pl.col('trade_date') <= sessions[-h-2]).then(pl.col(f'label_{h}'))
        .otherwise(None).alias(f'label_{h}') for h in (1, 5, 10, 20, 60)])


def statistical_stage(*, output: Path, data_root: Path) -> dict:
    """Use all predeclared controls; label-based results never change a signal."""
    inputs = output/'inputs'
    verify_inputs(inputs)
    spec = tomllib.loads((inputs/'config.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((inputs/'battery.toml').read_text(encoding='utf-8'))
    signal_info = json.loads((output/'signal_summary.json').read_text(encoding='utf-8'))
    if digest(output/'signals.parquet') != signal_info['signal_sha256']:
        raise ValueError('Frozen signals changed')
    signal = pl.read_parquet(output/'signals.parquet')
    source = Path(spec['data']['statistics_source'])
    if json.loads((source/'summary.json').read_text())['as_of'] != str(spec['data']['as_of']):
        raise ValueError('Saved battery input cutoff differs from this experiment')
    stage = output/'statistics'
    stage.mkdir(exist_ok=False)
    (stage/'battery.toml').write_bytes((inputs/'battery.toml').read_bytes())
    sessions = available_sessions(data_root, spec['data']['as_of'])
    parts = {name: [] for name in SIGNAL_COLUMNS}
    label_hashes = {}
    for year in sorted(set(signal['trade_date'].dt.year())):
        values = signal.filter(pl.col('trade_date').dt.year() == year)
        dates = values['trade_date'].unique().to_list()
        paths = {'universe': source/f'inputs/{year}/universe.parquet',
                 'monthly': source/f'inputs/{year}/monthly_labels.parquet',
                 'daily': data_root/f'factors/forward_returns/year={year}/data.parquet'}
        before = {str(p): digest(p) for p in paths.values()}
        universe = pl.scan_parquet(paths['universe']).filter(pl.col('trade_date').is_in(dates)).collect()
        labels = pl.scan_parquet(paths['monthly']).filter(pl.col('trade_date').is_in(dates)).collect()
        daily = masked_labels(paths['daily'], sessions=sessions, as_of=spec['data']['as_of'], dates=dates)
        for name in SIGNAL_COLUMNS:
            # Within each formation period require all three arms to be finite.
            suffix = '12_1' if '12_1' in name else '6_skip1'
            common = [f'residual_momentum_{suffix}_ff3_36', f'raw_momentum_{suffix}',
                      f'vol_scaled_momentum_{suffix}']
            factor_values = values.select('symbol', 'trade_date',
                pl.when(pl.all_horizontal(pl.col(c).is_finite().fill_null(False) for c in common))
                .then(pl.col(name)).otherwise(None).alias('value'))
            parts[name].append(evaluate_factor_year(universe=universe, values=factor_values,
                daily_labels=daily, monthly_labels=labels, direction=1, settings=settings))
        if any(digest(Path(p)) != sha for p, sha in before.items()):
            raise ValueError('Saved label/control input changed during evaluation')
        label_hashes.update(before)
        print(json.dumps({'statistical_year': year, 'signals': len(parts)}), flush=True)
    rows, ic_tables = [], {}
    for name, pieces in parts.items():
        summaries, persistence = summarize_factor_statistics(pieces, sessions=sessions, settings=settings)
        folder = stage/name
        folder.mkdir()
        for field in ('daily_ic', 'monthly_ic', 'monthly_groups', 'monthly_scores'):
            combined = pl.concat([getattr(piece, field) for piece in pieces], how='vertical_relaxed')
            combined.write_parquet(folder/f'{field}.parquet')
            if field == 'monthly_ic':
                ic_tables[name] = combined
        persistence.write_parquet(folder/'persistence.parquet')
        rows.extend({'factor': name, 'family': 'residual_momentum_fixed_literature_family',
                     'direction': 1, **summary} for summary in summaries)
    table = pl.from_dicts(rows, infer_schema_length=None)
    table.write_parquet(stage/'statistics.parquet')
    screen = screen_statistics(table, factors=list(SIGNAL_COLUMNS), settings=settings)
    screen.write_parquet(stage/'statistical_screen.parquet')
    paired = []
    for suffix in ('12_1', '6_skip1'):
        residual = ic_tables[f'residual_momentum_{suffix}_ff3_36']
        for control in (f'raw_momentum_{suffix}', f'vol_scaled_momentum_{suffix}'):
            for variant in settings['variants']:
                pair = residual.filter(pl.col('variant') == variant).select('trade_date',
                    pl.col('rank_ic').alias('residual_ic')).join(
                        ic_tables[control].filter(pl.col('variant') == variant).select('trade_date',
                            pl.col('rank_ic').alias('control_ic')), on='trade_date', validate='1:1').sort('trade_date')
                delta = pair.select(pl.col('residual_ic') - pl.col('control_ic')).to_series().to_list()
                paired.append({'formation': suffix, 'control': control, 'variant': variant,
                    **monthly_ic_summary(pair['trade_date'].to_list(), delta, lag=6)})
    write_json(stage/'paired_ic.json', paired)
    survivors = screen.filter((pl.col('variant') == settings['primary_variant'])
        & pl.col('factor').str.starts_with('residual_') & pl.col('statistical_pass'))['factor'].to_list()
    summary = {'experiment': spec['research']['id'], 'as_of': spec['data']['as_of'],
        'stage': 'completed_monthly_battery_statistics', 'auto_trade': False,
        'primary_statistical_survivors': survivors,
        'decision': 'CONTINUE_REMAINING_BATTERY' if survivors else 'STOP_FIXED_POSITIVE_RESIDUAL_MOMENTUM_FAMILY',
        'factor_admissions': None, 'account_replays': 0, 'cost_after_gain_established': False,
        'limitations': ['Retrospective history, not unseen holdout',
            'Month-end signals only; decay is month-end sampled, not full daily battery',
            'Adjusted-price and local size/value proxy, not official FF3 or audited wealth index',
            'Long-short groups are gross diagnostics, not shortable personal-account returns',
            'No sign flip, parameter search, Top-K rescue or admission from this stage'],
        'statistics': screen.select('factor', 'variant', 'months', 'mean_ic', 'icir', 'newey_west_t',
            'yearly_positive_fraction', 'long_short_sharpe', 'statistical_pass', 'statistical_failures',
            'bh_adjusted_p').to_dicts(), 'source_hashes': label_hashes,
        'completed_at': dt.datetime.now(dt.timezone.utc)}
    write_json(output/'summary.json', summary)
    report = ['# 残差动量固定族：月度电池统计阶段', '',
        '使用既有电池的预处理、次开盘标签和统计门槛；本报告不是成本后账户收益或因子准入。', '',
        '|信号|版本|月数|Rank IC|ICIR|NW t|年度正率|分组多空 Sharpe|统计通过|',
        '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for r in summary['statistics']:
        def fmt(key):
            return 'NA' if r[key] is None else f'{r[key]:.4f}'
        report.append(f"|{r['factor']}|{r['variant']}|{r['months']}|{fmt('mean_ic')}|{fmt('icir')}|"
            f"{fmt('newey_west_t')}|{fmt('yearly_positive_fraction')}|{fmt('long_short_sharpe')}|{r['statistical_pass']}|")
    report += ['', '下一步：' + ('继续剩余电池验证。' if survivors else '停止此固定正向残差动量族，不翻转方向或调窗救回。'),
        '', '边界：' + '；'.join(summary['limitations']), '',
        '[原始论文](https://repub.eur.nl/pub/22252/ResidualMomentum-2011.pdf)。',
        '具体配对增量见 statistics/paired_ic.json，年度及分组证据见 statistics/*/*.parquet。']
    (output/'report.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/residual_momentum_family_20260930.toml'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=('freeze', 'signals', 'statistics'), required=True)
    args = parser.parse_args()
    if args.stage == 'freeze':
        result = freeze_inputs(config=args.config, output=args.output/'inputs', data_root=args.data_root)
    elif args.stage == 'signals':
        result = signals(args.output)
    else:
        result = statistical_stage(output=args.output, data_root=args.data_root)
    print(json.dumps({k: v for k, v in result.items() if k not in ('source_hashes', 'source_files', 'statistics')},
                     default=str, ensure_ascii=False))


if __name__ == '__main__':
    main()
