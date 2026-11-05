"""Attach reproducible 1x calendar reports to completed registered results."""
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.reporting.period_metrics import period_metrics, write_period_reports


def attach(records: list[dict], root: Path) -> dict:
    from quant.reporting.dashboard_curves import catalog, read_curve
    from quant.reporting.strategy_description import describe

    references = [s for s in catalog(root) if s.get('code') in ('H00300.CSI', 'H00905.CSI')]
    benchmarks = {s['label']: pl.DataFrame(read_curve(s)).select(
        pl.col('date').str.to_date(), pl.col('value').alias('unit_nav')) for s in references}
    reports, completed, unavailable = {}, 0, []
    for row in records:
        report = root/row['report_path']
        if not report.is_file():
            continue
        run, variant = root/row['run_path'], row['variant']
        base = root/row['source_run'] if (run/'cost_metrics.parquet').exists() and row.get('source_run') else run
        if '/' in variant:
            factor, variant = variant.split('/', 1)
            summary = json.loads((run/'summary.json').read_text(encoding='utf-8'))
            scorecard = root/summary['scorecard_path']
            costs = json.loads((scorecard.parent/'summary.json').read_text(encoding='utf-8'))['cost_runs']
            base = next((root/p for p in costs
                         if json.loads((root/p/'summary.json').read_text(encoding='utf-8'))['factor'] == factor), run/'missing')
        paths = sorted((base/variant/'cost_1').glob('????/nav.parquet'))
        if not paths:
            paths = list((base/variant/'cost_1').glob('nav.parquet'))
        if not paths and (run/'summary.json').is_file():
            summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
            completed_entries=summary.get('completed',[])
            # Account families publish main/<variant>/cost_1 and explicit receipts.
            # Do not substitute a stress/proxy ledger or a different cost level.
            entries=[item for item in (completed_entries if isinstance(completed_entries,list) else []) if isinstance(item,dict)
                and item.get('variant')==variant and item.get('period')=='main'
                and item.get('cost_multiplier')==1 and item.get('path')]
            if len(entries)>1:
                raise ValueError('Ambiguous completed 1x main-account receipt')
            if entries:
                folder=root/entries[0]['path']
                paths=list(folder.glob('nav.parquet')) or sorted(folder.glob('????/nav.parquet'))
        if not paths and row.get('source_run'):
            paths = sorted((root/row['source_run']/variant/'cost_1').glob('????/nav.parquet'))
        if not paths and (run/'config.toml').is_file() and '/' not in row['variant']:
            settings = tomllib.loads((run/'config.toml').read_text(encoding='utf-8'))
            control = settings.get('research', {}).get('control')
            if control and variant in ('control', 'budgeted'):
                paths = sorted((root/control/variant/'cost_1').glob('????/nav.parquet'))
            if variant.startswith('capital_'):
                paths = sorted((run/variant/'budgeted'/'cost_1').glob('????/nav.parquet'))
        label = row['experiment_id']+' / '+row['variant']+' · 1x成本'
        key = hashlib.sha256(row['variant'].encode()).hexdigest()[:16]
        relative = f'periods_1x/{key}/report.md'
        if paths:
            frames = [pl.read_parquet(p).select('date', 'unit_nav', 'market_value') for p in paths]
            nav = pl.concat(frames, how='vertical_relaxed').sort('date')
            description = (label+'。因子多头分组账户；raw 与中性化信号分别统计。' if '/' in row['variant']
                           else label+'。'+describe(root/row['config_path'], row['variant']))
            periods = period_metrics(nav, benchmarks, benchmark_initial_nav=None)
            folder = report.parent/relative
            write_period_reports(folder.parent, periods, description)
            (folder.parent/'sources.json').write_text(json.dumps({
                'cost_multiplier': 1, 'nav': [str(p) for p in paths],
                'benchmarks': references, 'original_conclusion': row['conclusion'],
                'note': 'Calendar diagnostics only; original admission unchanged.'}, ensure_ascii=False, indent=2), encoding='utf-8')
            reports.setdefault(report, []).append(f'- [{label}]({relative})')
            completed += 1
        else:
            reports.setdefault(report, []).append(f'- {label}：没有已完成的1x日净值，年度/月度指标不适用。')
            unavailable.append(label)
    begin, end = '<!-- periods-1x:start -->', '<!-- periods-1x:end -->'
    for report, links in reports.items():
        original = report.read_text(encoding='utf-8')
        block = (begin+'\n## 1x成本：各因子／策略年度与月度结果\n\n'
                 '各自报告含年度指标及按年份拆分的月度表。超额分别对照沪深300和中证500全收益指数；'
                 '不是原准入使用的全市场等权超额。基准缺失不填充，不改变原结论。\n\n'
                 +'\n'.join(dict.fromkeys(links))+'\n'+end)
        if begin in original and end in original:
            before, rest = original.split(begin, 1)
            original = before+block+rest.split(end, 1)[1]
        else:
            original += '\n\n'+block+'\n'
        report.write_text(original, encoding='utf-8')
    return {'completed': completed, 'unavailable': unavailable, 'reports': len(reports)}


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    records = pl.read_parquet(root/'artifacts/registry/experiments.parquet').to_dicts()
    print(json.dumps(attach(records, root), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
