import datetime as dt

import pytest

from quant.data.connectors.hkex_shareholding import parse_holdings


def page(percent='11.81%'):
    return '<span>Shareholding Date: 2026/09/10</span><table><tr><th class="col-stock-code">Code</th></tr>' + (
        '<tr><td class="col-stock-code"><div class="mobile-list-body">700</div></td>'
        '<td><div class="mobile-list-body">Tencent</div></td>'
        '<td><div class="mobile-list-body">1,075,865,691</div></td>'
        f'<td><div class="mobile-list-body">{percent}</div></td></tr></table>')


def test_hkex_shares_and_percent_units_preserve_missingness():
    frame = parse_holdings(page(), expected_date=dt.date(2026, 9, 10))
    assert frame['symbol'].item() == '00700.HK'
    assert frame['shares'].item() == 1075865691
    assert frame['issued_share_percent'].item() == 11.81
    assert parse_holdings(page(''))['issued_share_percent'].item() is None


def test_hkex_rejects_date_fallback_and_invalid_percent():
    with pytest.raises(ValueError, match='different shareholding date'):
        parse_holdings(page(), expected_date=dt.date(2017, 3, 17))
    with pytest.raises(ValueError, match='Invalid HKEX holding values'):
        parse_holdings(page('101%'))
