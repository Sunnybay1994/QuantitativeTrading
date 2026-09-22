"""Historical and available-at snapshot entry point for market indicators."""
import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import tomllib
from pathlib import Path

import pandas as pd
import polars as pl

from quant.data.refresh_stocks import read_stock_data
from quant.research.market_indicators import (
    aggregate_daily, conditional_returns, realtime_snapshot, score_states, stock_features,
)

TZ = dt.timezone(dt.timedelta(hours=8))


def load_config(path):
    cfg = tomllib.loads(path.read_text(encoding='utf-8'))
    if (cfg['auto_trade'] is not False or not 0 < cfg['minimum_coverage'] <= 1
            or cfg['minimum_stocks'] < 1 or not 0 <= cfg['low_percentile'] < cfg['high_percentile'] <= 100
            or not 1 <= cfg['minimum_history'] <= cfg['normalization_window']
            or cfg['quote_max_age_seconds'] <= 0):
        raise ValueError('Invalid indicator configuration')
    return cfg


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False),
                    encoding='utf-8')


def read_benchmark(path, end):
    """Frozen 510300 fund-adjusted prices for trend/vol, not a strategy return."""
    bars = pl.read_parquet(path).filter(pl.col('trade_date') <= end).sort('trade_date')
    if (bars.height < 2 or set(bars['symbol']) != {'510300.SH'}
            or bars['trade_date'].is_duplicated().any()):
        raise ValueError('Invalid market benchmark')
    adjusted = bars['close'] * bars['adj_factor']
    if adjusted.null_count() or not adjusted.is_finite().all() or (adjusted <= 0).any():
        raise ValueError('Invalid adjusted benchmark price')
    return bars.select(pl.col('trade_date').alias('date')).with_columns(
        (adjusted / adjusted[0]).alias('unit_nav'))


def source_inventory(data_root, settings, start, end):
    """Capture exact on-disk source identities before and after a read."""
    paths = []
    for year in range(start.year, end.year + 1):
        paths += list((data_root / 'clean/tushare_bulk/snapshots' / settings['stock_snapshot']
                       / f'bar_1d/asset=stock/year={year}').glob('*.parquet'))
        paths += list((data_root / 'clean/tushare_daily_basic/snapshots' / settings['daily_basic_snapshot']
                       / f'year={year}').glob('*.parquet'))
    for folder in (data_root / 'clean/tushare_incremental').glob('date=*'):
        if str(start) <= folder.name[5:] <= str(end):
            paths += [p for p in folder.glob('*.parquet') if p.stem in ('bar_1d', 'daily_basic', 'adjust_factor')]
    return {str(p): {'bytes': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns} for p in sorted(set(paths))}


