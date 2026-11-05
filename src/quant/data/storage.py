"""raw/clean Parquet 存储。

raw 快照不可覆盖；clean 是可重建派生层，按交易日分区并按业务键幂等合并。
"""

import datetime as dt
import hashlib
import io
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import polars as pl
from polars.exceptions import PolarsError

from quant.domain import (
    AdjustmentFactorSchema,
    Bar1dSchema,
    ConnectCalendarSchema,
    ConnectEligibilityEventSchema,
    ConnectEligibilitySnapshotSchema,
    InstrumentSchema,
    ResearchPrice1dSchema,
    TradeCalendarSchema,
    UniverseMembershipSchema,
)

_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


def publish_directory(staging: Path, destination: Path, *, staging_root: Path, destination_root: Path) -> None:
    """Publish a complete derived directory, retaining staging on bounded failure."""
    source_parent,target_parent=staging_root.resolve(),destination_root.resolve()
    if (staging.parent.resolve()!=source_parent or destination.parent.resolve()!=target_parent
            or not staging.resolve().is_relative_to(source_parent)
            or not destination.resolve().is_relative_to(target_parent)):
        raise ValueError('Directory publication escapes its intended output roots')
    for attempt in range(11):
        if destination.exists():
            raise FileExistsError('Refuse to replace an existing published directory')
        try:
            staging.rename(destination)
            return
        except PermissionError:
            if attempt==10:
                raise
            time.sleep(.1)


@dataclass(frozen=True)
class RawSnapshot:
    """一次原始响应及其血缘元数据。"""

    snapshot_id: str
    data_path: Path
    metadata_path: Path
    checksum_sha256: str


@dataclass(frozen=True)
class RequestRawSnapshot:
    """A deterministic, immutable raw response written for one request ID."""

    snapshot_id: str
    data_path: Path
    metadata_path: Path
    checksum_sha256: str
    metadata_sha256: str
    size_bytes: int
    row_count: int
    columns: tuple[str, ...]


