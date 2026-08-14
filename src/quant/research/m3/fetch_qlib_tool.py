"""固定版本 Qlib dump_bin.py 获取器：校验 URL/字节数/SHA-256 后原子落盘。"""

from __future__ import annotations

import hashlib
import os
import stat
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
        size_bytes=cast(int, qlib["dump_script_bytes"]),
        qlib_version=cast(Any, qlib["version"]),
        command="dump_all",
    )


def ensure_qlib_dump_tool(
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
    expected_bytes = spec.size_bytes
    url = spec.url

    if os.path.lexists(target_path):
        _require_no_reparse_chain(target_path)
        status = os.lstat(target_path)
        attributes = getattr(status, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1
            or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"已存在的 {target_path} 不是可信单链接普通文件，拒绝复用")
        payload = target_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) == expected_bytes and digest == expected_sha:
            return target_path
        raise ValueError(
            f"已存在的 {target_path} 与配置校验不一致，拒绝覆盖："
            f"size={len(payload)} sha256={digest}"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    _require_no_reparse_chain(target_path.parent)
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
    try:
        os.link(tmp_path, target_path)
    except FileExistsError:
        raise ValueError(f"发布 {target_path} 时目标已存在，拒绝覆盖") from None
    except OSError:
        raise ValueError(f"发布 {target_path} 时无法执行原子 no-clobber") from None
    finally:
        tmp_path.unlink(missing_ok=True)
    return target_path


def _require_no_reparse_chain(path: Path) -> None:
    for candidate in (path, *path.parents):
        try:
            status = os.lstat(candidate)
        except FileNotFoundError:
            continue
        attributes = getattr(status, "st_file_attributes", 0)
        if stat.S_ISLNK(status.st_mode) or (
            attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("Qlib dump tool 路径包含 symlink/reparse point")

