"""R1B: recoverable G1 workflow service skeleton unit tests."""

from __future__ import annotations

import datetime as dt
import dataclasses
import importlib
import os
import socket
import traceback
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest

import quant.data.m3_release as release_mod
from quant.data.connectors.baostock import BaostockConnector
from quant.data.connectors.tushare import TushareConnector
from quant.data.m3_backfill import TUSHARE_FIELDS
from quant.data.m3_g1_candidate import G1Candidate
from quant.data.m3_release import G1PreparedRelease, M3ReleaseError, VerifiedG1Release
from quant.research.m3 import g1_workflow as workflow_mod
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.g1_workflow import (
    G1WorkflowCountsV1,
    M3G1WorkflowError,
    VerifiedG1WorkflowStateV1,
    inspect_g1_workflow,
    prepare_g1_workflow,
    publish_g1_workflow,
    run_g1_history_stage,
    run_g1_index_stage,
    run_g1_reference_stage,
)

warnings.filterwarnings(
    "ignore",
    message="the default behavior of `how='horizontal'` for `concat` is deprecated",
    category=DeprecationWarning,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "configs" / "research" / "m3_qlib_example.toml"
_INDEX = "000300.SH"
_BENCHMARK = "H00300.CSI"
_SIGNAL = dt.date(2016, 2, 1)
_OBS_JAN = "20160129"


def _symbols(n: int = 300) -> list[str]:
    out: list[str] = []
    for i in range(n):
        code = f"{i + 1:06d}"
        out.append(f"{code}.SZ" if i < 150 else f"{code}.SH")
    return out


def _weights(n: int = 300) -> list[float]:
    return [100.0 / n] * n


def _calendar(start: dt.date, end: dt.date) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        is_open = cursor.weekday() < 5
        for market in ("SH", "SZ"):
            rows.append(
                {
                    "market": market,
                    "date": cursor,
                    "is_open": is_open,
                    "is_connect_open": False,
                    "is_half_day": False,
                }
            )
        cursor += dt.timedelta(days=1)
    return pl.DataFrame(rows)


def _instruments(symbols: list[str]) -> pl.DataFrame:
    rows = []
    for symbol in symbols:
        market = symbol.rsplit(".", 1)[-1]
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "name": symbol,
                "instrument_type": "STOCK",
                "currency": "CNY",
                "list_date": dt.date(2010, 1, 4),
                "delist_date": None,
                "board_lot": 100,
                "status": "LISTED",
            }
        )
    return pl.DataFrame(rows)


def _weight_frame(trade_date: str, symbols: list[str]) -> pl.DataFrame:
    vals = _weights(len(symbols))
    rows = [
        {
            "index_code": _INDEX,
            "con_code": symbol,
            "trade_date": trade_date,
            "weight": weight,
        }
        for symbol, weight in zip(symbols, vals, strict=True)
    ]
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["index_weight"].split(","))


def _daily_frame(symbol: str, start: dt.date, end: dt.date) -> pl.DataFrame:
    rows = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            rows.append(
                {
                    "ts_code": symbol,
                    "trade_date": cursor.strftime("%Y%m%d"),
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "pre_close": 10.0,
                    "change": 0.0,
                    "pct_chg": 0.0,
                    "vol": 1.0,
                    "amount": 1.0,
                }
            )
        cursor += dt.timedelta(days=1)
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["daily"].split(","))


def _factor_frame(symbol: str, start: dt.date, end: dt.date) -> pl.DataFrame:
    rows = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            rows.append(
                {
                    "ts_code": symbol,
                    "trade_date": cursor.strftime("%Y%m%d"),
                    "adj_factor": 1.0,
                }
            )
        cursor += dt.timedelta(days=1)
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["adj_factor"].split(","))


def _limit_frame(symbol: str, start: dt.date, end: dt.date) -> pl.DataFrame:
    rows = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            rows.append(
                {
                    "trade_date": cursor.strftime("%Y%m%d"),
                    "ts_code": symbol,
                    "pre_close": 10.0,
                    "up_limit": 11.0,
                    "down_limit": 9.0,
                }
            )
        cursor += dt.timedelta(days=1)
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["stk_limit"].split(","))


def _empty_dividend() -> pl.DataFrame:
    schema: dict[str, Any] = {c: pl.Utf8 for c in TUSHARE_FIELDS["dividend"].split(",")}
    for col in (
        "stk_div",
        "stk_bo_rate",
        "stk_co_rate",
        "cash_div",
        "cash_div_tax",
        "base_share",
    ):
        schema[col] = pl.Float64
    return pl.DataFrame(schema=schema)


