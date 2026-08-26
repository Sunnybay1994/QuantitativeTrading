"""Fresh, read-only formal A-share PAPER execution policy capability."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import NoReturn, SupportsIndex, cast

from quant.backtest.costs import (
    ExecutionCostPeriod,
    ExecutionCostSchedule,
    build_execution_cost_schedule,
)
from quant.domain.enums import Currency, Market
from quant.execution.config import TradingConfig, trading_config_identity
from quant.execution.contracts import MoneyAmount, build_money_amount
from quant.execution.paper_runtime import (
    FormalPaperRuntimeConfig,
    VerifiedPaperRuntimeEnvironment,
    verify_existing_paper_runtime_preflight,
)

_SCHEMA_VERSION = "paper-execution-policy-v1"
_FORMAL_SELECTOR = "paper_a_share_v1"
_CLASSIFICATION = "formal-paper-simulation"
_ASSUMPTION_NOTICE = (
    "Versioned local PAPER simulation assumptions; not broker quotes or "
    "live-trading authority."
)
_EFFECTIVE_FROM = dt.date(2026, 1, 1)
_SUPPORTED_MARKETS = (Market.SH, Market.SZ)
_SELECTOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_FORBIDDEN_SELECTOR_PARTS = ("development", "example", "fixture", "unknown")
_REPARSE_POINT = 0x400


class PaperExecutionPolicyError(ValueError):
    """Stable and sanitized formal PAPER policy failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"PaperExecutionPolicyError({self.code!r})"


