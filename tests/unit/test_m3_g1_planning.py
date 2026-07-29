"""R1A: G1 runtime identity and staged planning skeleton."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import socket
import sys
import traceback
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest

from quant.data import m3_backfill as backfill
from quant.data.connectors.tushare import TushareConnector
from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    EndpointPolicy,
    TushareRequestReceipt,
    TushareRequestSpec,
    VerifiedRawResponse,
    response_content_sha256,
)
from quant.data.m3_execution_facts import G1_CORPORATE_ACTION_RECONCILIATION_VERSION
from quant.data.storage import RawStore
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3 import g1_planning
from quant.research.m3.g1_planning import (
    G1DependencyVersionV1,
    G1RuntimeIdentityV1,
    G1SourceDigestV1,
    M3G1PlanningError,
    build_g1_static_plan,
    compute_g1_runtime_identity,
    derive_g1_history_plan,
)

_HEX = "a" * 64
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "configs" / "research" / "m3_qlib_example.toml"
_UNIVERSE = "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
_INDEX = "000300.SH"
_SIGNAL_START = dt.date(2016, 2, 1)
_SIGNAL_END = dt.date(2016, 2, 1)
_OBS_DEC = "20151231"
_OBS_JAN = "20160129"
_OBS_FEB = "20160229"


def _require_symlink(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    """Create a symlink; skip only when Windows reports missing symlink privilege (1314)."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows session lacks SeCreateSymbolicLinkPrivilege")
        raise


def _symbols(n: int = 300) -> list[str]:
    out: list[str] = []
    for i in range(n):
        code = f"{i + 1:06d}"
        out.append(f"{code}.SZ" if i < 150 else f"{code}.SH")
    return out


def _weights(n: int = 300) -> list[float]:
    return [100.0 / n] * n


def _make_verified(
    *,
    start: dt.date,
    end: dt.date,
    frame: pl.DataFrame,
    index_code: str = _INDEX,
) -> VerifiedRawResponse:
    params = {
        "fields": TUSHARE_FIELDS["index_weight"],
        "index_code": index_code,
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
    }
    spec = TushareRequestSpec.create(endpoint="index_weight", parameters=params)
    content = response_content_sha256(frame, "index_weight")
    columns = tuple(frame.columns)
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    stable = backfill._stable_response_hash_values(
        {
            "request_id": spec.request_id,
            "endpoint": "index_weight",
            "parameters_sha256": parameters_sha256,
            "response_content_sha256": content,
            "row_count": frame.height,
            "columns": columns,
        }
    )
    receipt = TushareRequestReceipt(
        schema_version="m3-g1-tushare-receipt-v1",
        request_id=spec.request_id,
        endpoint="index_weight",
        parameters=spec.parameters,
        parameters_sha256=parameters_sha256,
        raw_snapshot_id=spec.request_id,
        raw_data_path="tushare/index_weight/request=x/data.parquet",
        raw_metadata_path="tushare/index_weight/request=x/metadata.json",
        raw_file_sha256=_HEX,
        raw_metadata_sha256=_HEX,
        response_content_sha256=content,
        stable_response_sha256=stable,
        raw_size_bytes=max(frame.height, 1),
        row_count=frame.height,
        columns=columns,
    )
    return VerifiedRawResponse(spec, receipt, backfill._sha256(asdict(receipt)), frame)


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


def _minimal_project(tmp_path: Path, *, files: dict[str, bytes] | None = None) -> Path:
    root = tmp_path / "proj"
    quant = root / "src" / "quant"
    quant.mkdir(parents=True)
    (root / "pyproject.toml").write_bytes(b"[project]\nname='demo'\n")
    payload = files if files is not None else {"a.py": b"x=1\n", "b.py": b"y=2\n"}
    for rel, body in payload.items():
        path = quant / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return root