class RawStore:
    """以内容校验和保存不可变原始响应。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(
        self,
        *,
        source: str,
        table: str,
        frame: pl.DataFrame,
        parameters: dict[str, Any],
        fetched_at: dt.datetime | None = None,
    ) -> RawSnapshot:
        """写入 raw 快照；完全相同的快照重复提交时返回原路径。"""
        _validate_path_part(source)
        _validate_path_part(table)
        timestamp = fetched_at or dt.datetime.now(dt.timezone.utc)
        if timestamp.tzinfo is None:
            raise ValueError("fetched_at 必须包含时区")
        timestamp = timestamp.astimezone(dt.timezone.utc)

        buffer = io.BytesIO()
        frame.write_parquet(buffer)
        payload = buffer.getvalue()
        checksum = hashlib.sha256(payload).hexdigest()
        params_json = json.dumps(parameters, ensure_ascii=False, sort_keys=True, default=str)
        identity = hashlib.sha256(
            f"{timestamp.isoformat()}\n{params_json}\n{checksum}".encode()
        ).hexdigest()
        snapshot_id = f"{timestamp.strftime('%H%M%S.%fZ')}-{identity[:12]}"
        partition = self.root / source / table / f"date={timestamp.date().isoformat()}"
        data_path = partition / f"{snapshot_id}.parquet"
        metadata_path = partition / f"{snapshot_id}.json"

        if data_path.exists() and metadata_path.exists():
            return RawSnapshot(snapshot_id, data_path, metadata_path, checksum)

        partition.mkdir(parents=True, exist_ok=True)
        _write_new(data_path, payload)
        metadata = {
            "snapshot_id": snapshot_id,
            "source": source,
            "table": table,
            "fetched_at": timestamp.isoformat(),
            "parameters": parameters,
            "rows": frame.height,
            "columns": frame.columns,
            "checksum_sha256": checksum,
        }
        _write_new(
            metadata_path,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2, default=str).encode(),
        )
        return RawSnapshot(snapshot_id, data_path, metadata_path, checksum)

    def request_paths(self, *, source: str, table: str, request_id: str) -> tuple[Path, Path]:
        """Return the sole controlled data/metadata paths for a request."""
        _validate_path_part(source)
        _validate_path_part(table)
        if not re.fullmatch(r"[0-9a-f]{64}", request_id):
            raise ValueError("request_id 必须是 64 位小写 SHA-256")
        directory = self.root / source / table / f"request={request_id}"
        return directory / "data.parquet", directory / "metadata.json"

    def inspect_request_state(
        self, *, source: str, table: str, request_id: str
    ) -> Literal["ABSENT", "EMPTY", "COMPLETE"]:
        """Inspect the complete physical layout for one deterministic request."""
        data_path, metadata_path = self.request_paths(
            source=source, table=table, request_id=request_id
        )
        _reject_symlinks(self.root, data_path)
        directory = data_path.parent
        try:
            mode = os.lstat(directory).st_mode
        except FileNotFoundError:
            return "ABSENT"
        except OSError:
            raise ValueError("request raw 目录检查失败") from None
        if not stat.S_ISDIR(mode):
            raise ValueError("request raw request path 必须是实际目录")
        entries = _controlled_request_entries(directory)
        if entries == []:
            return "EMPTY"
        if entries == ["data.parquet", "metadata.json"]:
            return "COMPLETE"
        raise ValueError("request raw 目录文件集合非法或为孤儿")

    def write_request(
        self,
        *,
        source: str,
        table: str,
        request_id: str,
        frame: pl.DataFrame,
        parameters: dict[str, str],
        fetched_at: dt.datetime | None = None,
        after_data_write: Any | None = None,
        after_metadata_write: Any | None = None,
    ) -> RequestRawSnapshot:
        """Create or strictly verify the deterministic raw pair for one request.

        The legacy :meth:`write` API is deliberately untouched.  A one-sided pair
        is evidence of an interrupted write and is never repaired automatically.
        """
        data_path, metadata_path = self.request_paths(
            source=source, table=table, request_id=request_id
        )
        state = self.inspect_request_state(
            source=source, table=table, request_id=request_id
        )
        directory = data_path.parent
        if state == "COMPLETE":
            existing = self.verify_request(
                source=source,
                table=table,
                request_id=request_id,
                parameters=parameters,
            )
            incoming = io.BytesIO()
            try:
                frame.write_parquet(incoming)
            except (OSError, PolarsError):
                raise ValueError("request raw Parquet 序列化失败") from None
            if (
                hashlib.sha256(incoming.getvalue()).hexdigest() != existing.checksum_sha256
                or frame.height != existing.row_count
                or tuple(frame.columns) != existing.columns
            ):
                raise ValueError("同 request_id 的 incoming raw 内容冲突")
            return existing

        timestamp = fetched_at or dt.datetime.now(dt.timezone.utc)
        if timestamp.tzinfo is None:
            raise ValueError("fetched_at 必须包含时区")
        timestamp = timestamp.astimezone(dt.timezone.utc)
        buffer = io.BytesIO()
        try:
            frame.write_parquet(buffer)
        except (OSError, PolarsError):
            raise ValueError("request raw Parquet 序列化失败") from None
        payload = buffer.getvalue()
        checksum = hashlib.sha256(payload).hexdigest()
        metadata = {
            "schema_version": "request-raw-v1",
            "snapshot_id": request_id,
            "source": source,
            "table": table,
            "request_id": request_id,
            "fetched_at": timestamp.isoformat(),
            "parameters": parameters,
            "rows": frame.height,
            "columns": frame.columns,
            "checksum_sha256": checksum,
            "size_bytes": len(payload),
        }
        metadata_payload = json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ValueError("request raw 目录创建失败") from None
        if self.inspect_request_state(
            source=source, table=table, request_id=request_id
        ) != "EMPTY":
            raise ValueError("request raw 首次写入前目录状态冲突")
        _write_new_strict(data_path, payload)
        if after_data_write is not None:
            after_data_write()
        _write_new_strict(metadata_path, metadata_payload)
        if after_metadata_write is not None:
            after_metadata_write()
        return self.verify_request(
            source=source,
            table=table,
            request_id=request_id,
            parameters=parameters,
        )

    def verify_request(
        self,
        *,
        source: str,
        table: str,
        request_id: str,
        parameters: dict[str, str],
    ) -> RequestRawSnapshot:
        """Strictly re-read a deterministic request raw pair from disk."""
        snapshot, _ = self.verify_request_bundle(
            source=source,
            table=table,
            request_id=request_id,
            parameters=parameters,
        )
        return snapshot

    def verify_request_bundle(
        self,
        *,
        source: str,
        table: str,
        request_id: str,
        parameters: dict[str, str],
    ) -> tuple[RequestRawSnapshot, pl.DataFrame]:
        """Return a snapshot and frame verified from the same captured raw bytes."""
        data_path, metadata_path = self.request_paths(
            source=source, table=table, request_id=request_id
        )
        if self.inspect_request_state(
            source=source, table=table, request_id=request_id
        ) != "COMPLETE":
            raise ValueError("request raw 完整证据不存在")
        try:
            payload = data_path.read_bytes()
            metadata_payload = metadata_path.read_bytes()
        except OSError:
            raise ValueError("request raw 文件读取失败") from None
        metadata = _strict_json_object(metadata_payload)
        expected_keys = {
            "schema_version", "snapshot_id", "source", "table", "request_id",
            "fetched_at", "parameters", "rows", "columns", "checksum_sha256",
            "size_bytes",
        }
        if set(metadata) != expected_keys:
            raise ValueError("request raw metadata 字段集合非法")
        if (
            metadata["schema_version"] != "request-raw-v1"
            or metadata["snapshot_id"] != request_id
            or metadata["request_id"] != request_id
            or metadata["source"] != source
            or metadata["table"] != table
            or metadata["parameters"] != parameters
        ):
            raise ValueError("request raw metadata 与请求不一致")
        if type(metadata["rows"]) is not int or type(metadata["size_bytes"]) is not int:
            raise ValueError("request raw metadata 数值类型非法")
        if type(metadata["fetched_at"]) is not str:
            raise ValueError("request raw fetched_at 类型非法")
        try:
            fetched_at = dt.datetime.fromisoformat(metadata["fetched_at"])
        except ValueError as exc:
            raise ValueError("request raw fetched_at 非法") from exc
        if fetched_at.tzinfo is None:
            raise ValueError("request raw fetched_at 缺少时区")
        if not isinstance(metadata["columns"], list) or not all(
            type(value) is str for value in metadata["columns"]
        ):
            raise ValueError("request raw metadata columns 非法")
        checksum = hashlib.sha256(payload).hexdigest()
        if metadata["checksum_sha256"] != checksum or metadata["size_bytes"] != len(payload):
            raise ValueError("request raw 文件 hash/大小不一致")
        try:
            frame = pl.read_parquet(io.BytesIO(payload))
        except (OSError, PolarsError):
            raise ValueError("request raw Parquet 无法读取") from None
        if frame.height != metadata["rows"] or frame.columns != metadata["columns"]:
            raise ValueError("request raw Parquet 行列与 metadata 不一致")
        snapshot = RequestRawSnapshot(
            snapshot_id=request_id,
            data_path=data_path,
            metadata_path=metadata_path,
            checksum_sha256=checksum,
            metadata_sha256=hashlib.sha256(metadata_payload).hexdigest(),
            size_bytes=len(payload),
            row_count=frame.height,
            columns=tuple(frame.columns),
        )
        return snapshot, frame


class CleanBarStore:
    """按交易日保存通过契约的 bar_1d，重复更新按业务键覆盖。"""

    key = ["symbol", "trade_date", "source"]

    def __init__(self, root: Path) -> None:
        self.root = root

    def upsert(self, frame: pl.DataFrame) -> int:
        """幂等写入日线并返回本次输入行数。"""
        validated = Bar1dSchema.validate(frame)
        self.root.mkdir(parents=True, exist_ok=True)
        for trade_date in validated.get_column("trade_date").unique().sort().to_list():
            incoming = validated.filter(pl.col("trade_date") == trade_date)
            target = self.root / f"date={trade_date.isoformat()}" / "data.parquet"
            if target.exists():
                incoming = pl.concat([pl.read_parquet(target), incoming], how="vertical_relaxed")
            merged = incoming.unique(subset=self.key, keep="last", maintain_order=True).sort(self.key)
            Bar1dSchema.validate(merged)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp.parquet")
            merged.write_parquet(temporary)
            temporary.replace(target)
        return validated.height


class CleanCalendarStore:
    """按市场幂等保存交易日历。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def upsert(self, frame: pl.DataFrame) -> int:
        validated = TradeCalendarSchema.validate(frame)
        for market in validated.get_column("market").unique().to_list():
            incoming = validated.filter(pl.col("market") == market)
            target = self.root / f"market={market}" / "data.parquet"
            if target.exists():
                incoming = pl.concat([pl.read_parquet(target), incoming], how="vertical_relaxed")
            merged = incoming.unique(subset=["market", "date"], keep="last").sort("date")
            TradeCalendarSchema.validate(merged)
            _replace_parquet(target, merged)
        return validated.height


