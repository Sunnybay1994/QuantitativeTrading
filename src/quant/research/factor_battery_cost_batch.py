"""Run the registered cost battery, prioritizing statistically useful factors."""
import argparse
import json
import os
import tomllib
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import polars as pl

from quant.research.factor_battery_costs import run_factor_costs


def cost_order(screen: pl.DataFrame, *, primary: str) -> list[str]:
    table = screen.filter(pl.col('variant') == primary)
    if not table.height or table['factor'].n_unique() != table.height:
        raise ValueError('Cost ordering requires unique primary factor rows')
    return table.with_columns(pl.col('icir').cast(pl.Float64).fill_nan(None)).sort(
        ['statistical_pass', 'icir', 'factor'], descending=[True, True, False],
        nulls_last=True)['factor'].to_list()


def existing_cost_factor(run: Path, *, settings: dict, snapshot: str) -> str:
    """A supplied in-flight run is reserved too, so it cannot be duplicated."""
    saved = tomllib.loads((run/'battery.toml').read_text(encoding='utf-8'))
    selection = saved.pop('cost_replay')
    if saved != settings or selection['execution_snapshot'] != snapshot:
        raise ValueError('Existing cost run has different settings or execution inputs')
    return selection['factor']


def run_cost_batch(*, statistics: Path, screen: Path, output: Path, data_root: Path,
                   execution_snapshot: str, existing_runs: list[Path], workers: int,
                   only_statistical_pass: bool = False, resume: bool = False) -> dict:
    settings_bytes = (statistics/'battery.toml').read_bytes()
    settings = tomllib.loads(settings_bytes.decode('utf-8'))
    if workers < 1 or (screen/'battery.toml').read_bytes() != settings_bytes:
        raise ValueError('Cost batch requires matching statistical screening settings')
    table = pl.read_parquet(screen/'statistical_screen.parquet')
    expected = pl.read_parquet(statistics/'statistics.parquet', columns=['factor', 'variant'])
    if table.height != expected.height or set(table.select('factor', 'variant').rows()) != set(expected.rows()):
        raise ValueError('Cost batch cannot omit registered statistical rows')
    ordered = cost_order(table, primary=settings['primary_variant'])
    skipped = []
    if only_statistical_pass:
        passing = set(table.filter(pl.col('statistical_pass'))['factor'].to_list())
        skipped = [factor for factor in ordered if factor not in passing]
        ordered = [factor for factor in ordered if factor in passing]
    existing = {}
    for run in existing_runs:
        factor = existing_cost_factor(run, settings=settings, snapshot=execution_snapshot)
        if factor not in ordered or factor in existing:
            raise ValueError('Unknown or duplicate externally supplied cost factor')
        existing[factor] = str(run)
    output.mkdir(parents=True, exist_ok=True)
    config = output/'battery.toml'
    if config.is_file() and config.read_bytes() != settings_bytes:
        raise ValueError('Use a new batch directory for changed settings')
    if not config.exists():
        config.write_bytes(settings_bytes)
    completed, failures, pending_external = {}, {}, {}
    todo = []
    for factor in ordered:
        folder = Path(existing[factor]) if factor in existing else output/factor
        if (folder/'summary.json').is_file():
            if existing_cost_factor(folder, settings=settings, snapshot=execution_snapshot) != factor:
                raise ValueError('Cached cost run belongs to another factor')
            completed[factor] = str(folder)
        elif factor in existing:
            pending_external[factor] = str(folder)
        elif folder.exists():
            if resume and (folder/'replay_config.json').is_file():
                if existing_cost_factor(folder, settings=settings, snapshot=execution_snapshot) != factor:
                    raise ValueError('Partial cost run belongs to another factor')
                todo.append(factor)
            else:
                failures[factor] = 'Partial prior output retained; use --resume with complete account checkpoints or a new directory'
        else:
            todo.append(factor)
    os.environ['POLARS_MAX_THREADS'] = '4'
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_factor_costs, statistics=statistics, output=output/factor,
                               data_root=data_root, execution_snapshot=execution_snapshot, factor=factor,
                               resume=resume and (output/factor).exists()): factor
                   for factor in todo}
        for future in as_completed(futures):
            factor = futures[future]
            try:
                future.result()
                completed[factor] = str(output/factor)
            except Exception as exc:
                failures[factor] = str(exc)
            print(json.dumps({'factor': factor, 'completed': len(completed), 'failed': len(failures),
                              'error': failures.get(factor)}), flush=True)
    # External runs may have completed while the queued work ran.
    for factor, external_folder in list(pending_external.items()):
        if (Path(external_folder)/'summary.json').is_file():
            completed[factor] = pending_external.pop(factor)
    result = {'factors': len(ordered), 'completed_runs': completed, 'failures': failures,
              'pending_external_runs': pending_external, 'statistically_rejected_factors': skipped}
    (output/'batch_summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--statistics', type=Path, required=True)
    parser.add_argument('--screen', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--execution-snapshot', required=True)
    parser.add_argument('--existing-run', type=Path, action='append', default=[])
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--resume', action='store_true', help='Resume local interrupted factors with annual account checkpoints')
    args = parser.parse_args()
    result = run_cost_batch(statistics=args.statistics, screen=args.screen, output=args.output,
                            data_root=args.data_root, execution_snapshot=args.execution_snapshot,
                            existing_runs=args.existing_run, workers=args.workers, resume=args.resume)
    print(json.dumps(result))
    if result['failures'] or result['pending_external_runs']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