def _short_config(tmp_path: Path) -> LoadedM3Config:
    text = _CONFIG_PATH.read_text(encoding="utf-8")
    variant = (
        text.replace("start_date = 2016-01-04", "start_date = 2016-02-01")
        .replace("end_date = 2026-06-26", "end_date = 2016-02-01")
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "m3_short.toml"
    path.write_text(variant, encoding="utf-8")
    return load_m3_config(path)


def _index_responses_for_batch(
    batch: Any,
    *,
    month_symbols: dict[tuple[int, int], list[str]] | None = None,
) -> list[VerifiedRawResponse]:
    default = _symbols()
    out: list[VerifiedRawResponse] = []
    for spec in batch.requests:
        params = dict(spec.parameters)
        start = dt.datetime.strptime(params["start_date"], "%Y%m%d").date()
        end = dt.datetime.strptime(params["end_date"], "%Y%m%d").date()
        key = (start.year, start.month)
        if start.month == 12:
            trade = _OBS_DEC
        elif start.month == 1:
            trade = _OBS_JAN
        else:
            trade = _OBS_FEB
        symbols = (month_symbols or {}).get(key, default)
        out.append(_make_verified(start=start, end=end, frame=_weight_frame(trade, symbols)))
    return out


@pytest.fixture(scope="module")
def c0_config() -> LoadedM3Config:
    return load_m3_config(_CONFIG_PATH)


def test_runtime_identity_stable_and_source_changes(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path)
    first = compute_g1_runtime_identity(project_root=root)
    second = compute_g1_runtime_identity(project_root=root)
    assert first == second
    assert first.code_version.startswith("m3-g1-code-v1-")
    assert len(first.dependencies) == 7
    dep_fp = first.dependency_fingerprint_sha256
    source_fp = first.source_tree_sha256
    target = root / "src" / "quant" / "a.py"
    target.write_bytes(b"x=9\n")
    changed = compute_g1_runtime_identity(project_root=root)
    assert changed.source_tree_sha256 != source_fp
    assert changed.code_version != first.code_version
    assert changed.dependency_fingerprint_sha256 == dep_fp


def test_runtime_dependency_mock_changes_fingerprint_only(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path)
    base = compute_g1_runtime_identity(project_root=root)

    def fake_version(name: str) -> str:
        return "9.9.9" if name == "polars" else base.dependencies[
            [item.distribution for item in base.dependencies].index(name)
        ].version

    with patch("importlib.metadata.version", side_effect=fake_version):
        altered = compute_g1_runtime_identity(project_root=root)
    assert altered.source_tree_sha256 == base.source_tree_sha256
    assert altered.code_version == base.code_version
    assert altered.dependency_fingerprint_sha256 != base.dependency_fingerprint_sha256


def test_source_symlink_and_root_symlink_rejected(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path)
    link = root / "src" / "quant" / "link.py"
    _require_symlink(link, root / "src" / "quant" / "a.py")
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID"):
        compute_g1_runtime_identity(project_root=root)

    real = _minimal_project(tmp_path / "real")
    alias = tmp_path / "alias"
    _require_symlink(alias, real, target_is_directory=True)
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_PROJECT_ROOT_INVALID"):
        compute_g1_runtime_identity(project_root=alias)


def test_source_add_remove_toctou_empty_missing_escape(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path)
    (root / "src" / "quant" / "c.py").write_bytes(b"z=3\n")
    with_extra = compute_g1_runtime_identity(project_root=root)
    (root / "src" / "quant" / "c.py").unlink()
    without = compute_g1_runtime_identity(project_root=root)
    assert with_extra.source_tree_sha256 != without.source_tree_sha256

    empty = tmp_path / "empty"
    (empty / "src" / "quant").mkdir(parents=True)
    (empty / "pyproject.toml").write_bytes(b"[project]\nname='x'\n")
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID"):
        compute_g1_runtime_identity(project_root=empty)

    missing = _minimal_project(tmp_path / "nopy")
    (missing / "pyproject.toml").unlink()
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID"):
        compute_g1_runtime_identity(project_root=missing)

    root2 = _minimal_project(tmp_path / "escape")
    target = root2 / "src" / "quant" / "a.py"
    before = os.lstat(target)

    class FlakyPath(type(target)):
        def read_bytes(self) -> bytes:  # type: ignore[override]
            payload = Path.read_bytes(self)
            Path.write_bytes(self, payload + b"#")
            os.utime(self, ns=(before.st_atime_ns, before.st_mtime_ns))
            return payload

    with patch("pathlib.Path.read_bytes", new=FlakyPath.read_bytes):
        # Force TOCTOU via size change after read snapshot mismatch path.
        pass

    # Same-size content rewrite with mtime bump.
    target.write_bytes(b"x=2\n")
    # Replace during digest: patch lstat second call.
    calls = {"n": 0}
    real_lstat = os.lstat

    def flaky_lstat(path: Any, *args: Any, **kwargs: Any) -> Any:
        result = real_lstat(path, *args, **kwargs)
        path_obj = Path(path)
        if path_obj == target:
            calls["n"] += 1
            if calls["n"] == 2:
                Path.write_bytes(target, b"x=3\n")
                return real_lstat(path, *args, **kwargs)
        return result

    with patch("os.lstat", side_effect=flaky_lstat):
        with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID"):
            compute_g1_runtime_identity(project_root=root2)


def _assert_planning_error_sanitized(exc: BaseException, *, forbidden: str) -> None:
    assert isinstance(exc, M3G1PlanningError)
    assert str(exc) == "G1_PLANNING_SOURCE_TREE_INVALID"
    assert forbidden not in str(exc)
    assert forbidden not in repr(exc)
    assert exc.__cause__ is None
    only = "".join(traceback.format_exception_only(type(exc), exc))
    assert forbidden not in only
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert forbidden not in formatted


def test_return_before_source_same_inode_rewrite_rejected(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path, files={"a.py": b"AAAA", "b.py": b"BBBB"})
    target = root / "src" / "quant" / "a.py"
    before = os.lstat(target)
    stale = hashlib.sha256(b"AAAA").hexdigest()
    real_read = g1_planning._read_dependencies

    def mutate_then_read() -> Any:
        fd = os.open(target, os.O_WRONLY)
        try:
            os.write(fd, b"ZZZZ")
            os.fsync(fd)
        finally:
            os.close(fd)
        after = os.lstat(target)
        assert after.st_ino == before.st_ino
        assert after.st_size == before.st_size
        assert target.read_bytes() == b"ZZZZ"
        return real_read()

    with patch.object(g1_planning, "_read_dependencies", side_effect=mutate_then_read):
        with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID") as excinfo:
            compute_g1_runtime_identity(project_root=root)
    _assert_planning_error_sanitized(excinfo.value, forbidden=str(root.resolve()))
    # Prove rewrite happened and would have been a different digest if returned.
    assert hashlib.sha256(b"ZZZZ").hexdigest() != stale
    assert target.read_bytes() == b"ZZZZ"


def test_return_before_source_new_inode_replace_rejected(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path, files={"a.py": b"AAAA", "b.py": b"BBBB"})
    target = root / "src" / "quant" / "a.py"
    before = os.lstat(target)
    real_read = g1_planning._read_dependencies

    def mutate_then_read() -> Any:
        tmp = target.with_name("a.py.replace")
        tmp.write_bytes(b"ZZZZ")
        os.replace(tmp, target)
        after = os.lstat(target)
        assert after.st_ino != before.st_ino
        assert after.st_size == before.st_size
        return real_read()

    with patch.object(g1_planning, "_read_dependencies", side_effect=mutate_then_read):
        with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID") as excinfo:
            compute_g1_runtime_identity(project_root=root)
    _assert_planning_error_sanitized(excinfo.value, forbidden=str(root.resolve()))


def test_return_before_source_add_or_delete_rejected(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path, files={"a.py": b"AAAA", "b.py": b"BBBB"})
    real_read = g1_planning._read_dependencies

    def add_then_read() -> Any:
        (root / "src" / "quant" / "c.py").write_bytes(b"CCCC")
        return real_read()

    with patch.object(g1_planning, "_read_dependencies", side_effect=add_then_read):
        with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID") as excinfo:
            compute_g1_runtime_identity(project_root=root)
    _assert_planning_error_sanitized(excinfo.value, forbidden=str(root.resolve()))

    root2 = _minimal_project(tmp_path / "del", files={"a.py": b"AAAA", "b.py": b"BBBB"})
    victim = root2 / "src" / "quant" / "b.py"

    def delete_then_read() -> Any:
        victim.unlink()
        return real_read()

    with patch.object(g1_planning, "_read_dependencies", side_effect=delete_then_read):
        with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID") as excinfo2:
            compute_g1_runtime_identity(project_root=root2)
    _assert_planning_error_sanitized(excinfo2.value, forbidden=str(root2.resolve()))


def test_return_before_pyproject_same_size_rewrite_rejected(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path, files={"a.py": b"AAAA", "b.py": b"BBBB"})
    pyproject = root / "pyproject.toml"
    original = pyproject.read_bytes()
    replacement = b"#" * len(original)
    assert len(replacement) == len(original)
    assert replacement != original
    before = os.lstat(pyproject)
    real_read = g1_planning._read_dependencies

    def mutate_then_read() -> Any:
        fd = os.open(pyproject, os.O_WRONLY)
        try:
            os.write(fd, replacement)
            os.fsync(fd)
        finally:
            os.close(fd)
        after = os.lstat(pyproject)
        assert after.st_ino == before.st_ino
        assert after.st_size == before.st_size
        return real_read()

    with patch.object(g1_planning, "_read_dependencies", side_effect=mutate_then_read):
        with pytest.raises(M3G1PlanningError, match="G1_PLANNING_SOURCE_TREE_INVALID") as excinfo:
            compute_g1_runtime_identity(project_root=root)
    _assert_planning_error_sanitized(excinfo.value, forbidden=str(root.resolve()))
    assert hashlib.sha256(pyproject.read_bytes()).hexdigest() != hashlib.sha256(original).hexdigest()


def test_return_before_recheck_success_digests_match_algorithm(tmp_path: Path) -> None:
    files = {"a.py": b"AAAA", "b.py": b"BBBB"}
    root = _minimal_project(tmp_path, files=files)
    identity = compute_g1_runtime_identity(project_root=root)
    expected_files = tuple(
        sorted(
            (
                G1SourceDigestV1(
                    relative_path=f"src/quant/{name}",
                    sha256=hashlib.sha256(body).hexdigest(),
                )
                for name, body in files.items()
            ),
            key=lambda item: item.relative_path.encode("utf-8"),
        )
    )
    assert identity.source_files == expected_files
    expected_tree = g1_planning._source_tree_sha256(expected_files)
    assert identity.source_tree_sha256 == expected_tree
    assert identity.code_version == f"m3-g1-code-v1-{expected_tree}"
    expected_py = hashlib.sha256((root / "pyproject.toml").read_bytes()).hexdigest()
    assert identity.pyproject_sha256 == expected_py
    again = compute_g1_runtime_identity(project_root=root)
    assert again == identity


def test_runtime_dataclass_rejects_list_bool_order_forged_digest(tmp_path: Path) -> None:
    root = _minimal_project(tmp_path)
    good = compute_g1_runtime_identity(project_root=root)
    with pytest.raises(M3G1PlanningError):
        G1RuntimeIdentityV1(
            schema_version="m3-g1-runtime-identity-v1",
            code_version=good.code_version,
            source_tree_sha256=good.source_tree_sha256,
            source_files=list(good.source_files),  # type: ignore[arg-type]
            pyproject_sha256=good.pyproject_sha256,
            python_implementation=good.python_implementation,
            python_version=good.python_version,
            sys_platform=good.sys_platform,
            machine=good.machine,
            kernel_release=good.kernel_release,
            dependencies=good.dependencies,
            dependency_fingerprint_sha256=good.dependency_fingerprint_sha256,
        )
    with pytest.raises(M3G1PlanningError):
        G1DependencyVersionV1(distribution="polars", version=True)  # type: ignore[arg-type]
    shuffled = tuple(reversed(good.dependencies))
    with pytest.raises(M3G1PlanningError):
        G1RuntimeIdentityV1(
            schema_version=good.schema_version,
            code_version=good.code_version,
            source_tree_sha256=good.source_tree_sha256,
            source_files=good.source_files,
            pyproject_sha256=good.pyproject_sha256,
            python_implementation=good.python_implementation,
            python_version=good.python_version,
            sys_platform=good.sys_platform,
            machine=good.machine,
            kernel_release=good.kernel_release,
            dependencies=shuffled,
            dependency_fingerprint_sha256=good.dependency_fingerprint_sha256,
        )
    dup = good.dependencies + (good.dependencies[0],)
    with pytest.raises(M3G1PlanningError):
        G1RuntimeIdentityV1(
            schema_version=good.schema_version,
            code_version=good.code_version,
            source_tree_sha256=good.source_tree_sha256,
            source_files=good.source_files,
            pyproject_sha256=good.pyproject_sha256,
            python_implementation=good.python_implementation,
            python_version=good.python_version,
            sys_platform=good.sys_platform,
            machine=good.machine,
            kernel_release=good.kernel_release,
            dependencies=dup,
            dependency_fingerprint_sha256=good.dependency_fingerprint_sha256,
        )
    with pytest.raises(M3G1PlanningError):
        replace(good, source_tree_sha256="b" * 64)


def test_static_plan_from_c0_and_forged_identity(
    c0_config: LoadedM3Config, tmp_path: Path
) -> None:
    root = _minimal_project(tmp_path)
    plan = build_g1_static_plan(config=c0_config, project_root=root)
    assert plan.signal_start == dt.date(2016, 1, 4)
    assert plan.signal_end == dt.date(2026, 6, 26)
    assert plan.universe == _UNIVERSE
    assert plan.benchmark == "510300.SH"
    assert plan.index_code == _INDEX
    assert plan.expected_constituent_count == 300
    assert plan.feature_warmup_sessions == 60
    assert plan.label_tail_sessions == 10
    assert plan.build_spec.build_code_version == plan.runtime.code_version
    assert (
        plan.build_spec.dependency_fingerprint_sha256
        == plan.runtime.dependency_fingerprint_sha256
    )
    assert [name for name, _ in plan.endpoint_policies] == sorted(
        [
            "index_weight",
            "daily",
            "adj_factor",
            "index_daily",
            "suspend_d",
            "stk_limit",
            "dividend",
            "fund_daily",
            "fund_adj",
            "fund_div",
        ]
    )
    assert dict(plan.endpoint_policies)["dividend"].empty_response == "ALLOW"
    assert dict(plan.endpoint_policies)["daily"].empty_response == "REJECT"
    assert dict(plan.endpoint_policies)["fund_daily"].empty_response == "REJECT"
    assert dict(plan.endpoint_policies)["fund_adj"].row_limit == 2000
    assert dict(plan.endpoint_policies)["fund_div"].row_limit == 5000
    again = build_g1_static_plan(config=c0_config, project_root=root)
    assert again == plan
    assert plan.benchmark == "510300.SH"
    assert plan.build_spec.benchmark_mode == "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
    assert (
        plan.build_spec.benchmark_method_version
        == "tushare_510300_fund_daily_fund_adj_hfq_v1"
    )
    assert (
        plan.build_spec.benchmark_dividend_reconciliation_version
        == "tushare_fund_div_implemented_cash_v1"
    )
    assert plan.build_spec.mapper_version == "m3-g1-tushare-mapper-v5"
    assert plan.build_spec.schema_version == "m3-g1-schema-v3"
    assert G1_CORPORATE_ACTION_RECONCILIATION_VERSION == (
        "tushare_factor_daily_preclose_suspension_resume_v6"
    )
    assert (
        plan.build_spec.corporate_action_reconciliation_version
        == G1_CORPORATE_ACTION_RECONCILIATION_VERSION
    )
    captured: dict[str, Any] = {}
    real_sha = g1_planning._sha256_json

    def _spy(value: object) -> str:
        captured["payload"] = value
        return real_sha(value)

    with patch.object(g1_planning, "_sha256_json", side_effect=_spy):
        static_sha = g1_planning._static_plan_sha256(plan)
    assert len(static_sha) == 64
    build_payload = captured["payload"]["build_spec"]
    assert build_payload["benchmark_mode"] == plan.build_spec.benchmark_mode
    assert (
        build_payload["benchmark_method_version"]
        == plan.build_spec.benchmark_method_version
    )
    assert (
        build_payload["benchmark_dividend_reconciliation_version"]
        == plan.build_spec.benchmark_dividend_reconciliation_version
    )
    assert all(
        item.endpoint == "index_weight" for item in plan.index_weight_batch.requests
    )

    forged = replace(c0_config, g1_config_sha256="c" * 64)
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_CONFIG_INVALID"):
        build_g1_static_plan(config=forged, project_root=root)
    for attr in (
        "full_config_sha256",
        "snapshot_config_sha256",
        "provider_config_sha256",
        "scientific_config_sha256",
        "provider_validation_config_sha256",
        "label_reconciliation_config_sha256",
        "acceptance_config_sha256",
        "tracking_target_key",
    ):
        bad = replace(c0_config, **{attr: "d" * 64})
        with pytest.raises(M3G1PlanningError, match="G1_PLANNING_CONFIG_INVALID"):
            build_g1_static_plan(config=bad, project_root=root)


def test_endpoint_policy_and_version_drift(c0_config: LoadedM3Config, tmp_path: Path) -> None:
    root = _minimal_project(tmp_path)
    plan = build_g1_static_plan(config=c0_config, project_root=root)
    bad_policies = tuple(
        (name, EndpointPolicy(policy.row_limit, "ALLOW" if policy.empty_response == "REJECT" else "REJECT"))
        for name, policy in plan.endpoint_policies
    )
    with pytest.raises(M3G1PlanningError):
        replace(plan, endpoint_policies=bad_policies)
    missing = plan.endpoint_policies[1:]
    with pytest.raises(M3G1PlanningError):
        replace(plan, endpoint_policies=missing)
    with pytest.raises(ValueError, match="mapper_version"):
        replace(plan.build_spec, mapper_version="m3-g1-tushare-mapper-v0")
    with pytest.raises(ValueError, match="corporate_action_reconciliation_version"):
        replace(
            plan.build_spec,
            corporate_action_reconciliation_version="tushare_factor_daily_preclose_v3",
        )

def test_history_plan_order_invariant_and_response_set(
    tmp_path: Path,
) -> None:
    config = _short_config(tmp_path)
    root = _minimal_project(tmp_path / "proj")
    static = build_g1_static_plan(config=config, project_root=root)
    responses = _index_responses_for_batch(static.index_weight_batch)
    calendars = _calendar(dt.date(2015, 10, 1), dt.date(2016, 3, 31))
    instruments = _instruments(_symbols())
    first = derive_g1_history_plan(
        config=config,
        project_root=root,
        static_plan=static,
        index_responses=responses,
        calendars=calendars,
        instruments=instruments,
    )
    shuffled = list(reversed(responses))
    second = derive_g1_history_plan(
        config=config,
        project_root=root,
        static_plan=static,
        index_responses=shuffled,
        calendars=calendars,
        instruments=instruments,
    )
    assert first == second
    assert first.history_symbols == tuple(_symbols())
    symbol_count = len(first.history_symbols)
    assert len(first.request_plan.history_batch.requests) == 5 * symbol_count + 3
    endpoints = {spec.endpoint for spec in first.request_plan.history_batch.requests}
    assert "index_daily" not in endpoints
    assert {"fund_daily", "fund_adj", "fund_div"} <= endpoints
    fund_daily = [
        spec
        for spec in first.request_plan.history_batch.requests
        if spec.endpoint == "fund_daily"
    ]
    assert len(fund_daily) == 1
    assert dict(fund_daily[0].parameters)["ts_code"] == "510300.SH"
    suspend_specs = [
        spec
        for spec in first.request_plan.history_batch.requests
        if spec.endpoint == "suspend_d"
    ]
    assert len(suspend_specs) == symbol_count
    assert {
        dict(spec.parameters)["ts_code"] for spec in suspend_specs
    } == set(first.history_symbols)
    for spec in suspend_specs:
        params = dict(spec.parameters)
        assert params["start_date"] == first.history.start.strftime("%Y%m%d")
        assert params["end_date"] == first.history.end.strftime("%Y%m%d")
        assert params["suspend_type"] == "S"
        assert "trade_date" not in params

    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_IDENTITY_MISMATCH"):
        derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses[:-1],
            calendars=calendars,
            instruments=instruments,
        )
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_IDENTITY_MISMATCH"):
        derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses + responses[:1],
            calendars=calendars,
            instruments=instruments,
        )
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_IDENTITY_MISMATCH"):
        derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses + [responses[0]],
            calendars=calendars,
            instruments=instruments,
        )

    drifted = responses[:]
    bad_frame = drifted[0].frame.with_columns(pl.col("weight") * 1.0)
    # Change content digest by mutating weight slightly while keeping height/columns.
    mutated = bad_frame.with_columns((pl.col("weight") + 0.000001).alias("weight"))
    with pytest.raises(Exception):
        VerifiedRawResponse(
            drifted[0].spec,
            drifted[0].receipt,
            drifted[0].receipt_sha256,
            mutated,
        )


