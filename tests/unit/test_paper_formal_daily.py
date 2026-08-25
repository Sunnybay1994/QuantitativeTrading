from __future__ import annotations

import datetime as dt
import hashlib
import io
import sys
import traceback
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import polars as pl
import pytest

from quant.domain.enums import Market
from quant.execution import paper_formal_daily as daily
from quant.execution.gateways.contracts import DispatchCertainty
from quant.execution.reconcile import recover_local_state
from quant.execution.store import OutboxDeliveryState
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    publish_lightweight_research_run,
)
from tests.unit.test_execution_cli import _deps, _json

NOW = dt.datetime(2026, 8, 14, 1, 31, tzinfo=dt.timezone.utc)
SESSION = dt.date(2026, 8, 14)


def _parquet(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return buffer.getvalue()


def _candidate_run() -> LightweightResearchRunV1:
    return LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id="paper-candidate-v1",
        hypothesis="A frozen candidate is ready for PAPER-only observation.",
        strategy_name="first_paper_candidate",
        strategy_version="1.0.0",
        conclusion="PAPER_CANDIDATE",
        random_seed=0,
        config_relative_path="configs/research/paper_candidate.toml",
        config_sha256=hashlib.sha256(b"config").hexdigest(),
        code_sha256=hashlib.sha256(b"code").hexdigest(),
        universe_name="PAPER_CANDIDATE_A_SHARE_V1",
        universe_frozen_as_of=dt.date(2026, 8, 13),
        candidate_symbols=("000001.SZ", "600000.SH"),
        data_start=dt.date(2024, 1, 1),
        data_end=dt.date(2026, 8, 13),
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=(
            ResearchFoldV1(
                1,
                dt.date(2024, 1, 1),
                dt.date(2024, 12, 31),
                dt.date(2025, 1, 1),
                dt.date(2025, 6, 30),
                dt.date(2025, 7, 1),
                dt.date(2026, 8, 13),
            ),
        ),
        cost_multipliers=(0.5, 1.0, 2.0),
        selection_metric="net_sharpe",
        inputs=(
            ResearchInputDigestV1(
                name="clean_daily",
                rows=2,
                min_date=dt.date(2026, 8, 13),
                max_date=dt.date(2026, 8, 13),
                content_sha256=hashlib.sha256(b"input").hexdigest(),
            ),
        ),
        outputs=(),
        aggregate_metrics=(("fold_count", 1),),
        caveats=("PAPER only.",),
    )


def _source_plan(run_id: str) -> daily.FormalPaperDailySourcePlan:
    return daily.FormalPaperDailySourcePlan(
        schema_version="formal-paper-daily-source-v1",
        classification="formal-paper-simulation",
        selector="formal_source_v1",
        target_run_id=run_id,
        market_source_version="clean_opening_v1",
        allowed_markets=(Market.SH, Market.SZ),
        signal_timing="close",
        execution_timing="next_session_open",
        raw_sha256="a" * 64,
        source_identity="b" * 64,
    )


def test_candidate_loader_requires_candidate_and_completes_zero_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = pl.DataFrame(
        {
            "as_of": [dt.date(2026, 8, 13)],
            "strategy": ["first_paper_candidate"],
            "strategy_version": ["1.0.0"],
            "symbol": ["600000.SH"],
            "weight": [0.4],
        }
    )
    _, published, _ = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts",
        run=_candidate_run(),
        output_payloads={"target_weights.parquet": _parquet(target)},
    )
    plan = _source_plan(published.run_id)
    environment = SimpleNamespace(config=SimpleNamespace(project_root=tmp_path))
    monkeypatch.setattr(daily, "_fresh_environment", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        daily,
        "load_formal_paper_daily_source_plan",
        lambda **_kwargs: plan,
    )
    loader = daily.FormalPaperCandidateTargetLoader(
        environment=environment,  # type: ignore[arg-type]
        source_plan=plan,
        session_date=SESSION,
        now=NOW,
    )

    verified = loader.load()

    assert [(item.symbol, item.target_weight) for item in verified.targets] == [
        ("600000.SH", Decimal("0.4")),
        ("000001.SZ", Decimal("0")),
    ]


