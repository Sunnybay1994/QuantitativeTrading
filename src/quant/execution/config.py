"""Strict loader and canonical identity for M4 trading configuration."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import stat
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, TypeAlias, cast
from urllib.parse import unquote

FieldKind: TypeAlias = Literal[
    "string", "bool", "int", "float", "date", "str_array"
]

_HASH_VERSION = "trading-config-hash-v1"
_SCHEMA_VERSION = "trading-config-v1"
_ALLOWED_MODES = frozenset({"PAPER", "SHADOW"})
_MISSING = object()
_VERSION_SELECTOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SELECTOR_PATHS = (
    ("rules", "a_share_rule_selector"),
    ("rules", "hk_connect_rule_selector"),
    ("rules", "fee_schedule_selector"),
    ("rules", "fx_schedule_selector"),
)


@dataclass(frozen=True, order=True)
class ConfigIssue:
    """One sanitized, deterministic configuration violation."""

    code: str
    dotted_path: str
    message: str


class TradingConfigError(ValueError):
    """All independently detectable trading configuration issues."""

    def __init__(self, issues: Iterable[ConfigIssue]) -> None:
        ordered = tuple(
            sorted(
                set(issues),
                key=lambda item: (item.dotted_path, item.code, item.message),
            )
        )
        if not ordered:
            raise ValueError("TradingConfigError requires at least one issue")
        self.issues = ordered
        super().__init__(f"Trading configuration rejected with {len(ordered)} issue(s)")

    def __repr__(self) -> str:
        return f"TradingConfigError(issue_count={len(self.issues)})"


@dataclass(frozen=True)
class FieldSpec:
    """Machine-readable contract for one normalized TOML assignment shape."""

    kind: FieldKind
    required: bool = True
    literal: object = _MISSING
    minimum: int | float | None = None
    maximum: int | float | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True
    non_empty: bool = False


def _field_specs() -> dict[str, FieldSpec]:
    specs: dict[str, FieldSpec] = {}

    def add(
        path: str,
        kind: FieldKind,
        *,
        required: bool = True,
        literal: object = _MISSING,
        minimum: int | float | None = None,
        maximum: int | float | None = None,
        minimum_inclusive: bool = True,
        maximum_inclusive: bool = True,
        non_empty: bool = False,
    ) -> None:
        if path in specs:
            raise AssertionError(f"duplicate trading field spec: {path}")
        specs[path] = FieldSpec(
            kind=kind,
            required=required,
            literal=literal,
            minimum=minimum,
            maximum=maximum,
            minimum_inclusive=minimum_inclusive,
            maximum_inclusive=maximum_inclusive,
            non_empty=non_empty,
        )

    add("meta.schema_version", "string", literal=_SCHEMA_VERSION)
    add("execution.mode", "string")
    add("execution.auto_trade", "bool", literal=False)
    add("execution.manual_approval", "bool")
    add("execution.sell_only", "bool")
    add("execution.frozen_symbols", "str_array")
    add("rules.a_share_rule_selector", "string", non_empty=True)
    add("rules.hk_connect_rule_selector", "string", non_empty=True)
    add("rules.fee_schedule_selector", "string", non_empty=True)
    add("rules.fx_schedule_selector", "string", non_empty=True)
    add("data.snapshot_max_age_seconds", "int", minimum=1)
    add("store.sqlite_uri", "string", non_empty=True)
    add("risk.limits[].effective_from", "date")
    add("risk.limits[].effective_to", "date", required=False)
    add("risk.limits[].max_order_notional", "float", minimum=0.0, minimum_inclusive=False)
    add("risk.limits[].max_symbol_weight", "float", minimum=0.0, maximum=1.0, minimum_inclusive=False)
    add("risk.limits[].max_gross_exposure", "float", minimum=0.0, minimum_inclusive=False)
    add("risk.limits[].max_daily_notional", "float", minimum=0.0, minimum_inclusive=False)
    add("risk.limits[].max_orders_per_day", "int", minimum=1)
    add("risk.limits[].max_cancels_per_day", "int", minimum=0)
    return specs


_FIELD_SPECS = MappingProxyType(_field_specs())


@dataclass(frozen=True, slots=True)
class TradingConfig:
    """Strictly validated, recursively immutable trading document."""

    document: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.document, Mapping):
            raise TradingConfigError(
                (ConfigIssue("TYPE_ERROR", "config", "expected mapping"),)
            )
        normalized = _validate_and_normalize(self.document)
        frozen = cast(Mapping[str, object], _freeze(normalized))
        object.__setattr__(self, "document", frozen)

    @property
    def schema_version(self) -> str:
        """Schema version derived from the validated canonical document."""
        meta = self.document["meta"]
        if not isinstance(meta, Mapping):
            raise TypeError("TradingConfig meta section is not a mapping")
        return cast(str, meta["schema_version"])

    def section(self, name: str) -> Mapping[str, object]:
        """Return one required, read-only root section without implicit defaults."""
        value = self.document[name]
        if not isinstance(value, Mapping):
            raise TypeError(f"TradingConfig section is not a mapping: {name}")
        return cast(Mapping[str, object], value)


def load_trading_config(path: Path) -> TradingConfig:
    """Read, strictly validate, normalize, and freeze one trading TOML file."""
    raw = _read_config_bytes(path)
    if raw is None:
        raise TradingConfigError(
            (
                ConfigIssue(
                    "CONFIG_IO_ERROR",
                    "config",
                    "configuration must be a readable regular UTF-8 TOML file",
                ),
            )
        )

    parsed = _parse_toml(raw)
    if parsed is None:
        raise TradingConfigError(
            (
                ConfigIssue(
                    "TOML_PARSE_ERROR",
                    "config",
                    "configuration must be valid UTF-8 TOML",
                ),
            )
        )

    return TradingConfig(document=parsed)


def trading_config_identity(config: TradingConfig) -> str:
    """Return the canonical SHA-256 identity of a validated TradingConfig."""
    if not isinstance(config, TradingConfig):
        raise TypeError("trading_config_identity requires TradingConfig")
    if not _is_recursively_immutable(config.document):
        raise TradingConfigError(
            (
                ConfigIssue(
                    "VALUE_ERROR",
                    "config",
                    "TradingConfig document must remain recursively immutable",
                ),
            )
        )
    thawed = _thaw(config.document)
    if not isinstance(thawed, dict):
        raise TypeError("TradingConfig document must thaw to a mapping")
    normalized = _validate_and_normalize(cast(dict[str, object], thawed))
    return _trusted_config_sha256(normalized)


def _read_config_bytes(path: Path) -> bytes | None:
    try:
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            raise OSError
        return path.read_bytes()
    except (OSError, ValueError, TypeError):
        return None


def _parse_toml(raw: bytes) -> dict[str, object] | None:
    try:
        return cast(dict[str, object], tomllib.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def _validate_and_normalize(document: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(document, Mapping):
        raise TradingConfigError((ConfigIssue("TYPE_ERROR", "config", "expected mapping"),))
    mutable = _thaw(document)
    if not isinstance(mutable, dict):
        raise TradingConfigError((ConfigIssue("TYPE_ERROR", "config", "expected mapping"),))
    issues: list[ConfigIssue] = []

    _scan_secrets(mutable, issues)
    observed = list(_iter_assignment_leaves(mutable, issues))
    observed_shapes: dict[str, list[tuple[tuple[str | int, ...], object]]] = {}
    for tokens, value in observed:
        shape = _shape(tokens)
        observed_shapes.setdefault(shape, []).append((tokens, value))
        if shape not in _FIELD_SPECS:
            issues.append(ConfigIssue("UNKNOWN_KEY", _display_path(tokens), "key is not allowed"))

    for shape, spec in _FIELD_SPECS.items():
        entries = observed_shapes.get(shape, [])
        if "[]" not in shape:
            if not entries and spec.required:
                issues.append(ConfigIssue("MISSING_KEY", shape, "required key is missing"))
            elif len(entries) > 1:
                issues.append(ConfigIssue("VALUE_ERROR", shape, "key must occur exactly once"))
        for tokens, value in entries:
            _validate_field(_display_path(tokens), value, spec, issues)

    periods = _get_path(mutable, ("risk", "limits"))
    _validate_period_container(periods, issues)
    _validate_cross_fields(mutable, issues)

    mode = _get_path(mutable, ("execution", "mode"))
    if type(mode) is str and mode not in _ALLOWED_MODES:
        issues.append(
            ConfigIssue(
                "VALUE_ERROR",
                "execution.mode",
                "mode must be PAPER or SHADOW",
            )
        )

    auto_trade = _get_path(mutable, ("execution", "auto_trade"))
    if type(auto_trade) is bool and auto_trade is True:
        issues.append(
            ConfigIssue(
                "VALUE_ERROR",
                "execution.auto_trade",
                "auto_trade must remain false for M4",
            )
        )

    frozen_symbols = _get_path(mutable, ("execution", "frozen_symbols"))
    if _strict_str_sequence(frozen_symbols):
        symbols = cast(Sequence[str], frozen_symbols)
        if len(set(symbols)) != len(symbols):
            issues.append(
                ConfigIssue(
                    "VALUE_ERROR",
                    "execution.frozen_symbols",
                    "frozen symbols must be unique",
                )
            )
        else:
            cast(dict[str, object], mutable["execution"])["frozen_symbols"] = tuple(
                sorted(symbols)
            )

    sqlite_uri = _get_path(mutable, ("store", "sqlite_uri"))
    if type(sqlite_uri) is str:
        canonical_uri = _canonical_sqlite_uri(sqlite_uri, issues)
        if canonical_uri is not None:
            cast(dict[str, object], mutable["store"])["sqlite_uri"] = canonical_uri

    for section_name, field_name in _SELECTOR_PATHS:
        selector = _get_path(mutable, (section_name, field_name))
        if type(selector) is str:
            _validate_version_selector(
                f"{section_name}.{field_name}",
                selector,
                issues,
            )

    if issues:
        raise TradingConfigError(issues)
    return cast(dict[str, object], _normalize_scalars(mutable))


def _iter_assignment_leaves(
    value: object,
    issues: list[ConfigIssue],
    tokens: tuple[str | int, ...] = (),
) -> Iterable[tuple[tuple[str | int, ...], object]]:
    if isinstance(value, Mapping):
        if not value and tokens:
            yield tokens, value
        for key, child in value.items():
            if type(key) is not str:
                issues.append(
                    ConfigIssue("TYPE_ERROR", _display_path(tokens), "mapping keys must be strings")
                )
                continue
            yield from _iter_assignment_leaves(child, issues, (*tokens, key))
        return
    if isinstance(value, (list, tuple)) and _shape(tokens) == "risk.limits":
        if not value:
            yield tokens, value
        for index, child in enumerate(value):
            if not isinstance(child, Mapping):
                yield (*tokens, index), child
            else:
                yield from _iter_assignment_leaves(child, issues, (*tokens, index))
        return
    yield tokens, value


def _validate_field(path: str, value: object, spec: FieldSpec, issues: list[ConfigIssue]) -> None:
    expected = spec.kind
    valid_type = False
    comparable: object = value
    if expected == "string":
        valid_type = type(value) is str
    elif expected == "bool":
        valid_type = type(value) is bool
    elif expected == "int":
        valid_type = type(value) is int and type(value) is not bool
    elif expected == "float":
        valid_type = type(value) is float
    elif expected == "date":
        valid_type = type(value) is dt.date
    elif expected == "str_array":
        valid_type = isinstance(value, (list, tuple))
        if valid_type:
            valid_type = all(type(item) is str for item in cast(Sequence[object], value))
            comparable = tuple(cast(Sequence[object], value))

    if not valid_type:
        issues.append(ConfigIssue("TYPE_ERROR", path, f"expected strict {expected}"))
        return
    if expected == "string" and not cast(str, value).strip():
        issues.append(ConfigIssue("EMPTY_STRING", path, "expected non-empty string"))
    if expected == "float":
        if not math.isfinite(cast(float, value)):
            issues.append(ConfigIssue("NON_FINITE", path, "expected finite float"))
            return
    if spec.non_empty and isinstance(comparable, (str, tuple)) and not comparable:
        issues.append(ConfigIssue("EMPTY_STRING", path, "expected non-empty value"))
    if spec.literal is not _MISSING and comparable != spec.literal:
        issues.append(ConfigIssue("VALUE_ERROR", path, "value does not match the versioned contract"))
    if spec.minimum is not None and isinstance(value, (int, float)) and type(value) is not bool:
        bad = value < spec.minimum if spec.minimum_inclusive else value <= spec.minimum
        if bad:
            issues.append(ConfigIssue("VALUE_ERROR", path, "value is below the allowed range"))
    if spec.maximum is not None and isinstance(value, (int, float)) and type(value) is not bool:
        bad = value > spec.maximum if spec.maximum_inclusive else value >= spec.maximum
        if bad:
            issues.append(ConfigIssue("VALUE_ERROR", path, "value is above the allowed range"))


def _validate_period_container(periods: object, issues: list[ConfigIssue]) -> None:
    path = "risk.limits"
    if periods is _MISSING:
        issues.append(ConfigIssue("MISSING_KEY", path, "required array table is missing"))
        return
    if not isinstance(periods, (list, tuple)):
        issues.append(ConfigIssue("TYPE_ERROR", path, "expected non-empty array of tables"))
        return
    if not periods:
        issues.append(ConfigIssue("VALUE_ERROR", path, "expected non-empty array of tables"))
        return
    for index, period in enumerate(periods):
        item_path = f"{path}[{index}]"
        if not isinstance(period, Mapping):
            issues.append(ConfigIssue("TYPE_ERROR", item_path, "expected table"))
            continue
        required_names = {
            "effective_from",
            "max_order_notional",
            "max_symbol_weight",
            "max_gross_exposure",
            "max_daily_notional",
            "max_orders_per_day",
            "max_cancels_per_day",
        }
        if index < len(periods) - 1:
            required_names.add("effective_to")
        for name in required_names:
            if name not in period:
                issues.append(ConfigIssue("MISSING_KEY", f"{item_path}.{name}", "required key is missing"))
        if index == len(periods) - 1 and "effective_to" in period:
            issues.append(
                ConfigIssue(
                    "CROSS_FIELD_ERROR",
                    f"{item_path}.effective_to",
                    "final risk period must remain open-ended",
                )
            )


def _validate_cross_fields(document: dict[str, object], issues: list[ConfigIssue]) -> None:
    periods = _get_path(document, ("risk", "limits"))
    if not isinstance(periods, (list, tuple)) or not periods:
        return
    if not all(isinstance(item, Mapping) for item in periods):
        return
    typed_periods = cast(Sequence[Mapping[str, object]], periods)
    for index in range(len(typed_periods)):
        from_date = typed_periods[index].get("effective_from")
        to_date = typed_periods[index].get("effective_to")
        if type(from_date) is dt.date and type(to_date) is dt.date and to_date < from_date:
            issues.append(
                ConfigIssue(
                    "CROSS_FIELD_ERROR",
                    f"risk.limits[{index}].effective_to",
                    "risk period end must not precede start",
                )
            )
    for index in range(len(typed_periods) - 1):
        current_to = typed_periods[index].get("effective_to")
        next_from = typed_periods[index + 1].get("effective_from")
        if type(current_to) is dt.date and type(next_from) is dt.date:
            if next_from != current_to + dt.timedelta(days=1):
                issues.append(
                    ConfigIssue(
                        "CROSS_FIELD_ERROR",
                        f"risk.limits[{index + 1}].effective_from",
                        "risk periods must be consecutive calendar days",
                    )
                )


def _scan_secrets(value: object, issues: list[ConfigIssue], tokens: tuple[str | int, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if type(key) is not str:
                _scan_secrets(child, issues, (*tokens, "<non-string-key>"))
                continue
            child_tokens = (*tokens, key)
            if _is_sensitive_key(key):
                issues.append(
                    ConfigIssue(
                        "SECRET_VALUE",
                        _display_path(child_tokens),
                        "credential keys are forbidden",
                    )
                )
            _scan_secrets(child, issues, child_tokens)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _scan_secrets(child, issues, (*tokens, index))
    elif type(value) is str:
        _validate_safe_string(_display_path(tokens), value, issues)


def _validate_safe_string(path: str, value: str, issues: list[ConfigIssue]) -> None:
    _scan_secret_value(path, value, issues)
    _scan_unsafe_path_value(path, value, issues)


def _scan_secret_value(path: str, value: str, issues: list[ConfigIssue]) -> None:
    decoded = _controlled_percent_decode(value)
    patterns = (
        r"\bbearer\s+\S+",
        r"\btoken\s*=",
        r"\bapi[_-]?key\s*=",
        r"\bpassword\s*=",
        r"\bsecret\s*=",
        r"\bsk-[A-Za-z0-9_-]+",
    )
    if any(re.search(pattern, decoded, flags=re.IGNORECASE) for pattern in patterns):
        issues.append(ConfigIssue("SECRET_VALUE", path, "credential-like values are forbidden"))
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        issues.append(ConfigIssue("SECRET_VALUE", path, "control characters are forbidden"))


def _is_sensitive_key(key: str) -> bool:
    normalized = _controlled_percent_decode(key).lower().replace("-", "_")
    return normalized in {
        "token",
        "api_token",
        "api_key",
        "apikey",
        "secret",
        "password",
        "passwd",
        "authorization",
        "cookie",
        "credential",
        "private_key",
        "account",
        "account_id",
        "accountid",
    }


def _scan_unsafe_path_value(path: str, value: str, issues: list[ConfigIssue]) -> None:
    if "://" in value:
        return
    decoded = _controlled_percent_decode(value)
    if (
        value.startswith("/")
        or decoded.startswith("/")
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
        or value.startswith("\\\\")
        or "\\" in value
        or "\\" in decoded
    ):
        issues.append(ConfigIssue("UNSAFE_PATH", path, "absolute and non-POSIX paths are forbidden"))


def _controlled_percent_decode(value: str) -> str:
    decoded = value
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _canonical_sqlite_uri(uri: str, issues: list[ConfigIssue]) -> str | None:
    path = "store.sqlite_uri"
    if "%" in uri or "\\" in uri or any(ord(char) < 32 or ord(char) == 127 for char in uri):
        issues.append(ConfigIssue("UNSAFE_URI", path, "URI contains forbidden encoding or separators"))
        return None
    sqlite_match = re.fullmatch(r"sqlite:///([^?#]+)", uri, flags=re.IGNORECASE)
    if not sqlite_match:
        issues.append(ConfigIssue("UNSAFE_URI", path, "URI must be relative SQLite"))
        return None
    relative = sqlite_match.group(1)
    if relative.startswith("/"):
        issues.append(ConfigIssue("UNSAFE_URI", path, "SQLite URI must use a relative logical path"))
        return None
    if re.match(r"^[A-Za-z]:", relative) is not None:
        issues.append(ConfigIssue("UNSAFE_URI", path, "SQLite URI must use a relative logical path"))
        return None
    if not _validate_relative_posix_path(relative, path, issues):
        return None
    return f"sqlite:///{relative}"


def _validate_version_selector(path: str, value: str, issues: list[ConfigIssue]) -> None:
    """Reject URI, path, and traversal syntax for versioned rule/fee/FX selectors."""
    decoded = _controlled_percent_decode(value)
    forbidden_chars = any(char in "/\\:%" for char in value) or any(
        char in "/\\:%" for char in decoded
    )
    control = any(ord(char) < 32 or ord(char) == 127 for char in value)
    path_semantics = value in {".", ".."} or decoded in {".", ".."}
    segments = value.replace("\\", "/").split("/")
    decoded_segments = decoded.replace("\\", "/").split("/")
    if any(segment in {".", ".."} for segment in (*segments, *decoded_segments)):
        path_semantics = True
    if (
        not value
        or control
        or forbidden_chars
        or path_semantics
        or _VERSION_SELECTOR_RE.fullmatch(value) is None
        or _VERSION_SELECTOR_RE.fullmatch(decoded) is None
    ):
        issues.append(
            ConfigIssue(
                "VALUE_ERROR",
                path,
                "version selector must be a non-path identifier",
            )
        )


def _is_recursively_immutable(value: object) -> bool:
    if isinstance(value, MappingProxyType):
        return all(_is_recursively_immutable(child) for child in value.values())
    if isinstance(value, tuple):
        return all(_is_recursively_immutable(child) for child in value)
    if isinstance(value, (dict, list)):
        return False
    if isinstance(value, Mapping):
        return False
    return True


def _validate_relative_posix_path(
    value: str,
    path: str,
    issues: list[ConfigIssue],
) -> bool:
    decoded = _controlled_percent_decode(value)
    invalid = (
        not value
        or value.startswith("/")
        or value.endswith("/")
        or "\\" in value
        or "%" in value
        or re.match(r"^[A-Za-z]:", value) is not None
        or value.startswith("//")
        or any(segment in {"", ".", ".."} for segment in value.split("/"))
        or any(segment in {"", ".", ".."} for segment in decoded.replace("\\", "/").split("/"))
    )
    if invalid:
        issues.append(ConfigIssue("UNSAFE_URI", path, "expected a canonical relative POSIX path"))
        return False
    return True


def _trusted_config_sha256(document: Mapping[str, object]) -> str:
    schema_version = cast(str, cast(Mapping[str, object], document["meta"])["schema_version"])
    payload = _thaw(document)
    if isinstance(payload, dict):
        meta = cast(dict[str, object], payload.get("meta", {}))
        meta = dict(meta)
        meta.pop("schema_version", None)
        if meta:
            payload["meta"] = meta
        else:
            payload.pop("meta", None)
    return _sha256_json(
        {
            "hash_version": _HASH_VERSION,
            "schema_version": schema_version,
            "payload": payload,
        }
    )


def _sha256_json(value: object) -> str:
    canonical = _json_value(value)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {cast(str, key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is float and value == 0.0:
        return 0.0
    return value


def _normalize_scalars(value: object) -> object:
    if isinstance(value, Mapping):
        return {cast(str, key): _normalize_scalars(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_scalars(child) for child in value]
    if type(value) is float and value == 0.0:
        return 0.0
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({cast(str, key): _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(child) for child in value]
    return value


def _get_path(root: object, tokens: tuple[str, ...]) -> object:
    current = root
    for token in tokens:
        if not isinstance(current, Mapping) or token not in current:
            return _MISSING
        current = current[token]
    return current


def _shape(tokens: tuple[str | int, ...]) -> str:
    parts: list[str] = []
    for token in tokens:
        if isinstance(token, int):
            if parts:
                parts[-1] += "[]"
        else:
            parts.append(token)
    return ".".join(parts)


def _display_path(tokens: tuple[str | int, ...]) -> str:
    output = ""
    for token in tokens:
        if isinstance(token, int):
            output += f"[{token}]"
        else:
            output += ("." if output else "") + token
    return output or "config"


def _strict_str_sequence(value: object) -> bool:
    return isinstance(value, (list, tuple)) and all(type(item) is str for item in value)


__all__ = [
    "ConfigIssue",
    "TradingConfig",
    "TradingConfigError",
    "load_trading_config",
    "trading_config_identity",
]