class CleanInstrumentStore:
    """按市场幂等保存可交易证券主表。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def upsert(self, frame: pl.DataFrame) -> int:
        validated = InstrumentSchema.validate(frame)
        for market in validated.get_column("market").unique().to_list():
            incoming = validated.filter(pl.col("market") == market)
            target = self.root / f"market={market}" / "data.parquet"
            if target.exists():
                incoming = pl.concat([pl.read_parquet(target), incoming], how="vertical_relaxed")
            merged = incoming.unique(subset=["symbol"], keep="last").sort("symbol")
            InstrumentSchema.validate(merged)
            _replace_parquet(target, merged)
        return validated.height


class CleanAdjustmentFactorStore:
    """按数据源幂等保存累计后复权因子。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def upsert(self, frame: pl.DataFrame) -> int:
        validated = AdjustmentFactorSchema.validate(frame)
        for source in validated.get_column("source").unique().to_list():
            incoming = validated.filter(pl.col("source") == source)
            target = self.root / f"source={source}" / "data.parquet"
            if target.exists():
                existing = pl.read_parquet(target).filter(
                    ~pl.col("symbol").is_in(incoming.get_column("symbol").unique())
                )
                incoming = pl.concat([existing, incoming], how="vertical_relaxed")
            merged = incoming.unique(
                subset=["symbol", "effective_date", "source"], keep="last"
            ).sort(["symbol", "effective_date"])
            AdjustmentFactorSchema.validate(merged)
            _replace_parquet(target, merged)
        return validated.height


