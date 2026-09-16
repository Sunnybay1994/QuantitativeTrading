"""Evidence-backed research retention, keeping original assessments immutable."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
NAMES = {'portfolio_constraints_verified': '组合约束尚未全部验证', 'net_excess': '超额未达标',
         'double_cost_positive': '双倍成本检验未通过', 'sharpe': '夏普未达标',
         'active_evidence': '有效持仓证据不足', 'turnover': '换手偏高', 'drawdown': '回撤偏大', 'underwater': '回撤恢复慢',
         'stress_windows': '压力期表现不足', 'annual_outperformance': '年度超额不稳定'}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def classify(row: dict, assessment: dict, policy: dict) -> dict:
    checks = assessment.get('checks', {})
    failed = [k for k, v in checks.items() if v is not True]
    result = {'review_conclusion': row['conclusion'], 'risk_notes': [NAMES.get(k, k) for k in failed],
              'original_conclusion': row['conclusion'], 'retained': False}
    try:
        years = (dt.date.fromisoformat(row['end'])-dt.date.fromisoformat(row['start'])).days/365.25
    except (ValueError, TypeError, KeyError):
        years = 0
    strong = ((row.get('excess_1x') or 0) >= policy['strong_excess']
              or (row.get('sharpe_1x') or 0) >= policy['strong_sharpe'])
    if (row['conclusion'] == 'REJECTED' and '/' not in row['variant'] and strong
            and years >= policy['minimum_years'] and failed and set(failed) <= set(policy['soft_checks'])
            and all(checks.get(k) is True for k in policy['required_checks'])
            and 'holding' in str(row.get('measurement', ''))):
        result.update(review_conclusion='RESEARCH_ONLY', retained=True)
    return result


def tags(settings: dict, variant: str, battery: dict) -> list[str]:
    if '/' in variant:
        return ['横截面因子', '数据频率待核对', 'Top组多头回测',
                '信号中性化≠市场中性' if 'neutral' in variant else '原始信号']
    research = settings.get('research', settings)
    portfolio, policy = settings.get('portfolio', {}), settings.get('policy', {})
    top = portfolio.get('primary_top_k') or research.get('top_k') or policy.get('top_k')
    cross = bool(top or '_top' in variant)
    timing = variant == 'overlay' and bool(policy.get('reference'))
    method = '横截面＋择时' if timing else '横截面选股' if cross else '策略类型待核对'
    engine = battery.get('portfolio', {}).get('cost_engine', '')
    rebalance = portfolio.get('rebalance') or battery.get('portfolio', {}).get('rebalance') or policy.get('frequency', '')
    # Account engine frequency is not the original feature frequency.
    level = '日线回放' if engine == 'quant.backtest.daily_account' else '回放频率待核对'
    direction = '多头' if (cross and (portfolio.get('weights') == 'equal_within_selected_stocks'
                                      or battery.get('portfolio', {}).get('top_group_weights') == 'equal')) else '方向待核对'
    return [method, level, direction, '月度调仓' if 'month' in rebalance else '调仓频率待核对']


def enrich(rows: list[dict], root: Path = ROOT) -> list[dict]:
    policy = tomllib.loads((root/'configs/research/strategy_retention.toml').read_text(encoding='utf-8'))
    result = []
    for original in rows:
        row = dict(original)
        run, config = Path(row['run_path']), Path(row['config_path'])
        try:
            settings = tomllib.loads(config.read_text(encoding='utf-8')) if config.suffix == '.toml' else {}
            saved = load(run/'assessment.json')
            assessment = saved.get('assessments', {}).get(row['variant'], {})
            if not assessment and '_top' in row['variant']:
                assessment = load(run/row['variant'].rsplit('_top', 1)[0]/'assessment.json').get(
                    'primary' if row.get('primary') else 'sensitivity', {})
            if (row['variant'] == 'constrained'
                    and saved.get('replacement_checks', {}).get('all_signal_constraints_satisfied') is False):
                assessment = {**assessment, 'checks': {**assessment.get('checks', {}),
                                                      'portfolio_constraints_verified': False}}
            battery_path = run/'battery.toml'
            if not battery_path.is_file() and row.get('source_run'):
                battery_path = Path(row['source_run'])/'battery.toml'
            battery = tomllib.loads(battery_path.read_text(encoding='utf-8')) if battery_path.is_file() else {}
            row.update(classify(row, assessment, policy), tags=tags(settings, row['variant'], battery))
            row['tag_source'] = str(config)
            if row['tags'][0] == '策略类型待核对' and row.get('source_run'):
                inherited = Path(row['source_run'])/'config.toml'
                if inherited.is_file():
                    row['tags'] = tags(tomllib.loads(inherited.read_text(encoding='utf-8')), row['variant'], battery)
                    row['tag_source'] += '；继承源策略：'+str(inherited)
            if saved.get('replace_q10_construction') is False and row['variant'] == 'constrained':
                row['risk_notes'].append('未改善原Q10，不作为替代组合')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row.update(review_conclusion=row['conclusion'], original_conclusion=row['conclusion'], retained=False,
                       risk_notes=['证据读取失败：'+type(exc).__name__], tags=['分类待核对'])
        result.append(row)
    # Explicit reassessment of the same account, not a better backtest with a similar name.
    successors = {}
    for candidate in result:
        if candidate.get('source_run') and candidate['conclusion'] == 'PAPER_CANDIDATE':
            key = (str(Path(candidate['source_run']).resolve()), candidate['variant'])
            successors.setdefault(key, []).append(candidate)
    for row in result:
        newer = [r for r in successors.get((str(Path(row['run_path']).resolve()), row['variant']), [])
                 if all(r.get(k) == row.get(k) for k in ('cagr_1x', 'sharpe_1x', 'mdd_1x', 'cagr_2x'))]
        if newer:
            chosen = max(newer, key=lambda r: r['result_time'])
            row.update(review_conclusion='PAPER_CANDIDATE', retained=False,
                       reassessment_report=chosen['report_path'], risk_notes=['同一净值已有更新复核；旧拒绝原因保留在原报告'])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = enrich(pl.read_parquet(ROOT/'artifacts/registry/experiments.parquet').to_dicts())
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'review.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    kept = [r for r in rows if r['retained']]
    lines = ['# 旧策略研究保留复核', '', '保留研究不等于模拟盘准入；原报告与交易限制不变。', '',
             '|实验 / 变体|复核结论|风险提示|', '|---|---|---|']
    for r in kept:
        lines.append(f"|{r['experiment_id']} / {r['variant']}|RESEARCH_ONLY|{'；'.join(r['risk_notes'])}|")
    (args.output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'rows': len(rows), 'retained': len(kept), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
