"""Run the registered factor evaluation pipeline and write its final scorecard."""
import argparse
import datetime as dt
import json
from pathlib import Path

from quant.research.factor_battery_batch import run_statistics
from quant.research.factor_battery_benchmarks import run_benchmarks
from quant.research.factor_battery_cost_batch import run_cost_batch
from quant.research.factor_battery_redundancy import run_redundancy
from quant.research.factor_battery_scorecard import run_scorecard
from quant.research.factor_battery_screen import run_screen


def run_pipeline(*, config: Path, library: Path, as_of: dt.date, output: Path,
                 data_root: Path, execution_snapshot: str, workers: int) -> dict:
    """Use a new run directory; retain partial outputs if a stage fails.

    The factor panels and dated execution inputs must already be published.
    Stages run sequentially, with worker parallelism inside the heavy stages.
    """
    if workers < 1:
        raise ValueError('Workers must be positive')
    output.mkdir(parents=True, exist_ok=False)
    statistics, screen = output/'statistics', output/'screen'
    benchmarks, redundancy, costs = output/'benchmarks', output/'redundancy', output/'costs'
    print('Computing full-library statistics', flush=True)
    run_statistics(data_root=data_root, config=config, library=library, as_of=as_of,
                   output=statistics, selected='all', workers=workers)
    print('Screening the complete multiple-testing family', flush=True)
    run_screen(statistics=statistics, output=screen, library=library)
    print('Replaying both stock benchmarks at all cost levels', flush=True)
    run_benchmarks(statistics=statistics, output=benchmarks, data_root=data_root,
                   execution_snapshot=execution_snapshot)
    print('Computing full-library historical correlations', flush=True)
    run_redundancy(statistics=statistics, output=redundancy, library=library, workers=workers)
    print('Replaying all factor portfolios at all cost levels', flush=True)
    batch = run_cost_batch(statistics=statistics, screen=screen, output=costs, data_root=data_root,
                          execution_snapshot=execution_snapshot, existing_runs=[], workers=workers)
    print('Writing scorecard and outstanding cost failures', flush=True)
    scorecard = run_scorecard(screen=screen, output=output/'scorecard', cost_runs=[], cost_root=costs,
                             benchmarks=benchmarks, redundancy=redundancy, data_root=data_root)
    result = {'as_of': str(as_of), 'scorecard': scorecard, 'cost_failures': batch['failures'],
              'scorecard_path': str(output/'scorecard'/'factor_scorecard.parquet')}
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    failures = '\n'.join(f'- {factor}: {reason}' for factor, reason in sorted(batch['failures'].items()))
    (output/'report.md').write_text(
        f"# 因子评估流水线：{as_of}\n\n"
        f"评分表{scorecard['rows']}行，完整成本{scorecard['cost_complete_rows']}行，"
        f"通过准入{scorecard['admitted_rows']}行，待补准入证据{scorecard['admission_unresolved_rows']}行。\n\n"
        f"评分表：`scorecard/factor_scorecard.parquet`。\n\n"
        + ('成本回放失败明细：\n\n'+failures+'\n' if failures else '成本批处理无失败项。\n'),
        encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/factors/battery.toml'))
    parser.add_argument('--library', type=Path, default=Path('configs/factors/library'))
    parser.add_argument('--as-of', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--execution-snapshot', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    result = run_pipeline(config=args.config, library=args.library, as_of=args.as_of,
                          output=args.output, data_root=args.data_root,
                          execution_snapshot=args.execution_snapshot, workers=args.workers)
    print(json.dumps(result))
    if result['cost_failures']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