class CleanResearchPriceStore:
    """按交易日保存研究专用调整收盘价。"""

    key = ["symbol", "trade_date"]

    def __init__(self, root: Path) -> None:
        self.root = root

    def upsert(self, frame: pl.DataFrame) -> int:
        validated = ResearchPrice1dSchema.validate(frame)
        for trade_date in validated.get_column("trade_date").unique().sort().to_list():
            incoming = validated.filter(pl.col("trade_date") == trade_date)
            target = self.root / f"date={trade_date.isoformat()}" / "data.parquet"
            if target.exists():
                incoming = pl.concat(
                    [pl.read_parquet(target), incoming], how="vertical_relaxed"
                )
            merged = incoming.unique(
                subset=self.key, keep="last", maintain_order=True
            ).sort(self.key)
            ResearchPrice1dSchema.validate(merged)
            _replace_parquet(target, merged)
        return validated.height


class CleanConnectSnapshotStore:
    """按路由和快照日保存港股通名单，不覆盖旧快照。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def upsert(self, frame: pl.DataFrame) -> int:
        validated = ConnectEligibilitySnapshotSchema.validate(frame)
        for route, snapshot_date in validated.select("route", "snapshot_date").unique().iter_rows():
            incoming = validated.filter(
                (pl.col("route") == route) & (pl.col("snapshot_date") == snapshot_date)
            )
            target = self.root / f"route={route}" / f"date={snapshot_date}" / "data.parquet"
            _replace_parquet(target, incoming.sort("symbol"))
        return validated.height

    def read_route_date(self, *, route: str, snapshot_date: dt.date) -> pl.DataFrame:
        """显式只读单一 route+date 快照；不做全盘/legacy 发现。"""
        _validate_path_part(route)
        if type(snapshot_date) is not dt.date:
            raise ValueError("snapshot_date 必须是 exact date")
        target = (
            self.root / f"route={route}" / f"date={snapshot_date.isoformat()}" / "data.parquet"
        )
        return _read_clean_parquet_guarded(
            self.root, target, ConnectEligibilitySnapshotSchema
        )


class CleanConnectEventStore:
    """幂等保存官方标的调整事件。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def upsert(self, frame: pl.DataFrame) -> int:
        validated = ConnectEligibilityEventSchema.validate(frame)
        for route in validated.get_column("route").unique().to_list():
            incoming = validated.filter(pl.col("route") == route)
            target = self.root / f"route={route}" / "data.parquet"
            if target.exists():
                incoming = pl.concat([pl.read_parquet(target), incoming], how="vertical_relaxed")
            merged = incoming.unique(
                subset=["route", "effective_date", "symbol", "action"], keep="last"
            ).sort(["effective_date", "symbol"])
            ConnectEligibilityEventSchema.validate(merged)
            _replace_parquet(target, merged)
        return validated.height

    def read_route(self, *, route: str) -> pl.DataFrame:
        """显式只读单一 route 事件；不做全盘/legacy 发现。"""
        _validate_path_part(route)
        target = self.root / f"route={route}" / "data.parquet"
        return _read_clean_parquet_guarded(
            self.root, target, ConnectEligibilityEventSchema
        )

    def replace_route(self, frame: pl.DataFrame) -> int:
        """原子替换单一 route 的 clean 事件；不 concat 旧文件。"""
        validated = ConnectEligibilityEventSchema.validate(frame)
        if validated.height == 0:
            raise ValueError("replace_route 要求非空 frame")
        routes = validated.get_column("route").unique().to_list()
        if len(routes) != 1:
            raise ValueError("replace_route 要求恰好一个 route")
        route = str(routes[0])
        _validate_path_part(route)
        selected = validated.sort(["effective_date", "symbol", "action"])
        target = self.root / f"route={route}" / "data.parquet"
        _replace_parquet_guarded(self.root, target, selected)
        reread = pl.read_parquet(target)
        ConnectEligibilityEventSchema.validate(reread)
        key_cols = ["effective_date", "symbol", "action"]
        expected = set(selected.select(key_cols).iter_rows())
        actual = set(reread.select(key_cols).iter_rows())
        if reread.height != selected.height or actual != expected:
            raise ValueError("replace_route 写后校验失败")
        return selected.height


