"""Retrospective threshold sensitivity; never changes a strategy's saved admission."""
import argparse
import json
import math
from pathlib import Path
import tomllib

import polars as pl


def threshold_checks(checks: dict[str, bool], *, turnover: float, limit: float) -> dict:
    if (not checks or 'turnover' not in checks or any(type(v) is not bool for v in checks.values())
            or not math.isfinite(turnover) or turnover < 0 or not math.isfinite(limit) or limit <= 0):
        raise ValueError('Require finite turnover, positive limit and explicit original checks')
    changed = {**checks, 'turnover': turnover <= limit}
    return {'limit': limit, 'all_checks_pass': all(changed.values()),
            'failed': [name for name, passed in changed.items() if not passed]}


def run(*, config: Path, output: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['scope'] != 'retrospective_primary_only' or spec['auto_trade'] is not False:
        raise ValueError('Only retrospective primary-scenario reporting is supported')
    rows = []
    for candidate in spec['candidates']:
        assessment = json.loads(Path(candidate['assessment']).read_text(encoding='utf-8'))
        for name in candidate['assessment_key'].split('.'):
            assessment = assessment[name]
        metrics_path = Path(candidate['metrics'])
        metrics = (pl.read_parquet(metrics_path).to_dicts() if metrics_path.suffix == '.parquet'
                   else json.loads(metrics_path.read_text(encoding='utf-8'))['rows'])
        selected = [r for r in metrics if r['variant'] == candidate['variant']]
        if sorted(r['cost_multiplier'] for r in selected) != [.5, 1., 2.]:
            raise ValueError('Require exactly the three original cost scenarios')
        one = next(r for r in selected if r['cost_multiplier'] == 1.)
        turnover = one['annualized_one_way_turnover']
        original = threshold_checks(assessment['checks'], turnover=turnover, limit=spec['original_limit'])
        if ('turnover' in original['failed']) != (assessment['checks']['turnover'] is False):
            raise ValueError('Saved turnover check differs from the original limit')
        rows.append({'name': candidate['name'], 'assessment': candidate['assessment'],
            'original_conclusion': assessment['conclusion'], 'turnover': turnover,
            'original_failed': original['failed'], 'only_turnover_failed': original['failed'] == ['turnover'],
            'cagr_by_cost': {str(r['cost_multiplier']): r['cagr'] for r in selected},
            'sensitivity': [threshold_checks(assessment['checks'], turnover=turnover, limit=limit)
                            for limit in spec['limits']]})
    rejected = [r for r in rows if r['original_conclusion'] == 'REJECTED']
    result = {'scope': spec['scope'], 'original_limit': spec['original_limit'],
        'candidates': len(rows), 'rejected': len(rejected),
        'rejected_with_turnover': sum('turnover' in r['original_failed'] for r in rejected),
        'rejected_only_turnover': sum(r['only_turnover_failed'] for r in rejected),
        'rows': rows, 'original_decisions_changed': False}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config.toml').write_bytes(config.read_bytes())
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 换手阈值敏感性', '',
        f"最近主线{len(rows)}个去重主方案，{len(rejected)}个被拒；"
        f"其中{result['rejected_with_turnover']}个换手未通过，{result['rejected_only_turnover']}个仅换手未通过。",
        '范围为配置明确列出的主方案，不计重复对照、Top100敏感性组合或旧口径报告。', '',
        '单边年换手 = Σ[(当日买入金额+卖出金额)/(2×前一日净资产)] × 252/持股期交易日数。',
        '从首次持股计到报告截止日，首日建仓和之后现金期均计入；6倍是研究筛选线，不是交易规则。', '',
        '|方案|实际年换手|0.5×年化|1×年化|2×年化|原未通过项|', '|---|---:|---:|---:|---:|---|']
    for row in rows:
        costs = row['cagr_by_cost']
        lines.append(f"|{row['name']}|{row['turnover']:.4f}|{costs['0.5']:.2%}|"
            f"{costs['1.0']:.2%}|{costs['2.0']:.2%}|{', '.join(row['original_failed'])}|")
    lines += ['', '|阈值|换手这一项通过的方案数|全部既有检查通过的方案数|', '|---|---:|---:|']
    for index, limit in enumerate(spec['limits']):
        lines.append(f"|{limit:g}|{sum(r['turnover'] <= limit for r in rows)}|"
            f"{sum(r['sensitivity'][index]['all_checks_pass'] for r in rows)}|")
    lines += ['', '阈值敏感性是已研究历史的回顾性分析，原结论保持。',
        '下一步：将6.5倍作为放宽情景审视两项约6.30倍方案；同时核对实际持仓数、碎单与手工执行量，继续原三档成本压力和前向记录。', '']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k: result[k] for k in ('candidates', 'rejected', 'rejected_with_turnover',
                                            'rejected_only_turnover')}))


if __name__ == '__main__':
    main()
