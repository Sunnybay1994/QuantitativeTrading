"""R5 real-input qualification receipt; never fabricate an unfinished battery."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.research.pit_quality_research import monthly_signal_sessions
from quant.research.sue_preliminary_s4 import read_inputs, select_points, visible_inputs


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*, config: Path, output: Path, data_root: Path, known_at: dt.datetime):
    """Complete bounded qualification, with actual snapshots and missing diagnostics."""
    if known_at.tzinfo is None:
        raise ValueError('Require actual zoned knowledge cutoff')
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    registered = dt.datetime.fromisoformat(spec['registered_at'])
    if registered >= known_at or spec['auto_trade'] is not False:
        raise ValueError('Require preregistration before execution and auto_trade=false')
    output.mkdir(parents=True, exist_ok=False)
    config_copy = output / 'config.toml'
    config_copy.write_bytes(config.read_bytes())
    history, manifest = read_inputs(data_root, known_at=known_at)
    implementation = [Path(__file__), Path(__file__).with_name('sue_preliminary_s4.py'),
                      Path('src/quant/factors/earnings_surprise.py'), config,
                      Path(spec['battery_config']), Path(spec['original_family'])]
    manifest.extend({'path': str(p), 'sha256': digest(p)} for p in implementation)
    calendar_path = data_root / 'clean/trade_calendar/market=SH/data.parquet'
    manifest.append({'path': str(calendar_path), 'sha256': digest(calendar_path)})
    calendar = pl.read_parquet(calendar_path)
    sessions = tuple(calendar.filter(pl.col('is_open'))['date'].sort())
    end = min(spec['audit_end'], known_at.astimezone(dt.timezone(dt.timedelta(hours=8))).date())
    dates = monthly_signal_sessions(sessions, start=spec['audit_start'], end=end)
    monthly = []
    for date in dates:
        visible = visible_inputs(history, date)
        points = select_points(history, date)
        usable = points.filter(pl.col('input_reason') == 'usable')
        monthly.append(dict(signal_date=date, visible_rows=visible.height,
                            latest_points=points.height, basis_verified_points=usable.height,
                            eligible_for_formula=usable.height >= spec['minimum_symbols']))
    pl.DataFrame(monthly).write_parquet(output / 'monthly_input_coverage.parquet')
    history.write_parquet(output / 'observations.parquet')
    tables = []
    for table in spec['sources']:
        frame = history.filter(pl.col('source_table') == table)
        tables.append(dict(table=table, rows=frame.height,
            symbols=frame['symbol'].n_unique(), first_announcement=frame['announcement_date'].min(),
            last_announcement=frame['announcement_date'].max(),
            distinct_announcement_months=frame['announcement_date'].dt.strftime('%Y-%m').n_unique(),
            announcement_months_in_audit=frame.filter(
                (pl.col('announcement_date') >= spec['audit_start'])
                & (pl.col('announcement_date') <= end))['announcement_date'].dt.strftime('%Y-%m').n_unique(),
            first_observed_at=frame['observed_at'].min(), first_available_at=frame['available_at'].min(),
            last_observed_at=frame['observed_at'].max(),
            future_period_vs_announcement=frame.filter(pl.col('report_period_end') > pl.col('announcement_date')).height,
            input_reasons=frame.group_by('input_reason').len().sort('input_reason').to_dicts()))
    qualified = sum(r['eligible_for_formula'] for r in monthly)
    if any(digest(Path(row['path'])) != row['sha256'] for row in manifest):
        raise ValueError('Input changed during R5 audit; preserve attempt, do not certify')
    # This bounded runner is deliberately not a second battery or registry. It
    # stops before scoring if no historical signal inputs qualify; otherwise the
    # existing N1/N3/N4 path must supply its real completed receipts.
    result = dict(id=spec['id'], stage='input_qualification_completed',
        status='SAMPLE_INSUFFICIENT' if qualified < spec['minimum_months'] else 'EXISTING_PIPELINE_REQUIRED',
        created_at=known_at.isoformat(), config_sha256=digest(config_copy),
        signal_start=dates[0] if dates else None, signal_end=dates[-1] if dates else None,
        checked_signal_months=len(dates), months_with_visible_inputs=sum(r['visible_rows'] > 0 for r in monthly),
        months_with_100_basis_verified_points=qualified, minimum_formal_months=spec['minimum_months'],
        formal_months=None, formal_months_measured=False,
        incremental_nw_t=None, sue_rank_correlation=None, january_ic=None,
        unavailable_metric_reason='No completed S4 panel with matched historical labels and controls',
        completed_battery=False, admission=None, cost_after_increment=None,
        stages={'N1': 'input qualification only; not queued', 'N3': 'not run', 'N4': 'not run'},
        registered=False, registry_reason='Existing registry accepts completed battery receipts only; no fabricated scorecard',
        next_action='Obtain genuinely timestamped historical revisions and explicit parent-profit basis; then existing N1/N3/N4, no new current-download backfill or threshold changes',
        tables=tables, inputs_sha256=manifest, auto_trade=False,
        production_unchanged=['original SUE', 'frozen sue_prelim placeholder', 'Q10', 'no q10_signal_v3'])
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    lines = ['# R5 S4 输入资格核验', '',
             f"状态：{result['status']}；阶段：输入核验已完成，电池尚未完成。", '',
             f"已核对 {len(dates)} 个月末信号；有当时可见输入 {result['months_with_visible_inputs']} 月；具有至少100个已核实归母点值 {qualified} 月。",
             '正式统计、增量 NW-t、SUE 秩相关、1月 IC 均未建立，保留 null；不记策略失败、零通过或成本后增益。', '',
             '| 表 | 原生版本行 | 公告范围 | 首次真实可得 |', '|---|---:|---|---|']
    lines += [f"| {r['table']} | {r['rows']} | {r['first_announcement']} 至 {r['last_announcement']} | {r['first_available_at']} |" for r in tables]
    lines += ['',
        '公告日期跨度不能代替历史到达证据；首次观测后只能前向积累。修正版本逐行保留，不以 update_flag 推断早期版本。',
        '预告原生万元区间可计算中值，快报原生净利润单位为元，但没有归母口径证据时不代替原SUE归母值。',
        '未来报告期预告保留，不仅因早于报告期结束便认作错误；本定义只在报告期结束后尝试评分。',
        '来源：[Tushare 预告](https://tushare.pro/document/2?doc_id=45)、[快报](https://tushare.pro/document/2?doc_id=46)。',
        '当前下载更早公告也不能补回历史PIT。下一步需要真实历史版本与明确归母口径，再走原N1→N3→N4。',
        '注册表仅接受完成电池。本回执未写入虚构成绩；未建v3、未替换冻结SUE，也未运行采集或回放。']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/sue_preliminary_s4_v1.toml'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    result = run(config=args.config, output=args.output, data_root=args.data_root, known_at=dt.datetime.now(dt.UTC))
    print(json.dumps({k: result[k] for k in ('status', 'checked_signal_months', 'months_with_visible_inputs', 'completed_battery', 'registered')}))
