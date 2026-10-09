"""Re-evaluate frozen PEAD NAVs against a versioned benchmark, without replay."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
from pathlib import Path
import tomllib

import polars as pl

from quant.reporting.period_metrics import period_metrics
from quant.research.benchmark_corporate_repair import sha, write_json
from quant.research.pead_account_report import build_report, benchmark_comparisons


def leaf_differences(a, b, prefix='') -> list[dict]:
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return [dict(path=prefix, old_keys=sorted(a), new_keys=sorted(b))]
        return [d for k in a for d in leaf_differences(a[k], b[k], prefix + '/' + str(k))]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [dict(path=prefix, old_length=len(a), new_length=len(b))]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in leaf_differences(x, y, prefix + '/' + str(i))]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        equal = math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-11)
    else:
        equal = a == b
    return [] if equal else [dict(path=prefix, old=a, new=b)]


def _comparison_rows(report: dict) -> list[dict]:
    rows = []
    for a in report['accounts']:
        groups = [('holding', 'holding', None, True, a['benchmark_comparisons'])]
        groups += [('stress', s['window'], s.get('total_return'), s['applicable'], s.get('benchmark_comparisons', [])) for s in a['stress']]
        for kind, window, strategy_return, applicable, comparisons in groups:
            for b in comparisons:
                risk = b.get('benchmark_risk', {})
                bench_return = risk.get('total_return')
                rows.append(dict(case=a['case'], cost_multiplier=a['cost_multiplier'], kind=kind,
                    window=window, benchmark=b['benchmark'], start=b.get('first_date'), end=b.get('last_date'),
                    applicable=applicable, benchmark_total_return=bench_return,
                    benchmark_cagr=b.get('benchmark_cagr'), net_cagr_excess=b.get('net_cagr_excess'),
                    benchmark_max_drawdown=risk.get('max_drawdown'),
                    excess_return=(strategy_return - bench_return if strategy_return is not None and bench_return is not None else None)))
    for p in report['periods']:
        for s in p['rows']:
            for b in s['benchmark_results']:
                rows.append(dict(case=p['case'], cost_multiplier=p['cost_multiplier'], kind=s['frequency'],
                    window=s['period'], benchmark=b['benchmark'], start=s['start'], end=s['end'], applicable=True,
                    benchmark_total_return=b['total_return'], benchmark_cagr=None, net_cagr_excess=None,
                    benchmark_max_drawdown=None, excess_return=b['excess_return']))
    return rows


def calendar_grid(calendar: pl.DataFrame, nav: pl.DataFrame, start: dt.date, end: dt.date) -> list:
    """Remove only verified closed boundary days; never remove an absent open day."""
    grids = []
    for market in ('SH', 'SZ'):
        part = calendar.filter((pl.col('market') == market) & pl.col('date').is_between(start, end)).sort('date')
        if part.height != (end - start).days + 1 or part['date'].n_unique() != part.height:
            raise ValueError('Frozen calendar does not cover complete requested window')
        grids.append(part.filter(pl.col('is_open'))['date'].to_list())
    if not grids[0] or grids[0] != grids[1]:
        raise ValueError('Empty or inconsistent mainland session calendar')
    if nav.filter(pl.col('date').is_between(start, end))['date'].to_list() != grids[0]:
        raise ValueError('Account is missing actual open sessions; no shrinking')
    return grids[0]


def align_stress(report: dict, accounts: dict, benchmarks: dict, calendar: pl.DataFrame) -> tuple[dict, list]:
    aligned, changes = copy.deepcopy(report), []
    for account in aligned['accounts']:
        key = account['case'], account['cost_multiplier']
        nav = accounts[key]['nav']
        for window in account['stress']:
            if not window['applicable']:
                continue
            grid = calendar_grid(calendar, nav, dt.date.fromisoformat(window['start']), dt.date.fromisoformat(window['end']))
            old = window['benchmark_comparisons']
            window['benchmark_comparisons'] = json.loads(json.dumps(
                benchmark_comparisons(nav, benchmarks, start=grid[0], end=grid[-1]), default=str))
            for b, c in zip(old, window['benchmark_comparisons']):
                if b['comparison_status'] != c['comparison_status']:
                    changes.append(dict(case=key[0], cost=key[1], window=window['window'],
                        benchmark=b['benchmark'], previous_status=b['comparison_status'],
                        new_status=c['comparison_status'], calendar_start=window['start'],
                        calendar_end=window['end'], first_session=grid[0], last_session=grid[-1], sessions=len(grid)))
    return aligned, changes


def validate_continuity(index: Path, root: Path) -> dict:
    events = pl.read_parquet(index / 'events.parquet')
    levels = pl.read_parquet(index / 'data.parquet')
    ledger = pl.read_parquet(root / 'pending_claim_ledger.parquet')
    recognized = events.filter(pl.col('kind') == 'exchange_claim_recognized')
    released = events.filter(pl.col('kind') == 'exchange_claim_released')
    assert recognized.height == released.height == 12
    pairs = recognized.join(released, on=['index_name', 'symbol'], suffix='_released', validate='1:1')
    max_units = (pairs['successor_units'] - pairs['successor_units_released']).abs().max()
    max_books = (pairs['book_value'] - pairs['book_value_released']).abs().max()
    assert max_units < 1e-10 and max_books < 1e-9
    transitions = events.filter(pl.col('kind').is_in(['exchange_claim_recognized', 'exchange_claim_released', 'pending_claim_rebalance']))
    conservation = (transitions['value_after'] - transitions['value_before']).abs().max()
    assert conservation < 1e-9
    assert released.filter(pl.col('notice_available_date') > pl.col('date')).is_empty()
    summed = ledger.group_by('index_name', 'date').agg(pl.col('book_value').sum())
    paired = summed.join(levels, left_on=['index_name', 'date'], right_on=['index_name', 'trade_date'], validate='1:1')
    nav_residual = (paired['book_value'] - paired['pending_claim_value']).abs().max()
    assert nav_residual < 1e-9
    assert events.filter(pl.col('kind') == 'delist_zero_recovery').is_empty()
    return dict(recognized=recognized.height, released=released.height,
        max_unit_difference=max_units, max_book_difference=max_books,
        max_transition_conservation_error=conservation, max_published_nav_ledger_error=nav_residual,
        pending_rebalances=events.filter(pl.col('kind') == 'pending_claim_rebalance').height,
        deliveries_merging_existing_successor=released.filter(pl.col('existing_successor_units') > 0).height,
        pending_days=ledger.height, unresolved_terminal_claims=0)


def evaluate(config: Path, data_root: Path) -> dict:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    root = Path(settings['artifact_root'])
    out = root / 'evaluation_complete'
    if out.exists():
        raise FileExistsError('Evaluation exists; choose a new output rather than overwriting')
    consumer = Path(settings['consumer'])
    old_folder = data_root / 'clean/equal_weight_indexes' / settings['original_version']
    new_folder = data_root / 'clean/equal_weight_indexes' / settings['version']
    manifest = json.loads((consumer / 'benchmarks/manifest.json').read_text(encoding='utf-8'))
    for path, digest in manifest['sources_sha256'].items():
        assert sha(Path(path)) == digest, path
    for path, digest in manifest['files'].items():
        assert sha(consumer / 'benchmarks' / path) == digest, path
    source_paths = [p for p in consumer.rglob('*') if p.is_file()]
    source_paths += [p for p in old_folder.glob('*') if p.is_file()]
    before = {str(p): sha(p) for p in source_paths}
    continuity = validate_continuity(new_folder, root)
    old_data = pl.read_parquet(old_folder / 'data.parquet').sort('index_name', 'trade_date')
    new_data = pl.read_parquet(new_folder / 'data.parquet').sort('index_name', 'trade_date')
    original_benchmarks = {}
    for p in (consumer / 'benchmarks').glob('*.parquet'):
        original_benchmarks['510300_total_return_reference' if p.stem == '510300' else p.stem] = pl.read_parquet(p)
    original_benchmarks = {name: original_benchmarks[name] for name in
                          ('all_market_equal_weight', 'csi800_equal_weight', '510300_total_return_reference')}
    repaired_benchmarks = dict(original_benchmarks)
    for name in ('all_market_equal_weight', 'csi800_equal_weight'):
        repaired_benchmarks[name] = new_data.filter(pl.col('index_name') == name).select(
            pl.col('trade_date').alias('date'), (pl.col('index_level') / 1000).alias('unit_nav'))
        frozen = original_benchmarks[name]
        source = old_data.filter(pl.col('index_name') == name).select(
            pl.col('trade_date').alias('date'), (pl.col('index_level') / 1000).alias('unit_nav'))
        assert frozen['date'].equals(source['date'])
        assert (frozen['unit_nav'] - source['unit_nav']).abs().max() < 1e-12
    accounts = {}
    for case in ('pead40', 'all_events'):
        for cost in (.5, 1., 2.):
            folder = consumer / f'{case}_cost{cost:g}'
            accounts[case, cost] = {n: pl.read_parquet(folder / (n + '.parquet'))
                                    for n in ('nav', 'trades', 'positions', 'rejections')}
    rules = tomllib.loads((consumer / 'model_rules.toml').read_text(encoding='utf-8'))['admission']
    stress = tomllib.loads((consumer / 'stress.toml').read_text(encoding='utf-8'))['windows']
    kwargs = dict(initial_cash=100000., stress_windows=stress, admission_rules=rules)
    old_report = build_report(accounts, original_benchmarks, **kwargs)
    saved_report = json.loads((consumer / 'evaluation/summary.json').read_text(encoding='utf-8'))
    mismatches = leaf_differences(saved_report, old_report)
    if mismatches:
        write_json(root / 'original_evaluation_mismatch.json', mismatches)
        raise ValueError('Original consumer report failed reproduction')
    new_report = build_report(accounts, repaired_benchmarks, **kwargs)
    original_reproduced = old_report
    calendar_frame = pl.read_parquet(consumer / 'inputs/calendar.parquet')
    old_report, calendar_changes = align_stress(old_report, accounts, original_benchmarks, calendar_frame)
    new_report, _ = align_stress(new_report, accounts, repaired_benchmarks, calendar_frame)
    assert old_report['paired'] == new_report['paired']
    for a, b in zip(old_report['accounts'], new_report['accounts']):
        for k in ('full', 'holding', 'calendar_turnover', 'underwater', 'positions', 'rejected_orders'):
            assert a[k] == b[k], k
    out.mkdir()
    write_json(out / 'original_reproduced.json', original_reproduced)
    write_json(out / 'original_calendar_aligned.json', old_report)
    write_json(out / 'calendar_alignment_changes.json', calendar_changes)
    metrics = dict(new_report)
    # The old report's pending labels are historical source data, not conclusions
    # from this measurement repair; retain them explicitly under that name.
    metrics['frozen_independent_checks'] = metrics.pop('admission')
    metrics['benchmark_measurement'] = 'seven exchanges repaired under registered stale-book claim convention'
    metrics['limitations'] = [v for v in metrics['limitations'] if 'delisting consideration remains unresolved' not in v]
    metrics['limitations'].append('Pending-claim book value is a declared convention, not observed fair value; no promotion or original-vintage claim.')
    metrics.pop('development_decision')
    write_json(out / 'repaired_metrics.json', metrics)
    write_json(out / 'all_metric_differences.json', leaf_differences(old_report, new_report))
    daily = old_data.select('index_name', 'trade_date', pl.col('index_level').alias('old_level'),
                           pl.col('daily_return').alias('old_return')).join(
        new_data.select('index_name', 'trade_date', pl.col('index_level').alias('new_level'),
                        pl.col('daily_return').alias('new_return'), 'pending_claim_weight'),
        on=['index_name', 'trade_date'], validate='1:1').with_columns(
            (pl.col('new_return') - pl.col('old_return')).alias('daily_return_difference'),
            (pl.col('new_level') / pl.col('old_level') - 1).alias('level_relative_difference'))
    daily.write_parquet(out / 'daily_index_differences.parquet')
    changed = daily.filter(pl.col('daily_return_difference').abs() > 1e-12)
    changed.write_csv(out / 'changed_daily_returns.csv')
    comparison = []
    for old, new in zip(_comparison_rows(old_report), _comparison_rows(new_report)):
        assert all(old[k] == new[k] for k in ('case', 'cost_multiplier', 'kind', 'window', 'benchmark', 'start', 'end'))
        row = {k: old[k] for k in ('case', 'cost_multiplier', 'kind', 'window', 'benchmark', 'start', 'end', 'applicable')}
        for k in ('benchmark_total_return', 'benchmark_cagr', 'net_cagr_excess', 'benchmark_max_drawdown', 'excess_return'):
            row['old_' + k], row['new_' + k] = old[k], new[k]
            row['delta_' + k] = new[k] - old[k] if old[k] is not None and new[k] is not None else None
        dates = daily.filter((pl.col('index_name') == old['benchmark']) &
                            pl.col('trade_date').is_between(dt.date.fromisoformat(old['start']), dt.date.fromisoformat(old['end']))) if old['start'] else daily.head(0)
        row['changed_return_sessions'] = dates.filter(pl.col('daily_return_difference').abs() > 1e-12).height
        row['outperformance_sign_changed'] = (old['excess_return'] is not None and new['excess_return'] is not None
                                             and (old['excess_return'] >= 0) != (new['excess_return'] >= 0))
        comparison.append(row)
    frame = pl.DataFrame(comparison, infer_schema_length=None)
    frame.write_parquet(out / 'all_window_comparison_differences.parquet')
    frame.filter(pl.col('delta_benchmark_total_return').abs() > 1e-10).write_csv(out / 'changed_window_comparisons.csv')
    common, ranks = [], []
    for a in old_report['accounts']:
        case, cost = a['case'], a['cost_multiplier']
        nav = accounts[case, cost]['nav']
        start = max(dt.date.fromisoformat(a['holding']['active_start']),
                    max(f['date'].min() for f in original_benchmarks.values()))
        end = nav['date'].max()
        older = benchmark_comparisons(nav, original_benchmarks, start=start, end=end)
        newer = benchmark_comparisons(nav, repaired_benchmarks, start=start, end=end)
        for b, c in zip(older, newer):
            assert b['comparison_status'] == c['comparison_status'] == 'complete'
            common.append(dict(case=case, cost_multiplier=cost, benchmark=b['benchmark'], start=start, end=end,
                old_benchmark_cagr=b['benchmark_cagr'], new_benchmark_cagr=c['benchmark_cagr'],
                old_net_cagr_excess=b['net_cagr_excess'], new_net_cagr_excess=c['net_cagr_excess'],
                delta_net_cagr_excess=c['net_cagr_excess'] - b['net_cagr_excess']))
        old_best = max(older, key=lambda b: b['benchmark_cagr'])
        new_best = max(newer, key=lambda b: b['benchmark_cagr'])
        ranks.append(dict(case=case, cost_multiplier=cost, start=start, end=end,
            old_strongest=old_best['benchmark'], new_strongest=new_best['benchmark'],
            old_excess=old_best['net_cagr_excess'], new_excess=new_best['net_cagr_excess'],
            strongest_changed=old_best['benchmark'] != new_best['benchmark']))
    pl.DataFrame(common).write_csv(out / 'common_window_excess_differences.csv')
    write_json(out / 'common_window_strongest.json', ranks)
    calendar = []
    for name in ('all_market_equal_weight', 'csi800_equal_weight'):
        old = period_metrics(original_benchmarks[name], {}, start=original_benchmarks[name]['date'].min())
        new = period_metrics(repaired_benchmarks[name], {}, start=repaired_benchmarks[name]['date'].min())
        for b, c in zip(old, new):
            calendar.append(dict(index_name=name, frequency=b['frequency'], period=b['period'],
                start=b['start'], end=b['end'], old_return=b['total_return'], new_return=c['total_return'],
                difference=c['total_return'] - b['total_return']))
    pl.DataFrame(calendar).write_csv(out / 'benchmark_calendar_differences.csv')
    assert all(sha(Path(p)) == digest for p, digest in before.items()), 'Frozen consumer/source changed'
    proofs = json.loads((root / 'synchronization_proofs.json').read_text(encoding='utf-8'))
    quiet = frame.filter(pl.col('changed_return_sessions') == 0)
    max_quiet = quiet['delta_benchmark_total_return'].abs().max()
    assert max_quiet is None or max_quiet < 1e-10
    end_summary = daily.group_by('index_name', maintain_order=True).agg(
        pl.col('level_relative_difference').last().alias('terminal_level_relative_difference'),
        (pl.col('daily_return_difference').abs() > 1e-12).sum().alias('changed_return_sessions'),
        pl.col('daily_return_difference').abs().max().alias('maximum_abs_daily_return_difference'))
    result = dict(status='complete_versioned_repair_and_frozen_NAV_evaluation', auto_trade=False,
        new_version=settings['version'], consumer=str(consumer), original_report_reproduced=True,
        frozen_source_and_consumer_files_unchanged=True, preserved_files=len(before), account_replays=0,
        calendar_comparisons_restored=len(calendar_changes),
        continuity=continuity, index_summary=end_summary.to_dicts(), comparison_rows=frame.height,
        changed_comparison_rows=frame.filter(pl.col('delta_benchmark_total_return').abs() > 1e-10).height,
        outperformance_sign_changes=frame.filter(pl.col('outperformance_sign_changed')).to_dicts(),
        common_window_strongest=ranks, unchanged_return_window_rows=quiet.height,
        max_return_difference_in_unchanged_daily_windows=max_quiet,
        max_baseline_daily_error=max(p['max_baseline_daily_error'] for p in proofs),
        max_post_sync_daily_error=max(p['max_post_sync_return_error'] for p in proofs),
        independent_checks_unchanged=old_report['admission'] == new_report['admission'],
        paired_account_differences_unchanged=old_report['paired'] == new_report['paired'],
        failed_independent_checks=old_report['admission'], promotion=False,
        limitation='Versioned accounting correction under stale-book pending valuation; not a newly observed fair-value path, execution proof, or strategy admission.')
    write_json(out / 'summary.json', result)
    write_json(out / 'source_manifest.json', dict(frozen_files_sha256=before,
        repaired_files_sha256={str(p): sha(p) for p in new_folder.glob('*') if p.is_file()},
        evaluation_script_sha256=sha(Path(__file__))))
    lines = ['# 基准换股修复及冻结 PEAD 比较', '',
        f"新版本：`{settings['version']}`。原基准、六条策略账户及其交易文件均未改写；策略重跑次数为0。", '',
        '## 固定口径', '',
        '已知默认换股权益于退市时确认为待交付权益；等待期按前身最后账面值保留，跨月仅重配剩余资本。该账面值不是已观测公允价值。已公告可流通且存在有效行情后按份额交付，与已有后继证券合并；不自动行使现金选择权、不填未来价格。', '',
        '## 基准变化', '', '|指数|末端点位相对变化|改变日收益的交易日|最大单日收益差|', '|---|---:|---:|---:|']
    for r in result['index_summary']:
        lines.append(f"|{r['index_name']}|{r['terminal_level_relative_difference'] * 100:.6f}%|{r['changed_return_sessions']}|{r['maximum_abs_daily_return_difference'] * 10000:.6f}bp|")
    lines += ['', f"原评估完整复现；按冻结交易日历恢复{len(calendar_changes)}条原先因自然日结束边界而不可用的压力比较。对齐后{frame.height}条比较全部重算，其中{result['changed_comparison_rows']}条收益比较因换股修复改变。", '',
        f"{quiet.height}条窗口没有日收益变化，区间收益差最大{max_quiet:.3g}。此前的108条直接事件窗口不是完整影响范围。", '',
        '## 同一窗口的超额', '', '|账户|成本|原最强基准|新最强基准|原CAGR超额|新CAGR超额|', '|---|---:|---|---|---:|---:|']
    for r in ranks:
        lines.append(f"|{r['case']}|{r['cost_multiplier']}|{r['old_strongest']}|{r['new_strongest']}|{r['old_excess'] * 100:.6f}pp|{r['new_excess'] * 100:.6f}pp|")
    lines += ['', f"同窗范围：{ranks[0]['start']}—{ranks[0]['end']}；不把早年点位损失算作该窗口的全部收益误差。", '',
        '## 结论与核验', '',
        f"- 相对收益正负号改变的保存比较：{len(result['outperformance_sign_changes'])}条；详见summary.json。",
        '- PEAD自身Sharpe、水下期等指标及其与all_events配对差值逐项不变；没有因基准修复获得准入。',
        f"- 12次权益确认和12次交付匹配；包含{continuity['pending_rebalances']}次待交付权益跨月调仓和{continuity['deliveries_merging_existing_successor']}次已有后继证券合并。",
        f"- 单位份额/账面值连续；与发布净值的最大权益账差为{continuity['max_published_nav_ledger_error']:.3g}指数点。",
        f"- 旧算法局部复现最大日误差{result['max_baseline_daily_error']:.3g}；重同步后五日验证最大误差{result['max_post_sync_daily_error']:.3g}。",
        '- 旧版修复草稿01因局部份额未换算至连续净值尺度已标记无效；最终v2纠正该明细尺度，日收益计算未因此改变。',
        '- 法律登记/工商注销未确证的日期继续未知；不将权益确认日冒充法定登记完成日。',
        '- 尚未推广到其他模型、因子评估或运行批次；当前证明的消费者仅为本报告所列冻结PEAD路径。', '',
        '## 可复核产物', '',
        '- daily_index_differences.parquet / changed_daily_returns.csv：全部日期及非零日收益差。',
        '- benchmark_calendar_differences.csv：年度、月度差异。',
        '- all_window_comparison_differences.parquet：持股期、年度、月度、压力窗口全部差异。',
        '- common_window_excess_differences.csv：三个基准在相同窗口的超额变化。',
        '- ../synchronization_proofs.json、../pending_claim_ledger.parquet：实际权重再同步、份额连续证据。',
        '- source_manifest.json：原账户/基准文件及新版本哈希。']
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    result = evaluate(args.config, args.data_root)
    print(json.dumps({k: result[k] for k in ('status', 'index_summary', 'comparison_rows', 'changed_comparison_rows',
                                           'independent_checks_unchanged', 'paired_account_differences_unchanged')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
