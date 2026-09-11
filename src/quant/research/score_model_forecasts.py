"""Score saved monthly research forecasts after their returns become observable."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.model_forecast_labels import monthly_schedule, read_forecast_labels
from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date

ZONE = dt.timezone(dt.timedelta(hours=8))


def score_record(*, predictions: pl.DataFrame, record: dict, labels: pl.DataFrame,
                 sessions: tuple[dt.date, ...], known_through: dt.date, forward_start: dt.date,
                 minimum_symbols: int, minimum_paired_coverage: float) -> dict:
    day = dt.date.fromisoformat(record['as_of'])
    if day > known_through or predictions.filter(pl.col('trade_date') != day).height:
        raise ValueError('Forecast date exceeds scoring cutoff or differs from saved record')
    if (predictions.select('symbol', 'trade_date').is_duplicated().any()
            or predictions.filter(~pl.col('prediction').is_finite().fill_null(False)).height):
        raise ValueError('Require unique finite saved forecasts')
    result = {'trade_date': day, 'rehearsal': record['rehearsal'], 'signal_count': predictions.height,
              'paired_count': 0, 'paired_coverage': 0.0, 'rank_ic': None, 'forward_evidence': False}
    schedule = monthly_schedule(sessions, day)
    if schedule is None:
        return {**result, 'status': 'not_month_end_or_calendar_incomplete'}
    entry, exit_day = schedule
    recorded = dt.datetime.fromisoformat(record['recorded_at']) if record.get('recorded_at') else None
    timely = bool(recorded is not None and recorded.tzinfo is not None
                  and dt.datetime.combine(day, dt.time(15), ZONE) <= recorded
                  < dt.datetime.combine(entry, dt.time(9, 30), ZONE))
    result['forward_evidence'] = bool(timely and not record['rehearsal'] and day >= forward_start)
    if exit_day > known_through:
        return {**result, 'status': 'awaiting_realized_return'}
    known = labels.filter(pl.col('trade_date') == day)
    if (known.select('symbol', 'trade_date').is_duplicated().any()
            or known.filter((pl.col('execution_date_rebalance') != entry).fill_null(True)
                | (pl.col('exit_date_rebalance') != exit_day).fill_null(True)).height):
        raise ValueError('Labels must use exact next monthly execution dates')
    joined = predictions.join(known.select('symbol', 'trade_date', 'label_rebalance'),
                               on=['symbol', 'trade_date'], how='left', validate='1:1')
    if predictions.is_empty():
        return {**result, 'status': 'missing_predictions'}
    stats = rank_ic_by_date(joined, score='prediction', label='label_rebalance',
        minimum_symbols=minimum_symbols, minimum_paired_coverage=minimum_paired_coverage).row(0, named=True)
    return {**result, **stats, 'status': 'scored' if stats['rank_ic'] is not None else 'insufficient_pairs'}


def run_scores(*, forecasts: list[Path], known_through: dt.date, output: Path, data_root: Path) -> dict:
    now = dt.datetime.now(ZONE)
    if known_through > now.date() or (known_through == now.date() and now.hour < 15):
        raise ValueError('Require completed scoring close')
    records = [json.loads((p/'summary.json').read_text(encoding='utf-8')) for p in forecasts]
    if (len({r['source_selection'] for r in records}) != 1
            or len({r['as_of'] for r in records}) != len(records)):
        raise ValueError('Use one frozen selection and one record per signal date')
    selection = Path(records[0]['source_selection'])
    decision = json.loads((selection/'selection.json').read_text(encoding='utf-8'))
    config = tomllib.loads((selection/'config.toml').read_text(encoding='utf-8'))
    source = Path(config['research']['predictions'])
    battery = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    if any(r['method'] != decision['selected_method'] or r['auto_trade'] is not False for r in records):
        raise ValueError('Saved records must match the frozen research method')
    predictions = [pl.read_parquet(p/'predictions.parquet') for p in forecasts]
    keys = pl.concat([p.select('symbol', 'trade_date') for p in predictions])
    labels, sessions = read_forecast_labels(data_root=data_root,
        refresh_config=Path(battery['data']['refresh_config']), keys=keys, known_through=known_through)
    rows = [score_record(predictions=p, record=r, labels=labels, sessions=sessions,
        known_through=known_through, forward_start=dt.date.fromisoformat(decision['forward_start']),
        minimum_symbols=battery['minimum_symbols'], minimum_paired_coverage=battery['minimum_paired_coverage'])
        for p, r in zip(predictions, records, strict=True)]
    rows.sort(key=lambda r: r['trade_date'])
    groups = {}
    for name, flag in [('forward', True), ('retrospective', False)]:
        subset = [r for r in rows if r['forward_evidence'] is flag
                  and r['status'] != 'not_month_end_or_calendar_incomplete']
        groups[name] = monthly_ic_summary([r['trade_date'] for r in subset], [r['rank_ic'] for r in subset],
                                         lag=battery['monthly_newey_west_lag'])
    result = {'known_through': str(known_through), 'source_selection': str(selection),
        'records': len(rows), **groups, 'conclusion': 'RESEARCH_ONLY', 'auto_trade': False,
        'minimum_symbols': battery['minimum_symbols'], 'minimum_paired_coverage': battery['minimum_paired_coverage'],
        'minimum_observation_months': 12,
        'source_rejections_remain_effective': True}
    output.mkdir(parents=True, exist_ok=False)
    pl.DataFrame(rows).write_csv(output/'monthly_scores.csv')
    labels.write_parquet(output/'realized_labels.parquet')
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 固定模型预测评分', '', f'收益已知截止日：{known_through}。', '',
        f"事前预测有效月数：{groups['forward']['months']}；历史演练有效月数：{groups['retrospective']['months']}。",
        '按月末信号的下一开盘至下次调仓开盘收益计算RankIC，原始预测全体为覆盖率分母。', '',
        '|信号日|预测数|配对数|RankIC|事前记录|结果|', '|---|---:|---:|---:|---|---|']
    lines += [f"|{r['trade_date']}|{r['signal_count']}|{r['paired_count']}|{r['rank_ic']}|{r['forward_evidence']}|{r['status']}|" for r in rows]
    lines += ['', '历史演练不计入12个月前向观察；评分不改变既有策略拒绝结论。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--forecast', type=Path, action='append', required=True)
    parser.add_argument('--known-through', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run_scores(forecasts=args.forecast, known_through=args.known_through,
                               output=args.output, data_root=args.data_root)))


if __name__ == '__main__':
    main()
