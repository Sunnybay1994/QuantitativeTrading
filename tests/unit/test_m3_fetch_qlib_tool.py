"""D8: 固定版本 Qlib dump 工具获取器（默认不联网）。"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from quant.research.m3.fetch_qlib_tool import (
    build_qlib_dump_tool_spec,
    ensure_qlib_dump_tool,
)
from quant.research.m3.config import load_m3_config
from quant.research.m3.contracts import QlibDumpToolSpec


def test_build_dump_script_spec_from_loaded_m3_config() -> None:
    config = load_m3_config(Path("configs/research/m3_qlib_example.toml"))
    spec = build_qlib_dump_tool_spec(config)
    assert spec.qlib_version == "0.9.7"
    assert spec.size_bytes == 21847
    assert spec.command == "dump_all"
    assert len(spec.sha256) == 64
    assert spec.url.endswith("/scripts/dump_bin.py")


def test_checked_in_dump_tool_matches_frozen_config() -> None:
    """The local offline tool must not drift from its narrow config identity."""
    config = load_m3_config(Path("configs/research/m3_qlib_example.toml"))
    spec = build_qlib_dump_tool_spec(config)
    payload = Path("data/external/qlib/v0.9.7/dump_bin.py").read_bytes()
    assert len(payload) == spec.size_bytes
    assert hashlib.sha256(payload).hexdigest() == spec.sha256


def test_download_validates_and_atomically_moves(tmp_path: Path) -> None:
    payload = b"qlib-dump-bin-fixture-content"
    digest = hashlib.sha256(payload).hexdigest()
    spec = QlibDumpToolSpec(
        url="https://example.invalid/dump_bin.py",
        sha256=digest,
        size_bytes=len(payload),
        qlib_version="0.9.7",
        command="dump_all",
    )
    target = tmp_path / "data" / "external" / "qlib" / "v0.9.7" / "dump_bin.py"

    def fake_opener(_url: str):
        return io.BytesIO(payload)

    path = ensure_qlib_dump_tool(
        spec=spec, target_path=target, opener=fake_opener
    )
    assert path == target
    assert target.read_bytes() == payload
    # 复用
    path2 = ensure_qlib_dump_tool(
        spec=spec, target_path=target, opener=fake_opener
    )
    assert path2 == target


def test_existing_mismatched_file_is_rejected(tmp_path: Path) -> None:
    payload = b"correct-content"
    digest = hashlib.sha256(payload).hexdigest()
    spec = QlibDumpToolSpec(
        url="https://example.invalid/dump_bin.py",
        sha256=digest,
            size_bytes=len(payload),
            qlib_version="0.9.7",
            command="dump_all",
    )
    target = tmp_path / "dump_bin.py"
    target.write_bytes(b"wrong-content")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        ensure_qlib_dump_tool(
            spec=spec,
            target_path=target,
            opener=lambda _url: io.BytesIO(payload),
        )


def test_download_hash_mismatch_rejected(tmp_path: Path) -> None:
    spec = QlibDumpToolSpec(
        url="https://example.invalid/dump_bin.py",
        sha256="a" * 64,
        size_bytes=4,
        qlib_version="0.9.7",
        command="dump_all",
    )
    target = tmp_path / "dump_bin.py"
    with pytest.raises(ValueError, match="校验失败"):
        ensure_qlib_dump_tool(
            spec=spec,
            target_path=target,
            opener=lambda _url: io.BytesIO(b"abcd"),
        )
    assert not target.exists()


def test_existing_matching_hardlink_is_rejected(tmp_path: Path) -> None:
    payload = b"correct-content"
    source = tmp_path / "source.py"
    source.write_bytes(payload)
    target = tmp_path / "dump_bin.py"
    target.hardlink_to(source)
    spec = QlibDumpToolSpec(
        url="https://example.invalid/dump_bin.py",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        qlib_version="0.9.7",
        command="dump_all",
    )
    with pytest.raises(ValueError, match="单链接普通文件"):
        ensure_qlib_dump_tool(spec=spec, target_path=target)


def test_download_race_does_not_overwrite_new_target(tmp_path: Path) -> None:
    payload = b"correct-content"
    target = tmp_path / "dump_bin.py"
    spec = QlibDumpToolSpec(
        url="https://example.invalid/dump_bin.py",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        qlib_version="0.9.7",
        command="dump_all",
    )

    def racing_opener(_url: str) -> io.BytesIO:
        target.write_bytes(b"concurrent-writer")
        return io.BytesIO(payload)

    with pytest.raises(ValueError, match="目标已存在"):
        ensure_qlib_dump_tool(
            spec=spec, target_path=target, opener=racing_opener
        )
    assert target.read_bytes() == b"concurrent-writer"
