"""Score one frozen P7 batch, report API quality, and evaluate all accumulated batches."""
import argparse
import json
from pathlib import Path
import time
import tomllib

from quant.data.forecast_text_scores import read_corpus
from quant.factors.forecast_text_score import score_key
from quant.research.evaluate_monthly_text_sample import combined_request_keys, run as evaluate
from quant.research.report_text_batch import run as report_quality
from quant.research.score_forecast_text import load_settings, run_batch


def render_report(result: dict) -> str:
    quality, evaluation = result['quality'], result['evaluation']
    lines = ['# P7月度文本流水线', '',
        f"本次调用{result['requests_this_run']}次；请求批次成功{quality['successful_texts']}/{quality['selected_unique_texts']}段。"
        f"共享缓存峰值费率记账含预留${quality['shared_charged_or_reserved_usd']:.6f}。", '',
        f"合并评估保留{evaluation['sample_rows']}个冻结股票月。", '',
        '|信号|单月最多共同样本|有效IC月|', '|---|---:|---:|']
    lines += [f"|{r['factor']}|{r['max_common_symbols']}|{r['usable_months']}|" for r in evaluation['coverage']]
    monthly = evaluation.get('monthly_statistics')
    if monthly:
        lines += ['', f"原始值及规模行业中性化共{monthly['variants']}条月度统计序列；"
                  f"{monthly['coverage_sufficient_variants']}条达到原月份覆盖要求。"]
    costs, scorecard = result.get('costs'), result.get('scorecard')
    if costs is None:
        lines += ['', '本次未请求成本阶段；统计结果见evaluation/monthly_statistics。']
    else:
        lines += ['', f"成本任务：完成{len(costs['completed_runs'])}个因子，"
            f"统计未通过而跳过{len(costs.get('statistically_rejected_factors', []))}个，"
            f"失败{len(costs['failures'])}个，等待外部任务{len(costs['pending_external_runs'])}个。"]
        if costs['failures'] or costs['pending_external_runs']:
            lines.append('成本证据尚未齐全；检查costs中的失败或等待项，不能把缺失成本当作通过。')
    if scorecard is not None:
        lines += [f"评分表：{scorecard.get('rows', '未知')}行，统计通过{scorecard.get('statistical_pass_rows', '未知')}行，"
            f"成本完整{scorecard.get('cost_complete_rows', '未知')}行，通过因子条件{scorecard['admitted_rows']}行，"
            f"准入未决{scorecard.get('admission_unresolved_rows', '未知')}行。",
            '逐版本结果见scorecard；因子条件通过不直接产生策略持仓。']
    lines += ['', '下一步：结合月度覆盖、数值控制下的增量诊断及实际成本结果决定是否继续研究。',
        '响应成功率不是独立语义准确率，线性控制后的相关性也不能单独证明预测增量。', '']
    return '\n'.join(lines)


def validate_batch(plan: Path, prior_plans: list[Path]) -> dict:
    """Check the request file and rubric before spending or creating a result directory."""
    spec = tomllib.loads((plan / 'config.toml').read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False:
        raise ValueError('Monthly text pipeline is research only')
    combined_request_keys(plan, prior_plans)
    settings = load_settings(Path(spec['scoring']))
    source = read_corpus(plan / 'scoring_batch.parquet')
    actual = {score_key(text, settings) for text in source.filter(
        ~source['same_day_conflict'])['reason_text'].drop_nulls()}
    expected = set(json.loads((plan / 'summary.json').read_text())['selected_request_keys'])
    if not expected or actual != expected:
        raise ValueError('Request file or scoring settings differ from the frozen plan')
    return spec


def run(*, plan: Path, prior_plans: list[Path], cache: Path, output: Path,
        data_root: Path, execute: bool = False, max_requests: int = 0,
        max_usd: float = 0., workers: int = 1, execution_snapshot: str | None = None,
        return_benchmark_config: Path | None = None) -> dict:
    """Offline mode reads the cache only; live mode retains all missing/failed events."""
    spec = validate_batch(plan, prior_plans)
    if execution_snapshot and (return_benchmark_config is None or not return_benchmark_config.is_file()):
        raise ValueError('Cost evaluation requires a saved return benchmark configuration')
    if execute and (max_requests <= 0 or not 0 < max_usd <= 30):
        raise ValueError('Provide positive cumulative request and USD caps, with USD at most 30')
    if workers not in range(1, 5):
        raise ValueError('Workers must be 1-4')
    if not execute and not cache.is_file():
        raise ValueError('Offline evaluation requires an existing scoring cache')
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    scoring = None
    if execute:
        scoring = run_batch(source=plan / 'scoring_batch.parquet',
            config=Path(spec['scoring']), design_path=Path(spec['design']),
            output=output / 'scoring', cache_path=cache, execute=True,
            max_requests=max_requests, max_usd=max_usd, workers=workers)
    quality = report_quality(plan=plan, cache=cache, output=output / 'quality')
    evaluation = evaluate(plan=plan, additional_plans=prior_plans, cache=cache,
                          output=output / 'evaluation', data_root=data_root)
    costs = scorecard = None
    if execution_snapshot:
        from quant.research.factor_battery_cost_batch import run_cost_batch
        from quant.research.factor_battery_scorecard import run_scorecard
        from quant.research.forecast_text_redundancy import run_redundancy
        cost_inputs = output / 'evaluation' / 'cost_inputs'
        costs = run_cost_batch(statistics=cost_inputs, screen=cost_inputs / 'screen',
            output=output / 'costs', data_root=data_root, execution_snapshot=execution_snapshot,
            existing_runs=[], workers=workers, only_statistical_pass=True)
        redundancy = None
        if evaluation['cost_inputs']['primary_statistical_pass']:
            redundancy = output / 'redundancy'
            run_redundancy(statistics=cost_inputs, peer_statistics=Path(spec['statistics']),
                peer_library=Path('configs/factors/library'), output=redundancy, workers=workers)
        scorecard = run_scorecard(screen=cost_inputs / 'screen', output=output / 'scorecard',
            cost_runs=[Path(p) for p in costs['completed_runs'].values()], cost_root=None,
            benchmarks=None, redundancy=redundancy, data_root=data_root,
            return_benchmark_config=return_benchmark_config)
    result = {'conclusion': 'RESEARCH_ONLY', 'execute': execute,
        'requests_this_run': scoring['requests_this_run'] if scoring else 0,
        'elapsed_seconds': time.monotonic() - started,
        'request_plan': str(plan), 'prior_plans': [str(p) for p in prior_plans],
        'max_requests': max_requests if execute else None,
        'max_usd': max_usd if execute else None, 'workers': workers if execute else 0,
        'quality': quality, 'evaluation': evaluation, 'costs': costs, 'scorecard': scorecard}
    (output / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (output / 'report.md').write_text(render_report(result), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--prior-plan', dest='prior_plans', type=Path, action='append', default=[])
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-requests', type=int, default=0)
    parser.add_argument('--max-usd', type=float, default=0.)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--execution-snapshot')
    parser.add_argument('--return-benchmark-config', type=Path)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ('conclusion', 'requests_this_run',
                                                 'elapsed_seconds')}))
    if result['costs'] and (result['costs']['failures'] or result['costs']['pending_external_runs']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
