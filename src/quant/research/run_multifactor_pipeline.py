"""One command from causal annual factor screens to model reports."""
import argparse
import json
import tomllib
from pathlib import Path

from quant.reporting.multifactor_models import report_models
from quant.research.model_training_costs import run_cost_prefixes
from quant.research.model_training_prefix import run_prefixes
from quant.research.model_training_selection import run_selection
from quant.research.run_multifactor_predictions import run_predictions
from quant.research.run_multifactor_replay import run_model_replay


def run_pipeline(*, config: Path, output: Path, data_root: Path) -> dict:
    model_bytes = config.read_bytes()
    model = tomllib.loads(model_bytes.decode('utf-8'))
    research = model['research']
    benchmarks = Path(research['stock_benchmarks'])
    output.mkdir(parents=True, exist_ok=False)
    (output/'model.toml').write_bytes(model_bytes)
    print('Recomputing annual training statistics', flush=True)
    run_prefixes(config=config, output=output/'statistics')
    print('Adding completed cost histories', flush=True)
    costs = run_cost_prefixes(prefix=output/'statistics', output=output/'costs',
        cost_runs=[Path(path) for path in research.get('cost_runs', [])],
        cost_root=Path(research['cost_root']), benchmarks=benchmarks, data_root=data_root)
    print('Selecting factors using historical correlations', flush=True)
    selection = run_selection(costs=output/'costs', output=output/'selection')
    incomplete = [row for row in selection['annual_selection'] if not row['selection_complete']]
    result = {'model_results_ready': False, 'completed_cost_factors': costs['complete_cost_factors'],
              'annual_selection': selection['annual_selection'], 'conclusions': None}
    if not incomplete:
        print('Training the three fixed models', flush=True)
        run_predictions(selection=output/'selection', output=output/'predictions')
        print('Replaying the full account calendar', flush=True)
        run_model_replay(predictions=output/'predictions', benchmarks=benchmarks,
                         output=output/'replay', data_root=data_root)
        print('Writing model reports', flush=True)
        reports = report_models(run=output/'replay', benchmarks=benchmarks,
                                output=output/'reports', data_root=data_root)
        result.update(model_results_ready=True, conclusions=reports['conclusions'])
    lines = ['# 多因子流水线结果', '',
        f"已完成成本的因子数：{costs['complete_cost_factors']}。模型结果齐全：{result['model_results_ready']}。", '',
        '|年度|选择完整|待补因子|已确定前缀|', '|---|---|---:|---|']
    for row in selection['annual_selection']:
        lines.append(f"|{row['test_year']}|{row['selection_complete']}|{row['unresolved_factors']}|"
                     f"{', '.join(row['confirmed_selected_prefix']) or '空'}|")
    lines += ['', ('下一步：依据reports目录中三个模型的结论执行模拟盘决策。' if not incomplete else
        '下一步：继续既有成本批处理，证据补齐后以新输出目录重跑本命令；本次保留年度筛选，不生成缺失年份的模型收益。'), '']
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (output/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run_pipeline(config=args.config, output=args.output, data_root=args.data_root)))


if __name__ == '__main__':
    main()