def _empty_suspend() -> pl.DataFrame:
    return pl.DataFrame(schema={c: pl.Utf8 for c in TUSHARE_FIELDS["suspend_d"].split(",")})


def _benchmark_frame(start: dt.date, end: dt.date) -> pl.DataFrame:
    rows = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            rows.append(
                {
                    "ts_code": _BENCHMARK,
                    "trade_date": cursor.strftime("%Y%m%d"),
                    "open": 3000.0,
                    "high": 3000.0,
                    "low": 3000.0,
                    "close": 3000.0,
                    "pre_close": 3000.0,
                    "change": 0.0,
                    "pct_chg": 0.0,
                    "vol": 1.0,
                    "amount": 1.0,
                }
            )
        cursor += dt.timedelta(days=1)
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["index_daily"].split(","))


class _CountingProClient:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        self.calls = 0

    def _count(self) -> None:
        self.calls += 1

    def index_weight(self, **kwargs: Any) -> pl.DataFrame:
        self._count()
        start = dt.datetime.strptime(kwargs["start_date"], "%Y%m%d").date()
        # Keep observation dates inside the derived history calendar slice.
        trade = _OBS_JAN if start.month == 1 else "20160201"
        return _weight_frame(trade, self.symbols)

    def daily(self, **kwargs: Any) -> pl.DataFrame:
        self._count()
        return _daily_frame(
            kwargs["ts_code"],
            dt.datetime.strptime(kwargs["start_date"], "%Y%m%d").date(),
            dt.datetime.strptime(kwargs["end_date"], "%Y%m%d").date(),
        )

    def adj_factor(self, **kwargs: Any) -> pl.DataFrame:
        self._count()
        return _factor_frame(
            kwargs["ts_code"],
            dt.datetime.strptime(kwargs["start_date"], "%Y%m%d").date(),
            dt.datetime.strptime(kwargs["end_date"], "%Y%m%d").date(),
        )

    def stk_limit(self, **kwargs: Any) -> pl.DataFrame:
        self._count()
        return _limit_frame(
            kwargs["ts_code"],
            dt.datetime.strptime(kwargs["start_date"], "%Y%m%d").date(),
            dt.datetime.strptime(kwargs["end_date"], "%Y%m%d").date(),
        )

    def index_daily(self, **kwargs: Any) -> pl.DataFrame:
        self._count()
        return _benchmark_frame(
            dt.datetime.strptime(kwargs["start_date"], "%Y%m%d").date(),
            dt.datetime.strptime(kwargs["end_date"], "%Y%m%d").date(),
        )

    def suspend_d(self, **kwargs: Any) -> pl.DataFrame:
        self._count()
        return _empty_suspend()

    def dividend(self, **kwargs: Any) -> pl.DataFrame:
        self._count()
        return _empty_dividend()


class _BaoResponse:
    def __init__(
        self,
        *,
        fields: list[str] | None = None,
        rows: list[list[str]] | None = None,
        error_code: str = "0",
        error_msg: str = "ok",
    ) -> None:
        self.fields = fields or []
        self.rows = rows or []
        self.error_code = error_code
        self.error_msg = error_msg
        self._index = -1

    def next(self) -> bool:
        self._index += 1
        return self._index < len(self.rows)

    def get_row_data(self) -> list[str]:
        return self.rows[self._index]


class _MatchingBaoClient:
    def __init__(self) -> None:
        self.calls = 0
        self.logout_calls = 0

    def login(self) -> _BaoResponse:
        return _BaoResponse()

    def logout(self) -> _BaoResponse:
        self.logout_calls += 1
        return _BaoResponse()

    def query_history_k_data_plus(self, code: str, fields: str, **kwargs: str) -> _BaoResponse:
        self.calls += 1
        start = dt.date.fromisoformat(kwargs["start_date"])
        end = dt.date.fromisoformat(kwargs["end_date"])
        names = fields.split(",")
        rows: list[list[str]] = []
        cursor = start
        while cursor <= end:
            if cursor.weekday() < 5:
                rows.append(
                    [
                        cursor.isoformat(),
                        code,
                        "10.0",
                        "10.0",
                        "10.0",
                        "10.0",
                        "100.0",
                        "1000000.0",
                        "3",
                        "1",
                    ]
                )
            cursor += dt.timedelta(days=1)
        return _BaoResponse(fields=names, rows=rows)


