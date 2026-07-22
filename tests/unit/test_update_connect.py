"""update_connect CLI：--replace-clean 契约与无副作用失败。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from quant.data import update_connect
from quant.data.storage import CleanConnectEventStore
from quant.data.update_connect import build_parser, main


def _sse_event_raw() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "VALID_DATE": ["2026-07-10"],
            "SECURITY_CODE": ["00700"],
            "ADJUST_TYPE": ["调进"],
            "SECURITY_ABBR": ["腾讯控股"],
            "ABBR_EN": ["TENCENT"],
            "SECURITY_TYPE": ["股票"],
            "FILE_DATE": ["2026-07-09"],
        }
    )


class _FakeConnector:
    source = "sse"
    route = "SH_CONNECT"

    def fetch_eligibility_events(self) -> pl.DataFrame:
        return _sse_event_raw()


def test_parser_accepts_replace_clean_flag() -> None:
    args = build_parser().parse_args(
        ["--route", "SH_CONNECT", "--table", "events", "--replace-clean"]
    )
    assert args.replace_clean is True
    default = build_parser().parse_args(["--route", "SH_CONNECT", "--table", "events"])
    assert default.replace_clean is False


@pytest.mark.parametrize("table", ["snapshot", "calendar"])
def test_replace_clean_rejects_non_events_before_connector_or_fs(
    table: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("connector must not be constructed")

    monkeypatch.setattr(update_connect, "SseConnectConnector", boom)
    monkeypatch.setattr(update_connect, "SzseConnectConnector", boom)

    argv = [
        "--route",
        "SH_CONNECT",
        "--table",
        table,
        "--replace-clean",
        "--data-root",
        str(tmp_path),
    ]
    if table == "calendar":
        argv.extend(["--start", "2026-01-01", "--end", "2026-12-31"])
    with pytest.raises(ValueError, match="--replace-clean 只允许与 --table events 同用"):
        main(argv)
    assert list(tmp_path.iterdir()) == []


def test_default_events_cli_reports_upsert_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(update_connect, "SseConnectConnector", lambda: _FakeConnector())
    code = main(
        ["--route", "SH_CONNECT", "--table", "events", "--data-root", str(tmp_path)]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["clean_mode"] == "UPSERT"
    assert payload["clean_rows"] == 1
    assert "token" not in json.dumps(payload).lower()


def test_replace_clean_events_cli_reports_replace_route_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = CleanConnectEventStore(tmp_path / "clean" / "connect_event")
    store.upsert(
        pl.DataFrame(
            {
                "route": ["SH_CONNECT"],
                "effective_date": [dt.date(2026, 7, 10)],
                "symbol": ["00700.HK"],
                "action": ["REMOVE"],
                "name_cn": ["腾讯控股"],
                "name_en": ["TENCENT"],
                "security_type": ["STOCK"],
                "published_date": [dt.date(2026, 7, 9)],
                "source": ["sse"],
            }
        )
    )
    monkeypatch.setattr(update_connect, "SseConnectConnector", lambda: _FakeConnector())
    code = main(
        [
            "--route",
            "SH_CONNECT",
            "--table",
            "events",
            "--replace-clean",
            "--data-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["clean_mode"] == "REPLACE_ROUTE"
    assert payload["clean_rows"] == 1
    written = pl.read_parquet(
        tmp_path / "clean" / "connect_event" / "route=SH_CONNECT" / "data.parquet"
    )
    assert written.get_column("action").to_list() == ["ADD"]
    assert (tmp_path / "raw").exists()
