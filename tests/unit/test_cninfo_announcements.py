import datetime as dt

import polars as pl
import pytest
import requests

from quant.data import collect_financial_corrections as collector
from quant.data.connectors.cninfo_announcements import correction_pages

START = dt.date(2026, 9, 1)
END = dt.date(2026, 9, 10)


class Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class Session:
    def __init__(self, bodies):
        self.bodies = iter(bodies)
        self.pages = []
        self.parameters = []

    def post(self, url, **kwargs):
        self.pages.append(kwargs["data"]["pageNum"])
        self.parameters.append(kwargs["data"].copy())
        return Response(next(self.bodies))


def test_all_pages_and_empty_result():
    session = Session([
        {"totalAnnouncement": 2, "announcements": [{"announcementId": "a"}]},
        {"totalAnnouncement": 2, "announcements": [{"announcementId": "b"}]},
    ])
    assert len(list(correction_pages(START, END, session=session))) == 2
    assert session.pages == ["1", "2"]
    empty = Session([{"totalAnnouncement": 0, "announcements": None}])
    assert list(correction_pages(START, END, session=empty))[0][1] == []


def test_large_day_partitions_reconcile_full_exchange_union():
    from quant.data.connectors.cninfo_announcements import announcement_pages
    bodies=[{'totalAnnouncement':3001,'announcements':[]}]
    for prefix,count in [('sh',1000),('sz',1000),('bj',1001)]:
        for offset in range(0,count,30):
            bodies.append({'totalAnnouncement':count,'announcements':[
                {'announcementId':f'{prefix}{i}'} for i in range(offset,min(offset+30,count))]})
    session=Session(bodies)
    result=list(announcement_pages(START,END,category='fixed-category',searchkey='repurchase',session=session))
    assert [params['plate'] for params,_ in result]==['sh']*34+['sz']*34+['bj']*34
    assert sum(len(items) for _,items in result)==3001
    assert all(0 < len(items) <= 30 for _,items in result)
    for exchange in ('sh','sz','bj'):
        assert [p['pageNum'] for p in session.parameters if p['plate']==exchange] == [str(i) for i in range(1,35)]
    assert all(p['category']=='fixed-category' and p['searchkey']=='repurchase'
               and p['seDate']==f'{START}~{END}' for p in session.parameters)


def test_large_day_partition_overlap_is_rejected():
    from quant.data.connectors.cninfo_announcements import announcement_pages,AnnouncementSetChanged
    session=Session([
        {'totalAnnouncement':3001,'announcements':[]},
        {'totalAnnouncement':1,'announcements':[{'announcementId':'same'}]},
        {'totalAnnouncement':1,'announcements':[{'announcementId':'same'}]},
    ])
    with pytest.raises(AnnouncementSetChanged,match='overlap'):
        list(announcement_pages(START,END,category='',session=session))


def test_oversized_exchange_partition_fails_without_wrapping_or_accepting_partial_data():
    from quant.data.connectors.cninfo_announcements import announcement_pages
    session=Session([{'totalAnnouncement':3001,'announcements':[]}]*2)
    with pytest.raises(ValueError,match='partition exceeds paging limit'):
        list(announcement_pages(START,END,category='',session=session))
    assert [p['plate'] for p in session.parameters] == ['', 'sh']
    assert session.pages == ['1','1']


def test_large_day_partition_gap_rejected():
    from quant.data.connectors.cninfo_announcements import announcement_pages,AnnouncementSetChanged
    bodies=[{'totalAnnouncement':3001,'announcements':[]}]
    bodies += [{'totalAnnouncement':1,'announcements':[{'announcementId':prefix}]} for prefix in ('sh','sz','bj')]
    with pytest.raises(AnnouncementSetChanged,match='union'):
        list(announcement_pages(START,END,category='',session=Session(bodies)))


@pytest.mark.parametrize("second", [
    {"totalAnnouncement": 2, "announcements": []},
    {"totalAnnouncement": 2, "announcements": [{"announcementId": "a"}]},
    {"totalAnnouncement": 3, "announcements": [{"announcementId": "b"}]},
    {"announcements": []},
])
def test_incomplete_or_changing_pages_fail(second):
    session = Session([
        {"totalAnnouncement": 2, "announcements": [{"announcementId": "a"}]}, second,
    ])
    with pytest.raises(ValueError):
        list(correction_pages(START, END, session=session))