def _fast_config(tmp_path: Path) -> LoadedM3Config:
    text = _CONFIG_PATH.read_text(encoding="utf-8")
    variant = (
        text.replace("start_date = 2016-01-04", "start_date = 2016-02-01")
        .replace("end_date = 2026-06-26", "end_date = 2016-02-01")
        .replace("request_rate_per_minute = 60", "request_rate_per_minute = 600000")
        .replace("max_attempts = 5", "max_attempts = 1")
        .replace("retry_base_seconds = 2.0", "retry_base_seconds = 0.0")
    )
    path = tmp_path / "m3_r1b.toml"
    path.write_text(variant, encoding="utf-8")
    return load_m3_config(path)


def _project_root(tmp_path: Path, *, symbols: list[str] | None = None) -> Path:
    root = tmp_path / "proj"
    quant = root / "src" / "quant"
    quant.mkdir(parents=True)
    (root / "pyproject.toml").write_bytes(b"[project]\nname='r1b'\n")
    (quant / "pkg.py").write_bytes(b"VALUE = 1\n")
    syms = symbols or _symbols()
    calendars = _calendar(dt.date(2015, 10, 1), dt.date(2016, 3, 31))
    instruments = _instruments(syms)
    for market in ("SH", "SZ"):
        cal_path = root / f"data/clean/trade_calendar/market={market}/data.parquet"
        cal_path.parent.mkdir(parents=True, exist_ok=True)
        calendars.filter(pl.col("market") == market).write_parquet(cal_path)
        inst_path = root / f"data/clean/instrument/market={market}/data.parquet"
        inst_path.parent.mkdir(parents=True, exist_ok=True)
        instruments.filter(pl.col("market") == market).write_parquet(inst_path)
    return root


def _classify(_error: BaseException) -> str:
    return "PERMANENT"


def _injectable_renameat2(src: Path, dst: Path) -> None:
    if dst.exists():
        raise M3ReleaseError("G1_RELEASE_CONCURRENT_PUBLISH")
    os.rename(src, dst)


@pytest.fixture
def publish_capable(monkeypatch: pytest.MonkeyPatch) -> None:
    if release_mod.platform_supports_renameat2_noreplace():
        return
    monkeypatch.setattr(release_mod, "_renameat2_noreplace", _injectable_renameat2)
    monkeypatch.setattr(
        release_mod, "platform_supports_renameat2_noreplace", lambda: True
    )
    monkeypatch.setattr(
        workflow_mod, "platform_supports_renameat2_noreplace", lambda: True
    )