def test_research_only_run_cannot_be_used_as_formal_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = pl.DataFrame(
        {
            "as_of": [dt.date(2026, 8, 13)],
            "strategy": ["first_paper_candidate"],
            "strategy_version": ["1.0.0"],
            "symbol": ["600000.SH"],
            "weight": [0.4],
        }
    )
    _, published, _ = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts",
        run=replace(_candidate_run(), conclusion="RESEARCH_ONLY"),
        output_payloads={"target_weights.parquet": _parquet(target)},
    )
    plan = _source_plan(published.run_id)
    environment = SimpleNamespace(config=SimpleNamespace(project_root=tmp_path))
    monkeypatch.setattr(daily, "_fresh_environment", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        daily,
        "load_formal_paper_daily_source_plan",
        lambda **_kwargs: plan,
    )

    with pytest.raises(daily.FormalPaperDailyInputError):
        daily.FormalPaperCandidateTargetLoader(
            environment=environment,  # type: ignore[arg-type]
            source_plan=plan,
            session_date=SESSION,
            now=NOW,
        ).load()


def _market_frames() -> tuple[pl.DataFrame, ...]:
    instruments = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "600000.SH"],
            "market": ["SZ", "SH"],
            "name": ["Ping An", "SPDB"],
            "instrument_type": ["STOCK", "STOCK"],
            "currency": ["CNY", "CNY"],
            "list_date": [dt.date(1991, 4, 3), dt.date(1999, 11, 10)],
            "delist_date": [None, None],
            "board_lot": [100, 100],
            "status": ["LISTED", "LISTED"],
        }
    )
    opening = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "600000.SH"],
            "session_date": [SESSION, SESSION],
            "open": [10.0, 12.0],
            "source": ["clean", "clean"],
            "source_snapshot_id": ["open-v1", "open-v1"],
            "known_at": [NOW, NOW],
        }
    ).with_columns(pl.col("known_at").dt.convert_time_zone("UTC"))
    limits = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "600000.SH"],
            "trade_date": [SESSION, SESSION],
            "pre_close": [9.8, 11.8],
            "has_price_limit": [True, True],
            "up_limit": [10.78, 12.98],
            "down_limit": [8.82, 10.62],
            "source": ["clean", "clean"],
            "source_snapshot_id": ["limit-v1", "limit-v1"],
        }
    )
    suspensions = pl.DataFrame(
        schema={
            "symbol": pl.String,
            "trade_date": pl.Date,
            "suspension_scope": pl.String,
            "suspension_detail": pl.String,
            "source": pl.String,
            "source_snapshot_id": pl.String,
        }
    )
    calendar = pl.DataFrame(
        {
            "market": ["SH", "SZ"],
            "date": [SESSION, SESSION],
            "is_open": [True, True],
            "is_connect_open": [False, False],
            "is_half_day": [False, False],
        }
    )
    return instruments, opening, limits, suspensions, calendar


