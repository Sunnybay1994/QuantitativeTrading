import datetime as dt
import statistics

import polars as pl
import pytest

from quant.data.quarterly_parent_income import select_quarterly_parent_income
from quant.factors.quarterly_roe_stability import compute_quarterly_roe_stability
from quant.research.monthly_quarterly_roe_stability import build_monthly_quarterly_roe_stability


def row(period: dt.date, published: dt.date, value: float | None) -> dict:
    return {'symbol': '000001.SZ', 'end_date': period, 'ann_date': published,
            'f_ann_date': published, 'available_date': published, 'report_type': '1',
            'comp_type': '1', 'update_flag': '0', 'n_income_attr_p': value}


def test_predecessor_revision_is_bound_to_successor_publication() -> None:
    q1, q2 = dt.date(2023, 3, 31), dt.date(2023, 6, 30)
    history = pl.DataFrame([row(q1, dt.date(2023, 4, 20), 10.),
                            row(q1, dt.date(2023, 9, 1), 100.),
                            row(q2, dt.date(2023, 8, 20), 30.)])
    exact, _ = select_quarterly_parent_income(history, as_of=dt.date(2023, 8, 20))
    assert exact.height == 1
    selected, _ = select_quarterly_parent_income(history, as_of=dt.date(2023, 9, 2))
    assert selected.filter(pl.col('end_date') == q2)['single_parent_income'].item() == 20.
    assert selected.filter(pl.col('end_date') == q1)['single_parent_income'].item() == 100.


@pytest.mark.parametrize('prior', [None, 11.])
def test_missing_or_conflicted_predecessor_is_not_zero(prior: float | None) -> None:
    q1, q2 = dt.date(2023, 3, 31), dt.date(2023, 6, 30)
    rows = [row(q1, dt.date(2023, 4, 20), prior), row(q2, dt.date(2023, 8, 20), 30.)]
    if prior is not None:
        rows.append(row(q1, dt.date(2023, 4, 20), 10.))
    selected, _ = select_quarterly_parent_income(pl.DataFrame(rows), as_of=dt.date(2023, 9, 2))
    assert selected.filter(pl.col('end_date') == q2)['single_parent_income'].item() is None


def period(index: int) -> dt.date:
    year, q = divmod(index, 4)
    return dt.date(year, (q + 1) * 3, (31, 30, 30, 31)[q])


def test_calendar_window_and_minimum_observations() -> None:
    dates = [period(i) for i in range(2008 * 4, 2008 * 4 + 61)]
    q = pl.DataFrame({'symbol': ['000001.SZ'] * 61, 'end_date': dates,
                      'single_parent_income': [1e8, *range(60)]})
    b = q.select('symbol', 'end_date').with_columns(pl.lit(100.).alias('total_hldr_eqy_exc_min_int'))
    anchor = q.select('symbol', 'end_date').tail(1)
    out = compute_quarterly_roe_stability(q, b, anchor)
    assert out['valid_quarters'].item() == 60
    assert out['pit_quarterly_roe_volatility'].item() == pytest.approx(statistics.stdev(range(60)) / 100)
    for count in (11, 12):
        subset = pl.concat([q.head(1), q.tail(count)])
        out = compute_quarterly_roe_stability(subset, b, anchor)
        assert out['valid_quarters'].item() == count
        assert (out['pit_quarterly_roe_volatility'].item() is None) == (count == 11)


def test_monthly_anchor_freshness_and_missing_current_quarter() -> None:
    incomes, balances = [], []
    cumulative = 0.
    for i in range(13):
        end = period(2020 * 4 + i)
        cumulative = float(i + 1) if end.month == 3 else cumulative + i + 1
        item = row(end, end + dt.timedelta(days=20), cumulative)
        incomes.append(item)
        balances.append({k: v for k, v in item.items() if k != 'n_income_attr_p'}
                        | {'total_hldr_eqy_exc_min_int': 100.})
    incomes[-1]['n_income_attr_p'] = None
    args = dict(income_history=pl.DataFrame(incomes), balance_history=pl.DataFrame(balances),
                candidate_symbols=('000001.SZ',))
    result = build_monthly_quarterly_roe_stability(**args, signal_dates=(dt.date(2023, 4, 21),)).factors
    assert result['financial_period_end'].item() == dt.date(2023, 3, 31)
    assert result['valid_quarters'].item() == 12
    assert result['pit_quarterly_roe_volatility'].item() == pytest.approx(statistics.stdev(range(1, 13)) / 100)
    stale = build_monthly_quarterly_roe_stability(**args, signal_dates=(dt.date(2023, 10, 1),)).factors
    assert stale['pit_quarterly_roe_volatility'].item() is None

@pytest.mark.parametrize('equity', [0., -1., None, float('inf')])
def test_invalid_equity_does_not_count_as_valid_roe(equity: float | None) -> None:
    dates = [period(2020 * 4 + i) for i in range(12)]
    q = pl.DataFrame({'symbol': ['000001.SZ'] * 12, 'end_date': dates,
                      'single_parent_income': list(range(12))})
    b = q.select('symbol', 'end_date').with_columns(
        pl.Series('total_hldr_eqy_exc_min_int', [100.] * 11 + [equity]))
    out = compute_quarterly_roe_stability(q, b, q.select('symbol', 'end_date').tail(1))
    assert out['valid_quarters'].item() == 11
    assert out['pit_quarterly_roe_volatility'].item() is None


def test_late_predecessor_cannot_repair_earlier_successor() -> None:
    history = pl.DataFrame([row(dt.date(2023, 3, 31), dt.date(2023, 8, 21), 10.),
                            row(dt.date(2023, 6, 30), dt.date(2023, 8, 20), 30.)])
    selected, _ = select_quarterly_parent_income(history, as_of=dt.date(2023, 9, 2))
    assert selected.filter(pl.col('end_date') == dt.date(2023, 6, 30))['single_parent_income'].item() is None