def history(config, output, *, start=None, end=None, data_root=Path('data'), returns_path=None):
    cfg = load_config(config)
    start, end = start or cfg['start'], end or cfg['end']
    if start > end or end >= dt.datetime.now(TZ).date():
        raise ValueError('Historical run requires a completed prior date')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config.toml').write_bytes(config.read_bytes())
    refresh = Path(cfg['refresh_config'])
    frozen_refresh = output / 'refresh_config.toml'
    frozen_refresh.write_bytes(refresh.read_bytes())
    settings = tomllib.loads(frozen_refresh.read_text(encoding='utf-8'))
    benchmark_snapshot = (settings['factor_benchmark_snapshot'] if
        cfg['benchmark_snapshot'] == 'from_refresh_config' else cfg['benchmark_snapshot'])
    benchmark_path = data_root / 'clean/factor_benchmark' / benchmark_snapshot / 'bars.parquet'
    benchmark = read_benchmark(benchmark_path, end)
    warm = start - dt.timedelta(days=560)
    calendar_path = data_root / 'clean/trade_calendar/market=SH/data.parquet'
    calendar = pl.read_parquet(calendar_path).filter(pl.col('is_open')).sort('date')
    next_sessions = calendar.filter(pl.col('date') > end)['date'].head(1).to_list()
    if not next_sessions:
        raise ValueError('Next exchange session unavailable')
    sessions = calendar.filter(pl.col('date').is_between(warm - dt.timedelta(days=140), next_sessions[0]))['date'].to_list()
    inventory = source_inventory(data_root, settings, warm - dt.timedelta(days=140), end)
    daily, reference = [], None
    for year in range(warm.year, end.year + 1):
        lo, hi = max(warm, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        read_start = lo - dt.timedelta(days=140)
        bars = read_stock_data(data_root=data_root, config=frozen_refresh, table='bar_1d', start=read_start, end=hi)
        basic = read_stock_data(data_root=data_root, config=frozen_refresh, table='daily_basic', start=read_start, end=hi)
        panel = stock_features(bars, basic, sessions)
        if panel.is_empty():
            continue
        agg = aggregate_daily(panel, cfg['minimum_stocks'], cfg['minimum_coverage'])
        daily.append(agg.filter(pl.col('trade_date').is_between(lo, hi)))
        if year == end.year:
            last_seq = panel['session'].max()
            reference = panel.filter(pl.col('session') >= last_seq - 20).sort('trade_date').unique('symbol', keep='last')
            reference = reference.select('symbol', 'trade_date', 'close', 'adj_close', 'ma20', 'past_amount20')
        print(json.dumps({'year': year, 'daily_rows': daily[-1].height}), flush=True)
    if not daily or reference is None:
        raise ValueError('No historical market input')
    after = source_inventory(data_root, settings, warm - dt.timedelta(days=140), end)
    if inventory != after:
        raise RuntimeError('Sources changed while reading; retry as new run')
    raw = pl.concat(daily).sort('trade_date')
    states = score_states(raw, benchmark, sessions, cfg).filter(pl.col('trade_date').is_between(start, end))
    raw.write_parquet(output / 'daily_components.parquet')
    benchmark.write_parquet(output / 'benchmark.parquet')
    states.write_parquet(output / 'market_states.parquet')
    states.write_csv(output / 'market_states.csv')
    states.with_columns(pl.col('trade_date').dt.year().alias('year')).group_by(
        'year', 'market_state').agg(pl.len().alias('sessions'),
        pl.col('coverage').min().alias('minimum_coverage')).sort('year', 'market_state').write_csv(
            output / 'state_quality_by_year.csv')
    reference.write_parquet(output / 'latest_reference.parquet')
    manifest = dict(created_at=dt.datetime.now(TZ).isoformat(), source_files=inventory,
        source_identity_note='Historical snapshot IDs plus size/mtime guard; these are not per-file content hashes.',
        stock_snapshot=settings['stock_snapshot'], daily_basic_snapshot=settings['daily_basic_snapshot'],
        benchmark_snapshot=benchmark_snapshot,
        benchmark_sha256=hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
        calendar_sha256=hashlib.sha256(calendar_path.read_bytes()).hexdigest(),
        code_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                     [Path(__file__), Path(__file__).with_name('market_indicators.py')]},
        outputs_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.parquet')})
    write_json(output / 'source_manifest.json', manifest)
    counts = states.group_by('market_state').len().sort('market_state')
    summary = dict(scope=cfg['scope'], start=str(start), end=str(end), days=states.height,
        state_counts=counts.to_dicts(), latest=states.tail(1).to_dicts()[0],
        source_timing='Reconstructed history, not original data-arrival evidence',
        limitations=['Observed rolling active universe, not a verified listing/suspension census.',
                    'No full-sample normalizers, profit-fitted states or automatic strategy switching.',
                    'Sentiment is a price/breadth proxy, not Baker-Wurgler, survey sentiment or VIX.'])
    if returns_path:
        r = pd.read_csv(returns_path, parse_dates=['date']).set_index('date')
        conditional = conditional_returns(states, r)
        conditional.to_csv(output / 'conditional_returns.csv', index=False)
        summary['returns_path'] = str(returns_path)
        summary['returns_sha256'] = hashlib.sha256(returns_path.read_bytes()).hexdigest()
    write_json(output / 'summary.json', summary)
    table = states.tail(10).select('trade_date', 'reference_stocks', 'coverage', 'liquidity_score',
        'sentiment_proxy_score', 'volatility_percentile', 'trend', 'market_state').to_pandas().round(3).to_markdown(index=False)
    report = ('# 市场流动性、情绪代理与状态\n\n机器生成；研究描述，不更改策略或准入。\n\n'
        + f'区间 {start} 至 {end}，{states.height} 个交易日。范围：{cfg["scope"]}。\n\n'
        + counts.to_pandas().to_markdown(index=False) + '\n\n## 最近观测\n\n' + table
        + '\n\n## 口径与边界\n\n'
        + '- 流动性：换手率中位数历史分位与Amihud价格冲击反向历史分位等权；金额单位人民币。\n'
        + '- 情绪代理：涨跌家数差、站上20日均线比例、收盘区间位置的历史分位等权。不是心理情绪实测。\n'
        + '- 标准化只用前252个交易日中的至少126个有效值；当日不进入自己的参考分布。缺分量不改权重。\n'
        + '- 状态在收盘后形成，effective_date为下一交易日；历史available_at无法证明，不冒充当时可获取。\n'
        + '- 分母为过去20日或当日出现的沪深A股；缺失不等于停牌，覆盖不足状态unknown。北交所未纳入。\n'
        + '- 市场宽度、波动、交易拥挤度单独保留；不把成交放量直接解释成流动性充裕。\n'
        + '- conditional_returns.csv仅按滞后状态和年份描述日均收益/样本量，不拼接不连续日期，不证明择时增益。\n'
        + '- 原始指标/下一日标签/输入身份/规范均已保存。live命令读取已有行情或规范化快照，不启动行情采集。\n')
    if returns_path and not conditional.empty:
        totals = conditional.assign(weighted_bps=lambda x: x.mean_daily_bps * x.sessions).groupby(
            ['strategy', 'state']).agg(sessions=('sessions', 'sum'),
                years=('year', 'nunique'), positive_year_slices=('mean_daily_bps', lambda x: (x > 0).sum()),
                weighted_bps=('weighted_bps', 'sum')).reset_index()
        totals['mean_daily_bps'] = totals.pop('weighted_bps') / totals['sessions']
        totals.to_csv(output / 'conditional_summary.csv', index=False)
        report += ('\n## 滞后状态收益切片\n\n仅为所提供策略集合的描述；同源变体不算独立机制，'
                   '不连续状态样本不计算年化收益/Sharpe。现金日仍包含在输入收益中，未替用户筛选持股期。\n\n'
                   + totals.round(3).to_markdown(index=False) + '\n')
    (output / 'report.md').write_text(report, encoding='utf-8')
    return summary


def live(config, history_root, output, *, now=None, quotes_path=None):
    cfg = load_config(config)
    now = now or dt.datetime.now(TZ)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware as-of required')
    now = now.astimezone(TZ)
    reference = pl.read_parquet(history_root / 'latest_reference.parquet')
    if reference['trade_date'].max() >= now.date():
        raise ValueError('Live reference must predate snapshot')
    calendar = pl.read_parquet('data/clean/trade_calendar/market=SH/data.parquet')
    previous = calendar.filter(pl.col('is_open') & (pl.col('date') < now.date()))['date'].max()
    if reference['trade_date'].max() != previous:
        raise ValueError('Live reference is not the preceding exchange session')
    if quotes_path:
        quotes = pl.read_parquet(quotes_path).to_dicts() if quotes_path.suffix == '.parquet' else json.loads(quotes_path.read_text(encoding='utf-8'))
        if not isinstance(quotes, list):
            raise ValueError('Quotes must be a list of normalized records')
    else:
        database = Path(cfg['realtime_database']).resolve()
        if not database.exists():
            raise FileNotFoundError(database)
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            rows = db.execute('SELECT payload FROM quotes WHERE id IN '
                '(SELECT MAX(id) FROM quotes WHERE received_at<=? AND provider_time<=? GROUP BY symbol)',
                (now.isoformat(), now.isoformat())).fetchall()
        quotes = [json.loads(row[0]) for row in rows]
    result = realtime_snapshot(quotes, reference, now=now, settings=cfg)
    result['reference_date'] = str(previous)
    open_today = calendar.filter((pl.col('date') == now.date()) & pl.col('is_open')).height == 1
    result['exchange_open_day'] = open_today
    result['session_phase'] = ('continuous' if open_today and
        (dt.time(9, 30) <= now.time() <= dt.time(11, 30) or
         dt.time(13) <= now.time() <= dt.time(15)) else 'outside_continuous_session')
    prior_state = pl.read_parquet(history_root / 'market_states.parquet').filter(pl.col('trade_date') == previous)
    result['previous_close_state'] = prior_state.select('trade_date', 'market_state').to_dicts()
    result['history_root'] = str(history_root.resolve())
    result['history_manifest_sha256'] = hashlib.sha256((history_root / 'source_manifest.json').read_bytes()).hexdigest()
    result['config_sha256'] = hashlib.sha256(config.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'snapshot.json', result)
    write_json(output / 'quotes_consumed.json', quotes)
    (output / 'report.md').write_text('# 盘中市场指标\n\n' + json.dumps(
        result, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['history', 'live'])
    parser.add_argument('--config', type=Path, default=Path('configs/research/market_indicators_v1.toml'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', type=dt.date.fromisoformat)
    parser.add_argument('--end', type=dt.date.fromisoformat)
    parser.add_argument('--returns', type=Path)
    parser.add_argument('--history', type=Path)
    parser.add_argument('--quotes', type=Path)
    parser.add_argument('--as-of', type=dt.datetime.fromisoformat)
    args = parser.parse_args()
    if args.mode == 'history':
        result = history(args.config, args.output, start=args.start, end=args.end, returns_path=args.returns)
    else:
        if args.history is None:
            parser.error('live requires --history')
        result = live(args.config, args.history, args.output, now=args.as_of, quotes_path=args.quotes)
    print(json.dumps(result, ensure_ascii=False, default=str, allow_nan=False))


if __name__ == '__main__':
    main()