def test_opening_market_publication_is_exact_and_no_clobber(tmp_path: Path) -> None:
    first = daily.publish_formal_paper_opening_market_input(
        project_root=tmp_path,
        session_date=SESSION,
        known_as_of=NOW,
        source_version="clean_opening_v1",
        instruments=_market_frames()[0],
        opening_prices=_market_frames()[1],
        price_limits=_market_frames()[2],
        suspensions=_market_frames()[3],
        calendar=_market_frames()[4],
    )
    second = daily.publish_formal_paper_opening_market_input(
        project_root=tmp_path,
        session_date=SESSION,
        known_as_of=NOW,
        source_version="clean_opening_v1",
        instruments=_market_frames()[0],
        opening_prices=_market_frames()[1],
        price_limits=_market_frames()[2],
        suspensions=_market_frames()[3],
        calendar=_market_frames()[4],
    )
    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[2] is False
    assert second[2] is True
    assert {path.name for path in first[0].iterdir()} == {
        "instrument.parquet",
        "opening_price.parquet",
        "price_limit_1d.parquet",
        "suspension_1d.parquet",
        "trade_calendar.parquet",
        "receipt.json",
    }

    (first[0] / "receipt.json").write_bytes(b"{}")
    with pytest.raises(daily.FormalPaperDailyInputError):
        daily.publish_formal_paper_opening_market_input(
            project_root=tmp_path,
            session_date=SESSION,
            known_as_of=NOW,
            source_version="clean_opening_v1",
            instruments=_market_frames()[0],
            opening_prices=_market_frames()[1],
            price_limits=_market_frames()[2],
            suspensions=_market_frames()[3],
            calendar=_market_frames()[4],
        )


def _dummy_operator_kwargs() -> dict[str, object]:
    return {
        "environment": object(),
        "policy": object(),
        "composition": object(),
        "session_date": SESSION,
        "now": NOW,
    }


def _assert_sanitized_runner_error(
    error: daily.FormalPaperDailyRunnerError, *, hidden: str | None = None
) -> None:
    assert error.code == "PAPER_FORMAL_DAILY_RUNNER_INVALID"
    assert str(error) == "PAPER_FORMAL_DAILY_RUNNER_INVALID"
    assert error.__cause__ is None
    assert error.__context__ is None
    if hidden is not None:
        rendered = "".join(traceback.format_exception(error))
        assert hidden not in str(error)
        assert hidden not in repr(error)
        assert hidden not in rendered


def _hostile_exception_graph(marker: str) -> RuntimeError:
    cause = ValueError(marker)
    error = RuntimeError(marker)
    error.__cause__ = cause
    error.__context__ = cause
    cause.__cause__ = error
    cause.__context__ = error
    return error