class CleanConnectCalendarStore:
    """按路由幂等保存港股通交易日历。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def upsert(self, frame: pl.DataFrame) -> int:
        validated = ConnectCalendarSchema.validate(frame)
        for route in validated.get_column("route").unique().to_list():
            incoming = validated.filter(pl.col("route") == route)
            target = self.root / f"route={route}" / "data.parquet"
            if target.exists():
                incoming = pl.concat([pl.read_parquet(target), incoming], how="vertical_relaxed")
            merged = incoming.unique(subset=["route", "date"], keep="last").sort("date")
            ConnectCalendarSchema.validate(merged)
            _replace_parquet(target, merged)
        return validated.height


class CleanUniverseMembershipStore:
    """保存可重建的历史股票池区间；每次按 universe 原子替换。"""

    _CONNECT_UNIVERSES = frozenset({"SH_CONNECT", "SZ_CONNECT"})

    def __init__(self, root: Path) -> None:
        self.root = root

    def replace(self, frame: pl.DataFrame) -> int:
        validated = UniverseMembershipSchema.validate(frame)
        for universe in validated.get_column("universe").unique().to_list():
            target = self.root / f"universe={universe}" / "data.parquet"
            selected = validated.filter(pl.col("universe") == universe).sort(
                ["symbol", "effective_from"]
            )
            _replace_parquet(target, selected)
        return validated.height

    def replace_universe(self, frame: pl.DataFrame) -> int:
        """原子替换单一 SH/SZ_CONNECT universe；不 concat 旧文件。"""
        validated = UniverseMembershipSchema.validate(frame)
        if validated.height == 0:
            raise ValueError("replace_universe 要求非空 frame")
        universes = validated.get_column("universe").unique().to_list()
        if len(universes) != 1:
            raise ValueError("replace_universe 要求恰好一个 universe")
        universe = str(universes[0])
        if universe not in self._CONNECT_UNIVERSES:
            raise ValueError("replace_universe 只允许 SH_CONNECT/SZ_CONNECT")
        _validate_path_part(universe)
        selected = validated.sort(["symbol", "effective_from"])
        target = self.root / f"universe={universe}" / "data.parquet"
        _replace_parquet_guarded(self.root, target, selected)
        reread = pl.read_parquet(target)
        UniverseMembershipSchema.validate(reread)
        key_cols = ["universe", "symbol", "effective_from", "effective_to"]
        expected = set(selected.select(key_cols).iter_rows())
        actual = set(reread.select(key_cols).iter_rows())
        if reread.height != selected.height or actual != expected:
            raise ValueError("replace_universe 写后校验失败")
        return selected.height


def _write_new(path: Path, payload: bytes) -> None:
    """独占创建文件，绝不覆盖既有 raw 资产。"""
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        return


def _write_new_strict(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        raise ValueError("不可覆盖既有 request raw 证据") from None
    except OSError:
        raise ValueError("request raw 文件创建失败") from None


def _strict_json_object(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8", errors="strict")

        def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in values:
                if key in result:
                    raise ValueError("JSON 含重复字段")
                result[key] = value
            return result

        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("JSON 非 finite")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("request raw metadata 不是严格 UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise ValueError("request raw metadata 必须是对象")
    return value


def _reject_symlinks(root: Path, target: Path) -> None:
    _validate_controlled_root(root)
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("request raw 路径逃逸") from None
    cursor = root
    parts = target.relative_to(root).parts
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            mode = os.lstat(cursor).st_mode
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError("request raw 路径检查失败") from None
        if stat.S_ISLNK(mode):
            raise ValueError("request raw 路径不得包含 symlink")
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise ValueError("request raw 路径祖先必须是目录")


def _controlled_request_entries(directory: Path) -> list[str]:
    try:
        entries = list(directory.iterdir())
        if any(not stat.S_ISREG(os.lstat(path).st_mode) for path in entries):
            raise ValueError("request raw 目录只能包含受控普通文件")
        return sorted(path.name for path in entries)
    except ValueError:
        raise
    except OSError:
        raise ValueError("request raw 目录检查失败") from None


def _validate_controlled_root(root: Path) -> None:
    try:
        absolute = Path(os.path.abspath(root))
        for path in reversed((absolute, *absolute.parents)):
            try:
                mode = os.lstat(path).st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                raise ValueError("受控 raw root 祖先不得是 symlink")
            if not stat.S_ISDIR(mode):
                raise ValueError("受控 raw root 祖先必须是目录")
    except ValueError:
        raise
    except (OSError, TypeError):
        raise ValueError("受控 raw root 非法") from None


def _validate_path_part(value: str) -> None:
    if not _SAFE_PART.fullmatch(value):
        raise ValueError(f"非法路径分段: {value}")


def _replace_parquet(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.parquet")
    frame.write_parquet(temporary)
    temporary.replace(path)


def _assert_safe_clean_replace_target(root: Path, target: Path) -> None:
    """Fail-closed：拒绝 symlink 祖先/目标与非普通文件目标，不跟随到外部。"""
    _validate_controlled_root(root)
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise ValueError("clean 路径逃逸受控 root") from None
    cursor = root
    parts = relative.parts
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            mode = os.lstat(cursor).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("clean 路径检查失败") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("clean 路径不得包含 symlink")
        is_last = index == len(parts) - 1
        if is_last:
            if not stat.S_ISREG(mode):
                raise ValueError("clean 替换目标必须是普通文件")
        elif not stat.S_ISDIR(mode):
            raise ValueError("clean 路径祖先必须是目录")


def _assert_safe_clean_read_target(root: Path, target: Path) -> None:
    """Fail-closed 只读：目标与受控祖先必须存在且非 symlink；目标必须是普通文件。"""
    _validate_controlled_root(root)
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise ValueError("clean 路径逃逸受控 root") from None
    cursor = root
    parts = relative.parts
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            mode = os.lstat(cursor).st_mode
        except FileNotFoundError as exc:
            raise ValueError("clean 读取目标不存在") from exc
        except OSError as exc:
            raise ValueError("clean 路径检查失败") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("clean 路径不得包含 symlink")
        is_last = index == len(parts) - 1
        if is_last:
            if not stat.S_ISREG(mode):
                raise ValueError("clean 读取目标必须是普通文件")
        elif not stat.S_ISDIR(mode):
            raise ValueError("clean 路径祖先必须是目录")


def _read_clean_parquet_guarded(
    root: Path,
    target: Path,
    schema: type[Any],
) -> pl.DataFrame:
    """受控只读 parquet；不跟随 symlink，Schema 非法时稳定失败。"""
    _assert_safe_clean_read_target(root, target)
    try:
        frame = pl.read_parquet(target)
    except (OSError, PolarsError):
        raise ValueError("clean Parquet 读取失败") from None
    try:
        return schema.validate(frame)
    except Exception:
        raise ValueError("clean Schema 校验失败") from None


def _replace_parquet_guarded(root: Path, path: Path, frame: pl.DataFrame) -> None:
    """受控原子替换 parquet；目标或祖先为 symlink/非普通文件时拒绝写入。"""
    _assert_safe_clean_replace_target(root, path)
    parent = path.parent
    try:
        parent_mode = os.lstat(parent).st_mode
    except FileNotFoundError:
        parent.mkdir(parents=True, exist_ok=True)
        _assert_safe_clean_replace_target(root, path)
        parent_mode = os.lstat(parent).st_mode
    except OSError as exc:
        raise ValueError("clean 父目录检查失败") from exc
    if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
        raise ValueError("clean 父目录必须是普通目录")
    temporary = path.with_suffix(".tmp.parquet")
    try:
        tmp_mode = os.lstat(temporary).st_mode
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ValueError("clean 临时文件路径检查失败") from exc
    else:
        if stat.S_ISLNK(tmp_mode) or not stat.S_ISREG(tmp_mode):
            raise ValueError("clean 临时文件路径非法")
    frame.write_parquet(temporary)
    try:
        written_mode = os.lstat(temporary).st_mode
    except OSError as exc:
        raise ValueError("clean 临时文件写后检查失败") from exc
    if stat.S_ISLNK(written_mode) or not stat.S_ISREG(written_mode):
        raise ValueError("clean 临时文件写后非法")
    _assert_safe_clean_replace_target(root, path)
    try:
        os.replace(temporary, path)
    except OSError as exc:
        raise ValueError("clean 原子替换失败") from exc
    try:
        final_mode = os.lstat(path).st_mode
    except OSError as exc:
        raise ValueError("clean 写后目标检查失败") from exc
    if stat.S_ISLNK(final_mode) or not stat.S_ISREG(final_mode):
        raise ValueError("clean 写后目标非法")
