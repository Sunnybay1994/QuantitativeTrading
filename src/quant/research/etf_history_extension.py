"""Mechanically prepare the already specified three-ETF history extension."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl

SOURCE = Path('artifacts/research/etf_allocation_attribution_20260922_03')
AUDIT = Path('artifacts/research/etf_history_audit_20260928_01')
GOLD = Path('artifacts/research/etf_gold_event_evidence_20260928_01')
END = dt.date(2026, 8, 31)


def total_return_prices(bars: pl.DataFrame, dividends: pl.DataFrame) -> pl.DataFrame:
    """Cash-adjusted close returns, compounded only forwards in exchange time."""
    if bars.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate history price keys')
    if dividends.select('symbol', 'ex_date').is_duplicated().any():
        raise ValueError('Duplicate history dividend keys')
    frame = bars.sort('symbol', 'trade_date').join(
        dividends.select('symbol', pl.col('ex_date').alias('trade_date'), 'div_cash'),
        on=['symbol', 'trade_date'], how='left', validate='1:1').with_columns(
        pl.col('div_cash').fill_null(0.))
    if frame.filter(pl.col('close').is_null() | ~pl.col('close').is_finite() | (pl.col('close') <= 0)).height:
        raise ValueError('Invalid history closing price')
    frame = frame.with_columns(((pl.col('close') + pl.col('div_cash')) /
        pl.col('close').shift(1).over('symbol')).fill_null(1.).alias('_gross'))
    return frame.select('symbol', 'trade_date',
        (pl.col('_gross').cum_prod().over('symbol') * pl.col('close').first().over('symbol')).alias('adjusted_close'),
        pl.lit('TOTAL_RETURN_DIVIDEND').alias('adjustment_method'),
        pl.lit('audited_tdx_early_frozen_published_later').alias('source'))


def prepare(output: Path) -> Path:
    hashes = {}
    def capture(path):
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path
    diagnostic = json.loads(capture(AUDIT/'diagnostic.json').read_text(encoding='utf-8'))
    for row in diagnostic['summary']:
        if any(row[key] for key in ('missing_tdx_sessions', 'raw_daily_conflict_dates',
                'overlap_close_conflicts_over_tick', 'adjustment_conflict_dates', 'pre2023_missing_adjustment_dates')):
            raise ValueError('Unresolved price/adjustment gaps')
    # The independent audit is a frozen receipt, not a claim that its paths still match.
    for name, digest in diagnostic['sources'].items():
        if capture(Path(name)) and hashes[name] != digest:
            raise ValueError(f'Audited input changed: {name}')
    gold = json.loads(capture(GOLD/'event_evidence.json').read_text(encoding='utf-8'))
    if (gold['status'] != 'official_report_action_chain_reconciled'
            or gold['annual_share_ledger_checks_passed'] != 10 or gold['year_transition_checks_passed'] != 9):
        raise ValueError('Gold action evidence is incomplete')
    for row in gold['annual_share_reconciliation']:
        path = capture(GOLD/f"annual_{row['year']}.pdf")
        if hashes[str(path)] != row['sha256'] or float(row['residual_shares']) != 0.:
            raise ValueError('Official gold report receipt changed')
    capture(AUDIT/'event_followup.json')
    capture(Path('artifacts/data_collection_watch/20260928_etf_event_receipts.json'))
    frames = {name: pl.read_parquet(capture(SOURCE/f'{name}.parquet'))
              for name in ('bars', 'prices', 'calendar', 'instruments', 'dividends')}
    pieces = []
    for symbol in sorted(frames['instruments']['symbol']):
        original = frames['bars'].filter(pl.col('symbol') == symbol)
        path = capture(Path(f'data/clean/bar_1d_tdx/source=tdx/market=SH/symbol={symbol}/data.parquet'))
        early = pl.read_parquet(path).filter(pl.col('trade_date') < original['trade_date'].min())
        early = early.with_columns(pl.lit(1.).alias('adj_factor')).select(original.columns).cast(original.schema)
        pieces.extend([early, original])
    bars = pl.concat(pieces).sort('symbol', 'trade_date')
    start = bars.group_by('symbol').agg(pl.col('trade_date').min())['trade_date'].max()
    bars = bars.filter(pl.col('trade_date').is_between(start, END))
    sessions = frames['calendar'].filter((pl.col('market') == 'SH') & pl.col('is_open')
        & pl.col('date').is_between(start, END))['date'].to_list()
    for symbol in frames['instruments']['symbol']:
        if bars.filter(pl.col('symbol') == symbol)['trade_date'].to_list() != sessions:
            raise ValueError('Incomplete common continuous history')
    cash = pl.read_csv(capture(AUDIT/'implemented_cash_events.csv'), try_parse_dates=True).select(
        'symbol', pl.col('imp_anndate').cast(pl.String).str.to_date('%Y%m%d').alias('ann_date'),
        pl.col('record_date').cast(pl.String).str.to_date('%Y%m%d'), 'ex_date',
        pl.col('pay_date').cast(pl.String).str.to_date('%Y%m%d'), 'div_cash')
    old_start = frames['bars']['trade_date'].min()
    dividends = pl.concat([cash.filter(pl.col('ex_date') < old_start), frames['dividends']]).filter(
        pl.col('ex_date').is_between(start, END)).sort('symbol', 'ex_date')
    prices = total_return_prices(bars, dividends)
    frames.update(bars=bars, prices=prices, dividends=dividends)
    output.mkdir(parents=True, exist_ok=False)
    inputs = output/'inputs'
    inputs.mkdir()
    for name, frame in frames.items():
        frame.write_parquet(inputs/f'{name}.parquet')
        capture(inputs/f'{name}.parquet')
    receipt = dict(classification='RESEARCH_ONLY', auto_trade=False, start=str(start), end=str(END),
        sessions=len(sessions), source_hashes=hashes, limitations=[
            'Earlier TDX daily prices for bond/gold lack an independent daily price series before 2023.',
            'Official action evidence closes the specific requested gap, not a full corporate-action certification.',
            'Observed development history, not a new holdout; original pool/window/costs/account rules unchanged.'])
    (inputs/'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    config = Path('configs/research/etf_measurement_execution_v1.toml')
    target = output/'config.toml'
    target.write_text(config.read_text(encoding='utf-8') + f'\nhistory_inputs = "{inputs.as_posix()}"\n'
        'historical_cost_policy = "unchanged_fixed_cost_sensitivity_not_verified_historical_broker_fees"\n', encoding='utf-8')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = prepare(args.output)
    from quant.research.etf_measurement import run
    run(config, args.output/'replay')


if __name__ == '__main__':
    main()