@dataclass(frozen=True, slots=True)
class _PolicyAttestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("paper policy capability is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedPaperExecutionPolicy:
    """Exact process-local proof of one fresh formal PAPER policy."""

    schema_version: str
    selector: str
    session_date: dt.date
    source_path: Path
    source_file_identity: str
    source_parent_identity: str
    raw_sha256: str
    trading_config: TradingConfig
    trading_config_identity: str
    supported_markets: tuple[Market, ...]
    execution_cost_schedule: ExecutionCostSchedule
    cost_schedule_identity: str
    minimum_order_notionals: tuple[MoneyAmount, ...]
    a_share_rule_selector: str
    adapter_policy_version: str
    fill_policy_version: str
    fault_policy_version: str
    finality_policy_version: str
    clock_policy_version: str
    fx_snapshot_identity: None
    policy_identity: str
    verified_at: dt.datetime
    _attestation: _PolicyAttestation = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("paper policy capability is process-local")


@dataclass(slots=True)
class _AnchoredPolicyFile:
    descriptor: int
    source_path: Path
    parent_path: Path
    project_root: Path
    raw: bytes
    raw_sha256: str
    source_file_identity: str
    source_parent_identity: str
    project_root_identity: str
    object_identity: tuple[int, int, int]

    def close(self) -> None:
        os.close(self.descriptor)


@dataclass(frozen=True, slots=True)
class _ParsedPolicy:
    trading_config: TradingConfig
    supported_markets: tuple[Market, ...]
    execution_cost_schedule: ExecutionCostSchedule
    minimum_order_notionals: tuple[MoneyAmount, ...]
    a_share_rule_selector: str
    adapter_policy_version: str
    fill_policy_version: str
    fault_policy_version: str
    finality_policy_version: str
    clock_policy_version: str


class _Failure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _create_policy_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def _token(payload: Mapping[str, object]) -> bytes:
        return hmac.new(key, _canonical_json(payload), hashlib.sha256).digest()

    def _verify_token(policy: VerifiedPaperExecutionPolicy) -> bool:
        if type(policy._attestation) is not _PolicyAttestation:
            return False
        return hmac.compare_digest(policy._attestation.token, _token(_policy_payload(policy)))

    def _load_impl(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        session_date: dt.date,
        now: dt.datetime,
    ) -> VerifiedPaperExecutionPolicy:
        anchored: _AnchoredPolicyFile | None = None
        try:
            timestamp = _require_inputs(environment, session_date, now)
            selector = _require_formal_selector(environment.config.policy_selector)
            _fresh_verify_environment(environment, timestamp)
            source = (
                environment.config.project_root
                / "configs"
                / "trading"
                / "policies"
                / f"{selector}.toml"
            )
            anchored = _open_anchored_policy(source, environment.config.project_root)
            parsed = _parse_policy(anchored.raw, environment, session_date)
            _before_policy_mint_hook(anchored.source_path)
            _fresh_verify_environment(environment, timestamp)
            _fresh_verify_anchored_policy(anchored)
            config_id = trading_config_identity(parsed.trading_config)
            cost_id = paper_execution_cost_schedule_identity(
                parsed.execution_cost_schedule
            )
            identity_payload = _identity_payload(
                environment=environment,
                selector=selector,
                session_date=session_date,
                raw_sha256=anchored.raw_sha256,
                trading_config_identity_value=config_id,
                cost_schedule_identity_value=cost_id,
                parsed=parsed,
            )
            result = VerifiedPaperExecutionPolicy(
                schema_version=_SCHEMA_VERSION,
                selector=selector,
                session_date=session_date,
                source_path=anchored.source_path,
                source_file_identity=anchored.source_file_identity,
                source_parent_identity=anchored.source_parent_identity,
                raw_sha256=anchored.raw_sha256,
                trading_config=parsed.trading_config,
                trading_config_identity=config_id,
                supported_markets=parsed.supported_markets,
                execution_cost_schedule=parsed.execution_cost_schedule,
                cost_schedule_identity=cost_id,
                minimum_order_notionals=parsed.minimum_order_notionals,
                a_share_rule_selector=parsed.a_share_rule_selector,
                adapter_policy_version=parsed.adapter_policy_version,
                fill_policy_version=parsed.fill_policy_version,
                fault_policy_version=parsed.fault_policy_version,
                finality_policy_version=parsed.finality_policy_version,
                clock_policy_version=parsed.clock_policy_version,
                fx_snapshot_identity=None,
                policy_identity=_sha256(identity_payload),
                verified_at=timestamp,
                _attestation=_PolicyAttestation(b""),
            )
            payload = _policy_payload(result)
            object.__setattr__(result, "_attestation", _PolicyAttestation(_token(payload)))
            if not _verify_token(result):
                raise _Failure("PAPER_POLICY_SEMANTICS_INVALID")
            return result
        finally:
            if anchored is not None:
                anchored.close()

    def load_verified_paper_execution_policy(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        session_date: dt.date,
        now: dt.datetime,
    ) -> VerifiedPaperExecutionPolicy:
        """Fresh-load and mint the sole formal A-share PAPER policy capability."""
        failure: str | None = None
        result: VerifiedPaperExecutionPolicy | None = None
        try:
            result = _load_impl(
                environment=environment,
                session_date=session_date,
                now=now,
            )
        except PaperExecutionPolicyError as exc:
            failure = exc.code
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_POLICY_SEMANTICS_INVALID"
        if failure is not None or result is None:
            raise PaperExecutionPolicyError(
                failure or "PAPER_POLICY_SEMANTICS_INVALID"
            ) from None
        return result

    def _verify_impl(
        *,
        policy: VerifiedPaperExecutionPolicy,
        environment: VerifiedPaperRuntimeEnvironment,
        now: dt.datetime,
    ) -> VerifiedPaperExecutionPolicy:
        if type(policy) is not VerifiedPaperExecutionPolicy or not _verify_token(policy):
            raise _Failure("PAPER_POLICY_STALE")
        try:
            fresh = load_verified_paper_execution_policy(
                environment=environment,
                session_date=policy.session_date,
                now=now,
            )
        except PaperExecutionPolicyError as exc:
            if exc.code == "PAPER_POLICY_ENVIRONMENT_INVALID":
                raise _Failure(exc.code) from None
            raise _Failure("PAPER_POLICY_STALE") from None
        if fresh != policy:
            raise _Failure("PAPER_POLICY_STALE")
        return fresh

    def verify_existing_paper_execution_policy(
        *,
        policy: VerifiedPaperExecutionPolicy,
        environment: VerifiedPaperRuntimeEnvironment,
        now: dt.datetime,
    ) -> VerifiedPaperExecutionPolicy:
        """Fresh-load and exact-compare an existing process-local policy proof."""
        failure: str | None = None
        result: VerifiedPaperExecutionPolicy | None = None
        try:
            result = _verify_impl(policy=policy, environment=environment, now=now)
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_POLICY_STALE"
        if failure is not None or result is None:
            raise PaperExecutionPolicyError(failure or "PAPER_POLICY_STALE") from None
        return result

    return load_verified_paper_execution_policy, verify_existing_paper_execution_policy


(
    load_verified_paper_execution_policy,
    verify_existing_paper_execution_policy,
) = _create_policy_api()
del _create_policy_api


def _require_inputs(
    environment: VerifiedPaperRuntimeEnvironment,
    session_date: dt.date,
    now: dt.datetime,
) -> dt.datetime:
    if type(environment) is not VerifiedPaperRuntimeEnvironment:
        raise _Failure("PAPER_POLICY_ENVIRONMENT_INVALID")
    try:
        if type(environment.config) is not FormalPaperRuntimeConfig:
            raise ValueError
        environment_time = _require_utc(environment.verified_at)
    except _Failure:
        raise _Failure("PAPER_POLICY_ENVIRONMENT_INVALID") from None
    except Exception:
        raise _Failure("PAPER_POLICY_ENVIRONMENT_INVALID") from None
    if type(session_date) is not dt.date or isinstance(session_date, dt.datetime):
        raise _Failure("PAPER_POLICY_SEMANTICS_INVALID")
    timestamp = _require_utc(now)
    if timestamp < environment_time:
        raise _Failure("PAPER_POLICY_STALE")
    return timestamp


def _require_utc(value: dt.datetime) -> dt.datetime:
    try:
        if (
            type(value) is not dt.datetime
            or value.tzinfo is None
            or value.utcoffset() != dt.timedelta(0)
        ):
            raise ValueError
    except Exception:
        raise _Failure("PAPER_POLICY_STALE") from None
    return value


def _require_formal_selector(value: object) -> str:
    if (
        type(value) is not str
        or _SELECTOR_RE.fullmatch(value) is None
        or any(part in value.lower() for part in _FORBIDDEN_SELECTOR_PARTS)
        or value != _FORMAL_SELECTOR
    ):
        raise _Failure("PAPER_POLICY_SELECTOR_UNSUPPORTED")
    return value


def _fresh_verify_environment(
    environment: VerifiedPaperRuntimeEnvironment, now: dt.datetime
) -> None:
    try:
        verify_existing_paper_runtime_preflight(
            environment,
            config_path=environment.config.source_path,
            now=now,
        )
    except Exception:
        raise _Failure("PAPER_POLICY_ENVIRONMENT_INVALID") from None


def _open_anchored_policy(source: Path, project_root: Path) -> _AnchoredPolicyFile:
    descriptor: int | None = None
    try:
        if not isinstance(source, Path) or not isinstance(project_root, Path):
            raise ValueError
        root = Path(os.path.abspath(os.fspath(project_root)))
        absolute = Path(os.path.abspath(os.fspath(source)))
        if not _is_within(absolute, root):
            raise ValueError
        _reject_link_chain(root)
        root_status = os.lstat(root)
        _require_directory_status(root_status)
        root_identity = _directory_identity(root, root_status)
        parent = absolute.parent
        _reject_link_chain(parent)
        parent_status = os.lstat(parent)
        _require_directory_status(parent_status)
        parent_identity = _directory_identity(parent, parent_status)
        path_status = os.lstat(absolute)
        _require_regular_status(path_status)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(absolute, flags)
        opened = os.fstat(descriptor)
        _require_regular_status(opened)
        object_identity = _object_identity(opened)
        if _object_identity(path_status) != object_identity:
            raise ValueError
        raw = _read_descriptor(descriptor)
        after = os.fstat(descriptor)
        if _object_identity(after) != object_identity or len(raw) != after.st_size:
            raise ValueError
        return _AnchoredPolicyFile(
            descriptor=descriptor,
            source_path=absolute,
            parent_path=parent,
            project_root=root,
            raw=raw,
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            source_file_identity=_file_identity(absolute, after),
            source_parent_identity=parent_identity,
            project_root_identity=root_identity,
            object_identity=object_identity,
        )
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        raise _Failure("PAPER_POLICY_SOURCE_INVALID") from None


def _fresh_verify_anchored_policy(anchored: _AnchoredPolicyFile) -> None:
    try:
        opened = os.fstat(anchored.descriptor)
        if _object_identity(opened) != anchored.object_identity:
            raise ValueError
        os.lseek(anchored.descriptor, 0, os.SEEK_SET)
        current = _read_descriptor(anchored.descriptor)
        if current != anchored.raw or len(current) != opened.st_size:
            raise ValueError
        path_status = os.lstat(anchored.source_path)
        parent_status = os.lstat(anchored.parent_path)
        root_status = os.lstat(anchored.project_root)
        if (
            _object_identity(path_status) != anchored.object_identity
            or _file_identity(anchored.source_path, path_status)
            != anchored.source_file_identity
            or _directory_identity(anchored.parent_path, parent_status)
            != anchored.source_parent_identity
            or _directory_identity(anchored.project_root, root_status)
            != anchored.project_root_identity
            or hashlib.sha256(current).hexdigest() != anchored.raw_sha256
        ):
            raise ValueError
    except Exception:
        raise _Failure("PAPER_POLICY_SOURCE_INVALID") from None


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _parse_policy(
    raw: bytes,
    environment: VerifiedPaperRuntimeEnvironment,
    session_date: dt.date,
) -> _ParsedPolicy:
    try:
        text = raw.decode("utf-8")
        document = cast(dict[str, object], tomllib.loads(text))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise _Failure("PAPER_POLICY_SOURCE_INVALID") from None
    try:
        _require_document_shape(document)
        if text != _render_canonical(document):
            raise _Failure("PAPER_POLICY_SOURCE_INVALID")
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_POLICY_SOURCE_INVALID") from None
    try:
        return _validate_semantics(document, environment, session_date)
    except Exception:
        raise _Failure("PAPER_POLICY_SEMANTICS_INVALID") from None


def _require_document_shape(document: object) -> None:
    root = _table(document, {"meta", "selectors", "costs", "trading_config"})
    _table(
        root["meta"],
        {
            "schema_version",
            "policy_version",
            "classification",
            "assumption_notice",
            "effective_from",
            "supported_markets",
        },
    )
    _table(
        root["selectors"],
        {
            "a_share_rule_selector",
            "cost_schedule_selector",
            "adapter_policy_version",
            "fill_policy_version",
            "fault_policy_version",
            "finality_policy_version",
            "clock_policy_version",
        },
    )
    costs = _table(root["costs"], {"minimum_order_notional_cny", "periods"})
    periods = _sequence(costs["periods"])
    if len(periods) != 2:
        raise ValueError
    for period in periods:
        _table(
            period,
            {
                "market",
                "effective_from",
                "commission_rate",
                "commission_min",
                "stamp_tax_sell",
                "transfer_fee",
                "settlement_currency",
            },
        )
    trading = _table(
        root["trading_config"], {"meta", "execution", "rules", "data", "store", "risk"}
    )
    _table(trading["meta"], {"schema_version"})
    _table(
        trading["execution"],
        {"mode", "auto_trade", "manual_approval", "sell_only", "frozen_symbols"},
    )
    _table(
        trading["rules"],
        {
            "a_share_rule_selector",
            "hk_connect_rule_selector",
            "fee_schedule_selector",
            "fx_schedule_selector",
        },
    )
    _table(trading["data"], {"snapshot_max_age_seconds"})
    _table(trading["store"], {"sqlite_uri"})
    risk = _table(trading["risk"], {"limits"})
    limits = _sequence(risk["limits"])
    if len(limits) != 1:
        raise ValueError
    _table(
        limits[0],
        {
            "effective_from",
            "max_order_notional",
            "max_symbol_weight",
            "max_gross_exposure",
            "max_daily_notional",
            "max_orders_per_day",
            "max_cancels_per_day",
        },
    )


def _validate_semantics(
    document: dict[str, object],
    environment: VerifiedPaperRuntimeEnvironment,
    session_date: dt.date,
) -> _ParsedPolicy:
    meta = _mapping(document["meta"])
    selectors = _mapping(document["selectors"])
    costs = _mapping(document["costs"])
    trading_document = _mapping(document["trading_config"])
    expected_meta = {
        "schema_version": _SCHEMA_VERSION,
        "policy_version": _FORMAL_SELECTOR,
        "classification": _CLASSIFICATION,
        "assumption_notice": _ASSUMPTION_NOTICE,
        "effective_from": _EFFECTIVE_FROM,
        "supported_markets": ["SH", "SZ"],
    }
    if meta != expected_meta or session_date < _EFFECTIVE_FROM:
        raise ValueError
    expected_selectors = {
        "a_share_rule_selector": "a_share_execution_rules_v1",
        "cost_schedule_selector": "paper_a_share_cost_schedule_v1",
        "adapter_policy_version": "paper_durable_a_share_adapter_v1",
        "fill_policy_version": "paper_deterministic_fill_v1",
        "fault_policy_version": "paper_controlled_fault_drills_v1",
        "finality_policy_version": "paper_session_eod_finality_v1",
        "clock_policy_version": "utc_system_clock_v1",
    }
    if selectors != expected_selectors:
        raise ValueError
    if any(not _valid_version(cast(str, value)) for value in selectors.values()):
        raise ValueError
    if costs["minimum_order_notional_cny"] != "1.00":
        raise ValueError
    periods = _sequence(costs["periods"])
    expected_periods = (
        _expected_period("SH"),
        _expected_period("SZ"),
    )
    if tuple(periods) != expected_periods:
        raise ValueError
    trading_config = TradingConfig(document=trading_document)
    execution = trading_config.section("execution")
    rules = trading_config.section("rules")
    store = trading_config.section("store")
    risk = trading_config.section("risk")
    if (
        execution["mode"] != "PAPER"
        or execution["auto_trade"] is not False
        or execution["manual_approval"] is not True
        or rules["a_share_rule_selector"] != selectors["a_share_rule_selector"]
        or rules["hk_connect_rule_selector"] != "hk_connect_disabled_v1"
        or rules["fee_schedule_selector"] != selectors["cost_schedule_selector"]
        or rules["fx_schedule_selector"] != "cny_only_no_fx_v1"
        or store["sqlite_uri"] != f"sqlite:///{environment.config.oms_sqlite_filename}"
        or environment.config.oms_sqlite_filename != "oms.sqlite3"
    ):
        raise ValueError
    limits = _sequence(risk["limits"])
    covering = tuple(
        item
        for item in limits
        if cast(dt.date, _mapping(item)["effective_from"]) <= session_date
        and (
            "effective_to" not in _mapping(item)
            or session_date <= cast(dt.date, _mapping(item)["effective_to"])
        )
    )
    if len(covering) != 1:
        raise ValueError
    cost_periods = tuple(
        ExecutionCostPeriod(
            market=Market(cast(str, _mapping(item)["market"])),
            effective_from=cast(dt.date, _mapping(item)["effective_from"]),
            effective_to=None,
            commission_rate=_decimal(_mapping(item)["commission_rate"]),
            commission_min=_decimal(_mapping(item)["commission_min"]),
            stamp_tax_sell=_decimal(_mapping(item)["stamp_tax_sell"]),
            transfer_fee=_decimal(_mapping(item)["transfer_fee"]),
            settlement_currency=Currency(cast(str, _mapping(item)["settlement_currency"])),
        )
        for item in periods
    )
    schedule = build_execution_cost_schedule(
        selector=cast(str, selectors["cost_schedule_selector"]),
        periods=cost_periods,
    )
    if (
        tuple(period.market for period in schedule.periods) != _SUPPORTED_MARKETS
        or any(
            not (
                period.effective_from <= session_date
                and (period.effective_to is None or session_date <= period.effective_to)
                and period.settlement_currency is Currency.CNY
            )
            for period in schedule.periods
        )
    ):
        raise ValueError
    minimums = (build_money_amount(Currency.CNY, Decimal("1.00")),)
    return _ParsedPolicy(
        trading_config=trading_config,
        supported_markets=_SUPPORTED_MARKETS,
        execution_cost_schedule=schedule,
        minimum_order_notionals=minimums,
        a_share_rule_selector=cast(str, selectors["a_share_rule_selector"]),
        adapter_policy_version=cast(str, selectors["adapter_policy_version"]),
        fill_policy_version=cast(str, selectors["fill_policy_version"]),
        fault_policy_version=cast(str, selectors["fault_policy_version"]),
        finality_policy_version=cast(str, selectors["finality_policy_version"]),
        clock_policy_version=cast(str, selectors["clock_policy_version"]),
    )


def _expected_period(market: str) -> dict[str, object]:
    return {
        "market": market,
        "effective_from": _EFFECTIVE_FROM,
        "commission_rate": "0.00025",
        "commission_min": "5.00",
        "stamp_tax_sell": "0.0005",
        "transfer_fee": "0.00001",
        "settlement_currency": "CNY",
    }


def _render_canonical(document: dict[str, object]) -> str:
    meta = _mapping(document["meta"])
    selectors = _mapping(document["selectors"])
    costs = _mapping(document["costs"])
    trading = _mapping(document["trading_config"])
    execution = _mapping(trading["execution"])
    rules = _mapping(trading["rules"])
    data = _mapping(trading["data"])
    store = _mapping(trading["store"])
    limits = _mapping(_sequence(_mapping(trading["risk"])["limits"])[0])
    lines = [
        "[meta]",
        f"schema_version = {_quote(meta['schema_version'])}",
        f"policy_version = {_quote(meta['policy_version'])}",
        f"classification = {_quote(meta['classification'])}",
        f"assumption_notice = {_quote(meta['assumption_notice'])}",
        f"effective_from = {_date_text(meta['effective_from'])}",
        f"supported_markets = {_string_array(meta['supported_markets'])}",
        "",
        "[selectors]",
    ]
    for name in (
        "a_share_rule_selector",
        "cost_schedule_selector",
        "adapter_policy_version",
        "fill_policy_version",
        "fault_policy_version",
        "finality_policy_version",
        "clock_policy_version",
    ):
        lines.append(f"{name} = {_quote(selectors[name])}")
    lines.extend(
        [
            "",
            "[costs]",
            f"minimum_order_notional_cny = {_quote(costs['minimum_order_notional_cny'])}",
        ]
    )
    for period_value in _sequence(costs["periods"]):
        period = _mapping(period_value)
        lines.extend(["", "[[costs.periods]]"])
        for name in (
            "market",
            "effective_from",
            "commission_rate",
            "commission_min",
            "stamp_tax_sell",
            "transfer_fee",
            "settlement_currency",
        ):
            value = period[name]
            rendered = _date_text(value) if name == "effective_from" else _quote(value)
            lines.append(f"{name} = {rendered}")
    lines.extend(
        [
            "",
            "[trading_config.meta]",
            f"schema_version = {_quote(_mapping(trading['meta'])['schema_version'])}",
            "",
            "[trading_config.execution]",
            f"mode = {_quote(execution['mode'])}",
            f"auto_trade = {_bool_text(execution['auto_trade'])}",
            f"manual_approval = {_bool_text(execution['manual_approval'])}",
            f"sell_only = {_bool_text(execution['sell_only'])}",
            f"frozen_symbols = {_string_array(execution['frozen_symbols'])}",
            "",
            "[trading_config.rules]",
        ]
    )
    for name in (
        "a_share_rule_selector",
        "hk_connect_rule_selector",
        "fee_schedule_selector",
        "fx_schedule_selector",
    ):
        lines.append(f"{name} = {_quote(rules[name])}")
    lines.extend(
        [
            "",
            "[trading_config.data]",
            f"snapshot_max_age_seconds = {_int_text(data['snapshot_max_age_seconds'])}",
            "",
            "[trading_config.store]",
            f"sqlite_uri = {_quote(store['sqlite_uri'])}",
            "",
            "[[trading_config.risk.limits]]",
            f"effective_from = {_date_text(limits['effective_from'])}",
            f"max_order_notional = {_float_text(limits['max_order_notional'], 1)}",
            f"max_symbol_weight = {_float_text(limits['max_symbol_weight'], 2)}",
            f"max_gross_exposure = {_float_text(limits['max_gross_exposure'], 1)}",
            f"max_daily_notional = {_float_text(limits['max_daily_notional'], 1)}",
            f"max_orders_per_day = {_int_text(limits['max_orders_per_day'])}",
            f"max_cancels_per_day = {_int_text(limits['max_cancels_per_day'])}",
            "",
        ]
    )
    return "\n".join(lines)


def _table(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(cast(dict[object, object], value)) != keys:
        raise ValueError
    return cast(dict[str, object], value)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise ValueError
    return value


def _quote(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return json.dumps(value, ensure_ascii=True)


def _date_text(value: object) -> str:
    if type(value) is not dt.date or isinstance(value, dt.datetime):
        raise ValueError
    return value.isoformat()


def _string_array(value: object) -> str:
    sequence = _sequence(value)
    if any(type(item) is not str for item in sequence):
        raise ValueError
    return "[" + ", ".join(_quote(item) for item in sequence) + "]"


def _bool_text(value: object) -> str:
    if type(value) is not bool:
        raise ValueError
    return "true" if value else "false"


def _int_text(value: object) -> str:
    if type(value) is not int or isinstance(value, bool):
        raise ValueError
    return str(value)


def _float_text(value: object, places: int) -> str:
    if type(value) is not float:
        raise ValueError
    return f"{value:.{places}f}"


def _decimal(value: object) -> Decimal:
    if type(value) is not str:
        raise ValueError
    result = Decimal(value)
    if not result.is_finite() or result < 0 or format(result, "f") != value:
        raise ValueError
    return result


def _valid_version(value: str) -> bool:
    return (
        _SELECTOR_RE.fullmatch(value) is not None
        and not any(character in "/\\:%" for character in value)
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def paper_execution_cost_schedule_identity(schedule: ExecutionCostSchedule) -> str:
    """Return the sole canonical SHA-256 identity of one ExecutionCostSchedule."""
    if type(schedule) is not ExecutionCostSchedule:
        raise TypeError("paper_execution_cost_schedule_identity requires ExecutionCostSchedule")
    return _sha256(
        {
            "schema_version": "paper-execution-cost-schedule-identity-v1",
            "selector": schedule.selector,
            "periods": [
                {
                    "market": item.market.value,
                    "effective_from": item.effective_from.isoformat(),
                    "effective_to": None,
                    "commission_rate": format(item.commission_rate, "f"),
                    "commission_min": format(item.commission_min, "f"),
                    "stamp_tax_sell": format(item.stamp_tax_sell, "f"),
                    "transfer_fee": format(item.transfer_fee, "f"),
                    "settlement_currency": item.settlement_currency.value,
                }
                for item in schedule.periods
            ],
        }
    )


def _identity_payload(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    selector: str,
    session_date: dt.date,
    raw_sha256: str,
    trading_config_identity_value: str,
    cost_schedule_identity_value: str,
    parsed: _ParsedPolicy,
) -> dict[str, object]:
    return {
        "schema_version": "paper-execution-policy-identity-v1",
        "selector": selector,
        "session_date": session_date.isoformat(),
        "raw_sha256": raw_sha256,
        "environment_verification_identity": environment.verification_identity,
        "trading_config_identity": trading_config_identity_value,
        "cost_schedule_identity": cost_schedule_identity_value,
        "minimum_order_notionals": [
            {"currency": item.currency.value, "amount": format(item.amount, "f")}
            for item in parsed.minimum_order_notionals
        ],
        "supported_markets": [item.value for item in parsed.supported_markets],
        "a_share_rule_selector": parsed.a_share_rule_selector,
        "adapter_policy_version": parsed.adapter_policy_version,
        "fill_policy_version": parsed.fill_policy_version,
        "fault_policy_version": parsed.fault_policy_version,
        "finality_policy_version": parsed.finality_policy_version,
        "clock_policy_version": parsed.clock_policy_version,
        "fx_snapshot_identity": None,
    }


def _policy_payload(policy: VerifiedPaperExecutionPolicy) -> dict[str, object]:
    return {
        "schema_version": policy.schema_version,
        "selector": policy.selector,
        "session_date": policy.session_date.isoformat(),
        "source_path": os.path.normcase(os.path.abspath(os.fspath(policy.source_path))),
        "source_file_identity": policy.source_file_identity,
        "source_parent_identity": policy.source_parent_identity,
        "raw_sha256": policy.raw_sha256,
        "trading_config_identity": policy.trading_config_identity,
        "fresh_trading_config_identity": trading_config_identity(policy.trading_config),
        "supported_markets": [item.value for item in policy.supported_markets],
        "cost_schedule_identity": policy.cost_schedule_identity,
        "fresh_cost_schedule_identity": paper_execution_cost_schedule_identity(
            policy.execution_cost_schedule
        ),
        "minimum_order_notionals": [
            {"currency": item.currency.value, "amount": format(item.amount, "f")}
            for item in policy.minimum_order_notionals
        ],
        "a_share_rule_selector": policy.a_share_rule_selector,
        "adapter_policy_version": policy.adapter_policy_version,
        "fill_policy_version": policy.fill_policy_version,
        "fault_policy_version": policy.fault_policy_version,
        "finality_policy_version": policy.finality_policy_version,
        "clock_policy_version": policy.clock_policy_version,
        "fx_snapshot_identity": policy.fx_snapshot_identity,
        "policy_identity": policy.policy_identity,
        "verified_at": policy.verified_at.isoformat(timespec="microseconds"),
    }


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _object_identity(status: os.stat_result) -> tuple[int, int, int]:
    return status.st_dev, status.st_ino, stat.S_IFMT(status.st_mode)


def _file_identity(path: Path, status: os.stat_result) -> str:
    return _sha256(
        {
            "type": "paper-policy-file-v1",
            "path": os.path.normcase(os.path.abspath(os.fspath(path))),
            "device": status.st_dev,
            "inode": status.st_ino,
            "mode": stat.S_IFMT(status.st_mode),
        }
    )


def _directory_identity(path: Path, status: os.stat_result) -> str:
    _require_directory_status(status)
    return _sha256(
        {
            "type": "paper-policy-directory-v1",
            "path": os.path.normcase(os.path.abspath(os.fspath(path))),
            "device": status.st_dev,
            "inode": status.st_ino,
            "mode": stat.S_IFMT(status.st_mode),
        }
    )


def _is_reparse(status: os.stat_result) -> bool:
    return bool(getattr(status, "st_file_attributes", 0) & _REPARSE_POINT)


def _require_regular_status(status: os.stat_result) -> None:
    if (
        not stat.S_ISREG(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or _is_reparse(status)
        or status.st_nlink != 1
    ):
        raise ValueError


def _require_directory_status(status: os.stat_result) -> None:
    if not stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise ValueError


def _reject_link_chain(path: Path) -> None:
    current = Path(os.path.abspath(os.fspath(path)))
    for candidate in (current, *current.parents):
        status = os.lstat(candidate)
        if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
            raise ValueError


def _is_within(candidate: Path, boundary: Path) -> bool:
    try:
        return os.path.commonpath((candidate, boundary)) == os.path.commonpath((boundary, boundary))
    except ValueError:
        return False


def _before_policy_mint_hook(path: Path) -> None:
    del path


__all__ = [
    "PaperExecutionPolicyError",
    "VerifiedPaperExecutionPolicy",
    "load_verified_paper_execution_policy",
    "paper_execution_cost_schedule_identity",
    "verify_existing_paper_execution_policy",
]
