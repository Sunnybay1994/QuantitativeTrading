import datetime as dt

import polars as pl

from quant.execution.shadow_data_gaps import summarize_gaps
from quant.reporting.daily_attention import attention


def test_shared_account_views_are_one_source_gap_and_not_retried():
    detail = pl.DataFrame({'asset_type': ['etf']*2, 'symbol': ['510300.SH']*2,
        'execution_date': [dt.date(2026, 9, 10)]*2, 'horizon': ['vwap_5m']*2,
        'reason': ['missing_or_invalid_minute_turnover']*2, 'account': ['a', 'b'], 'status': ['missing']*2})
    gaps, summary = summarize_gaps(detail)
    assert gaps.height == 1 and summary['missing_observations'] == 2
    assert gaps['same_source_retry_useful'].to_list() == [False]
    assert summary['resolved'] is False
    daily = {'stages': {'forward_tracking': {'status': 'complete', 'result': {'requires_review': True,
        'shadow': {'missing_horizons': 2, 'data_gaps': summary}}}}}
    assert '重复抓取同源数据不能补齐' in attention(daily)[0]['action']


def test_no_trade_is_not_assumed_to_be_source_failure_or_suspension():
    detail = pl.DataFrame({'asset_type': ['etf'], 'symbol': ['510300.SH'],
        'execution_date': [dt.date(2026, 9, 10)], 'horizon': ['vwap_5m'],
        'reason': ['no_traded_volume'], 'account': ['a'], 'status': ['missing']})
    gaps, summary = summarize_gaps(detail)
    assert gaps['gap_class'].to_list() == ['no_trade_observed']
    assert gaps['same_source_retry_useful'].to_list() == [None]
    assert summary['resolved'] is False
