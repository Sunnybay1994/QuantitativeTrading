import datetime as dt

from quant.data.collect_financial_disclosures import report_requests
from quant.data import collect_financial_disclosures as collector


def test_disclosure_titles_deduplicate_reports_and_keep_unresolved_periods():
    day = dt.date(2026, 9, 10)
    timestamp = int(dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc).timestamp()*1000)
    titles = ['2026年半年度报告', '2026年<em>半年度报告</em>更正公告',
              '2025年年度报告与2026年第一季度报告更正公告',
              '2026年第三季度报告', '关于财务报表的更正公告', '董事变更公告']
    rows = [{'secCode': '600000', 'announcementId': str(i), 'announcementTime': timestamp,
             'announcementTitle': title} for i, title in enumerate(titles)]
    result = report_requests(rows, start=day, end=day)
    assert result['requests'] == [{'symbol': '600000.SH', 'period': period}
                                   for period in ('2025-12-31', '2026-03-31', '2026-06-30')]
    assert len(result['announcements']) == 4
    assert {row['reason'] for row in result['unresolved']} == {
        'report_period_after_publication', 'report_period_not_explicit_in_title'}


def test_financial_candidate_requires_publication_time_and_supported_stock():
    rows = [{'secCode': code, 'announcementId': code, 'announcementTitle': '２０２６年半年度报告'}
            for code in ('000333', '430001', '900001')]
    result = report_requests(rows, start=dt.date(2026, 9, 1), end=dt.date(2026, 9, 10))
    assert not result['requests']
    assert [row['symbol'] for row in result['unresolved']] == ['000333.SZ']


def test_observed_halfyear_title_variants_and_investor_meetings():
    day = dt.date(2026, 9, 10)
    stamp = int(dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc).timestamp()*1000)
    titles = ['公司财务报表及审阅报告(2026年1月-6月)',
              '财务报告及审计报告(2026年半年报财务数据更新版本)',
              '关于举行2026年半年度报告网上业绩说明会的公告']
    rows = [{'secCode': '600000', 'announcementId': str(i), 'announcementTime': stamp,
             'announcementTitle': title} for i, title in enumerate(titles)]
    result = report_requests(rows, start=day, end=day)
    assert result['requests'] == [{'symbol': '600000.SH', 'period': '2026-06-30'}]
    assert len(result['announcements']) == 2 and not result['unresolved']


def test_collector_splits_days_before_pagination_and_reuses_completed_scan(tmp_path, monkeypatch):
    calls = []

    def pages(start, end, *, category):
        assert start == end and category == ''
        calls.append(start)
        stamp = int(dt.datetime.combine(start, dt.time(), tzinfo=dt.timezone.utc).timestamp()*1000)
        yield {'day': str(start)}, [{'secCode': '600000', 'announcementId': str(start),
            'announcementTime': stamp, 'announcementTitle': '2026年半年度报告'}]

    monkeypatch.setattr(collector, 'announcement_pages', pages)
    args = dict(start=dt.date(2026, 9, 8), end=dt.date(2026, 9, 10), data_root=tmp_path,
                output=tmp_path/'scan')
    result = collector.collect(**args)
    assert len(calls) == 3 and result['source_rows'] == 3 and len(result['requests']) == 1
    assert collector.collect(**args) == result and len(calls) == 3
