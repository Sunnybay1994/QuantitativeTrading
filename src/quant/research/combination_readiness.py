"""Check frozen mechanism evidence and whether saved targets can be reused at 100k."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {}

    def record(path):
        manifest[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    source = Path('artifacts/factors/nightly_batches/6b35e47b1f0dcf04/evaluation/scorecard/factor_scorecard.parquet')
    pressure = pl.read_parquet(record(source)).filter(pl.col('factor').str.starts_with('pressure_reversal')).to_dicts()
    for row in pressure:
        row['costs'] = {cost: {key: row[f'cost_{prefix}_{key}'] for key in
            ('cagr','sharpe','max_drawdown','annualized_one_way_turnover','all_market_equal_weight_cagr_excess')}
            for cost,prefix in [('0.5','0p5'),('1','1'),('2','2')]}
    evidence = [dict(factor=row['factor'], variant=row['variant'], admitted=row['factor_admitted'],
                     costs=row['costs']) for row in pressure]
    rejected = bool(evidence) and all(not row['admitted'] and all(
        row['costs'][cost]['all_market_equal_weight_cagr_excess'] < 0 for cost in ('1','2')) for row in evidence)
    allocation = Path('artifacts/research/etf_allocation_attribution_20260922_03/report.json')
    etf = json.loads(record(allocation).read_text(encoding='utf-8'))
    q10 = Path('artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01')
    config = tomllib.loads(record(q10/'config.toml').read_text(encoding='utf-8'))
    capital = tomllib.loads(record(q10/'model.toml').read_text(encoding='utf-8'))['portfolio']['initial_cash']
    originals = pl.read_parquet(record(q10/'targets_budgeted.parquet'))
    all_targets = {}
    reconstruction = []
    for cost in ('0.5','1','2'):
        paths = sorted((q10/f'budgeted/cost_{cost}').glob('*/budget_targets.parquet'))
        all_targets[cost] = pl.concat([pl.read_parquet(record(path)) for path in paths])
        errors = []
        for part in all_targets[cost].partition_by('as_of'):
            delta = part['desired_weight']-part['current_weight']
            distance = float(delta.abs().sum()/2)
            fraction = min(1., .5/distance) if distance else 1.
            errors.append(float((part['weight']-(part['current_weight']+delta*fraction)).abs().max()))
        reconstruction.append(dict(cost=cost, signals=len(errors), max_error=max(errors)))
    keys = ['as_of','execution_date','symbol']
    one = all_targets['1'].select(*keys, pl.col('weight').alias('one'))
    two = all_targets['2'].select(*keys, pl.col('weight').alias('two'))
    compared = one.join(two, on=keys, how='full', coalesce=True, validate='1:1').with_columns(
        pl.col('one','two').fill_null(0.)).with_columns((pl.col('one')-pl.col('two')).abs().alias('absolute_difference'))
    compared.filter(pl.col('absolute_difference')>1e-12).write_parquet(output/'cost_dependent_targets.parquet')
    master = originals.select(*keys,pl.col('weight').alias('saved_master'))
    desired = all_targets['1'].select(*keys,pl.col('desired_weight').alias('desired'))
    comparison = master.join(desired,on=keys,how='full',coalesce=True,validate='1:1').with_columns(
        pl.col('saved_master','desired').fill_null(0.))
    result = dict(auto_trade=False, account_replay_started=False, requested_capital=100000,
        pressure_decision='exclude_from_this_combination' if rejected else 'requires_review',
        pressure_evidence=evidence,
        pressure_basis='Frozen factor admission and reported cost-excess evidence, not newly recomputed benchmarks or proof of no possible diversification.',
        etf_decision='retain_for_combination_research_not_admission', etf_evidence=etf,
        saved_q10_initial_cash=capital, policy=config['policy'],
        q10_target_difference_rows=compared.filter(pl.col('absolute_difference')>1e-12).height,
        q10_target_difference_max=compared['absolute_difference'].max(),
        master_differs_from_desired_rows=comparison.filter((pl.col('saved_master')-pl.col('desired')).abs()>1e-12).height,
        blocker='Saved Q10 adjusted targets are endogenous to prior actual holdings and cost. Scaling them into a 100k mixed account does not reproduce Q10.',
        next_implementation='Freeze one joint allocation policy and same-risk static comparator; recompute Q10 budget from each cost-specific combined account at signal close, then merge executable orders before charging costs.',
        not_done=['joint allocation and same-risk comparator preregistration','100k sequential net-order three-cost replay','individual mechanism and stress-event attribution'],
        interpretation='Do not force pressure reversal into a portfolio. ETF remains a research alternative; this is not a rejection of Q10 plus ETF or a request to stop other research.')
    record(Path('src/quant/portfolio/turnover_budget.py'))
    record(Path(__file__))
    (output/'source_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'verification.json').write_text(json.dumps(dict(
        source_hashes_match=all(hashlib.sha256(Path(k).read_bytes()).hexdigest()==v for k,v in manifest.items()),
        sources=len(manifest), budget_reconstruction=reconstruction),indent=2),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# 固定跨机制组合：纳入证据与接入检查','',
           '机器生成，只读已有结果；不新增状态阈值、不重跑冻结策略。','',
           '压力反转：'+result['pressure_decision']+'。原准入和成本后证据见summary.json；不等于证明任何组合都无分散收益。',
           'ETF配置：保留组合研究理由；651日短历史与原研究限制保留，不升级准入。','',
           f"Q10保存账户初始资金{capital:g}元；1x/2x目标差异{result['q10_target_difference_rows']}行，最大权重差{result['q10_target_difference_max']:.8f}。",
           f"根目录目标与保存desired_weight差异{result['master_differs_from_desired_rows']}行。不能把它当成本无关的实际预算后目标。",'',
           '可复现阻塞：Q10预算以实际信号收盘持仓为输入，直接缩放旧目标会偷换规则。',
           '下一实现：冻结单一联合分配规则及同风险静态对照；在10万元连续账户内按成本场景重算预算与净订单，再计费。',
           '当前没有组合净值、组合增益或三档成本通过结论；原账户、观察与挖掘继续。']
    (output/'report.md').write_text('\n\n'.join(lines),encoding='utf-8')
    return {k:v for k,v in result.items() if k not in ('pressure_evidence','etf_evidence','policy')}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(run(parser.parse_args().output),ensure_ascii=False))