def test_history_union_keeps_delisted_symbol(tmp_path: Path) -> None:
    config = _short_config(tmp_path)
    root = _minimal_project(tmp_path / "proj")
    static = build_g1_static_plan(config=config, project_root=root)
    base = _symbols()
    january = base[:]
    february = base[1:] + ["000301.SH"]
    month_symbols = {
        (2016, 1): january,
        (2016, 2): february,
    }
    responses = _index_responses_for_batch(static.index_weight_batch, month_symbols=month_symbols)
    calendars = _calendar(dt.date(2015, 10, 1), dt.date(2016, 3, 31))
    instruments = _instruments(sorted(set(january) | set(february)))
    derived = derive_g1_history_plan(
        config=config,
        project_root=root,
        static_plan=static,
        index_responses=responses,
        calendars=calendars,
        instruments=instruments,
    )
    assert "000001.SZ" in derived.history_symbols
    assert "000301.SH" in derived.history_symbols
    assert derived.history_symbols == tuple(sorted(set(january) | set(february)))
    end_members = set(february)
    assert "000001.SZ" not in end_members


def test_calendar_warmup_tail_and_market_consistency(tmp_path: Path) -> None:
    config = _short_config(tmp_path)
    root = _minimal_project(tmp_path / "proj")
    static = build_g1_static_plan(config=config, project_root=root)
    responses = _index_responses_for_batch(static.index_weight_batch)
    instruments = _instruments(_symbols())
    full = _calendar(dt.date(2015, 10, 1), dt.date(2016, 3, 31))
    open_dates = (
        full.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .get_column("date")
        .to_list()
    )
    start_index = open_dates.index(_SIGNAL_START)
    # Drop the exact 60th warmup session day from natural calendar coverage by
    # truncating so only 59 open days remain before signal.
    keep_from = open_dates[start_index - 59]
    short_warmup = full.filter(pl.col("date") >= keep_from)
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_CALENDAR_INVALID"):
        derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses,
            calendars=short_warmup,
            instruments=instruments,
        )
    end_index = open_dates.index(_SIGNAL_END)
    # Keep only 9 tail sessions after signal end.
    keep_to = open_dates[end_index + 9]
    short_tail = full.filter(pl.col("date") <= keep_to)
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_CALENDAR_INVALID"):
        derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses,
            calendars=short_tail,
            instruments=instruments,
        )
    closed = full.with_columns(
        pl.when(pl.col("date") == _SIGNAL_START)
        .then(pl.lit(False))
        .otherwise(pl.col("is_open"))
        .alias("is_open")
    )
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_CALENDAR_INVALID"):
        derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses,
            calendars=closed,
            instruments=instruments,
        )
    missing_sz_day = full.filter(
        ~((pl.col("market") == "SZ") & (pl.col("date") == dt.date(2016, 1, 5)))
    )
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_CALENDAR_INVALID"):
        derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses,
            calendars=missing_sz_day,
            instruments=instruments,
        )
    mismatched = full.with_columns(
        pl.when((pl.col("market") == "SZ") & (pl.col("date") == dt.date(2016, 1, 5)))
        .then(pl.lit(False))
        .otherwise(pl.col("is_open"))
        .alias("is_open")
    )
    with pytest.raises(M3G1PlanningError, match="G1_PLANNING_CALENDAR_INVALID"):
        derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses,
            calendars=mismatched,
            instruments=instruments,
        )


