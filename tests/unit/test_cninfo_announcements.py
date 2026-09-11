import datetime as dt

import polars as pl
import pytest

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

    def post(self, url, **kwargs):
        self.pages.append(kwargs["data"]["pageNum"])
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
