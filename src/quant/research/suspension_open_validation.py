"""Pair saved rejection market checks without replaying cash or positions."""
import dataclasses
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.stock_execution_inputs import stock_session_states
from quant.research.suspension_execution_audit import digest, write_json


def compare(*, cases: Path, intersection: Path, new_snapshot: str, output: Path,
            data_root: Path = Path('data')) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    old = data_root/'clean/stock_execution/factor_battery_20260911_v2'
    new = data_root/'clean/stock_execution'/new_snapshot
    source = intersection/'matched_records.json'
    matched = json.loads(source.read_text(encoding='utf-8'))
    if not matched:
        raise ValueError('Paired rejection check requires actual matched saved records')
    inputs = pl.read_parquet(cases)
    keys = inputs.select('symbol', 'trade_date')
    bars = inputs.select('symbol', 'trade_date', 'open', 'volume')
    old_stops, new_stops = (pl.read_parquet(root/'suspensions.parquet') for root in (old, new))
    old_limits, new_limits = (pl.read_parquet(root/'limits.parquet') for root in (old, new))
    facts = pl.read_parquet(new/'suspension_open_facts.parquet')
    if digest(old/'limits.parquet') != digest(new/'limits.parquet'):
        raise ValueError('Price-band inputs changed in the paired check')
    sources = [cases, source, new/'suspension_open_facts.parquet', new/'summary.json',
        *[root/name for root in (old, new) for name in ('suspensions.parquet', 'limits.parquet')],
        Path(__file__), Path('src/quant/data/stock_execution_inputs.py'),
        Path('src/quant/data/stock_open_suspensions.py'), Path('src/quant/backtest/rules.py')]
    configs = {row['run']: Path(row['run'])/'battery.toml' for row in matched}
    sources += list(configs.values()) + [Path(row['source_path']) for row in matched]
    before = {str(p): digest(p) for p in sorted(set(sources))}
    write_json(output/'source_manifest_before.json', before)
    pairs = []
    for row in matched:
        if row['kind'] != 'rejections' or row['reason'] != 'SUSPENDED':
            raise ValueError('Unexpected saved record for suspension-only pairing')
        day, symbol = dt.date.fromisoformat(row['date']), row['symbol']
        multiplier = [float(p[5:]) for p in Path(row['source_path']).parts if p.startswith('cost_')]
        if len(multiplier) != 1:
            raise ValueError('Ambiguous saved cost scenario')
        config = tomllib.loads(configs[row['run']].read_text(encoding='utf-8'))
        if config['cost_replay']['execution_snapshot'] != old.name:
            raise ValueError('Saved replay configuration does not match original input version')
        slippage = config['costs']['a_share']['slippage']*multiplier[0]
        selected = bars.filter((pl.col('symbol') == symbol) & (pl.col('trade_date') == day))
        if selected.height != 1 or selected['open'].item() != row['reference_price']:
            raise ValueError('Saved rejection reference is not the same original open')
        args = dict(bars=selected, sessions=[day], symbols=[symbol], execution_dates=[day], slippage=slippage)
        previous = stock_session_states(limits=old_limits, suspensions=old_stops, **args)[day, symbol]
        corrected = stock_session_states(limits=new_limits, suspensions=new_stops, **args)[day, symbol]
        if not previous.suspended:
            raise ValueError('Original saved suspension no longer reproduces')
        def market_reason(state):
            if state.open_unknown:
                return 'OPEN_UNKNOWN'
            if state.suspended:
                return 'SUSPENDED'
            if row['side'] == 'BUY' and state.at_upper_limit:
                return 'BUY_AT_UPPER_LIMIT'
            if row['side'] == 'SELL' and state.at_lower_limit:
                return 'SELL_AT_LOWER_LIMIT'
            return 'market_checks_clear'
        detail = facts.filter((pl.col('symbol') == symbol) & (pl.col('trade_date') == day)).row(0, named=True)
        pairs.append({**row, 'cost_multiplier': multiplier[0], 'slippage': slippage,
            'old_state': dataclasses.asdict(previous), 'new_state': dataclasses.asdict(corrected),
            'old_market_reason': market_reason(previous), 'new_market_reason': market_reason(corrected),
            'source_timings': detail['suspend_timings'], 'source_paths': detail['source_paths'],
            'other_order_constraints': 'Not replayed: no assertion of fill, T+1 availability, participation, fees or resulting PnL'})
    # Entire supplied 26-case set is paired on the same three slippage settings.
    controls = []
    for slippage in (0.0005, 0.001, 0.002):
        for row in bars.iter_rows(named=True):
            day, symbol = row['trade_date'], row['symbol']
            args = dict(bars=pl.from_dicts([row]), sessions=[day], symbols=[symbol],
                execution_dates=[day], slippage=slippage)
            previous = stock_session_states(limits=old_limits, suspensions=old_stops, **args)[day, symbol]
            corrected = stock_session_states(limits=new_limits, suspensions=new_stops, **args)[day, symbol]
            band_only = stock_session_states(limits=old_limits,
                suspensions=old_stops.filter(~((pl.col('trade_date') == day) & (pl.col('symbol') == symbol))), **args)[day, symbol]
            if corrected != band_only or not previous.suspended:
                raise ValueError('Versioned correction changed something other than opening halt mapping')
            controls.append({'symbol': symbol, 'trade_date': day, 'slippage': slippage,
                'old_suspended': previous.suspended, 'new_suspended': corrected.suspended,
                'new_at_upper_limit': corrected.at_upper_limit, 'new_at_lower_limit': corrected.at_lower_limit,
                'identical_to_original_band_check': True})
    after = {name: digest(Path(name)) for name in before}
    if before != after:
        raise ValueError('Frozen execution evidence changed during pairing')
    write_json(output/'source_manifest_after.json', after)
    write_json(output/'matched_decision_pairs.json', pairs)
    pl.from_dicts(controls).write_parquet(output/'afternoon_case_pairs.parquet')
    result = {'saved_rejections_paired': len(pairs), 'unique_stock_days': len({(r['date'], r['symbol']) for r in pairs}),
        'new_market_reason_counts': {reason: sum(r['new_market_reason'] == reason for r in pairs)
            for reason in sorted({r['new_market_reason'] for r in pairs})},
        'full_case_cost_controls': len(controls), 'old_price_band_logic_unchanged': True,
        'unspecified_timing_positive_volume_unknown': facts.filter(pl.col('open_reason') == 'full_day_positive_volume_conflict').height,
        'source_conflicts_unknown': facts.filter(pl.col('open_reason') == 'conflicting_source_records').height,
        'open_including_intervals_remain_blocked': facts.filter(pl.col('open_reason') == 'interval_includes_open').height,
        'source_hashes_unchanged': True, 'account_runs': 0, 'battery_runs': 0,
        'pnl_effect': 'Not measured; removing an erroneous market-state rejection is not proof of a fill or profit improvement'}
    write_json(output/'summary.json', result)
    (output/'report.md').write_text('# 保存拒单的开盘市场状态配对\n\n```json\n'+json.dumps(result, ensure_ascii=False,
        indent=2)+'\n```\n', encoding='utf-8')
    return result
