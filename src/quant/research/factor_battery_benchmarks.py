"""Monthly equal-weight stock benchmarks on the battery's tradable universe."""
import argparse
import datetime as dt
import json
import tomllib
import uuid
from pathlib import Path

import polars as pl

from quant.data.factor_benchmarks import read_csi800_members
from quant.data.factor_panels import available_sessions
from quant.research.factor_battery_costs import run_cost_plans


def _retire_incompatible_benchmarks(output: Path) -> None:
    """Move aside a fingerprint-stale benchmarks stage so resume can rebuild."""
    parent = output.parent.resolve()
    if not output.exists():
        return
    if not output.resolve().is_relative_to(parent):
        raise ValueError('Benchmark output escaped its parent')
    stale = output.with_name(f'{output.name}_incompatible_{uuid.uuid4().hex[:8]}')
    if not stale.resolve().is_relative_to(parent):
        raise ValueError('Stale benchmark archive escaped its parent')
    output.rename(stale)


def equal_weight_targets(universe: pl.DataFrame, *, members: pl.DataFrame | None,
                         signals: list[dt.date], sessions: tuple[dt.date, ...],
                         end: dt.date, name: str) -> pl.DataFrame:
    """Membership is dated by signal close; weights never use future outcomes."""
    next_session = dict(zip(sessions, sessions[1:]))
    eligible = universe.filter(pl.col('eligible')).select('trade_date', 'symbol')
    if eligible.is_duplicated().any() or signals != sorted(set(signals)):
        raise ValueError('Invalid equal-weight signal keys')
    rows = []
    for signal in signals:
        execution = next_session.get(signal)
        if execution is None or execution > end:
            continue
        symbols = eligible.filter(pl.col('trade_date') == signal)['symbol'].to_list()
        if members is not None:
            latest = members.filter(pl.col('snapshot_date') <= signal)['snapshot_date'].max()
            if latest is None:
                raise ValueError(f'Missing historical CSI800 members on {signal}')
            constituents = set(members.filter(pl.col('snapshot_date') == latest)['symbol'])
            symbols = [symbol for symbol in symbols if symbol in constituents]
        if not symbols:
            raise ValueError(f'Empty executable equal-weight benchmark on {signal}')
        rows.extend({'as_of': signal, 'execution_date': execution, 'symbol': symbol,
                     'strategy': name, 'strategy_version': '1', 'weight': 1/len(symbols)} for symbol in symbols)
    return pl.DataFrame(rows, schema={'as_of': pl.Date, 'execution_date': pl.Date, 'symbol': pl.String,
                                     'strategy': pl.String, 'strategy_version': pl.String, 'weight': pl.Float64}).sort(
                                         'execution_date', 'symbol')


def run_benchmarks(*, statistics: Path, output: Path, data_root: Path, execution_snapshot: str,
                   reuse_root: Path | None = None, resume: bool = False) -> dict:
    config_bytes = (statistics/'battery.toml').read_bytes()
    settings = tomllib.loads(config_bytes.decode('utf-8'))
    end = settings['run']['as_of']
    sessions = available_sessions(data_root, end)
    frames, signals = [], set()
    for year in range(settings['start'].year, end.year+1):
        folder = statistics/'inputs'/str(year)
        dates = pl.read_parquet(folder/'monthly_labels.parquet', columns=['trade_date'])['trade_date'].unique()
        signals.update(dates.to_list())
        frames.append(pl.read_parquet(folder/'universe.parquet', columns=['trade_date', 'symbol', 'eligible']).filter(
            pl.col('trade_date').is_in(dates.implode())))
    universe = pl.concat(frames)
    members = read_csi800_members(data_root=data_root, snapshot=settings['data']['csi800_snapshot'])
    plans = {}
    for label, membership in (('all_market_equal_weight', None), ('csi800_equal_weight', members)):
        name = f'battery_{label}'
        plans[label] = (name, equal_weight_targets(universe, members=membership, signals=sorted(signals),
                                                  sessions=sessions, end=end, name=name))
    from quant.research import benchmark_reuse
    from quant.research.slice_budget import checkpoint
    checkpoint()
    reuse_context = None
    if reuse_root is not None:
        reuse_context = benchmark_reuse.context(settings=settings, plans=plans, sessions=sessions,
                                               data_root=data_root, snapshot=execution_snapshot)
        reused = benchmark_reuse.lookup(reuse_root, reuse_context, output)
        if reused is not None:
            return reused
    output.mkdir(parents=True, exist_ok=resume)
    if reuse_context is not None:
        inputs = output/'benchmark_inputs.json'
        if inputs.exists():
            try:
                benchmark_reuse.require_compatible_resume(inputs, reuse_context)
            except ValueError as exc:
                # Code/data fingerprint drifted (e.g. module split). Never brick
                # continuous mining: retire the stale stage and rebuild.
                if 'compatible scope receipt absent or stale' not in str(exc):
                    raise
                _retire_incompatible_benchmarks(output)
                output.mkdir(parents=True, exist_ok=False)
                resume = False
                inputs = output/'benchmark_inputs.json'
        if not inputs.exists():
            inputs.write_text(json.dumps(reuse_context, indent=2), encoding='utf-8')
    frozen_bytes = config_bytes + (
        '\n[benchmark_replay]\nstock_universe = "same_signal_day_eligible_universe_as_factors"\n'
        f'execution_snapshot = {json.dumps(execution_snapshot)}\n').encode('utf-8')
    if resume and (output/'battery.toml').read_bytes() != frozen_bytes:
        raise ValueError('Resumed benchmark settings changed')
    if not resume:
        (output/'battery.toml').write_bytes(frozen_bytes)
    result = run_cost_plans(settings=settings, plans=plans, sessions=sessions, output=output,
                          data_root=data_root, execution_snapshot=execution_snapshot, factor='stock_benchmarks', resume=resume)
    if reuse_context is not None:
        after = benchmark_reuse.context(settings=settings, plans=plans, sessions=sessions,
                                        data_root=data_root, snapshot=execution_snapshot)
        if after != reuse_context:
            raise ValueError('Benchmark inputs changed during replay; result not cached')
        benchmark_reuse.publish(reuse_root, reuse_context, output, plans, settings)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--statistics', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--execution-snapshot', required=True)
    args = parser.parse_args()
    print(json.dumps(run_benchmarks(statistics=args.statistics, output=args.output,
                                   data_root=args.data_root, execution_snapshot=args.execution_snapshot)))


if __name__ == '__main__':
    main()
