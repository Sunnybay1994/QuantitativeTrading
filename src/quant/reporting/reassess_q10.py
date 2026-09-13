"""Re-measure the frozen Q10 fills under the dated roadmap ruling."""
import argparse
import copy
import datetime as dt
import json
import tomllib
from pathlib import Path

from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
from quant.research.factor_battery_cost_report import load_cost_history


def run(config: Path, output: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))['research']
    source = Path(spec['source'])
    result = copy.deepcopy(json.loads((source/'assessment.json').read_text(encoding='utf-8')))
    if (spec['hard_limit'], spec['exception_limit'], spec['exception_minimum_double_cost_excess']) != (6., 8., .05):
        raise ValueError('Require the dated roadmap ruling')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    result['source'] = str(source)
    result['rule'] = spec['rule']
    result['calendar_turnover'] = {}
    for row in result['rows']:
        nav, trades = load_cost_history(source, row['variant'], row['cost_multiplier'],
                                       dt.date.fromisoformat(row['report_end']))
        measured = calendar_turnover(nav, trades)
        result['calendar_turnover'][f"{row['variant']}/{row['cost_multiplier']:g}"] = measured
        row['legacy_252_turnover'] = row['annualized_one_way_turnover']
        row['annualized_one_way_turnover'] = measured['median']
        row['maximum_calendar_turnover'] = measured['maximum']
    for variant, assessment in result['assessments'].items():
        rows = {r['cost_multiplier']: r for r in result['rows'] if r['variant'] == variant}
        strongest = next(b for b in assessment['benchmarks']
                         if b['benchmark'] == assessment['strongest_benchmark'])
        excess = rows[2.]['cagr']-strongest['cagr']
        assessment['double_cost_excess'] = excess
        assessment['checks']['turnover'] = turnover_passes(rows[1.]['annualized_one_way_turnover'], excess)
        assessment['conclusion'] = 'PAPER_CANDIDATE' if all(assessment['checks'].values()) else 'REJECTED'
    (output/'assessment.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    lines = ['# Q10 日历年换手重算', '', '|组合|成本|年化收益|Sharpe|最大回撤|换手中位数|换手最大值|',
             '|---|---:|---:|---:|---:|---:|---:|']
    for r in result['rows']:
        lines.append(f"|{r['variant']}|{r['cost_multiplier']:g}|{r['cagr']:.2%}|{r['sharpe']:.3f}|"
                     f"{r['max_drawdown']:.2%}|{r['annualized_one_way_turnover']:.3f}|{r['maximum_calendar_turnover']:.3f}|")
    for variant, a in result['assessments'].items():
        lines += ['', f"{variant}: {a['conclusion']}；2×成本超额 {a['double_cost_excess']:.2%}；"
                  f"未通过项：{', '.join(k for k,v in a['checks'].items() if not v) or '无'}。"]
    lines += ['', '换手为全年买卖成交额合计的一半/该年日均净值；部分年份保留实测值，不外推。', '',
              '|组合/成本|年份|首日|末日|部分年|单边成交金额|日均净值|换手|', '|---|---:|---|---|---|---:|---:|---:|']
    for key, measured in result['calendar_turnover'].items():
        for r in measured['annual']:
            lines.append(f"|{key}|{r['year']}|{r['first']}|{r['last']}|{r['partial_year']}|"
                         f"{r['one_way_notional']:.2f}|{r['mean_daily_equity']:.2f}|{r['turnover']:.4f}|")
    lines += ['', '下一步：通过候选进入第二模拟账户，从下一个月末收盘信号开始前向记录。',
              '关键风险：2024-01 的规模暴露由风险模型和约束组合继续处理。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    from quant.reporting.experiment_registry import register_run
    register_run(output)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.config, args.output)
    print(json.dumps(summary['assessments']['budgeted']['checks']))
    print(summary['assessments']['budgeted']['conclusion'])
