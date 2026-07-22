"""MLflow 薄适配器：仅在函数内部 import；默认测试不得启动真实 server。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path


_FORBIDDEN_KEY_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
)


def log_m3_run(
    *,
    tracking_uri: str,
    experiment_name: str,
    params: Mapping[str, object],
    metrics: Mapping[str, float],
    artifacts: Sequence[Path],
    tags: Mapping[str, str],
) -> str:
    """记录一次 M3 run，返回 run_id。

    在打开 MLflow run 之前完成全部安全与 artifact 存在性校验。
    """
    _assert_safe_value(params, "params")
    _assert_safe_value(tags, "tags")
    for path in artifacts:
        if not path.exists():
            raise FileNotFoundError(f"artifact 不存在: {path}")

    import mlflow  # type: ignore[import-not-found]

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run() as run:
        mlflow.log_params({key: _stringify(value) for key, value in params.items()})
        mlflow.log_metrics(dict(metrics))
        for key, value in tags.items():
            mlflow.set_tag(key, value)
        for path in artifacts:
            mlflow.log_artifact(str(path))
        return run.info.run_id


def _stringify(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _assert_safe_value(
    value: object,
    location: str,
    *,
    seen: set[int] | None = None,
) -> None:
    if seen is None:
        seen = set()
    obj_id = id(value)
    if obj_id in seen:
        raise ValueError(f"{location} 包含循环引用")
    if isinstance(value, (str, bytes, int, float, bool, type(None))):
        if isinstance(value, str):
            _assert_safe_string(value, location)
        return
    if isinstance(value, Path):
        _assert_safe_string(str(value), location)
        return

    if isinstance(value, Mapping):
        seen.add(obj_id)
        try:
            for key, item in value.items():
                key_text = str(key)
                _assert_safe_string(key_text, f"{location}.<key>")
                key_l = key_text.lower()
                if any(fragment in key_l for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                    raise ValueError(f"{location} 禁止包含敏感键: {key_text}")
                _assert_safe_value(item, f"{location}.{key_text}", seen=seen)
        finally:
            seen.discard(obj_id)
        return

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        seen.add(obj_id)
        try:
            for index, item in enumerate(value):
                _assert_safe_value(item, f"{location}[{index}]", seen=seen)
        finally:
            seen.discard(obj_id)
        return

    # 其他对象转字符串检查路径/凭据痕迹
    _assert_safe_string(str(value), location)


def _assert_safe_string(text: str, location: str) -> None:
    lower = text.lower()
    if any(fragment in lower for fragment in ("token=", "bearer ")):
        raise ValueError(f"{location} 疑似包含凭据内容")
    if text.startswith("/") or (len(text) >= 3 and text[1:3] == ":\\"):
        raise ValueError(f"{location} 禁止写入绝对本机路径")
    # Windows 正斜杠形式
    if len(text) >= 3 and text[1] == ":" and text[2] == "/":
        raise ValueError(f"{location} 禁止写入绝对本机路径")
