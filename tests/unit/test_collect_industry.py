from pathlib import Path

import polars as pl
import pytest

from quant.data.collect_industry import collect_industry
from quant.data.connectors.tushare import TushareConnector


class FixtureConnector(TushareConnector):
    def __init__(self, *, repeat: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.repeat = repeat

    def query_raw(self, api_name: str, **params: str) -> pl.DataFrame:
        self.calls.append((api_name, params))
        if api_name == "index_classify":
            return pl.DataFrame({"index_code": ["851911.SI"]})
        if params["is_new"] == "N":
            return pl.DataFrame()
        offset = 0 if self.repeat else int(params["offset"])
        return pl.DataFrame({"con_code": ["000001.SZ", "600000.SH", "600036.SH"][offset:offset + 2]})


def test_pages_current_retired_and_resume(tmp_path: Path) -> None:
    client = FixtureConnector()
    result = collect_industry(tmp_path, connector=client, pause_seconds=0, page_size=2)
    assert result["member_rows"] == 3
    assert result["network_requests"] == 9
    assert client.calls[-1][1]["is_new"] == "N"
    before = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    client.calls.clear()
    resumed = collect_industry(tmp_path, connector=client, pause_seconds=0, page_size=2)
    assert resumed["network_requests"] == 0 and client.calls == []
    assert resumed["member_rows"] == 3
    assert before == {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}


def test_supplier_ignoring_offset_is_not_silent_truncation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repeated a full page"):
        collect_industry(tmp_path, connector=FixtureConnector(repeat=True),
                         pause_seconds=0, page_size=2)


def test_transient_connection_error_retries_without_replacing_saved_pages(tmp_path: Path) -> None:
    class FlakyConnector(FixtureConnector):
        failed = False

        def query_raw(self, api_name: str, **params: str) -> pl.DataFrame:
            if api_name == "index_member" and not self.failed:
                self.failed = True
                raise ConnectionError("temporary disconnection")
            return super().query_raw(api_name, **params)

    result = collect_industry(tmp_path, connector=FlakyConnector(), pause_seconds=0, page_size=2)
    assert result["member_rows"] == 3
    assert result["network_requests"] == 10
