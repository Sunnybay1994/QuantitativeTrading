"""M3 运行身份与 stage receipt（纯标准库）。

Identity key 的 join 格式：对字段值组成的 JSON 数组做 UTF-8 编码后求 SHA-256，
输出裸 64 位小写 hex（无 ``sha256:`` 前缀）。例如 provider_key 的输入为::

    json.dumps(
        [
            snapshot_id,
            provider_config_hash,
            dump_tool_sha256,
            qlib_version,
            provider_runtime_fingerprint_sha256,
            code_version,
        ],
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )

receipt JSON 使用 ``sort_keys=True``，不含时间戳、绝对路径或机器信息。
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

Scope = Literal[
    "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
]
_SCOPES = frozenset(
    {"SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"}
)
_RECEIPT_VERSION: Literal["m3-stage-receipt-v1"] = "m3-stage-receipt-v1"
_TOP_LEVEL_KEYS = (
    "receipt_version",
    "stage",
    "scope",
    "scope_key",
    "inputs",
    "outputs",
)
_DIGEST_KEYS = ("root_alias", "relative_path", "size_bytes", "sha256")
_HEX64 = frozenset("0123456789abcdef")
_FS_UNSUPPORTED = frozenset(
    {
        errno.EINVAL,
        errno.ENOTSUP,
        getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
    }
)


@dataclass(frozen=True)
class ArtifactDigest:
    root_alias: str
    relative_path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_alias(self.root_alias)
        _validate_relative_posix(self.relative_path)
        if type(self.size_bytes) is not int or isinstance(self.size_bytes, bool):
            raise ValueError("size_bytes 必须为非负精确 int")
        if self.size_bytes < 0:
            raise ValueError("size_bytes 必须为非负精确 int")
        _require_bare_hex64("sha256", self.sha256)


@dataclass(frozen=True, kw_only=True)
class StageReceipt:
    receipt_version: Literal["m3-stage-receipt-v1"] = "m3-stage-receipt-v1"
    stage: str
    scope: Scope
    scope_key: str
    inputs: tuple[ArtifactDigest, ...]
    outputs: tuple[ArtifactDigest, ...]

    def __post_init__(self) -> None:
        if self.receipt_version != _RECEIPT_VERSION:
            raise ValueError("未知 receipt_version")
        _validate_stage(self.stage)
        _require_scope(self.scope)
        _require_bare_hex64("scope_key", self.scope_key)
        _validate_digest_tuple(self.inputs, label="inputs")
        _validate_digest_tuple(self.outputs, label="outputs")
        input_keys = {_digest_sort_key(item) for item in self.inputs}
        output_keys = {_digest_sort_key(item) for item in self.outputs}
        overlap = input_keys & output_keys
        if overlap:
            alias, relative = next(iter(sorted(overlap)))
            raise ValueError(f"inputs/outputs 交叉重复 (alias,path): {alias},{relative}")


def compute_snapshot_request_key(
    *,
    g1_release_id: str,
    g1_release_manifest_sha256: str,
    snapshot_config_sha256: str,
    code_version: str,
) -> str:
    """裸 hex SHA-256(JSON 数组 [g1_release_id, g1_release_manifest_sha256, snapshot_config_sha256, code_version])。"""
    return _identity_key(
        [
            _require_bare_hex64("g1_release_id", g1_release_id),
            _require_bare_hex64(
                "g1_release_manifest_sha256", g1_release_manifest_sha256
            ),
            _require_bare_hex64("snapshot_config_sha256", snapshot_config_sha256),
            _require_stable_version("code_version", code_version),
        ]
    )


def compute_provider_key(
    *,
    snapshot_id: str,
    provider_config_hash: str,
    dump_tool_sha256: str,
    qlib_version: str,
    provider_runtime_fingerprint_sha256: str,
    code_version: str,
) -> str:
    """裸 hex SHA-256(JSON 数组 provider identity 字段)。"""
    return _identity_key(
        [
            _require_bare_hex64("snapshot_id", snapshot_id),
            _require_bare_hex64("provider_config_hash", provider_config_hash),
            _require_bare_hex64("dump_tool_sha256", dump_tool_sha256),
            _require_stable_version("qlib_version", qlib_version),
            _require_bare_hex64(
                "provider_runtime_fingerprint_sha256",
                provider_runtime_fingerprint_sha256,
            ),
            _require_stable_version("code_version", code_version),
        ]
    )


def compute_provider_validation_key(
    *,
    provider_key: str,
    provider_receipt_sha256: str,
    provider_validation_config_sha256: str,
    provider_runtime_fingerprint_sha256: str,
    code_version: str,
) -> str:
    """裸 hex SHA-256(JSON 数组 provider-validation identity 字段)。"""
    return _identity_key(
        [
            _require_bare_hex64("provider_key", provider_key),
            _require_bare_hex64("provider_receipt_sha256", provider_receipt_sha256),
            _require_bare_hex64(
                "provider_validation_config_sha256",
                provider_validation_config_sha256,
            ),
            _require_bare_hex64(
                "provider_runtime_fingerprint_sha256",
                provider_runtime_fingerprint_sha256,
            ),
            _require_stable_version("code_version", code_version),
        ]
    )


def compute_experiment_key(
    *,
    snapshot_id: str,
    provider_receipt_sha256: str,
    scientific_config_hash: str,
    code_version: str,
    dependency_fingerprint_sha256: str,
) -> str:
    """裸 hex SHA-256(JSON 数组 experiment identity 字段)。"""
    return _identity_key(
        [
            _require_bare_hex64("snapshot_id", snapshot_id),
            _require_bare_hex64("provider_receipt_sha256", provider_receipt_sha256),
            _require_bare_hex64("scientific_config_hash", scientific_config_hash),
            _require_stable_version("code_version", code_version),
            _require_bare_hex64(
                "dependency_fingerprint_sha256", dependency_fingerprint_sha256
            ),
        ]
    )


def compute_label_reconciliation_key(
    *,
    experiment_key: str,
    horizon: int,
    provider_validation_receipt_sha256: str,
    label_manifest_sha256: str,
    label_reconciliation_config_sha256: str,
    dependency_fingerprint_sha256: str,
    code_version: str,
) -> str:
    """裸 hex SHA-256(JSON 数组 label-reconciliation identity 字段)。"""
    return _identity_key(
        [
            _require_bare_hex64("experiment_key", experiment_key),
            _require_positive_horizon(horizon),
            _require_bare_hex64(
                "provider_validation_receipt_sha256",
                provider_validation_receipt_sha256,
            ),
            _require_bare_hex64("label_manifest_sha256", label_manifest_sha256),
            _require_bare_hex64(
                "label_reconciliation_config_sha256",
                label_reconciliation_config_sha256,
            ),
            _require_bare_hex64(
                "dependency_fingerprint_sha256", dependency_fingerprint_sha256
            ),
            _require_stable_version("code_version", code_version),
        ]
    )


def compute_work_key(*, experiment_key: str, fold: str, horizon: int) -> str:
    """裸 hex SHA-256(JSON 数组 [experiment_key, fold, horizon])。"""
    return _identity_key(
        [
            _require_bare_hex64("experiment_key", experiment_key),
            _require_fold(fold),
            _require_positive_horizon(horizon),
        ]
    )


def verify_stage_receipt(
    *,
    receipt_path: Path,
    artifact_roots: Mapping[str, Path],
) -> StageReceipt | None:
    """缺文件返回 None；损坏/不一致抛错；验真通过返回 StageReceipt。"""
    roots = _validate_artifact_roots(artifact_roots)
    _assert_receipt_contained(receipt_path, roots)
    parent = receipt_path.parent
    _assert_existing_dir_no_symlink_chain(parent, label="receipt_parent")

    try:
        leaf_st = os.lstat(receipt_path)
    except FileNotFoundError:
        return None
    except OSError:
        raise ValueError("receipt 不可读") from None

    if stat.S_ISLNK(leaf_st.st_mode):
        raise ValueError("receipt 为 symlink")
    if not stat.S_ISREG(leaf_st.st_mode):
        raise ValueError("receipt 非普通文件")

    try:
        raw = Path(receipt_path).read_bytes()
    except OSError:
        raise ValueError("receipt 不可读") from None

    receipt = _parse_receipt_bytes(raw)
    _assert_context_consistency(receipt, roots, receipt_path=receipt_path)
    for digest in (*receipt.inputs, *receipt.outputs):
        _verify_digest_bytes(digest, roots)
    return receipt


def publish_stage_receipt(
    *,
    receipt_path: Path,
    stage: str,
    scope: Scope,
    scope_key: str,
    artifact_roots: Mapping[str, Path],
    inputs: Sequence[tuple[str, Path]],
    outputs: Sequence[tuple[str, Path]],
) -> StageReceipt:
    """构建并以原子 no-clobber 发布 stage receipt；相同内容验真后复用，冲突拒绝。"""
    _require_scope(scope)

    roots = _validate_artifact_roots(artifact_roots)
    _assert_receipt_publish_location(receipt_path, roots)

    input_digests = _digests_from_paths(inputs, roots, label="inputs")
    output_digests = _digests_from_paths(outputs, roots, label="outputs")
    receipt = StageReceipt(
        stage=stage,
        scope=scope,
        scope_key=scope_key,
        inputs=tuple(sorted(input_digests, key=_digest_sort_key)),
        outputs=tuple(sorted(output_digests, key=_digest_sort_key)),
    )
    _assert_context_consistency(receipt, roots, receipt_path=receipt_path)
    encoded = _canonical_receipt_bytes(receipt)

    existing_state = _receipt_leaf_state(receipt_path)
    if existing_state == "file":
        return _reuse_existing_receipt(
            receipt_path=receipt_path,
            encoded=encoded,
            artifact_roots=roots,
            receipt=receipt,
        )
    if existing_state == "symlink":
        raise ValueError("receipt 为 symlink")
    if existing_state == "other":
        raise ValueError("receipt 非普通文件")

    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{receipt_path.name}.",
            suffix=".tmp",
            dir=str(receipt_path.parent),
        )
    except OSError:
        raise ValueError("receipt 临时文件创建失败") from None

    tmp_path = Path(tmp_name)
    primary_error: BaseException | None = None
    close_fd: int | None = fd
    try:
        try:
            handle = os.fdopen(fd, "wb")
            close_fd = None
        except OSError:
            raise ValueError("receipt 临时文件写入失败") from None
        with handle:
            try:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            except OSError:
                raise ValueError("receipt 临时文件写入失败") from None
        for digest in (*receipt.inputs, *receipt.outputs):
            _verify_digest_bytes(digest, roots)
        try:
            os.link(tmp_path, receipt_path)
        except FileExistsError:
            return _reuse_existing_receipt(
                receipt_path=receipt_path,
                encoded=encoded,
                artifact_roots=roots,
                receipt=receipt,
            )
        except OSError:
            raise ValueError("receipt 原子创建失败") from None
        _fsync_parent_dir(receipt_path.parent)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if close_fd is not None:
            try:
                os.close(close_fd)
            except OSError:
                pass
        cleanup_error: BaseException | None = None
        try:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                raise ValueError("receipt 临时文件清理失败") from None
        except BaseException as exc:
            cleanup_error = exc
        if cleanup_error is not None and primary_error is None:
            raise cleanup_error
    return receipt


def _identity_key(values: Sequence[str | int]) -> str:
    payload = json.dumps(
        list(values),
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_bare_hex64(name: str, value: object) -> str:
    if type(value) is not str:
        raise ValueError(f"{name} 必须为 str 类型的裸 64 位小写 hex")
    if len(value) != 64 or any(char not in _HEX64 for char in value):
        raise ValueError(f"{name} 必须为裸 64 位小写 hex")
    return value


def _require_stable_version(name: str, value: object) -> str:
    if type(value) is not str:
        raise ValueError(f"{name} 必须为稳定版本字符串")
    if not value or value != value.strip():
        raise ValueError(f"{name} 不得为空或含首尾空白")
    if _has_control_chars(value):
        raise ValueError(f"{name} 含控制字符")
    if value.casefold() == "unavailable":
        raise ValueError(f"{name} 不得为 unavailable")
    return value


def _require_fold(value: object) -> str:
    fold = _require_stable_version("fold", value)
    if any(char in fold for char in "/\\:."):
        raise ValueError("fold 非法路径字符")
    if ".." in fold:
        raise ValueError("fold 非法路径字符")
    return fold


def _require_positive_horizon(value: object) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise ValueError("horizon 必须为正 int")
    if value <= 0:
        raise ValueError("horizon 必须为正 int")
    return value


def _has_control_chars(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def _require_scope(scope: object) -> Scope:
    if type(scope) is not str or scope not in _SCOPES:
        raise ValueError(f"非法 scope: {scope}")
    return scope  # type: ignore[return-value]


def _validate_stage(stage: object) -> str:
    if type(stage) is not str:
        raise ValueError("stage 必须为非空字符串")
    if not stage or stage != stage.strip():
        raise ValueError("stage 不得为空或纯空白")
    if _has_control_chars(stage):
        raise ValueError("stage 含控制字符")
    if "/" in stage or "\\" in stage or stage in {".", ".."}:
        raise ValueError("stage 不得为路径")
    return stage


def _validate_alias(alias: object) -> str:
    if type(alias) is not str:
        raise ValueError("root_alias 必须为非空字符串")
    if not alias or alias != alias.strip():
        raise ValueError("root_alias 不得为空或纯空白")
    if _has_control_chars(alias):
        raise ValueError("root_alias 含控制字符")
    if "/" in alias or "\\" in alias or alias in {".", ".."}:
        raise ValueError("root_alias 非法")
    return alias


def _validate_relative_posix(text: object) -> str:
    if type(text) is not str:
        raise ValueError("非法相对路径")
    if not text:
        raise ValueError("非法相对路径")
    if _has_control_chars(text):
        raise ValueError("相对路径含控制字符")
    if "\\" in text or ":" in text:
        raise ValueError("相对路径必须为 POSIX")
    if text.startswith("/") or text.startswith("//"):
        raise ValueError("禁止绝对路径")
    if PurePosixPath(text).as_posix() != text:
        raise ValueError(f"非法相对路径: {text}")
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"禁止 '.'/'..' 或空段: {text}")
    if text.endswith("/"):
        raise ValueError(f"非法相对路径: {text}")
    return text


def _validate_digest_tuple(
    digests: object, *, label: str
) -> tuple[ArtifactDigest, ...]:
    if type(digests) is not tuple:
        raise ValueError(f"{label} 必须为 ArtifactDigest 的 exact tuple")
    seen: set[tuple[str, str]] = set()
    previous: tuple[str, str] | None = None
    for item in digests:
        if type(item) is not ArtifactDigest:
            raise ValueError(f"{label} 元素必须为 ArtifactDigest")
        key = _digest_sort_key(item)
        if key in seen:
            raise ValueError(f"{label} 存在重复 (alias,path): {key[0]},{key[1]}")
        seen.add(key)
        if previous is not None and key < previous:
            raise ValueError(f"{label} 未按 (alias,path) 升序")
        previous = key
    return digests


def _digest_sort_key(digest: ArtifactDigest) -> tuple[str, str]:
    return (digest.root_alias, digest.relative_path)


def _canonical_receipt_bytes(receipt: StageReceipt) -> bytes:
    payload = {
        "receipt_version": receipt.receipt_version,
        "stage": receipt.stage,
        "scope": receipt.scope,
        "scope_key": receipt.scope_key,
        "inputs": [_digest_mapping(item) for item in receipt.inputs],
        "outputs": [_digest_mapping(item) for item in receipt.outputs],
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest_mapping(digest: ArtifactDigest) -> dict[str, str | int]:
    return {
        "root_alias": digest.root_alias,
        "relative_path": digest.relative_path,
        "size_bytes": digest.size_bytes,
        "sha256": digest.sha256,
    }


def _duplicate_aware_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_parse_constant(value: str) -> None:
    raise ValueError(f"拒绝 JSON constant: {value}")


def _parse_receipt_bytes(raw: bytes) -> StageReceipt:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("receipt 拒绝 UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("receipt UTF-8 非法") from None
    if "\r" in text:
        raise ValueError("receipt 拒绝 CRLF")
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_duplicate_aware_object,
            parse_constant=_reject_parse_constant,
        )
    except json.JSONDecodeError:
        raise ValueError("receipt JSON 非法") from None
    if type(payload) is not dict:
        raise ValueError("receipt 顶层必须为 object")
    if set(payload) != set(_TOP_LEVEL_KEYS):
        raise ValueError("receipt 顶层字段不精确")
    for key in _TOP_LEVEL_KEYS:
        if key not in payload:
            raise ValueError(f"receipt 缺少字段: {key}")

    version = payload["receipt_version"]
    if version != _RECEIPT_VERSION:
        raise ValueError("未知 receipt_version")
    stage = _validate_stage(payload["stage"])
    scope = _require_scope(payload["scope"])
    scope_key = _require_bare_hex64("scope_key", payload["scope_key"])
    inputs = _digests_from_json_list(payload["inputs"], label="inputs")
    outputs = _digests_from_json_list(payload["outputs"], label="outputs")
    receipt = StageReceipt(
        receipt_version=_RECEIPT_VERSION,
        stage=stage,
        scope=scope,
        scope_key=scope_key,
        inputs=inputs,
        outputs=outputs,
    )
    canonical = _canonical_receipt_bytes(receipt)
    if canonical != raw:
        raise ValueError("receipt 字节非规范")
    return receipt


def _digests_from_json_list(
    raw: object, *, label: str
) -> tuple[ArtifactDigest, ...]:
    if type(raw) is not list:
        raise ValueError(f"{label} 必须为数组")
    digests: list[ArtifactDigest] = []
    for item in raw:
        digests.append(_digest_from_json_object(item))
    return tuple(digests)


def _digest_from_json_object(item: object) -> ArtifactDigest:
    if type(item) is not dict:
        raise ValueError("digest 条目必须为 object")
    if set(item) != set(_DIGEST_KEYS):
        raise ValueError("digest 字段不精确")
    size_bytes = item["size_bytes"]
    if type(size_bytes) is not int or isinstance(size_bytes, bool):
        raise ValueError("size_bytes 必须为非负精确 int")
    return ArtifactDigest(
        root_alias=item["root_alias"],
        relative_path=item["relative_path"],
        size_bytes=size_bytes,
        sha256=item["sha256"],
    )


def _validate_artifact_roots(
    artifact_roots: Mapping[str, Path],
) -> dict[str, Path]:
    if not isinstance(artifact_roots, Mapping) or not artifact_roots:
        raise ValueError("artifact_roots 不得为空")
    validated: dict[str, Path] = {}
    seen_physical: dict[tuple[int, int], str] = {}
    for alias, root in artifact_roots.items():
        _validate_alias(alias)
        if not isinstance(root, Path):
            raise ValueError(f"root 非法: {alias}")
        abs_root = Path(os.path.abspath(root))
        _assert_existing_dir_no_symlink_chain(abs_root, label=f"root:{alias}")
        identity = _dir_identity(abs_root)
        prior = seen_physical.get(identity)
        if prior is not None:
            raise ValueError(f"重复物理 root alias: {prior},{alias}")
        seen_physical[identity] = alias
        validated[alias] = abs_root
    return validated


def _dir_identity(path: Path) -> tuple[int, int]:
    try:
        st = os.lstat(path)
    except OSError:
        raise ValueError("root 不可读") from None
    if stat.S_ISLNK(st.st_mode):
        raise ValueError("root 为 symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError("root 不是目录")
    return (st.st_dev, st.st_ino)


def _assert_existing_dir_no_symlink_chain(path: Path, *, label: str) -> None:
    abs_path = Path(os.path.abspath(path))
    try:
        st = os.lstat(abs_path)
    except FileNotFoundError:
        raise ValueError(f"{label} 不存在") from None
    except OSError:
        raise ValueError(f"{label} 不可读") from None
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(f"{label} 为 symlink")
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"{label} 不是目录")
    _assert_ancestor_components_no_symlink(abs_path)


def _assert_ancestor_components_no_symlink(path: Path) -> None:
    current = Path(os.path.abspath(path))
    while True:
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError:
            raise ValueError("路径组件不可读") from None
        if stat.S_ISLNK(st.st_mode):
            raise ValueError("路径组件为 symlink")
        parent = current.parent
        if parent == current:
            break
        current = parent


def _assert_receipt_contained(
    receipt_path: Path, roots: Mapping[str, Path]
) -> None:
    abs_receipt = Path(os.path.abspath(receipt_path))
    for root in roots.values():
        try:
            abs_receipt.relative_to(root)
            return
        except ValueError:
            continue
    raise ValueError("receipt 不在 artifact root 内")


def _assert_receipt_publish_location(
    receipt_path: Path, roots: Mapping[str, Path]
) -> None:
    _assert_receipt_contained(receipt_path, roots)
    _assert_existing_dir_no_symlink_chain(
        receipt_path.parent, label="receipt_parent"
    )


def _receipt_leaf_state(receipt_path: Path) -> str:
    try:
        st = os.lstat(receipt_path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        raise ValueError("receipt 不可读") from None
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "other"


def _reuse_existing_receipt(
    *,
    receipt_path: Path,
    encoded: bytes,
    artifact_roots: Mapping[str, Path],
    receipt: StageReceipt,
) -> StageReceipt:
    try:
        existing = Path(receipt_path).read_bytes()
    except OSError:
        raise ValueError("receipt 不可读") from None
    if existing != encoded:
        raise ValueError("已存在冲突 receipt，拒绝覆盖")
    verified = verify_stage_receipt(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified is None:
        raise ValueError("已存在 receipt 验真失败")
    if verified != receipt:
        raise ValueError("已存在冲突 receipt，拒绝覆盖")
    return verified


def _digests_from_paths(
    items: Sequence[tuple[str, Path]],
    artifact_roots: Mapping[str, Path],
    *,
    label: str,
) -> list[ArtifactDigest]:
    digests: list[ArtifactDigest] = []
    seen: set[tuple[str, str]] = set()
    for alias, path in items:
        if alias not in artifact_roots:
            raise ValueError(f"未知 root alias: {alias}")
        root = artifact_roots[alias]
        relative = _relative_posix_under_root(path, root, alias=alias)
        key = (alias, relative)
        if key in seen:
            raise ValueError(f"{label} 存在重复 (alias,path): {alias},{relative}")
        seen.add(key)
        abs_path = _resolve_leaf_under_root(root, relative, alias=alias)
        try:
            payload = abs_path.read_bytes()
        except OSError:
            raise ValueError(f"artifact 不可读: {alias}:{relative}") from None
        digests.append(
            ArtifactDigest(
                root_alias=alias,
                relative_path=relative,
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
    return digests


def _assert_context_consistency(
    receipt: StageReceipt,
    roots: Mapping[str, Path],
    *,
    receipt_path: Path,
) -> None:
    physical_seen: dict[tuple[int, int], tuple[str, str]] = {}
    for digest in (*receipt.inputs, *receipt.outputs):
        if digest.root_alias not in roots:
            raise ValueError(f"未知 root alias: {digest.root_alias}")
        abs_path = _resolve_leaf_under_root(
            roots[digest.root_alias], digest.relative_path, alias=digest.root_alias
        )
        identity = _regular_file_identity(abs_path, alias=digest.root_alias, relative=digest.relative_path)
        prior = physical_seen.get(identity)
        if prior is not None:
            raise ValueError(
                f"物理文件重复: {prior[0]}:{prior[1]} 与 "
                f"{digest.root_alias}:{digest.relative_path}"
            )
        physical_seen[identity] = (digest.root_alias, digest.relative_path)

    receipt_state = _receipt_leaf_state(receipt_path)
    if receipt_state == "file":
        receipt_identity = _regular_file_identity(
            Path(os.path.abspath(receipt_path)),
            alias="receipt",
            relative=receipt_path.name,
        )
        if receipt_identity in physical_seen:
            raise ValueError("receipt 自身不得列入 inputs/outputs")
    elif receipt_state == "missing":
        abs_receipt = Path(os.path.abspath(receipt_path))
        for digest in (*receipt.inputs, *receipt.outputs):
            abs_path = roots[digest.root_alias] / digest.relative_path
            if Path(os.path.abspath(abs_path)) == abs_receipt:
                raise ValueError("receipt 自身不得列入 inputs/outputs")
    elif receipt_state == "symlink":
        raise ValueError("receipt 为 symlink")
    elif receipt_state == "other":
        raise ValueError("receipt 非普通文件")


def _relative_posix_under_root(path: Path, root: Path, *, alias: str) -> str:
    abs_path = Path(os.path.abspath(path))
    abs_root = Path(os.path.abspath(root))
    try:
        relative = abs_path.relative_to(abs_root).as_posix()
    except ValueError:
        raise ValueError(f"路径不在 artifact root 内: {alias}") from None
    _validate_relative_posix(relative)
    _resolve_leaf_under_root(abs_root, relative, alias=alias)
    return relative


def _resolve_leaf_under_root(root: Path, relative: str, *, alias: str) -> Path:
    _validate_relative_posix(relative)
    current = Path(os.path.abspath(root))
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            raise ValueError(f"artifact 缺失: {alias}:{relative}") from None
        except OSError:
            raise ValueError(f"artifact 不可读: {alias}:{relative}") from None
        if stat.S_ISLNK(st.st_mode):
            raise ValueError(f"路径组件为 symlink: {alias}:{relative}")
        is_leaf = index == len(parts) - 1
        if is_leaf:
            if not stat.S_ISREG(st.st_mode):
                raise ValueError(f"artifact 非普通文件: {alias}:{relative}")
        elif not stat.S_ISDIR(st.st_mode):
            raise ValueError(f"路径组件非目录: {alias}:{relative}")
    try:
        current.relative_to(Path(os.path.abspath(root)))
    except ValueError:
        raise ValueError(f"路径逃逸: {alias}:{relative}") from None
    return current


def _regular_file_identity(
    path: Path, *, alias: str, relative: str
) -> tuple[int, int]:
    try:
        st = os.lstat(path)
    except OSError:
        raise ValueError(f"artifact 不可读: {alias}:{relative}") from None
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(f"路径组件为 symlink: {alias}:{relative}")
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"artifact 非普通文件: {alias}:{relative}")
    return (st.st_dev, st.st_ino)


def _verify_digest_bytes(
    digest: ArtifactDigest,
    artifact_roots: Mapping[str, Path],
) -> None:
    path = _resolve_leaf_under_root(
        artifact_roots[digest.root_alias],
        digest.relative_path,
        alias=digest.root_alias,
    )
    try:
        payload = path.read_bytes()
    except OSError:
        raise ValueError(
            f"artifact 不可读: {digest.root_alias}:{digest.relative_path}"
        ) from None
    if len(payload) != digest.size_bytes:
        raise ValueError(
            f"artifact 大小不符: {digest.root_alias}:{digest.relative_path}"
        )
    actual = hashlib.sha256(payload).hexdigest()
    if actual != digest.sha256:
        raise ValueError(
            f"artifact hash 不符: {digest.root_alias}:{digest.relative_path}"
        )


def _fsync_parent_dir(parent: Path) -> None:
    if not _directory_fsync_supported():
        # Windows has no reliable directory-fd fsync. Receipt file bytes are
        # flushed above; this matches the accepted Windows native publish rail.
        return
    try:
        fd = os.open(str(parent), os.O_RDONLY)
    except OSError as exc:
        if exc.errno in _FS_UNSUPPORTED:
            return
        raise ValueError("父目录 fsync 失败") from None
    primary_error: BaseException | None = None
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in _FS_UNSUPPORTED:
                raise ValueError("父目录 fsync 失败") from None
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            os.close(fd)
        except OSError:
            if primary_error is None:
                raise ValueError("父目录 fsync 失败") from None


def _directory_fsync_supported() -> bool:
    return os.name != "nt"

