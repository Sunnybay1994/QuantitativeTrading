"""M3 编排层的稳定值对象，不依赖 Qlib、LightGBM 或 MLflow。"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

_HEX64 = frozenset("0123456789abcdef")


def _require_bare_hex64(name: str, value: str) -> None:
    if type(value) is not str:
        raise ValueError(f"{name} 必须为 str 类型的裸 64 位小写 hex")
    if len(value) != 64 or any(char not in _HEX64 for char in value):
        raise ValueError(f"{name} 必须为裸 64 位小写 hex")


@dataclass(frozen=True)
class QlibDumpToolSpec:
    """Validated supply-chain identity injected into the Qlib dump fetcher."""

    url: str
    sha256: str
    bytes: int
    version: str

    def __post_init__(self) -> None:
        if not self.url or not self.version:
            raise ValueError("Qlib dump tool URL and version must not be empty")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("Qlib dump tool SHA-256 must be 64 lowercase hexadecimal characters")
        if self.bytes <= 0:
            raise ValueError("Qlib dump tool byte count must be positive")


@dataclass(frozen=True)
class DateSegment:
    """包含首尾交易日的时间段。"""

    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("时间段结束日不得早于开始日")


@dataclass(frozen=True)
class TemporalFold:
    """严格有序且互不重叠的训练、验证、测试折。"""

    name: str
    train: DateSegment
    validation: DateSegment
    test: DateSegment

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("fold 名称不得为空")
        if self.train.end >= self.validation.start:
            raise ValueError("训练段必须早于验证段")
        if self.validation.end >= self.test.start:
            raise ValueError("验证段必须早于测试段")


@dataclass(frozen=True)
class DatasetSnapshot:
    """clean 数据导出后的不可变快照清单摘要。"""

    snapshot_id: str
    manifest_path: Path
    source_fingerprint: str
    row_count: int
    symbol_count: int
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        _require_bare_hex64("snapshot_id", self.snapshot_id)
        _require_bare_hex64("source_fingerprint", self.source_fingerprint)
        if self.row_count <= 0 or self.symbol_count <= 0:
            raise ValueError("快照行数和证券数必须大于 0")
        if self.end < self.start:
            raise ValueError("快照结束日不得早于开始日")