def _forbid_deps_and_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom_deps(**_kwargs: object) -> object:
        raise AssertionError("dependencies must not be built")

    def boom_cli(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("CLI must not be called")

    monkeypatch.setattr(daily, "build_formal_paper_daily_dependencies", boom_deps)
    monkeypatch.setattr("quant.execution.cli.main", boom_cli)


class _ActionStr(str):
    pass


class _UnhashableEq:
    __hash__ = None

    def __eq__(self, other: object) -> bool:
        return False


def _forbid_operator_deps_and_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom_operator(**_kwargs: object) -> int:
        raise AssertionError("operator must not be called")

    monkeypatch.setattr(daily, "run_formal_paper_daily_operator", boom_operator)
    _forbid_deps_and_cli(monkeypatch)


@pytest.mark.parametrize("action", ["approve", "paper-submit", "cancel", "reconcile"])
def test_read_only_runner_rejects_dispatch_and_reconcile_actions_before_composition(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_deps_and_cli(monkeypatch)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_read_only(
            action=action,  # type: ignore[arg-type]
            environment=object(),  # type: ignore[arg-type]
            policy=object(),  # type: ignore[arg-type]
            composition=object(),  # type: ignore[arg-type]
            session_date=SESSION,
            now=NOW,
        )
    _assert_sanitized_runner_error(caught.value)


@pytest.mark.parametrize(
    "action",
    [
        {"inspect": 1},
        ["inspect"],
        bytearray(b"inspect"),
        _UnhashableEq(),
        _ActionStr("inspect"),
        _ActionStr("plan"),
    ],
)
def test_read_only_runner_rejects_non_exact_str_action_before_operator(
    action: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_operator_deps_and_cli(monkeypatch)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_read_only(
            action=action,  # type: ignore[arg-type]
            environment=object(),  # type: ignore[arg-type]
            policy=object(),  # type: ignore[arg-type]
            composition=object(),  # type: ignore[arg-type]
            session_date=SESSION,
            now=NOW,
        )
    _assert_sanitized_runner_error(caught.value)


@pytest.mark.parametrize("action", ["inspect", "plan"])
def test_read_only_runner_delegates_exact_str_inspect_and_plan_to_operator(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def spy_operator(**kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(daily, "run_formal_paper_daily_operator", spy_operator)
    environment = object()
    policy = object()
    composition = object()
    result = daily.run_formal_paper_daily_read_only(
        action=action,
        environment=environment,  # type: ignore[arg-type]
        policy=policy,  # type: ignore[arg-type]
        composition=composition,  # type: ignore[arg-type]
        session_date=SESSION,
        now=NOW,
    )
    assert result == 0
    assert calls == [
        {
            "action": action,
            "environment": environment,
            "policy": policy,
            "composition": composition,
            "session_date": SESSION,
            "now": NOW,
        }
    ]


@pytest.mark.parametrize("action", ["inspect", "plan", "reconcile"])
@pytest.mark.parametrize(
    "extra",
    [
        {"confirm_sha256": "a" * 64},
        {"command_id": "b" * 64},
        {"confirm_sha256": "a" * 64, "command_id": "b" * 64},
    ],
)
def test_operator_rejects_inspect_plan_reconcile_confirm_or_command_id_before_deps(
    action: str, extra: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_deps_and_cli(monkeypatch)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_operator(
            action=action,  # type: ignore[arg-type]
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
            **extra,
        )
    _assert_sanitized_runner_error(caught.value)


@pytest.mark.parametrize("action", ["approve", "paper-submit"])
def test_operator_rejects_approve_and_submit_with_command_id_before_deps(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_deps_and_cli(monkeypatch)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_operator(
            action=action,  # type: ignore[arg-type]
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
            command_id="c" * 64,
        )
    _assert_sanitized_runner_error(caught.value)


@pytest.mark.parametrize("command_id", [None, ""])
def test_operator_rejects_cancel_without_command_id_before_deps(
    command_id: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_deps_and_cli(monkeypatch)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_operator(
            action="cancel",
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
            command_id=command_id,
        )
    _assert_sanitized_runner_error(caught.value)


def test_operator_sanitizes_hostile_fresh_dependency_and_skips_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "TOKEN C:/secret sqlite:///hostile-path"
    cli_calls: list[object] = []

    def hostile(**_kwargs: object) -> object:
        raise RuntimeError(marker)

    def spy_cli(*args: object, **kwargs: object) -> int:
        cli_calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(daily, "build_formal_paper_daily_dependencies", hostile)
    monkeypatch.setattr("quant.execution.cli.main", spy_cli)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_operator(
            action="inspect",
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
        )
    _assert_sanitized_runner_error(caught.value, hidden=marker)
    assert cli_calls == []


@pytest.mark.parametrize(
    "action",
    [_ActionStr("inspect"), _ActionStr("plan"), b"inspect", 1, None, ["inspect"]],
)
def test_operator_rejects_non_exact_str_action_before_deps(
    action: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_deps_and_cli(monkeypatch)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_operator(
            action=action,  # type: ignore[arg-type]
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
        )
    _assert_sanitized_runner_error(caught.value)


def test_operator_sanitizes_hostile_cli_exception_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "TOKEN C:/secret sqlite:///hostile-path ACCOUNT-12345"
    cli_calls: list[object] = []

    def sentinel_deps(**_kwargs: object) -> object:
        return object()

    def hostile_cli(*args: object, **kwargs: object) -> int:
        cli_calls.append((args, kwargs))
        raise _hostile_exception_graph(marker)

    monkeypatch.setattr(daily, "build_formal_paper_daily_dependencies", sentinel_deps)
    monkeypatch.setattr("quant.execution.cli.main", hostile_cli)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_operator(
            action="inspect",
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
        )
    _assert_sanitized_runner_error(caught.value, hidden=marker)
    assert len(cli_calls) == 1
    assert type(caught.value) is daily.FormalPaperDailyRunnerError


def test_operator_sanitizes_cli_import_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "TOKEN C:/secret sqlite:///hostile-path ACCOUNT-12345"
    fake = ModuleType("quant.execution.cli")
    fake.__file__ = marker
    monkeypatch.setattr(daily, "build_formal_paper_daily_dependencies", lambda **_kwargs: object())
    monkeypatch.setitem(sys.modules, "quant.execution.cli", fake)
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_operator(
            action="inspect",
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
        )
    _assert_sanitized_runner_error(caught.value, hidden=marker)


@pytest.mark.parametrize("code", [0, 20, 30])
def test_operator_returns_cli_int_exit_codes(
    code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        daily, "build_formal_paper_daily_dependencies", lambda **_kwargs: object()
    )
    monkeypatch.setattr("quant.execution.cli.main", lambda *_args, **_kwargs: code)
    assert (
        daily.run_formal_paper_daily_operator(
            action="inspect",
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
        )
        == code
    )


def test_operator_approve_submit_challenge_idempotence_and_wrong_confirm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    dependencies, store, gateway, _, _ = _deps(tmp_path)
    builds: list[int] = []

    def build_once(**_kwargs: object) -> object:
        builds.append(1)
        return dependencies

    monkeypatch.setattr(daily, "build_formal_paper_daily_dependencies", build_once)
    kwargs = _dummy_operator_kwargs()
    try:
        assert (
            daily.run_formal_paper_daily_operator(action="approve", **kwargs)  # type: ignore[arg-type]
            == 20
        )
        approval = _json(capsys)["content_identity"]
        assert recover_local_state(store).commands == ()
        assert gateway.calls == []

        assert (
            daily.run_formal_paper_daily_operator(
                action="approve",
                confirm_sha256="d" * 64,
                **kwargs,  # type: ignore[arg-type]
            )
            == 20
        )
        assert capsys.readouterr().err == "CONFIRMATION_DRIFT\n"
        assert recover_local_state(store).commands == ()
        assert gateway.calls == []

        assert (
            daily.run_formal_paper_daily_operator(
                action="approve",
                confirm_sha256=approval,
                **kwargs,  # type: ignore[arg-type]
            )
            == 0
        )
        staged = _json(capsys)
        assert staged["code"] == "APPROVAL_STAGED"
        recovered = recover_local_state(store)
        assert len(recovered.commands) == 1
        assert gateway.calls == []

        assert (
            daily.run_formal_paper_daily_operator(action="approve", **kwargs)  # type: ignore[arg-type]
            == 20
        )
        replay = _json(capsys)["content_identity"]
        assert (
            daily.run_formal_paper_daily_operator(
                action="approve",
                confirm_sha256=replay,
                **kwargs,  # type: ignore[arg-type]
            )
            == 0
        )
        assert _json(capsys)["code"] == "APPROVAL_STAGED_REPLAY"
        assert len(recover_local_state(store).commands) == 1
        assert gateway.calls == []

        assert (
            daily.run_formal_paper_daily_operator(action="paper-submit", **kwargs)  # type: ignore[arg-type]
            == 20
        )
        submit = _json(capsys)["content_identity"]
        assert gateway.calls == []
        assert all(
            item.state is OutboxDeliveryState.PENDING
            for item in recover_local_state(store).deliveries
        )

        assert (
            daily.run_formal_paper_daily_operator(
                action="paper-submit",
                confirm_sha256=approval,
                **kwargs,  # type: ignore[arg-type]
            )
            == 20
        )
        assert capsys.readouterr().err == "CONFIRMATION_DRIFT\n"
        assert gateway.calls == []
        assert all(
            item.state is OutboxDeliveryState.PENDING
            for item in recover_local_state(store).deliveries
        )

        assert (
            daily.run_formal_paper_daily_operator(
                action="paper-submit",
                confirm_sha256=submit,
                **kwargs,  # type: ignore[arg-type]
            )
            == 0
        )
        assert _json(capsys)["code"] == "SUBMIT_COMPLETE"
        assert len(gateway.calls) == 1
        local = recover_local_state(store)
        assert len(local.commands) == 1
        assert local.deliveries[0].state is OutboxDeliveryState.SENT

        assert (
            daily.run_formal_paper_daily_operator(action="paper-submit", **kwargs)  # type: ignore[arg-type]
            == 0
        )
        assert _json(capsys)["code"] == "SUBMIT_ALREADY_COMPLETE"
        assert len(gateway.calls) == 1
        assert len(recover_local_state(store).commands) == 1
        assert len(builds) == 9
    finally:
        store.close()


def test_operator_unknown_submit_does_not_auto_resend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    dependencies, store, gateway, _, _ = _deps(tmp_path)
    gateway.certainty = DispatchCertainty.UNKNOWN
    monkeypatch.setattr(
        daily,
        "build_formal_paper_daily_dependencies",
        lambda **_kwargs: dependencies,
    )
    kwargs = _dummy_operator_kwargs()
    try:
        assert (
            daily.run_formal_paper_daily_operator(action="approve", **kwargs)  # type: ignore[arg-type]
            == 20
        )
        approval = _json(capsys)["content_identity"]
        assert (
            daily.run_formal_paper_daily_operator(
                action="approve",
                confirm_sha256=approval,
                **kwargs,  # type: ignore[arg-type]
            )
            == 0
        )
        _json(capsys)
        assert (
            daily.run_formal_paper_daily_operator(action="paper-submit", **kwargs)  # type: ignore[arg-type]
            == 20
        )
        submit = _json(capsys)["content_identity"]
        assert (
            daily.run_formal_paper_daily_operator(
                action="paper-submit",
                confirm_sha256=submit,
                **kwargs,  # type: ignore[arg-type]
            )
            == 30
        )
        assert capsys.readouterr().err == "SUBMIT_QUERY_REQUIRED\n"
        assert len(gateway.calls) == 1
        assert recover_local_state(store).deliveries[0].state is OutboxDeliveryState.UNKNOWN

        assert (
            daily.run_formal_paper_daily_operator(action="paper-submit", **kwargs)  # type: ignore[arg-type]
            == 30
        )
        assert capsys.readouterr().err == "SUBMIT_LOCAL_QUERY_REQUIRED\n"
        assert len(gateway.calls) == 1
        assert len(recover_local_state(store).commands) == 1
        assert recover_local_state(store).deliveries[0].state is OutboxDeliveryState.UNKNOWN
    finally:
        store.close()


def test_operator_forwards_approval_capability_and_trusted_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant.execution.approval_flow import build_formal_approval_credential_capability

    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(daily, "build_formal_paper_daily_dependencies", capture)
    monkeypatch.setattr("quant.execution.cli.main", lambda *_args, **_kwargs: 0)
    capability = build_formal_approval_credential_capability(
        b"formal-daily-forward-secret-bytes01",
        credential_id="credential/formal-forward",
        operator_id="formal-operator",
        session_date=SESSION,
    )
    assert (
        daily.run_formal_paper_daily_operator(
            action="approve",
            approval_capability=capability,
            trusted_expected_operator_id="formal-operator",
            trusted_expected_session_date=SESSION,
            **_dummy_operator_kwargs(),  # type: ignore[arg-type]
        )
        == 0
    )
    assert captured["approval_capability"] is capability
    assert captured["trusted_expected_operator_id"] == "formal-operator"
    assert captured["trusted_expected_session_date"] == SESSION


def test_build_dependencies_rejects_trusted_session_mismatch() -> None:
    with pytest.raises(daily.FormalPaperDailyRunnerError):
        daily.build_formal_paper_daily_dependencies(
            environment=cast(object, None),  # type: ignore[arg-type]
            policy=cast(object, None),  # type: ignore[arg-type]
            composition=cast(object, None),  # type: ignore[arg-type]
            session_date=SESSION,
            now=NOW,
            trusted_expected_session_date=SESSION + dt.timedelta(days=1),
        )