@pytest.mark.parametrize("second,match", [
    ({"totalAnnouncement": 2, "announcements": [{"announcementId": "a"}]}, "missing or repeated"),
    ({"totalAnnouncement": 2, "announcements": [{"announcementId": None}]}, "missing or repeated"),
    ({"totalAnnouncement": 2, "announcements": [{"announcementId": ""}]}, "missing or repeated"),
    ({"totalAnnouncement": 2, "announcements": [
        {"announcementId": "b"}, {"announcementId": "b"}]}, "missing or repeated"),
])
def test_missing_or_repeated_announcement_id_is_retryable_set_change(second, match):
    from quant.data.connectors.cninfo_announcements import AnnouncementSetChanged

    session = Session([
        {"totalAnnouncement": 2, "announcements": [{"announcementId": "a"}]}, second,
    ])
    with pytest.raises(AnnouncementSetChanged, match=match):
        list(correction_pages(START, END, session=session))


def test_raw_keeps_nonfinancial_rows_and_original_title(tmp_path, monkeypatch):
    rows = [
        {"announcementId": "a", "secCode": "002762",
         "announcementTitle": "2026年<em>半年度报告</em>更正公告"},
        {"announcementId": "b", "secCode": "000001", "announcementTitle": "董事更正公告"},
    ]
    monkeypatch.setattr(collector, "correction_pages", lambda *args: iter([({}, rows)]))
    result = collector.collect(START, END, tmp_path)
    assert result["rows"] == 2
    assert len(result["financial_title_candidates"]) == 1
    raw = pl.read_parquet(result["raw_paths"][0])
    assert raw.height == 2
    assert "<em>" in raw["announcementTitle"][0]


def test_transient_announcement_request_retries_same_page(monkeypatch):
    calls = []

    class RetrySession:
        def post(self, url, **kwargs):
            calls.append(kwargs['data']['pageNum'])
            if len(calls) == 1:
                raise requests.ConnectionError('temporary')
            return Response({'totalAnnouncement': 0, 'announcements': []})

    monkeypatch.setattr('quant.data.connectors.cninfo_announcements.time.sleep', lambda seconds: None)
    assert list(correction_pages(START, END, session=RetrySession()))[0][1] == []
    assert calls == ['1', '1']
def test_public_pdf_download_requires_bounded_document_path_and_pdf_bytes():
    from quant.data.connectors.cninfo_announcements import download_document

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        @property
        def headers(self):
            return {}

        def iter_content(self, chunk_size):
            yield b'%PDF-'
            yield b'fixture'

    class Session:
        def get(self, url, **kwargs):
            assert url == 'https://static.cninfo.com.cn/finalpage/2026-09-10/123.PDF'
            assert kwargs['stream'] and kwargs['timeout'] == 60
            return Response()

    assert download_document('finalpage/2026-09-10/123.PDF', session=Session()) == b'%PDF-fixture'
    with pytest.raises(ValueError, match='Unexpected'):
        download_document('https://elsewhere.example/file.pdf', session=Session())


def test_public_pdf_download_rejects_declared_and_streamed_oversized_documents():
    from quant.data.connectors.cninfo_announcements import (
        AnnouncementDocumentTooLarge,
        MAX_ANNOUNCEMENT_DOCUMENT_BYTES,
        download_document,
    )

    class DeclaredResponse:
        headers = {'Content-Length': str(MAX_ANNOUNCEMENT_DOCUMENT_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            raise AssertionError('must not stream after Content-Length rejects')

    class StreamResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b'%PDF-'
            yield b'x' * MAX_ANNOUNCEMENT_DOCUMENT_BYTES

    class Session:
        def __init__(self, response):
            self.response = response
            self.calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            return self.response

    declared = Session(DeclaredResponse())
    with pytest.raises(AnnouncementDocumentTooLarge, match='128 MiB'):
        download_document('finalpage/2026-09-10/123.PDF', session=declared)
    assert declared.calls == 1

    streamed = Session(StreamResponse())
    with pytest.raises(AnnouncementDocumentTooLarge, match='128 MiB'):
        download_document('finalpage/2026-09-10/123.PDF', session=streamed)
    assert streamed.calls == 1