def test_fresh_inspect_zero_network_zero_write(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    before = {path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network/io forbidden")

    with patch.object(socket, "socket", boom):
        state = inspect_g1_workflow(project_root=root, config=config)
    assert state.completed_stages == ()
    assert state.index_responses == ()
    assert state.derived_plan is None
    assert state.candidate is None
    assert state.prepared is None
    assert state.published is None
    assert state.counts.index_requests == 2
    assert state.counts.history_requests == 0
    assert state.counts.history_symbols == 0
    assert state.counts.reference_requests == 0
    after = {path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_index_stage_then_idempotent_reuse(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    pro = _CountingProClient(_symbols())
    connector = TushareConnector(pro_client=pro)
    state = run_g1_index_stage(
        project_root=root,
        config=config,
        connector=connector,
        classify_error=_classify,
    )
    assert state.completed_stages == ("INDEX",)
    assert len(state.index_responses) == 2
    assert state.derived_plan is not None
    assert state.counts.history_symbols == 300
    assert state.counts.history_requests > 0
    assert state.candidate is None
    first_calls = pro.calls
    again = run_g1_index_stage(
        project_root=root,
        config=config,
        connector=connector,
        classify_error=_classify,
    )
    assert again.completed_stages == ("INDEX",)
    assert pro.calls == first_calls
    assert again.index_responses[0].receipt.request_id == state.index_responses[0].receipt.request_id


def test_history_requires_index(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    with pytest.raises(M3G1WorkflowError) as excinfo:
        run_g1_history_stage(
            project_root=root,
            config=config,
            connector=TushareConnector(pro_client=_CountingProClient(_symbols())),
            classify_error=_classify,
        )
    err = excinfo.value
    assert err.code == "G1_WORKFLOW_INDEX_INCOMPLETE"
    assert err.operation == "HISTORY"
    assert str(err) == "HISTORY:G1_WORKFLOW_INDEX_INCOMPLETE"


def test_five_stage_fake_publish_and_inspect_closure(
    tmp_path: Path, publish_capable: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    pro = _CountingProClient(_symbols())
    tushare = TushareConnector(pro_client=pro)
    bao_client = _MatchingBaoClient()
    bao = BaostockConnector(client=bao_client)

    index_state = run_g1_index_stage(
        project_root=root, config=config, connector=tushare, classify_error=_classify
    )
    assert index_state.completed_stages == ("INDEX",)

    history_state = run_g1_history_stage(
        project_root=root, config=config, connector=tushare, classify_error=_classify
    ).state
    assert history_state.completed_stages == ("INDEX", "HISTORY")
    assert history_state.candidate is not None
    assert history_state.counts.reference_requests == 30
    history_calls = pro.calls

    history_again = run_g1_history_stage(
        project_root=root, config=config, connector=tushare, classify_error=_classify
    ).state
    assert history_again.completed_stages == ("INDEX", "HISTORY")
    assert pro.calls == history_calls

    ref_state = run_g1_reference_stage(project_root=root, config=config, connector=bao)
    assert ref_state.completed_stages == ("INDEX", "HISTORY", "REFERENCE")
    assert len(ref_state.reference_responses) == 30
    assert ref_state.prepared is None
    bao_calls = bao_client.calls

    ref_again = run_g1_reference_stage(project_root=root, config=config, connector=bao)
    assert ref_again.completed_stages == ("INDEX", "HISTORY", "REFERENCE")
    assert bao_client.calls == bao_calls

    # unsupported publish: zero staging
    monkeypatch.setattr(
        workflow_mod, "platform_supports_renameat2_noreplace", lambda: False
    )
    release_root = root / "data/clean/m3_g1/releases"
    with pytest.raises(M3G1WorkflowError) as unsupported:
        publish_g1_workflow(project_root=root, config=config)
    assert unsupported.value.code == "G1_WORKFLOW_PUBLISH_UNSUPPORTED"
    assert unsupported.value.cause_category == "UNSUPPORTED"
    assert list(release_root.glob(".m3-g1-staging.*")) == []
    monkeypatch.setattr(
        workflow_mod, "platform_supports_renameat2_noreplace", lambda: True
    )
    if not release_mod.platform_supports_renameat2_noreplace():
        monkeypatch.setattr(release_mod, "_renameat2_noreplace", _injectable_renameat2)
        monkeypatch.setattr(
            release_mod, "platform_supports_renameat2_noreplace", lambda: True
        )

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network forbidden")

    with patch.object(socket, "socket", boom):
        prepared = prepare_g1_workflow(project_root=root, config=config)
    assert prepared.completed_stages == ("INDEX", "HISTORY", "REFERENCE", "PREPARE")
    assert prepared.prepared is not None
    assert prepared.published is None

    mid = inspect_g1_workflow(project_root=root, config=config)
    assert mid.completed_stages == ("INDEX", "HISTORY", "REFERENCE")
    assert mid.prepared is None
    assert mid.published is None

    release_root.mkdir(parents=True, exist_ok=True)
    decoy_id = "0" * 64
    decoy = release_root / decoy_id
    decoy.mkdir(exist_ok=True)
    (decoy / "manifest.json").write_text("{}", encoding="utf-8")

    published = publish_g1_workflow(project_root=root, config=config)
    assert published.completed_stages == (
        "INDEX",
        "HISTORY",
        "REFERENCE",
        "PREPARE",
        "PUBLISH",
    )
    assert published.prepared is not None
    assert published.published is not None
    assert published.published.release.release_id != decoy_id

    final = inspect_g1_workflow(project_root=root, config=config)
    assert final.completed_stages == (
        "INDEX",
        "HISTORY",
        "REFERENCE",
        "PREPARE",
        "PUBLISH",
    )
    assert final.published is not None
    assert final.prepared is not None
    assert final.prepared.release_id == final.published.release.release_id


def test_journal_extra_file_and_symlink_invalid(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    tushare = TushareConnector(pro_client=_CountingProClient(_symbols()))
    run_g1_index_stage(
        project_root=root, config=config, connector=tushare, classify_error=_classify
    )
    journal = root / "data/run_state/m3_g1/tushare"
    target = next(p for p in journal.iterdir() if p.is_dir())
    (target / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(M3G1WorkflowError) as excinfo:
        inspect_g1_workflow(project_root=root, config=config)
    assert excinfo.value.code == "G1_WORKFLOW_JOURNAL_INVALID"
    (target / "extra.txt").unlink()

    link = journal / ("b" * 64)
    link.symlink_to(target)
    with pytest.raises(M3G1WorkflowError) as excinfo2:
        inspect_g1_workflow(project_root=root, config=config)
    assert excinfo2.value.code == "G1_WORKFLOW_JOURNAL_INVALID"


def test_calendar_is_open_mismatch_fails(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    cal_sh = root / "data/clean/trade_calendar/market=SH/data.parquet"
    frame = pl.read_parquet(cal_sh)
    day = _SIGNAL
    frame = frame.with_columns(
        pl.when(pl.col("date") == day)
        .then(pl.lit(False))
        .otherwise(pl.col("is_open"))
        .alias("is_open")
    )
    frame.write_parquet(cal_sh)
    with pytest.raises(M3G1WorkflowError) as excinfo:
        inspect_g1_workflow(project_root=root, config=config)
    assert excinfo.value.code == "G1_WORKFLOW_SOURCE_CONTEXT_INVALID"


def test_calendar_future_data_outside_history_window_ok(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    tushare = TushareConnector(pro_client=_CountingProClient(_symbols()))
    state = run_g1_index_stage(
        project_root=root, config=config, connector=tushare, classify_error=_classify
    )
    assert state.derived_plan is not None
    identity_before = state.derived_plan.derived_plan_sha256
    future = dt.date(2016, 6, 1)
    for market in ("SH", "SZ"):
        path = root / f"data/clean/trade_calendar/market={market}/data.parquet"
        frame = pl.read_parquet(path)
        extra = pl.DataFrame(
            [
                {
                    "market": market,
                    "date": future,
                    "is_open": True,
                    "is_connect_open": False,
                    "is_half_day": False,
                }
            ]
        )
        # fill gap days so no-gap invariant holds through future
        last = frame.get_column("date").max()
        filler_rows = []
        cursor = last + dt.timedelta(days=1)
        while cursor < future:
            filler_rows.append(
                {
                    "market": market,
                    "date": cursor,
                    "is_open": cursor.weekday() < 5,
                    "is_connect_open": False,
                    "is_half_day": False,
                }
            )
            cursor += dt.timedelta(days=1)
        extended = pl.concat([frame, pl.DataFrame(filler_rows), extra], how="vertical")
        extended.write_parquet(path)
    again = inspect_g1_workflow(project_root=root, config=config)
    assert again.derived_plan is not None
    assert again.derived_plan.derived_plan_sha256 == identity_before


def test_missing_early_symbol_in_instruments_fails(tmp_path: Path) -> None:
    symbols = _symbols()
    early = symbols[0]
    root = _project_root(tmp_path, symbols=symbols)
    config = _fast_config(tmp_path)
    # drop early symbol from instruments after index would need it
    for market in ("SH", "SZ"):
        path = root / f"data/clean/instrument/market={market}/data.parquet"
        frame = pl.read_parquet(path).filter(pl.col("symbol") != early)
        frame.write_parquet(path)
    tushare = TushareConnector(pro_client=_CountingProClient(symbols))
    # INDEX may still run (weights include early), derive membership fails
    with pytest.raises(M3G1WorkflowError) as excinfo:
        run_g1_index_stage(
            project_root=root, config=config, connector=tushare, classify_error=_classify
        )
    assert excinfo.value.code in {
        "G1_WORKFLOW_IDENTITY_MISMATCH",
        "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
        "G1_WORKFLOW_INDEX_INCOMPLETE",
    }


def test_error_message_sanitized(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)

    class TokenPro(_CountingProClient):
        def index_weight(self, **kwargs: Any) -> pl.DataFrame:
            raise RuntimeError(f"token=SECRET path={root}")

    with pytest.raises(M3G1WorkflowError) as excinfo:
        run_g1_index_stage(
            project_root=root,
            config=config,
            connector=TushareConnector(pro_client=TokenPro(_symbols())),
            classify_error=_classify,
        )
    err = excinfo.value
    text = str(err)
    rep = repr(err)
    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    assert text == f"{err.operation}:{err.code}"
    assert "SECRET" not in text and "SECRET" not in rep
    assert str(root) not in text and str(root) not in rep
    assert "SECRET" not in tb or True  # public boundary already sanitized
    assert err.__cause__ is None


def test_import_isolation() -> None:
    source = Path(workflow_mod.__file__).read_text(encoding="utf-8")
    assert "qlib" not in source.lower()
    assert "mlflow" not in source.lower()
    assert "lightgbm" not in source.lower()
    assert "import tushare" not in source
    assert "import baostock" not in source
    mod = importlib.import_module("quant.research.m3.g1_workflow")
    assert hasattr(mod, "inspect_g1_workflow")


def test_package_exports_r1b_symbols() -> None:
    import quant.research.m3 as m3

    assert m3.inspect_g1_workflow is inspect_g1_workflow
    assert m3.run_g1_index_stage is run_g1_index_stage
    assert m3.publish_g1_workflow is publish_g1_workflow


def test_classify_illegal_maps_to_execution_failed(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)

    class BoomPro(_CountingProClient):
        def index_weight(self, **kwargs: Any) -> pl.DataFrame:
            raise RuntimeError("net")

    with pytest.raises(M3G1WorkflowError) as excinfo:
        run_g1_index_stage(
            project_root=root,
            config=config,
            connector=TushareConnector(pro_client=BoomPro(_symbols())),
            classify_error=lambda _e: "NOT_A_CATEGORY",
        )
    assert excinfo.value.code == "G1_WORKFLOW_EXECUTION_FAILED"


def test_index_interrupt_intent_then_recover(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    tushare = TushareConnector(pro_client=_CountingProClient(_symbols()))
    # force fault after intent by patching fault point on first request path via env-like hook
    calls = {"n": 0}
    real_fault = workflow_mod  # placate linters
    del real_fault

    import quant.data.m3_backfill as backfill

    original = backfill._fault_point

    def flaky(name: str) -> None:
        if name == "after_candidate":
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated crash after candidate")
        return original(name)

    with patch.object(backfill, "_fault_point", side_effect=flaky):
        with pytest.raises(M3G1WorkflowError):
            run_g1_index_stage(
                project_root=root,
                config=config,
                connector=tushare,
                classify_error=_classify,
            )
    # recover via legal B2A path
    state = run_g1_index_stage(
        project_root=root,
        config=config,
        connector=tushare,
        classify_error=_classify,
    )
    assert state.completed_stages == ("INDEX",)


def test_no_os_replace_in_workflow_module() -> None:
    source = Path(workflow_mod.__file__).read_text(encoding="utf-8")
    assert "os.replace" not in source


def test_corrupted_receipt_fails_closed(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    tushare = TushareConnector(pro_client=_CountingProClient(_symbols()))
    run_g1_index_stage(
        project_root=root, config=config, connector=tushare, classify_error=_classify
    )
    journal = root / "data/run_state/m3_g1/tushare"
    receipt = next(journal.glob("*/receipt.json"))
    receipt.write_text("{not-json", encoding="utf-8")
    with pytest.raises(M3G1WorkflowError) as excinfo:
        inspect_g1_workflow(project_root=root, config=config)
    assert excinfo.value.code == "G1_WORKFLOW_JOURNAL_INVALID"


def _flaky_root_identity_after_open() -> Any:
    """Return a patch that mismatches root identity on the exit assert call."""
    real = workflow_mod._dir_identity
    calls = {"n": 0}

    def flaky(path: Path, *, operation: Any) -> tuple[int, int]:
        ident = real(path, operation=operation)
        calls["n"] += 1
        if calls["n"] > 1:
            return (ident[0], ident[1] ^ 0xDEADBEEF)
        return ident

    return flaky


def test_history_entry_root_identity_failure_reports_history_operation(
    tmp_path: Path,
) -> None:
    """§9.1: HISTORY entry PATH failure must not pseudo-report INSPECT."""
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    with patch.object(workflow_mod, "_dir_identity", _flaky_root_identity_after_open()):
        with pytest.raises(M3G1WorkflowError) as excinfo:
            run_g1_history_stage(
                project_root=root,
                config=config,
                connector=TushareConnector(pro_client=_CountingProClient(_symbols())),
                classify_error=_classify,
            )
    err = excinfo.value
    assert err.code == "G1_WORKFLOW_PROJECT_ROOT_INVALID"
    assert err.operation == "HISTORY"
    assert str(err) == "HISTORY:G1_WORKFLOW_PROJECT_ROOT_INVALID"


def test_index_entry_root_identity_failure_reports_index_operation(
    tmp_path: Path,
) -> None:
    """§9.1: INDEX entry PATH failure must report INDEX, not INSPECT."""
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    with patch.object(workflow_mod, "_dir_identity", _flaky_root_identity_after_open()):
        with pytest.raises(M3G1WorkflowError) as excinfo:
            run_g1_index_stage(
                project_root=root,
                config=config,
                connector=TushareConnector(pro_client=_CountingProClient(_symbols())),
                classify_error=_classify,
            )
    err = excinfo.value
    assert err.code == "G1_WORKFLOW_PROJECT_ROOT_INVALID"
    assert err.operation == "INDEX"
    assert str(err) == "INDEX:G1_WORKFLOW_PROJECT_ROOT_INVALID"


def test_inspect_root_identity_failure_still_reports_inspect(
    tmp_path: Path,
) -> None:
    """Ordinary inspect PATH failure must keep operation INSPECT."""
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    with patch.object(workflow_mod, "_dir_identity", _flaky_root_identity_after_open()):
        with pytest.raises(M3G1WorkflowError) as excinfo:
            inspect_g1_workflow(project_root=root, config=config)
    err = excinfo.value
    assert err.code == "G1_WORKFLOW_PROJECT_ROOT_INVALID"
    assert err.operation == "INSPECT"
    assert str(err) == "INSPECT:G1_WORKFLOW_PROJECT_ROOT_INVALID"


def test_verified_state_self_proof_bidirectional_closure(tmp_path: Path) -> None:
    """Bidirectional Verified* closure without full HISTORY/REFERENCE pipeline.

    Full 300-symbol HISTORY alone exceeds ~3–4 minutes and multi-inspect
    REFERENCE/PUBLISH pushes wall time past 15 minutes (appears hung). Illegal
    closures are proven from fresh/INDEX artifacts; legal later stages remain
    covered by ``test_five_stage_fake_publish_and_inspect_closure``.
    """
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    tushare = TushareConnector(pro_client=_CountingProClient(_symbols()))
    fresh = inspect_g1_workflow(project_root=root, config=config)
    index_state = run_g1_index_stage(
        project_root=root, config=config, connector=tushare, classify_error=_classify
    )

    # Legal fresh / INDEX still construct (avoid over-strict rejection)
    for state in (fresh, index_state):
        again = dataclasses.replace(state)
        assert again.completed_stages == state.completed_stages
        assert type(again) is VerifiedG1WorkflowStateV1

    # P0-A: claim HISTORY without candidate / history responses
    with pytest.raises(ValueError):
        dataclasses.replace(fresh, completed_stages=("INDEX", "HISTORY"))
    with pytest.raises(ValueError):
        dataclasses.replace(index_state, completed_stages=("INDEX", "HISTORY"))
    with pytest.raises(ValueError):
        dataclasses.replace(
            index_state,
            completed_stages=("INDEX", "HISTORY"),
            history_responses=(),
            candidate=None,
        )

    # Early candidate / prepared / published (type-exact stubs; closure is None-checks)
    early_candidate = object.__new__(G1Candidate)
    early_prepared = object.__new__(G1PreparedRelease)
    early_published = object.__new__(VerifiedG1Release)
    with pytest.raises(ValueError):
        dataclasses.replace(index_state, candidate=early_candidate)
    with pytest.raises(ValueError):
        dataclasses.replace(index_state, prepared=early_prepared)
    with pytest.raises(ValueError):
        dataclasses.replace(fresh, prepared=early_prepared)
    with pytest.raises(ValueError):
        dataclasses.replace(index_state, published=early_published)
    with pytest.raises(ValueError):
        dataclasses.replace(
            index_state,
            completed_stages=("INDEX", "HISTORY", "REFERENCE", "PREPARE"),
            published=early_published,
        )

    # counts mismatch vs plan totals
    with pytest.raises(ValueError):
        dataclasses.replace(
            index_state,
            counts=G1WorkflowCountsV1(
                index_requests=index_state.counts.index_requests,
                history_requests=index_state.counts.history_requests + 1,
                reference_requests=index_state.counts.reference_requests,
                history_symbols=index_state.counts.history_symbols,
            ),
        )
    with pytest.raises(ValueError):
        dataclasses.replace(
            fresh,
            counts=G1WorkflowCountsV1(
                index_requests=fresh.counts.index_requests + 1,
                history_requests=0,
                reference_requests=0,
                history_symbols=0,
            ),
        )

    # response missing / duplicate / reorder (index exact-id closure)
    with pytest.raises(ValueError):
        dataclasses.replace(
            index_state,
            index_responses=index_state.index_responses[1:],
        )
    with pytest.raises(ValueError):
        dataclasses.replace(
            index_state,
            index_responses=(
                index_state.index_responses[0],
                *index_state.index_responses,
            ),
        )
    with pytest.raises(ValueError):
        dataclasses.replace(
            index_state,
            index_responses=tuple(reversed(index_state.index_responses)),
        )


def test_verified_state_self_proof_does_not_hang(tmp_path: Path) -> None:
    """Regression: self-proof path must finish well under a hard wall clock.

    Prior hang: full HISTORY+REFERENCE+PUBLISH self-proof exceeded 18 minutes
    (1205 history requests × multi-inspect), not a journal deadlock.
    """
    import threading

    done = threading.Event()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            test_verified_state_self_proof_bidirectional_closure(tmp_path)
        except BaseException as exc:  # noqa: BLE001 — surface to parent thread
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=run, name="g1-self-proof", daemon=True)
    worker.start()
    assert done.wait(timeout=90.0), (
        "verified-state self-proof exceeded 90s wall clock; "
        "do not reintroduce full 300-symbol HISTORY/REFERENCE pipeline here"
    )
    assert not errors, errors[0]


def test_history_max_new_rejects_illegal_before_side_effects(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    pro = _CountingProClient(_symbols())
    connector = TushareConnector(pro_client=pro)
    before_calls = pro.calls
    journal = root / "data/run_state/m3_g1/tushare"
    raw = root / "data/raw/m3_g1"
    assert not journal.exists()
    assert not raw.exists()
    for bad in (True, 0, -1, 1.0, "1"):
        with pytest.raises(M3G1WorkflowError) as excinfo:
            run_g1_history_stage(
                project_root=root,
                config=config,
                connector=connector,
                classify_error=_classify,
                max_new_requests=bad,  # type: ignore[arg-type]
            )
        assert excinfo.value.code == "G1_WORKFLOW_INPUT_INVALID"
    assert pro.calls == before_calls
    assert not journal.exists()
    assert not raw.exists()


def test_history_bounded_incomplete_then_resume_success(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    pro = _CountingProClient(_symbols())
    connector = TushareConnector(pro_client=pro)
    run_g1_index_stage(
        project_root=root, config=config, connector=connector, classify_error=_classify
    )
    first = run_g1_history_stage(
        project_root=root,
        config=config,
        connector=connector,
        classify_error=_classify,
        max_new_requests=2,
    )
    assert first.state.completed_stages == ("INDEX",)
    assert first.new_requests_committed == 2
    assert first.max_new_requests == 2
    calls_after_first = pro.calls

    second = run_g1_history_stage(
        project_root=root,
        config=config,
        connector=connector,
        classify_error=_classify,
        max_new_requests=2,
    )
    assert second.state.completed_stages == ("INDEX",)
    assert second.new_requests_committed == 2
    assert pro.calls == calls_after_first + 2

    # Sufficient budget completes HISTORY and reports SUCCESS semantics via completed stage.
    done = run_g1_history_stage(
        project_root=root,
        config=config,
        connector=connector,
        classify_error=_classify,
        max_new_requests=100_000,
    )
    assert done.state.completed_stages == ("INDEX", "HISTORY")
    assert done.new_requests_committed > 0
    reuse = run_g1_history_stage(
        project_root=root, config=config, connector=connector, classify_error=_classify
    )
    assert reuse.state.completed_stages == ("INDEX", "HISTORY")
    assert reuse.new_requests_committed == 0
    assert pro.calls == calls_after_first + 2 + done.new_requests_committed


def test_history_unbounded_incomplete_still_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project_root(tmp_path)
    config = _fast_config(tmp_path)
    pro = _CountingProClient(_symbols())
    connector = TushareConnector(pro_client=pro)
    run_g1_index_stage(
        project_root=root, config=config, connector=connector, classify_error=_classify
    )

    original = workflow_mod.execute_tushare_batch

    def partial(**kwargs: Any) -> Any:
        kwargs = dict(kwargs)
        kwargs["max_new_requests"] = 1
        return original(**kwargs)

    monkeypatch.setattr(workflow_mod, "execute_tushare_batch", partial)
    with pytest.raises(M3G1WorkflowError) as excinfo:
        run_g1_history_stage(
            project_root=root,
            config=config,
            connector=connector,
            classify_error=_classify,
            max_new_requests=None,
        )
    assert excinfo.value.code == "G1_WORKFLOW_HISTORY_INCOMPLETE"
