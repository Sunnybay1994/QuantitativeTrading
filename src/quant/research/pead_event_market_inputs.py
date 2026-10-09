"""Freeze existing market observations and inspect PEAD event eligibility."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.research.residual_momentum_inputs import digest, write_json


def freeze(*, output: Path, data_root: Path, config: Path):
    inputs = output/'inputs'
    parent = json.loads((inputs/'manifest.json').read_text(encoding='utf-8'))
    for name, sha in parent['files'].items():
        if digest(inputs/name) != sha:
            raise ValueError('Financial-stage input changed: '+name)
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    settings = tomllib.loads((inputs/'refresh.toml').read_text(encoding='utf-8'))
    history = data_root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']/'bar_1d/asset=stock'
    sources = sorted(p for p in history.glob('year=*/*.parquet')
                     if int(p.parent.name[5:]) <= spec['data']['end'].year)
    for folder in sorted((data_root/'clean/tushare_incremental').glob('date=*')):
        if (str(spec['data']['start']) <= folder.name[5:] <= str(spec['data']['end'])
                and all((folder/f'{name}.parquet').is_file()
                        for name in ('bar_1d', 'adjust_factor', 'daily_basic'))):
            sources.append(folder/'bar_1d.parquet')
    name_source = data_root/'clean/stock_name_history/data.parquet'
    before = {str(p): digest(p) for p in [*sources, name_source]}
    if not sources:
        raise ValueError('No historical market sources')
    frames = [pl.scan_parquet(path).select(spec['data']['bar_fields'])
        .filter(pl.col('trade_date').is_between(spec['data']['start'], spec['data']['end'])
                & pl.col('symbol').str.contains(r'^(60|68|00|30)[0-9]{4}\.(SH|SZ)$'))
        .with_columns(pl.lit(index).alias('_source_priority'))
        for index, path in enumerate(sources)]
    bars = pl.concat(frames, how='vertical_relaxed').collect()
    duplicates = bars.select('symbol', 'trade_date', '_source_priority').is_duplicated().sum()
    if duplicates:
        raise ValueError(f'Duplicate daily keys within a source partition: {duplicates}')
    original_rows = bars.height
    bars = (bars.sort('_source_priority').unique(['symbol', 'trade_date'], keep='last')
            .drop('_source_priority').sort('symbol', 'trade_date'))
    names = pl.read_parquet(name_source).filter(pl.col('symbol').is_in(bars['symbol'].unique().implode()))
    if any(digest(Path(path)) != sha for path, sha in before.items()):
        raise ValueError('Market source changed during freeze')
    target = output/'market_inputs'
    target.mkdir(exist_ok=False)
    (target/'config.toml').write_bytes(config.read_bytes())
    bars.write_parquet(target/'bars.parquet')
    names.write_parquet(target/'names.parquet')
    result = {'frozen_at': dt.datetime.now(dt.timezone.utc), 'bar_rows': bars.height,
        'symbols': bars['symbol'].n_unique(), 'first_date': bars['trade_date'].min(),
        'last_date': bars['trade_date'].max(), 'overlap_rows': original_rows-bars.height,
        'names_rows': names.height, 'sources_sha256': before,
        'financial_manifest_sha256': digest(inputs/'manifest.json'),
        'files': {p.name: digest(p) for p in target.iterdir() if p.is_file()},
        'code_sha256': digest(Path(__file__)), 'auto_trade': False,
        'strategy_validity_evaluated': False}
    write_json(target/'manifest.json', result)
    return result


def run(*, output: Path):
    from quant.research.pead_event_eligibility import enrich_event_eligibility
    target = output/'market_inputs'
    manifest = json.loads((target/'manifest.json').read_text(encoding='utf-8'))
    if digest(output/'inputs/manifest.json') != manifest['financial_manifest_sha256']:
        raise ValueError('Financial manifest changed')
    parent = json.loads((output/'inputs/manifest.json').read_text(encoding='utf-8'))
    for name, sha in parent['files'].items():
        if digest(output/'inputs'/name) != sha:
            raise ValueError('Financial input changed: '+name)
    for name, sha in manifest['files'].items():
        if digest(target/name) != sha:
            raise ValueError('Market input changed: '+name)
    spec = tomllib.loads((target/'config.toml').read_text(encoding='utf-8'))
    expected = {'eligibility': {'liquidity_sessions': 20, 'minimum_average_amount': 20000000.,
                                'minimum_valid_price_observations': 120},
                'threshold': {'minimum_events': 100, 'quantile': .9, 'interpolation': 'linear'}}
    if any(spec[section].get(key) != value for section, values in expected.items()
           for key, value in values.items()):
        raise ValueError('Eligibility module only implements the registered fixed B31 rules')
    event_summary = json.loads((output/'summary.json').read_text(encoding='utf-8'))
    if digest(output/'events.parquet') != event_summary['events_sha256']:
        raise ValueError('Financial events changed')
    result_dir = output/'eligibility'
    result_dir.mkdir(exist_ok=False)
    code = {p.name: p for p in [Path(__file__), Path(__file__).with_name('pead_event_eligibility.py')]}
    hashes = {name: digest(p) for name, p in code.items()}
    for name, path in code.items():
        (result_dir/name).write_bytes(path.read_bytes())
    write_json(result_dir/'input_identity.json', {'events_sha256': event_summary['events_sha256'],
        'market_manifest_sha256': digest(target/'manifest.json'), 'code_sha256': hashes})
    sessions = tuple(dt.date.fromisoformat(day) for day in
        json.loads((output/'inputs/sessions.json').read_text(encoding='utf-8')))
    frame = enrich_event_eligibility(events=pl.read_parquet(output/'events.parquet'),
        bars=pl.read_parquet(target/'bars.parquet'), names=pl.read_parquet(target/'names.parquet'),
        sessions=sessions)
    if any(digest(p) != hashes[name] for name, p in code.items()):
        raise ValueError('Eligibility code changed during execution')
    frame.write_parquet(result_dir/'events.parquet')
    coverage = frame.group_by(pl.col('announcement_date').dt.year().alias('year')).agg(
        pl.len().alias('financial_events'), (pl.col('status') == 'VALID').sum().alias('valid_financial'),
        pl.col('market_eligible').sum().alias('market_eligible'),
        (pl.col('market_eligible') & (pl.col('status') == 'VALID')).sum().alias('valid_eligible'),
        pl.col('selected').sum().alias('selected')).sort('year')
    coverage.write_csv(result_dir/'yearly_coverage.csv')
    result = {'stage': 'financial_and_market_event_inputs_complete', 'completed_at': dt.datetime.now(dt.timezone.utc),
        'auto_trade': False, 'events': frame.height, 'yearly_coverage': coverage.to_dicts(),
        'selected_events': int(frame['selected'].sum()), 'account_replays': 0,
        'cost_after_gain_established': False, 'original_vintage_proven': False,
        'events_sha256': digest(result_dir/'events.parquet'),
        'remaining': ['Freeze continuous personal CNY100k fee1 portfolio and matched same-event comparator',
                      'Complete entry/exit execution inputs and three-cost account/risk evaluation'],
        'limits': tomllib.loads((target/'config.toml').read_text(encoding='utf-8'))['limits']}
    write_json(result_dir/'summary.json', result)
    lines = ['# 公告事件市场资格与历史覆盖', '',
        '本阶段仅生成信号和可用性证据，尚未进行收益回测、账户执行或准入判定。', '',
        '|年份|财报事件|财务有效|市场合格|二者满足|上季阈值选中|', '|---:|---:|---:|---:|---:|---:|']
    lines += ['|'+'|'.join(str(row[key]) for key in coverage.columns)+'|' for row in coverage.to_dicts()]
    lines += ['', '下一步：'+'；'.join(result['remaining']), '', '数据边界：'+str(result['limits'])]
    (result_dir/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('freeze', 'eligibility'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--config', type=Path, default=Path('configs/research/pead_event_market_inputs_20260930.toml'))
    args = parser.parse_args()
    result = (freeze(output=args.output, data_root=args.data_root, config=args.config)
              if args.stage == 'freeze' else run(output=args.output))
    print(json.dumps({k: v for k, v in result.items()
        if k not in ('sources_sha256', 'files', 'yearly_coverage')}, default=str))


if __name__ == '__main__':
    main()
