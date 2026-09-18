from quant.reporting.daily_attention import attention


def test_local_source_failure_explained_without_treating_it_as_order():
    shadow = {'missing_horizons': 18, 'observed_horizons': 446, 'local_minute_recovery': [
        {'symbol': '510300.SH', 'date': '2026-09-10', 'status': 'recovered'},
        {'symbol': '511010.SH', 'date': '2026-09-10', 'status': 'unavailable',
         'reason': 'ValueError: Turnover units inconsistent with bar prices'}]}
    daily = {'stages': {'forward_tracking': {'status': 'complete',
             'result': {'requires_review': True, 'shadow': shadow}}}}
    rows = attention(daily)
    assert len(rows) == 2
    assert '511010.SH' in rows[1]['reason'] and '隐含价格' in rows[1]['reason']
    assert '无需下单' in rows[1]['action']
