"""Generate the four-section R3 review from completed machine evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def build(*,root,s2b):
    selection=json.loads((root/'selection_risk/summary.json').read_text())
    execution=json.loads((root/'execution_audit/summary.json').read_text())
    original=json.loads((root/'s2b_original_audit/summary.json').read_text())
    corrected=json.loads((s2b/'assessment.json').read_text())
    registration=json.loads((s2b/'registration.json').read_text())
    if not original['exact_legacy_reconstruction'] or registration['registered_count']!=1:
        raise ValueError('Require exact original reconstruction and a completed registered repair')
    suites=list(ET.parse(root/'tests.xml').getroot().iter('testsuite'))
    tests={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    if not tests['tests'] or tests['failures'] or tests['errors']:
        raise ValueError('Require passing R3 and R2 affected tests')
    scopes=selection['scopes']
    one=next(r for r in execution['size_contrast'] if r['size_neutral']=='off' and r['cost_multiplier']==1.)
    two_off=next(r for r in execution['size_contrast'] if r['size_neutral']=='off' and r['cost_multiplier']==2.)
    two_on=next(r for r in execution['size_contrast'] if r['size_neutral']=='on' and r['cost_multiplier']==2.)
    two_s2b=next(r for r in corrected['rows'] if r['cost_multiplier']==2.)
    lines=['# R3 真金前体检','',
        '**结论：目前不能确认可信的正样本外超额；资金规划按0增量超额。** 历史开发结果与独立前向证据分开，auto_trade=false。',
        '', '## 1 · 选择偏差与超额预期','',
        '| 试验数口径 | 声明次数 | 完整日收益/去重路径 | DSR | CSCV PBO |',
        '|---|---:|---:|---:|---:|']
    for name,value in scopes.items():
        lines.append(f"| {name} | {value['declared_attempts']} | {value['complete_paths']}/{value['unique_complete_return_paths']} | "
            f"{value['dsr']['dsr']:.4f} | {value['pbo']['pbo']:.2%} |")
    lines+=['','2019-01-02至2026-08-31共同1859日；DSR用偏度/峰度及可取得同窗试验Sharpe离散度，声明次数按独立次数作敏感性，并非已知有效独立试验数。',
        'PBO以10个连续均衡块、252种对称切分计算，只适用于披露的完整去重矩阵；缺失路径不填零、不复制列，不能称为863次完整搜索的PBO。重复版本和未登记尝试使试验数仍有不确定性。',
        '完整覆盖、逐切分、日收益矩阵及另一种零假设方差DSR敏感性见selection_risk/。',
        '方法：[DSR原论文](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)、[CSCV/PBO原论文](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)。',
        '', '| 试验数敏感性 | 条件年化超额区间 |','|---|---:|']
    for interval in execution['conditional_excess_intervals']:
        low,high=interval['conditional_annual_excess_interval_pp']
        lines.append(f"| {interval['declared_trials']} | [{low:.2f}, {high:.2f}] pp |")
    lines+=['','上表为92个月非重叠对数超额、HAC滞后3、Bonferroni家族显著性5%、固定历史基准年化下的条件均值区间；依赖平稳性，不是未见OOS预测区间。两种口径均跨零，不能据此承诺未来正超额。',
        '', '## 2 · 规模、价格带与现金','',
        f"现有100万元b0.5/Top50配对：1×非规模中性年化{one['cagr']:.2%}；2×最强基准超额，非中性{two_off['net_cagr_excess_strongest']:.2%}、规模约束版{two_on['net_cagr_excess_strongest']:.2%}。",
        '这是同窗构建对照，不能单凭它证明规模独立alpha；三档结果见execution_audit/summary.json。',
        f"审计{execution['fills']}笔成交，官方价格带覆盖{execution['official_band_coverage']:.0%}；收盘涨跌停日成交占{execution['close_limit_day_fill_fraction']:.2%}，买在涨停/卖在跌停的报价占{execution['adverse_execution_band_fraction']:.2%}。收盘触板不代表开盘不可成交。",
        f"实际日均现金比例{execution['mean_cash_fraction']:.2%}；未成交买单可关联现金的日均上界{execution['mean_unfilled_cash_fraction_upper_bound']:.3%}，下界0；缓冲、整手剩余与拒单不能混作因果归属。逐笔价格与现金界限在execution_audit/。",
        '', '## 3 · 撮合不变性','',
        '三条不变性测试已加入常规not slow集合并通过：改变当日高低收不改变开盘成交；同标的同日不能重复花费流动性；未成交买单保留现金且不计费用。',
        f"R3与受影响R2测试共{tests['tests']}项，失败{tests['failures']}、错误{tests['errors']}；JUnit见tests.xml。这不是全项目doctor通过收据。",
        '', '## 4 · S2b −77.1%审计','',
        f"原值{original['saved_2x_max_drawdown']:.3%}逐日精确重建，峰值{original['peak']['trade_date']}至谷值{original['trough']['trade_date']}；旧隐含最大权重{original['maximum_implied_exposure']:.0%}、最多{original['maximum_implied_names']}只，违反原Top3。",
        '**结论：数据与回放错误，不能归为真实可执行Top3的−77.1%回撤。** 退出权重未清零、拆并未入收益、截止日未执行同时存在；日持仓权重/价格/贡献在s2b_original_audit/drawdown_daily_positions.parquet，旧输出保留。',
        f"保持原池、12-1、Top3、债券现金腿和成本重算：2×年化{two_s2b['cagr']:.2%}、回撤{two_s2b['max_drawdown']:.2%}、Sharpe{two_s2b['sharpe']:.3f}；结论{corrected['assessments']['budgeted']['conclusion']}。",
        f"[修复报告]({s2b.resolve().as_posix()}/report.md)；这是修复后的历史目标权重代理，仍未验证真实份额撮合、排队/整手及隐含日度恒定权重交易费用，不升级准入。01导出日期顺序错误已隔离，02验证三成本同窗与每日成本单调性后才登记。"]
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    sources=[root/'selection_risk/summary.json',root/'execution_audit/summary.json',root/'s2b_original_audit/summary.json',
        s2b/'assessment.json',s2b/'registration.json',root/'tests.xml',Path(__file__)]
    result={'status':'diagnostic_completed','auto_trade':False,'dsr':{k:v['dsr']['dsr'] for k,v in scopes.items()},
        's2b_audit':'data_and_backtest_accounting_error','s2b_corrected_run':str(s2b),'tests':tests,
        'forward_evidence':'positive_unseen_oos_excess_not_established','planning_incremental_excess':0.,
        'provenance':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (root/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--s2b',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(root=args.root,s2b=args.s2b)))
