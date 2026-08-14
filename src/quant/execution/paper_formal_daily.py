"""Receipt-backed formal PAPER daily inputs and read-only runner composition."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import re
import stat
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping

import polars as pl

from quant.backtest.a_share_execution import build_a_share_rule_config
from quant.domain import (
    InstrumentSchema,
    PriceLimit1dSchema,
    Suspension1dSchema,
    TargetWeightSchema,
    TradeCalendarSchema,
)
from quant.domain.canonical_wire import canonical_json_bytes
from quant.domain.enums import Currency, Market
from quant.execution.cli_ports import (
    BrokerSnapshotPort,
    CliDependencies,
    VerifiedPlanningLoad,
    VerifiedTargetLoad,
    build_verified_planning_load,
    build_verified_target_load,
    verify_broker_evidence,
)
from quant.execution.paper_formal_broker_snapshot import (
    open_verified_formal_paper_broker_snapshot_port,
)
from quant.execution.paper_formal_service import (
    VerifiedFormalPaperServiceComposition,
    verify_existing_formal_paper_service_composition,
)
from quant.execution.contracts import (
    SymbolMarketState,
    VerifiedMarketSnapshot,
    build_symbol_market_state,
    build_verified_market_snapshot,
)
from quant.execution.paper_policy import (
    VerifiedPaperExecutionPolicy,
    verify_existing_paper_execution_policy,
)
from quant.execution.paper_runtime import (
    VerifiedPaperRuntimeEnvironment,
    verify_existing_paper_runtime_preflight,
)
from quant.portfolio.order_planner import OrderPlanTarget, build_order_planner_config
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    ResearchOutputDigestV1,
    canonical_json_bytes as research_canonical_json_bytes,
)

_SOURCE_SCHEMA = "formal-paper-daily-source-v1"
_SOURCE_CLASSIFICATION = "formal-paper-simulation"
_MARKET_SCHEMA = "formal-paper-opening-market-receipt-v1"
_TARGET_OUTPUT = "target_weights.parquet"
_MARKET_FILES = (
    "instrument.parquet",
    "opening_price.parquet",
    "price_limit_1d.parquet",
    "suspension_1d.parquet",
    "trade_calendar.parquet",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ)$")
_REPARSE_POINT = 0x400
_UTC = dt.timezone.utc


class FormalPaperDailyInputError(ValueError):
    """Stable sanitized failure for formal daily source inputs."""

    def __init__(self) -> None:
        self.code = "PAPER_FORMAL_DAILY_INPUT_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


class FormalPaperDailyRunnerError(ValueError):
    """Stable sanitized failure for formal read-only runner composition."""

    def __init__(self) -> None:
        self.code = "PAPER_FORMAL_DAILY_RUNNER_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class FormalPaperDailySourcePlan:
    schema_version: Literal["formal-paper-daily-source-v1"]
    classification: Literal["formal-paper-simulation"]
    selector: str
    target_run_id: str
    market_source_version: str
    allowed_markets: tuple[Market, ...]
    signal_timing: Literal["close"]
    execution_timing: Literal["next_session_open"]
    raw_sha256: str
    source_identity: str


@dataclass(frozen=True, slots=True)
class _TargetBundle:
    verified: VerifiedTargetLoad
    run: LightweightResearchRunV1
    as_of: dt.date
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _MarketBundle:
    receipt: Mapping[str, object]
    instruments: pl.DataFrame
    opening_prices: pl.DataFrame
    limits: pl.DataFrame
    suspensions: pl.DataFrame
    calendar: pl.DataFrame


class FormalPaperCandidateTargetLoader:
    """TargetLoader backed only by one exact PAPER_CANDIDATE run."""

    def __init__(
        self,
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        source_plan: FormalPaperDailySourcePlan,
        session_date: dt.date,
        now: dt.datetime,
    ) -> None:
        self._environment = environment
        self._source_plan = source_plan
        self._session_date = session_date
        self._now = now

    def load(self) -> VerifiedTargetLoad:
        return self._load_bundle().verified

    def _load_bundle(self) -> _TargetBundle:
        try:
            _fresh_environment(self._environment, self._now)
            current = load_formal_paper_daily_source_plan(
                environment=self._environment, now=self._now
            )
            if current != self._source_plan:
                raise ValueError
            root = (
                self._environment.config.project_root
                / "artifacts"
                / "research"
                / "runs"
                / current.target_run_id
            )
            run, output_raw = _verify_research_run(root)
            if (
                run.run_id != current.target_run_id
                or run.conclusion != "PAPER_CANDIDATE"
                or run.signal_timing != "close"
                or run.execution_timing != "next_session_open"
                or _TARGET_OUTPUT not in output_raw
            ):
                raise ValueError
            raw = output_raw[_TARGET_OUTPUT]
            frame = TargetWeightSchema.validate(pl.read_parquet(io.BytesIO(raw)))
            expected_columns = [
                "as_of",
                "strategy",
                "strategy_version",
                "symbol",
                "weight",
            ]
            if frame.columns != expected_columns or frame.is_empty():
                raise ValueError
            ordered = frame.sort(expected_columns[:-1])
            if not frame.equals(ordered):
                raise ValueError
            as_of_values = frame.get_column("as_of").unique().to_list()
            strategies = frame.get_column("strategy").unique().to_list()
            versions = frame.get_column("strategy_version").unique().to_list()
            if (
                len(as_of_values) != 1
                or type(as_of_values[0]) is not dt.date
                or len(strategies) != 1
                or strategies[0] != run.strategy_name
                or len(versions) != 1
                or versions[0] != run.strategy_version
                or as_of_values[0] >= self._session_date
            ):
                raise ValueError
            rows = {row["symbol"]: row for row in frame.to_dicts()}
            candidates = run.candidate_symbols
            if (
                any(_SYMBOL.fullmatch(symbol) is None for symbol in candidates)
                or not set(rows).issubset(candidates)
            ):
                raise ValueError
            targets = tuple(sorted(
                (
                OrderPlanTarget(
                    symbol=symbol,
                    market=_symbol_market(symbol),
                    connect_route=None,
                    target_weight=Decimal(str(rows.get(symbol, {"weight": 0.0})["weight"])),
                )
                for symbol in candidates
                ),
                key=lambda item: (item.market.value, item.symbol),
            ))
            target_identity = _sha256(
                {
                    "schema_version": "formal-paper-candidate-target-v1",
                    "run_id": run.run_id,
                    "target_weights_sha256": _sha256_bytes(raw),
                    "targets": [
                        {
                            "market": item.market.value,
                            "symbol": item.symbol,
                            "target_weight": format(item.target_weight, "f"),
                        }
                        for item in targets
                    ],
                }
            )
            verified = build_verified_target_load(
                target_identity=target_identity,
                receipt_identity=_sha256_bytes((root / "run.json").read_bytes()),
                targets=targets,
            )
            return _TargetBundle(verified, run, as_of_values[0], candidates)
        except Exception:
            pass
        raise FormalPaperDailyInputError() from None


class FormalPaperPlanningLoader:
    """PlanningLoader composing the candidate, opening facts and broker account."""

    def __init__(
        self,
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        source_plan: FormalPaperDailySourcePlan,
        target_loader: FormalPaperCandidateTargetLoader,
        broker_snapshot_port: BrokerSnapshotPort,
        gateway_identity: str,
        session_date: dt.date,
        now: dt.datetime,
    ) -> None:
        self._environment = environment
        self._policy = policy
        self._source_plan = source_plan
        self._target_loader = target_loader
        self._broker_snapshot_port = broker_snapshot_port
        self._gateway_identity = gateway_identity
        self._session_date = session_date
        self._now = now

    def load(self) -> VerifiedPlanningLoad:
        try:
            _fresh_environment(self._environment, self._now)
            policy = verify_existing_paper_execution_policy(
                policy=self._policy,
                environment=self._environment,
                now=self._now,
            )
            if policy is not self._policy or policy.session_date != self._session_date:
                raise ValueError
            target = self._target_loader._load_bundle()
            evidence = verify_broker_evidence(
                self._broker_snapshot_port.query_and_verify(
                    gateway_identity=self._gateway_identity
                )
            )
            if evidence.gateway_identity != self._gateway_identity:
                raise ValueError
            account_symbols = tuple(position.symbol for position in evidence.account.positions)
            requested = tuple(sorted(set(target.symbols) | set(account_symbols)))
            if any(_SYMBOL.fullmatch(symbol) is None for symbol in requested):
                raise ValueError
            market_root = (
                self._environment.config.project_root
                / "artifacts"
                / "paper_inputs"
                / "opening"
                / f"session={self._session_date.isoformat()}"
            )
            market_bundle = _verify_market_bundle(
                market_root,
                expected_session=self._session_date,
                expected_source_version=self._source_plan.market_source_version,
            )
            _verify_next_sessions(
                market_bundle.calendar,
                markets=tuple(sorted({item.value for item in self._source_plan.allowed_markets})),
                signal_date=target.as_of,
                session_date=self._session_date,
            )
            market = _build_market_snapshot(
                bundle=market_bundle,
                symbols=requested,
                policy=policy,
                session_date=self._session_date,
            )
            effective_from = min(
                item.effective_from for item in policy.execution_cost_schedule.periods
            )
            planner = build_order_planner_config(
                trading_config=policy.trading_config,
                a_share_rule_config=build_a_share_rule_config(
                    selector=policy.a_share_rule_selector,
                    effective_from=effective_from,
                    effective_to=None,
                ),
                connect_rule_configs=(),
                execution_cost_schedule=policy.execution_cost_schedule,
                fx_snapshot=None,
                minimum_order_notionals=policy.minimum_order_notionals,
            )
            return build_verified_planning_load(
                market=market,
                account=evidence.account,
                planner_config=planner,
            )
        except Exception:
            pass
        raise FormalPaperDailyInputError() from None


@dataclass(frozen=True, slots=True)
class _FixedClock:
    timestamp: dt.datetime

    def now(self) -> dt.datetime:
        return self.timestamp


def build_formal_paper_daily_dependencies(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    composition: VerifiedFormalPaperServiceComposition,
    session_date: dt.date,
    now: dt.datetime,
) -> CliDependencies:
    """Compose CLI dependencies from one fresh formal PAPER capability chain."""
    try:
        timestamp = _utc(now)
        if type(session_date) is not dt.date:
            raise TypeError
        _fresh_environment(environment, timestamp)
        fresh_policy = verify_existing_paper_execution_policy(
            policy=policy, environment=environment, now=timestamp
        )
        fresh_composition = verify_existing_formal_paper_service_composition(
            composition=composition, now=timestamp
        )
        store = composition._execution_store
        if (
            fresh_policy is not policy
            or fresh_composition is not composition
            or store.environment is not environment
            or store.policy is not policy
            or policy.session_date != session_date
            or composition.account_id != store.account_id
            or composition.gateway_identity != store.gateway_identity
        ):
            raise ValueError
        source_plan = load_formal_paper_daily_source_plan(
            environment=environment, now=timestamp
        )
        broker_snapshot = open_verified_formal_paper_broker_snapshot_port(
            store_capability=store.broker_store,
            environment=environment,
            policy=policy,
            binding=store.binding,
            account=store.account,
            now=timestamp,
        )
        target_loader = FormalPaperCandidateTargetLoader(
            environment=environment,
            source_plan=source_plan,
            session_date=session_date,
            now=timestamp,
        )
        planning_loader = FormalPaperPlanningLoader(
            environment=environment,
            policy=policy,
            source_plan=source_plan,
            target_loader=target_loader,
            broker_snapshot_port=broker_snapshot,
            gateway_identity=composition.gateway_identity,
            session_date=session_date,
            now=timestamp,
        )
        return CliDependencies(
            store_opener=composition.store_opener,
            target_loader=target_loader,
            planning_loader=planning_loader,
            service_factory=composition.service_factory,
            paper_gateway_factory=composition.gateway_factory,
            broker_snapshot_port=broker_snapshot,
            clock=_FixedClock(timestamp),
        )
    except Exception:
        pass
    raise FormalPaperDailyRunnerError() from None


def run_formal_paper_daily_read_only(
    *,
    action: Literal["inspect", "plan"],
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    composition: VerifiedFormalPaperServiceComposition,
    session_date: dt.date,
    now: dt.datetime,
) -> int:
    """Run exactly one non-dispatching daily PAPER CLI action."""
    if action not in ("inspect", "plan"):
        raise FormalPaperDailyRunnerError() from None
    dependencies = build_formal_paper_daily_dependencies(
        environment=environment,
        policy=policy,
        composition=composition,
        session_date=session_date,
        now=now,
    )
    from quant.execution.cli import main

    return main([action], dependencies=dependencies)


def load_formal_paper_daily_source_plan(
    *, environment: VerifiedPaperRuntimeEnvironment, now: dt.datetime
) -> FormalPaperDailySourcePlan:
    """Fresh-load the source selector controlling formal target and market roots."""
    try:
        _fresh_environment(environment, now)
        selector = environment.config.source_selector
        if not _formal_token(selector):
            raise ValueError
        path = (
            environment.config.project_root
            / "configs"
            / "trading"
            / "sources"
            / f"{selector}.toml"
        )
        raw = _read_stable_file(path)
        parsed = tomllib.loads(raw.decode("utf-8"))
        if type(parsed) is not dict or set(parsed) != {"meta", "target", "market"}:
            raise ValueError
        meta = _mapping(parsed["meta"], {"schema_version", "classification", "source_version"})
        target = _mapping(
            parsed["target"],
            {"run_id", "artifact_kind", "signal_timing", "execution_timing"},
        )
        market = _mapping(parsed["market"], {"source_version", "allowed_markets"})
        markets_raw = market["allowed_markets"]
        if type(markets_raw) is not list or markets_raw != ["SH", "SZ"]:
            raise ValueError
        if (
            meta["schema_version"] != _SOURCE_SCHEMA
            or meta["classification"] != _SOURCE_CLASSIFICATION
            or meta["source_version"] != selector
            or target["artifact_kind"] != "lightweight-research-run-v1"
            or target["signal_timing"] != "close"
            or target["execution_timing"] != "next_session_open"
            or type(target["run_id"]) is not str
            or _HEX64.fullmatch(target["run_id"]) is None
            or not _formal_token(market["source_version"])
        ):
            raise ValueError
        raw_sha = _sha256_bytes(raw)
        body = {
            "schema_version": _SOURCE_SCHEMA,
            "classification": _SOURCE_CLASSIFICATION,
            "selector": selector,
            "target_run_id": target["run_id"],
            "market_source_version": market["source_version"],
            "allowed_markets": markets_raw,
            "signal_timing": "close",
            "execution_timing": "next_session_open",
            "raw_sha256": raw_sha,
        }
        target_run_id = target["run_id"]
        market_source_version = market["source_version"]
        if type(target_run_id) is not str or type(market_source_version) is not str:
            raise ValueError
        return FormalPaperDailySourcePlan(
            schema_version="formal-paper-daily-source-v1",
            classification="formal-paper-simulation",
            selector=selector,
            target_run_id=target_run_id,
            market_source_version=market_source_version,
            allowed_markets=(Market.SH, Market.SZ),
            signal_timing="close",
            execution_timing="next_session_open",
            raw_sha256=raw_sha,
            source_identity=_sha256(body),
        )
    except Exception:
        pass
    raise FormalPaperDailyInputError() from None


def publish_formal_paper_opening_market_input(
    *,
    project_root: Path,
    session_date: dt.date,
    known_as_of: dt.datetime,
    source_version: str,
    instruments: pl.DataFrame,
    opening_prices: pl.DataFrame,
    price_limits: pl.DataFrame,
    suspensions: pl.DataFrame,
    calendar: pl.DataFrame,
) -> tuple[Path, str, bool]:
    """Publish one canonical, no-clobber opening-facts package from clean frames."""
    try:
        root = project_root.resolve(strict=True)
        if type(session_date) is not dt.date or isinstance(session_date, dt.datetime):
            raise ValueError
        timestamp = _utc(known_as_of)
        if not _formal_token(source_version):
            raise ValueError
        frames = _canonical_market_frames(
            session_date=session_date,
            known_as_of=timestamp,
            instruments=instruments,
            opening_prices=opening_prices,
            price_limits=price_limits,
            suspensions=suspensions,
            calendar=calendar,
        )
        payloads = {
            name: _parquet_bytes(frame)
            for name, frame in zip(_MARKET_FILES, frames, strict=True)
        }
        entries = {
            name: {"sha256": _sha256_bytes(raw), "size_bytes": len(raw)}
            for name, raw in payloads.items()
        }
        body: dict[str, object] = {
            "schema_version": _MARKET_SCHEMA,
            "session_date": session_date.isoformat(),
            "known_as_of": _utc_text(timestamp),
            "source_version": source_version,
            "quality_passed": True,
            "files": entries,
        }
        source_identity = _sha256(body)
        receipt_raw = canonical_json_bytes({**body, "source_identity": source_identity})
        output = (
            root
            / "artifacts"
            / "paper_inputs"
            / "opening"
            / f"session={session_date.isoformat()}"
        )
        complete = {**payloads, "receipt.json": receipt_raw}
        if output.exists():
            _verify_exact_payloads(output, complete)
            return output, source_identity, True
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.parent / f".{output.name}.tmp-{os.getpid()}"
        temp.mkdir()
        try:
            for name, raw in sorted(complete.items()):
                _write_exclusive(temp / name, raw)
            temp.rename(output)
        except BaseException:
            _remove_owned_temp(temp)
            raise
        _verify_exact_payloads(output, complete)
        return output, source_identity, False
    except Exception:
        pass
    raise FormalPaperDailyInputError() from None


def _verify_research_run(root: Path) -> tuple[LightweightResearchRunV1, dict[str, bytes]]:
    _require_plain_dir(root)
    manifest_raw = _read_stable_file(root / "run.json")
    value = _canonical_object(manifest_raw)
    run = _parse_run(value)
    outputs: dict[str, bytes] = {}
    expected = {"run.json"}
    physical: set[tuple[int, int]] = set()
    for item in run.outputs:
        relative = _relative(item.relative_path)
        expected.add(relative.as_posix())
        raw = _read_stable_file(root / relative)
        if len(raw) != item.size_bytes or _sha256_bytes(raw) != item.sha256:
            raise ValueError
        identity = _file_object(root / relative)
        if identity in physical:
            raise ValueError
        physical.add(identity)
        outputs[relative.as_posix()] = raw
    if _tree_files(root) != expected:
        raise ValueError
    expected_run_id = hashlib.sha256(
        research_canonical_json_bytes(
            [
                "lightweight-research-run-id-v1",
                {k: v for k, v in value.items() if k != "run_id"},
            ]
        )
    ).hexdigest()
    if run.run_id != expected_run_id or manifest_raw != research_canonical_json_bytes(value):
        raise ValueError
    return run, outputs


def _parse_run(value: Mapping[str, object]) -> LightweightResearchRunV1:
    expected = {
        "schema_version", "run_id", "hypothesis_id", "hypothesis", "strategy_name",
        "strategy_version", "conclusion", "random_seed", "config_relative_path",
        "config_sha256", "code_sha256", "universe_name", "universe_frozen_as_of",
        "candidate_symbols", "data_start", "data_end", "signal_timing",
        "execution_timing", "valuation_timing", "folds", "cost_multipliers",
        "selection_metric", "inputs", "outputs", "aggregate_metrics", "caveats",
    }
    if set(value) != expected:
        raise ValueError
    folds_raw = _list(value["folds"])
    inputs_raw = _list(value["inputs"])
    outputs_raw = _list(value["outputs"])
    metrics_raw = _list(value["aggregate_metrics"])
    return LightweightResearchRunV1(
        schema_version=_text(value["schema_version"]),  # type: ignore[arg-type]
        run_id=_text(value["run_id"]),
        hypothesis_id=_text(value["hypothesis_id"]),
        hypothesis=_text(value["hypothesis"]),
        strategy_name=_text(value["strategy_name"]),
        strategy_version=_text(value["strategy_version"]),
        conclusion=_text(value["conclusion"]),  # type: ignore[arg-type]
        random_seed=_integer(value["random_seed"]),
        config_relative_path=_text(value["config_relative_path"]),
        config_sha256=_text(value["config_sha256"]),
        code_sha256=_text(value["code_sha256"]),
        universe_name=_text(value["universe_name"]),
        universe_frozen_as_of=_date(value["universe_frozen_as_of"]),
        candidate_symbols=tuple(_text(item) for item in _list(value["candidate_symbols"])),
        data_start=_date(value["data_start"]),
        data_end=_date(value["data_end"]),
        signal_timing=_text(value["signal_timing"]),  # type: ignore[arg-type]
        execution_timing=_text(value["execution_timing"]),  # type: ignore[arg-type]
        valuation_timing=_text(value["valuation_timing"]),  # type: ignore[arg-type]
        folds=tuple(_parse_fold(_object(item)) for item in folds_raw),
        cost_multipliers=tuple(_float(item) for item in _list(value["cost_multipliers"])),
        selection_metric=_text(value["selection_metric"]),
        inputs=tuple(_parse_input(_object(item)) for item in inputs_raw),
        outputs=tuple(_parse_output(_object(item)) for item in outputs_raw),
        aggregate_metrics=tuple(_metric(item) for item in metrics_raw),
        caveats=tuple(_text(item) for item in _list(value["caveats"])),
    )


def _parse_fold(value: Mapping[str, object]) -> ResearchFoldV1:
    if set(value) != {
        "fold", "train_start", "train_end", "validation_start", "validation_end",
        "test_start", "test_end",
    }:
        raise ValueError
    return ResearchFoldV1(
        _integer(value["fold"]), _date(value["train_start"]), _date(value["train_end"]),
        _date(value["validation_start"]), _date(value["validation_end"]),
        _date(value["test_start"]), _date(value["test_end"]),
    )


def _parse_input(value: Mapping[str, object]) -> ResearchInputDigestV1:
    if set(value) != {"name", "rows", "min_date", "max_date", "content_sha256"}:
        raise ValueError
    return ResearchInputDigestV1(
        _text(value["name"]), _integer(value["rows"]), _optional_date(value["min_date"]),
        _optional_date(value["max_date"]), _text(value["content_sha256"]),
    )


def _parse_output(value: Mapping[str, object]) -> ResearchOutputDigestV1:
    if set(value) != {"relative_path", "size_bytes", "sha256"}:
        raise ValueError
    return ResearchOutputDigestV1(
        _text(value["relative_path"]), _integer(value["size_bytes"]), _text(value["sha256"])
    )


def _metric(value: object) -> tuple[str, float | int]:
    items = _list(value)
    if len(items) != 2 or type(items[1]) not in {int, float}:
        raise ValueError
    return _text(items[0]), items[1]  # type: ignore[return-value]


def _verify_market_bundle(
    root: Path, *, expected_session: dt.date, expected_source_version: str
) -> _MarketBundle:
    _require_plain_dir(root)
    receipt_raw = _read_stable_file(root / "receipt.json")
    receipt = _canonical_object(receipt_raw)
    if set(receipt) != {
        "schema_version", "session_date", "known_as_of", "source_version",
        "quality_passed", "files", "source_identity",
    }:
        raise ValueError
    if (
        receipt["schema_version"] != _MARKET_SCHEMA
        or _date(receipt["session_date"]) != expected_session
        or receipt["source_version"] != expected_source_version
        or receipt["quality_passed"] is not True
        or type(receipt["source_identity"]) is not str
        or _HEX64.fullmatch(receipt["source_identity"]) is None
    ):
        raise ValueError
    files = _object(receipt["files"])
    if set(files) != set(_MARKET_FILES) or _tree_files(root) != {"receipt.json", *_MARKET_FILES}:
        raise ValueError
    frames: list[pl.DataFrame] = []
    physical: set[tuple[int, int]] = set()
    for name in _MARKET_FILES:
        entry = _object(files[name])
        if set(entry) != {"sha256", "size_bytes"}:
            raise ValueError
        raw = _read_stable_file(root / name)
        if _sha256_bytes(raw) != entry["sha256"] or len(raw) != entry["size_bytes"]:
            raise ValueError
        identity = _file_object(root / name)
        if identity in physical:
            raise ValueError
        physical.add(identity)
        frames.append(pl.read_parquet(io.BytesIO(raw)))
    body = {key: receipt[key] for key in receipt if key != "source_identity"}
    if receipt["source_identity"] != _sha256(body):
        raise ValueError
    canonical = _canonical_market_frames(
        session_date=expected_session,
        known_as_of=_datetime(receipt["known_as_of"]),
        instruments=frames[0], opening_prices=frames[1], price_limits=frames[2],
        suspensions=frames[3], calendar=frames[4],
    )
    if any(not left.equals(right) for left, right in zip(frames, canonical, strict=True)):
        raise ValueError
    return _MarketBundle(receipt, *frames)


def _canonical_market_frames(
    *,
    session_date: dt.date,
    known_as_of: dt.datetime,
    instruments: pl.DataFrame,
    opening_prices: pl.DataFrame,
    price_limits: pl.DataFrame,
    suspensions: pl.DataFrame,
    calendar: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    timestamp = _utc(known_as_of)
    inst = InstrumentSchema.validate(instruments).sort("symbol")
    limits = PriceLimit1dSchema.validate(price_limits).sort(["symbol", "trade_date", "source"])
    susp = Suspension1dSchema.validate(suspensions).sort(["symbol", "trade_date", "source"])
    cal = TradeCalendarSchema.validate(calendar).sort(["market", "date"])
    expected_open_columns = {
        "symbol": pl.String,
        "session_date": pl.Date,
        "open": pl.Float64,
        "source": pl.String,
        "source_snapshot_id": pl.String,
        "known_at": pl.Datetime(time_zone="UTC"),
    }
    if opening_prices.schema != expected_open_columns:
        raise ValueError
    opening = opening_prices.sort("symbol")
    if (
        inst.is_empty()
        or limits.is_empty()
        or cal.is_empty()
        or opening.get_column("symbol").n_unique() != opening.height
        or limits.get_column("symbol").n_unique() != limits.height
        or susp.get_column("symbol").n_unique() != susp.height
        or any(_SYMBOL.fullmatch(value) is None for value in inst.get_column("symbol").to_list())
        or set(inst.get_column("market").to_list()) - {"SH", "SZ"}
        or set(inst.get_column("currency").to_list()) != {"CNY"}
        or set(limits.get_column("symbol").to_list()) != set(inst.get_column("symbol").to_list())
        or set(opening.get_column("symbol").to_list()) - set(inst.get_column("symbol").to_list())
        or set(susp.get_column("symbol").to_list()) - set(inst.get_column("symbol").to_list())
        or any(value != session_date for value in limits.get_column("trade_date").to_list())
        or any(value != session_date for value in opening.get_column("session_date").to_list())
        or any(value != session_date for value in susp.get_column("trade_date").to_list())
        or any(value != timestamp for value in opening.get_column("known_at").to_list())
        or opening.filter(~pl.col("open").is_finite() | (pl.col("open") <= 0)).height
        or opening.filter(pl.col("source").str.len_chars() == 0).height
        or opening.filter(pl.col("source_snapshot_id").str.len_chars() == 0).height
    ):
        raise ValueError
    session_rows = cal.filter(pl.col("date") == session_date)
    markets = sorted(set(inst.get_column("market").to_list()))
    if (
        session_rows.filter(pl.col("market").is_in(markets)).height != len(markets)
        or not session_rows.filter(pl.col("market").is_in(markets)).get_column("is_open").all()
    ):
        raise ValueError
    full_day = set(
        susp.filter(pl.col("suspension_scope") == "FULL_DAY").get_column("symbol").to_list()
    )
    if set(inst.get_column("symbol").to_list()) - full_day != set(opening.get_column("symbol").to_list()):
        raise ValueError
    return inst, opening, limits, susp, cal


def _build_market_snapshot(
    *, bundle: _MarketBundle, symbols: tuple[str, ...], policy: VerifiedPaperExecutionPolicy,
    session_date: dt.date,
) -> VerifiedMarketSnapshot:
    instruments = {row["symbol"]: row for row in bundle.instruments.to_dicts()}
    openings = {row["symbol"]: row for row in bundle.opening_prices.to_dicts()}
    limits = {row["symbol"]: row for row in bundle.limits.to_dicts()}
    suspensions = {row["symbol"]: row for row in bundle.suspensions.to_dicts()}
    states: list[SymbolMarketState] = []
    for symbol in symbols:
        instrument = instruments.get(symbol)
        limit = limits.get(symbol)
        suspension = suspensions.get(symbol)
        full_day = suspension is not None and suspension["suspension_scope"] == "FULL_DAY"
        opening = openings.get(symbol)
        if instrument is None or limit is None or (opening is None and not full_day):
            raise ValueError
        if full_day:
            reference = limit["pre_close"]
        else:
            if opening is None:
                raise ValueError
            reference = opening["open"]
        states.append(
            build_symbol_market_state(
                symbol=symbol,
                market=_symbol_market(symbol),
                session_date=session_date,
                quote_currency=Currency.CNY,
                reference_price=Decimal(str(reference)),
                limit_up=None if limit["up_limit"] is None else Decimal(str(limit["up_limit"])),
                limit_down=None if limit["down_limit"] is None else Decimal(str(limit["down_limit"])),
                suspended=suspension is not None,
                board_lot=instrument["board_lot"],
                tick_size=Decimal("0.01"),
                rule_version=policy.a_share_rule_selector,
            )
        )
    return build_verified_market_snapshot(
        as_of=_datetime(bundle.receipt["known_as_of"]),
        session_date=session_date,
        states=states,
        connect_contexts=(),
        calendar_identity=_frame_identity(bundle.calendar),
        source_identity=_text(bundle.receipt["source_identity"]),
    )


def _verify_next_sessions(
    calendar: pl.DataFrame, *, markets: tuple[str, ...], signal_date: dt.date,
    session_date: dt.date,
) -> None:
    for market in markets:
        rows = calendar.filter(
            (pl.col("market") == market)
            & (pl.col("date") >= signal_date)
            & (pl.col("date") <= session_date)
        ).sort("date")
        if rows.is_empty():
            raise ValueError
        opened = rows.filter(pl.col("is_open")).get_column("date").to_list()
        if opened != [signal_date, session_date]:
            raise ValueError


def _fresh_environment(environment: VerifiedPaperRuntimeEnvironment, now: dt.datetime) -> None:
    verify_existing_paper_runtime_preflight(
        environment,
        config_path=environment.config.source_path,
        now=_utc(now),
    )


def _verify_exact_payloads(root: Path, payloads: Mapping[str, bytes]) -> None:
    _require_plain_dir(root)
    if _tree_files(root) != set(payloads):
        raise ValueError
    for name, expected in payloads.items():
        if _read_stable_file(root / name) != expected:
            raise ValueError


def _tree_files(root: Path) -> set[str]:
    result: set[str] = set()
    for path in root.rglob("*"):
        status = path.lstat()
        if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
            raise ValueError
        if path.is_file():
            result.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ValueError
    return result


def _read_stable_file(path: Path) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise ValueError
    first = path.read_bytes()
    second = path.read_bytes()
    after = path.lstat()
    if first != second or _stat_identity(before) != _stat_identity(after):
        raise ValueError
    return first


def _require_plain_dir(path: Path) -> None:
    status = path.lstat()
    if not stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise ValueError


def _file_object(path: Path) -> tuple[int, int]:
    status = path.lstat()
    return status.st_dev, status.st_ino


def _is_reparse(status: os.stat_result) -> bool:
    return bool(getattr(status, "st_file_attributes", 0) & _REPARSE_POINT)


def _stat_identity(status: os.stat_result) -> tuple[int, int, int, int, int]:
    return status.st_dev, status.st_ino, stat.S_IFMT(status.st_mode), status.st_size, status.st_mtime_ns


def _parquet_bytes(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd", statistics=True)
    return buffer.getvalue()


def _write_exclusive(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _remove_owned_temp(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file() and not child.is_symlink():
            child.unlink()
        else:
            raise ValueError
    path.rmdir()


def _canonical_object(raw: bytes) -> Mapping[str, object]:
    value = json.loads(raw)
    if type(value) is not dict or raw != canonical_json_bytes(value):
        raise ValueError
    return value


def _mapping(value: object, keys: set[str]) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError
    return value


def _object(value: object) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ValueError
    return value


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError
    return value


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError
    return value


def _float(value: object) -> float:
    if type(value) is not float:
        raise ValueError
    return value


def _date(value: object) -> dt.date:
    if type(value) is not str:
        raise ValueError
    result = dt.date.fromisoformat(value)
    return result


def _optional_date(value: object) -> dt.date | None:
    return None if value is None else _date(value)


def _datetime(value: object) -> dt.datetime:
    if type(value) is not str:
        raise ValueError
    return _utc(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))


def _utc(value: dt.datetime) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ValueError
    return value


def _utc_text(value: dt.datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError
    return path


def _symbol_market(symbol: str) -> Market:
    suffix = symbol.rsplit(".", 1)[-1]
    return Market(suffix)


def _formal_token(value: object) -> bool:
    return (
        type(value) is str
        and _TOKEN.fullmatch(value) is not None
        and not any(part in value.lower() for part in ("development", "example", "fixture"))
    )


def _frame_identity(frame: pl.DataFrame) -> str:
    return _sha256(
        {
            "columns": frame.columns,
            "dtypes": [str(dtype) for dtype in frame.dtypes],
            "rows": [[_json_value(item) for item in row] for row in frame.iter_rows()],
        }
    )


def _json_value(value: object) -> object:
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is dt.datetime:
        return value.isoformat().replace("+00:00", "Z")
    if type(value) is Decimal:
        return format(value, "f")
    return value


def _sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "FormalPaperCandidateTargetLoader",
    "FormalPaperDailyInputError",
    "FormalPaperDailyRunnerError",
    "FormalPaperDailySourcePlan",
    "FormalPaperPlanningLoader",
    "build_formal_paper_daily_dependencies",
    "load_formal_paper_daily_source_plan",
    "publish_formal_paper_opening_market_input",
    "run_formal_paper_daily_read_only",
]
