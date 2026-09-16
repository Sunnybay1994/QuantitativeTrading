import datetime as dt

import polars as pl
import pytest

from quant.reporting.period_metrics import period_metrics
from quant.research.capacity_limits import validate_capitals


def nav(dates, values, holdings=None):
    frame = pl.DataFrame({'date': [dt.date.fromisoformat(d) for d in dates], 'unit_nav': values})
    return frame.with_columns(pl.Series('market_value', holdings)) if holdings else frame


def test_month_boundary_keeps_first_day_loss_and_compounds():
    frame = nav(['2025-12-31', '2026-01-02', '2026-01-05', '2026-02-02'], [1., .9, .99, 1.089])
    bench = nav(['2025-12-31', '2026-01-02', '2026-01-05', '2026-02-02'], [1., 1., 1., 1.])
    rows = period_metrics(frame, {'flat': bench})
    jan = next(r for r in rows if r['period'] == '2026-01')
    feb = next(r for r in rows if r['period'] == '2026-02')
    year = next(r for r in rows if r['period'] == '2026')
    assert jan['total_return'] == pytest.approx(-.01)
    assert jan['max_drawdown'] == pytest.approx(-.1)
    assert jan['sharpe'] == pytest.approx(0., abs=1e-10)
    assert jan['benchmark_results'][0]['excess_return'] == pytest.approx(-.01)
    assert (1+jan['total_return'])*(1+feb['total_return']) == pytest.approx(1+year['total_return'])
    assert feb['sharpe'] is None


def test_missing_benchmark_does_not_shrink_strategy_window():
    frame = nav(['2026-01-02', '2026-01-05'], [.9, 1.])
    rows = period_metrics(frame, {'missing': frame.tail(1)})
    assert rows[0]['sessions'] == 2
    assert rows[0]['benchmark_results'][0]['excess_return'] is None


def test_initial_cash_excluded_later_cash_kept():
    frame = nav(['2025-12-31', '2026-01-02', '2026-01-05'], [1., .9, .8], [0., 80., 0.])
    rows = period_metrics(frame, {})
    assert len(rows) == 2
    assert rows[0]['sessions'] == 2
    assert rows[0]['max_drawdown'] == pytest.approx(-.2)
    assert period_metrics(frame.with_columns(pl.lit(0.).alias('market_value')), {}) == []


@pytest.mark.parametrize('values', [[], [50000], [100000, 100000], [100000, 1000000, 5000000], [100000.0]])
def test_reject_other_capital_grids(values):
    with pytest.raises(ValueError, match='capital tiers'):
        validate_capitals(values)


def test_accept_two_or_one_capital_tiers():
    validate_capitals([100000, 1000000])
    validate_capitals([100000])


def test_html_download_escapes_description_and_contains_both_frequencies():
    from quant.reporting.period_metrics import render_html
    frame = nav(['2026-01-02', '2026-01-05'], [.9, 1.])
    report = {'label': 'test', 'description': '<script>bad</script>', 'capital': 100000,
              'currency': 'CNY', 'note': 'rf=0', 'excluded': [], 'sources': ['saved/nav.parquet'],
              'rows': period_metrics(frame, {'base': frame})}
    html = render_html(report, 'base')
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '<h2>年度</h2>' in html and '<h2>月度</h2>' in html
    assert 'saved/nav.parquet' in html and '100000 CNY' in html