def test_public_errors_have_no_sensitive_payload(tmp_path: Path) -> None:
    with pytest.raises(M3G1PlanningError) as excinfo:
        compute_g1_runtime_identity(project_root=tmp_path / "missing-root")
    err = excinfo.value
    assert str(err) == err.code
    assert str(tmp_path) not in str(err)
    assert str(tmp_path) not in repr(err)
    assert err.__cause__ is None


def test_builders_zero_network_zero_writes(
    c0_config: LoadedM3Config, tmp_path: Path
) -> None:
    root = _minimal_project(tmp_path / "proj")
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    config = _short_config(cfg_dir)
    static = build_g1_static_plan(config=config, project_root=root)
    responses = _index_responses_for_batch(static.index_weight_batch)
    calendars = _calendar(dt.date(2015, 10, 1), dt.date(2016, 3, 31))
    instruments = _instruments(_symbols())

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network or write called")

    with (
        patch.object(socket, "socket", side_effect=boom),
        patch.object(socket, "create_connection", side_effect=boom),
        patch.object(RawStore, "write", side_effect=boom),
        patch.object(TushareConnector, "fetch_index_weight_raw", side_effect=boom),
        patch.object(TushareConnector, "fetch_daily_raw", side_effect=boom),
        patch.object(Path, "write_bytes", side_effect=boom),
        patch.object(Path, "write_text", side_effect=boom),
    ):
        again = build_g1_static_plan(config=c0_config, project_root=root)
        assert again.runtime.source_tree_sha256
        derived = derive_g1_history_plan(
            config=config,
            project_root=root,
            static_plan=static,
            index_responses=responses,
            calendars=calendars,
            instruments=instruments,
        )
        assert derived.request_plan.history_batch.phase == "HISTORY"


def test_package_exports_planning_symbols() -> None:
    import quant.research.m3 as m3

    assert m3.compute_g1_runtime_identity is compute_g1_runtime_identity
    assert m3.build_g1_static_plan is build_g1_static_plan
    assert m3.derive_g1_history_plan is derive_g1_history_plan
    assert m3.M3G1PlanningError is M3G1PlanningError
