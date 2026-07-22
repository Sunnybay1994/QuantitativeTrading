"""D8: 固定版本 Qlib dump 工具获取器（默认不联网）。"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from quant.research.m3.fetch_qlib_tool import (
    build_qlib_dump_tool_spec,
    ensure_qlib_dump_script,
)
from quant.research.m3.config import load_m3_config
from quant.research.m3.contracts import QlibDumpToolSpec


def test_build_dump_script_spec_from_loaded_m3_config() -> None:
    config = load_m3_config(Path("configs/research/m3_qlib_example.toml"))
    spec = build_qlib_dump_tool_spec(config)
    assert spec.version == "0.9.7"
    assert spec.bytes == 21847
    assert len(spec.sha256) == 64
    assert spec.url.endswith("/scripts/dump_bin.py")


def test_download_validates_and_atomically_moves(tmp_path: Path) -> None:
    payload = b"qlib-dump-bin-fixture-content"
    digest = hashlib.sha256(payload).hexdigest()
    spec = QlibDumpToolSpec(
        url="https://example.invalid/dump_bin.py",
        sha256=digest,
        bytes=len(payload),
        version="0.9.7",
    )
    target = tmp_path / "data" / "external" / "qlib" / "v0.9.7" / "dump_bin.py"

    def fake_opener(_url: str):
        return io.BytesIO(payload)

    path = ensure_qlib_dump_script(
        spec=spec, target_path=target, opener=fake_opener
    )
    assert path == target
    assert target.read_bytes() == payload
    # 复用
    path2 = ensure_qlib_dump_script(
        spec=spec, target_path=target, opener=fake_opener
    )
    assert path2 == target


def test_existing_mismatched_file_is_rejected(tmp_path: Path) -> None:
    payload = b"correct-content"
    digest = hashlib.sha256(payload).hexdigest()
    spec = QlibDumpToolSpec(
        url="https://example.invalid/dump_bin.py",
        sha256=digest,
        bytes=len(payload),
        version="0.9.7",
    )
    target = tmp_path / "dump_bin.py"
    target.write_bytes(b"wrong-content")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        ensure_qlib_dump_script(
            spec=spec,
            target_path=target,
            opener=lambda _url: io.BytesIO(payload),
        )


def test_download_hash_mismatch_rejected(tmp_path: Path) -> None:
    spec = QlibDumpToolSpec(
        url="https://example.invalid/dump_bin.py",
        sha256="a" * 64,
        bytes=4,
        version="0.9.7",
    )
    target = tmp_path / "dump_bin.py"
    with pytest.raises(ValueError, match="校验失败"):
        ensure_qlib_dump_script(
            spec=spec,
            target_path=target,
            opener=lambda _url: io.BytesIO(b"abcd"),
        )
    assert not target.exists()
