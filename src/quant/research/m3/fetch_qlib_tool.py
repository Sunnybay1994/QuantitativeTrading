"""固定版本 Qlib dump_bin.py 获取器：校验 URL/字节数/SHA-256 后原子落盘。"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.request import urlopen

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import QlibDumpToolSpec

DEFAULT_TARGET_PATH = Path("data/external/qlib/v0.9.7/dump_bin.py")


def build_qlib_dump_tool_spec(config: LoadedM3Config) -> QlibDumpToolSpec:
    """Map the one validated runtime section into the provider tool contract."""
    qlib = cast(dict[str, Any], config.section("runtime")["qlib"])
    return QlibDumpToolSpec(
        url=cast(str, qlib["dump_script_url"]),
        sha256=cast(str, qlib["dump_script_sha256"]),
        bytes=cast(int, qlib["dump_script_bytes"]),
        version=cast(str, qlib["version"]),
    )


def ensure_qlib_dump_script(
    *,
    spec: QlibDumpToolSpec,
    target_path: Path = DEFAULT_TARGET_PATH,
    opener: Callable[[str], Any] = urlopen,
) -> Path:
    """确保本地存在 hash 匹配的 dump_bin.py。

    - 已存在且 hash/字节数匹配：复用；
    - 已存在但不匹配：拒绝，禁止静默覆盖；
    - 不存在：下载到临时文件，三项全部匹配后再原子移动。
    """
    expected_sha = spec.sha256
    expected_bytes = spec.bytes
    url = spec.url

    if target_path.exists():
        payload = target_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) == expected_bytes and digest == expected_sha:
            return target_path
        raise ValueError(
            f"已存在的 {target_path} 与配置校验不一致，拒绝覆盖："
            f"size={len(payload)} sha256={digest}"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target_path.parent, delete=False, prefix=".dump_bin.", suffix=".tmp"
    ) as tmp:
        tmp_path = Path(tmp.name)
        try:
            with opener(url) as response:
                while True:
                    chunk = response.read(1024 * 64)
                    if not chunk:
                        break
                    tmp.write(chunk)
            tmp.flush()
            os.fsync(tmp.fileno())
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    payload = tmp_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != expected_bytes or digest != expected_sha:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(
            f"下载内容校验失败: size={len(payload)} sha256={digest}; "
            f"expected size={expected_bytes} sha256={expected_sha}"
        )
    os.replace(tmp_path, target_path)
    return target_path

