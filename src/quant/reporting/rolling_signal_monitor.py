"""Read-only rolling monitoring of already scored model and held-factor signals."""
import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.research.factor_battery_statistics import monthly_ic_summary

DEFAULT_CONFIG = Path('configs/research/rolling_signal_monitor_v1.toml')


def evaluate(*, scores: pl.DataFrame, labels: pl.DataFrame, known_through: dt.date,
             windows: list[int], minimum_months: int, lag: int, icir_warning: float,
             direction: int = 1) -> dict[str, Any]:
    """Windows use label realization calendar months; HAC retains original signal-month gaps."""
    if direction != 1 or minimum_months < 2 or lag < 0 or not math.isfinite(icir_warning):
        raise ValueError('Invalid registered monitoring settings')
    if not windows or any(w < minimum_months for w in windows) or len(set(windows)) != len(windows):
        raise ValueError('Invalid rolling windows')
    scores = scores.with_columns(pl.col('rank_ic').cast(pl.Float64), pl.col('trade_date').cast(pl.Date))
    labels = labels.with_columns(pl.col('trade_date').cast(pl.Date), pl.col('exit_date_rebalance').cast(pl.Date))
    if scores['trade_date'].is_duplicated().any():
        raise ValueError('Duplicate monthly scoring records')
    if scores.filter(pl.col('rank_ic').is_not_null()
            & (~pl.col('rank_ic').is_finite() | (pl.col('rank_ic').abs() > 1))).height:
        raise ValueError('Nonfinite IC must not be treated as zero')
    exits = labels.group_by('trade_date').agg(pl.col('exit_date_rebalance').n_unique().alias('dates'),
        pl.col('exit_date_rebalance').max())
    if exits.filter((pl.col('dates') != 1) | (pl.col('exit_date_rebalance') <= pl.col('trade_date'))).height:
        raise ValueError('Require one later label exit date per monthly signal')
    rows = scores.join(exits.drop('dates'), on='trade_date', how='left', validate='1:1')
    if 'forward_evidence' not in rows.columns:
        rows = rows.with_columns(pl.lit(False).alias('forward_evidence'))
    if 'rehearsal' not in rows.columns:
        rows = rows.with_columns(pl.lit(True).alias('rehearsal'))
    rows = rows.with_columns((pl.col('forward_evidence').fill_null(False)
        & ~pl.col('rehearsal').fill_null(True)).alias('is_forward'))
    known = rows.filter((pl.col('trade_date') <= known_through)
        & (pl.col('exit_date_rebalance') <= known_through) & pl.col('rank_ic').is_not_null())
    end_month = known_through.year*12+known_through.month
    result: dict[str, Any] = {'excluded_or_unscored_records': rows.height-known.height,
        'forward_months': known.filter(pl.col('is_forward')).height,
        'historical_months': known.filter(~pl.col('is_forward')).height, 'windows': []}
    for mode, flag in [('forward', True), ('historical', False)]:
        for window in windows:
            sample = known.filter((pl.col('is_forward') == flag)
                & (pl.col('exit_date_rebalance').dt.year()*12
                   + pl.col('exit_date_rebalance').dt.month() >= end_month-window+1)).sort('trade_date')
            stats = monthly_ic_summary(sample['trade_date'].to_list(),
                sample['rank_ic'].to_list(), lag=lag)
            insufficient = stats['months'] < minimum_months
            alert = not insufficient and (stats['icir'] is None or stats['icir'] < icir_warning)
            result['windows'].append({'mode': mode, 'calendar_months': window, **stats,
                'status': 'insufficient' if insufficient else ('warning' if alert else 'within_monitor_threshold'),
                'warning': alert})
    return result


def _read(path: Path) -> pl.DataFrame:
    return pl.read_parquet(path) if path.suffix == '.parquet' else pl.read_csv(path, try_parse_dates=True)


def run(*, known_through: dt.date, output: Path, config: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings['auto_trade'] is not False:
        raise ValueError('Monitoring cannot enable trading')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    results = []
    ids = set()
    for series in settings.get('series', []):
        if series['id'] in ids or series['kind'] not in ('model', 'holding_factor'):
            raise ValueError('Require unique series ids and explicit signal kind')
        ids.add(series['id'])
        item = {'id': series['id'], 'kind': series['kind'], 'scores': series['scores'],
                'labels': series['labels'], 'context': series.get('context', '')}
        try:
            scores = _read(Path(series['scores']))
            if 'variant' in series:
                scores = scores.filter(pl.col('variant') == series['variant'])
            paths = series['labels'] if isinstance(series['labels'], list) else [series['labels']]
            labels = pl.concat([_read(Path(p)).select('trade_date', 'exit_date_rebalance').unique()
                                for p in paths]).unique()
            if series.get('direction', 1) != 1:
                raise ValueError('Saved model and battery IC already have registered direction')
            stats = evaluate(scores=scores, labels=labels,
                known_through=known_through, windows=settings['calendar_windows'],
                minimum_months=settings['minimum_months'], lag=settings['newey_west_lag'],
                icir_warning=settings['icir_warning'], direction=series.get('direction', 1))
            item.update(status='complete', **stats)
        except Exception as exc:
            item.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        results.append(item)
    forward = sum(r.get('forward_months', 0) for r in results)
    failed = any(r['status'] == 'failed' for r in results)
    warning = any(w['warning'] for r in results for w in r.get('windows', []) if w['mode'] == 'forward')
    ready = any(w['status'] != 'insufficient' for r in results
                for w in r.get('windows', []) if w['mode'] == 'forward')
    summary = {'known_through': str(known_through), 'auto_trade': False,
        'status': 'failed' if failed else ('warning' if warning else ('observed' if ready else 'insufficient')),
        'forward_scored_series_months': forward, 'requires_review': failed or warning,
        'reason': '已积累可评分记录' if ready else '未积累足够前向',
        'window_basis': 'calendar months of label exit; HAC uses signal calendar months',
        'threshold_role': 'monitoring only; existing strategy decisions unchanged', 'series': results}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False),
                                     encoding='utf-8')
    lines = ['# 滚动信号监控', '', f"收益已知截止：{known_through}；状态：{summary['status']}；{summary['reason']}。",
        '', '|序列|类别|模式|退出月窗口|有效月数|ICIR|状态|', '|---|---|---|---:|---:|---:|---|']
    for r in results:
        for w in r.get('windows', []):
            icir = f"{w['icir']:.4f}" if w['icir'] is not None and math.isfinite(w['icir']) else '不可计算'
            lines.append(f"|{r['id']}|{r['kind']}|{w['mode']}|{w['calendar_months']}|{w['months']}|{icir}|{w['status']}|")
        if r['status'] == 'failed':
            lines.append(f"|{r['id']}|{r['kind']}|输入失败||||{r['error']}|")
    lines += ['', *[f"{r['id']}：{r['context']}" for r in results if r['context']],
        '历史演练与真实前向分别计算；不足样本和缺失值不填零，预警只记录，不改变持仓。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--known-through', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({'status': result['status'], 'forward_months': result['forward_scored_series_months']}))
    if result['status'] == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
