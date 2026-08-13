"""Formal G7B next-session backtest-plan artifact contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import quant.backtest.a_share_plan as plan_module
from quant.backtest.a_share_plan import (
    BacktestPlanFreshVerificationContext,
    build_backtest_plan_artifact,
    verify_backtest_plan_artifact,
)
from quant.research.m3.contracts import VerifiedBacktestPlanArtifact
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_formal_target_support_for_plan",
    Path(__file__).with_name("test_m3_formal_target_artifact.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    context = _SUPPORT._context(tmp_path, monkeypatch)
    target_root, target_receipt, _, target = _SUPPORT._build_publish_verify(context)
    kwargs = context["target_kwargs"]
    fresh_context = BacktestPlanFreshVerificationContext(
        snapshot=kwargs["snapshot"],
        snapshot_spec=kwargs["snapshot_spec"],
        provider=kwargs["provider"],
        provider_spec=kwargs["provider_spec"],
        experiment_spec=kwargs["experiment_spec"],
        fold_spec=kwargs["fold_spec"],
        feature=kwargs["feature"],
        feature_spec=kwargs["feature_spec"],
        label=kwargs["label"],
        label_spec=kwargs["label_spec"],
        alignment=kwargs["alignment"],
        alignment_spec=kwargs["alignment_spec"],
        model=kwargs["model"],
        model_spec=kwargs["model_spec"],
        prediction=kwargs["prediction"],
        prediction_spec=kwargs["prediction_spec"],
        target_spec=kwargs["spec"],
        target_upstream_paths=kwargs["upstream_paths"],
        target_receipt_path=target_receipt,
    )
    plan_kwargs = {
        "target": target,
        "release": kwargs["release"],
        "folds": kwargs["folds"],
        "experiment": kwargs["experiment"],
        "config": kwargs["config"],
        "fresh_context": fresh_context,
        "artifact_roots": kwargs["artifact_roots"],
    }
    return {
        **context,
        "target_root": target_root,
        "target_receipt": target_receipt,
        "target": target,
        "fresh_context": fresh_context,
        "plan_kwargs": plan_kwargs,
    }


def _outputs(root: Path) -> list[tuple[str, Path]]:
    return [("root", root / name) for name in sorted(plan_module._FILES)]


def _build_publish(context: dict[str, Any], suffix: str = "base") -> tuple[Path, Path, Any]:
    kwargs = context["plan_kwargs"]
    root = context["common"] / f"formal-plan-{suffix}"
    root.mkdir()
    manifest = build_backtest_plan_artifact(**kwargs, output_root=root)
    receipt = (
        context["common"] / "receipts" / "backtest-plan"
        / f"{kwargs['target'].manifest.work_key}-{suffix}.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    inputs = plan_module._formal_receipt_inputs(
        kwargs["release"], kwargs["folds"], kwargs["experiment"],
        kwargs["fresh_context"], kwargs["target"],
    )
    publish_stage_receipt(
        receipt_path=receipt,
        stage="backtest-plan",
        scope="WORK",
        scope_key=kwargs["target"].manifest.work_key,
        artifact_roots=kwargs["artifact_roots"],
        inputs=[("root", path) for path in inputs],
        outputs=_outputs(root),
    )
    return root, receipt, manifest


def test_formal_plan_closed_loop_fresh_once_next_session_and_exact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    calls = 0
    real_verify = plan_module.verify_target_artifact

    def counted(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_verify(**kwargs)

    monkeypatch.setattr(plan_module, "verify_target_artifact", counted)
    root, receipt, manifest = _build_publish(context)
    verified = verify_backtest_plan_artifact(
        root=root, receipt_path=receipt, **context["plan_kwargs"]
    )
    assert calls == 2
    assert type(verified) is VerifiedBacktestPlanArtifact
    assert verified.manifest == manifest
    assert verified.root == root.resolve()
    assert verified.manifest_sha256 == hashlib.sha256(
        (root / "manifest.json").read_bytes()
    ).hexdigest()
    assert verified.plan_receipt_sha256 == hashlib.sha256(receipt.read_bytes()).hexdigest()
    inputs = plan_module._formal_receipt_inputs(
        context["plan_kwargs"]["release"], context["plan_kwargs"]["folds"],
        context["plan_kwargs"]["experiment"], context["fresh_context"],
        context["target"],
    )
    assert len(inputs) == len({path.resolve() for path in inputs}) == 19
    assert inputs[0].name == "manifest.json"
    assert inputs[1] == context["plan_kwargs"]["release"].release.quality_path
    assert inputs[1].name == "quality.json"
    assert inputs[2].name == "eligible_keys.parquet"
    assert all(path.name != "receipt.json" for path in inputs)
    assert not (context["plan_kwargs"]["release"].release.root / "receipt.json").exists()
    assert _sha(inputs[1]) == context["plan_kwargs"]["release"].quality_sha256
    sessions = plan_module._formal_sh_open_sessions(context["plan_kwargs"]["release"])
    index = {day: offset for offset, day in enumerate(sessions)}
    for row in verified.scheduled_targets.iter_rows(named=True):
        assert row["execution_date"] == sessions[index[row["as_of"]] + 1]
    assert verified.scheduled_targets.equals(
        verified.scheduled_targets.sort("execution_date", "as_of", "symbol")
    )


def test_formal_plan_rejects_unsorted_target_and_hostile_fresh_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    target = replace(context["target"], targets=context["target"].targets.reverse())
    kwargs = {**context["plan_kwargs"], "target": target}
    monkeypatch.setattr(plan_module, "verify_target_artifact", lambda **_: target)
    root = context["common"] / "formal-plan-unsorted"
    root.mkdir()
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$"):
        build_backtest_plan_artifact(**kwargs, output_root=root)
    assert not any(root.iterdir())

    def hostile(**_: Any) -> Any:
        raise RuntimeError("C:/PRIVATE/TOKEN_G7B")

    monkeypatch.setattr(plan_module, "verify_target_artifact", hostile)
    other = context["common"] / "formal-plan-hostile"
    other.mkdir()
    with pytest.raises(ValueError) as caught:
        build_backtest_plan_artifact(**context["plan_kwargs"], output_root=other)
    assert str(caught.value) == "M3_BACKTEST_PLAN_ARTIFACT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "TOKEN_G7B" not in repr(caught.value) and not any(other.iterdir())


def test_formal_plan_cost_config_and_tail_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    target = context["target"]
    monkeypatch.setattr(plan_module, "verify_target_artifact", lambda **_: target)
    config = context["plan_kwargs"]["config"]
    payload: Any = plan_module._formal_cost_schedule_payload(config)
    base = payload["schedules"][1]["periods"]
    assert base[0]["effective_to"] == "2022-04-28"
    assert base[1]["effective_from"] == "2022-04-29"
    assert base[1]["effective_to"] == "2023-08-27"
    assert base[2]["effective_from"] == "2023-08-28"
    for schedule in payload["schedules"]:
        assert [period["stamp_tax_sell"] for period in schedule["periods"]] == [
            period["stamp_tax_sell"] for period in base
        ]
        assert [period["transfer_fee"] for period in schedule["periods"]] == [
            period["transfer_fee"] for period in base
        ]
    document = dict(config.document)
    backtest = dict(config.section("backtest"))
    a_share = dict(backtest["a_share"])
    a_share["friction_multipliers"] = (0.5, 1.0, 3.0)
    backtest["a_share"] = a_share
    document["backtest"] = backtest
    bad_config = replace(config, document=document)
    root = context["common"] / "formal-plan-config-drift"
    root.mkdir()
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$"):
        build_backtest_plan_artifact(
            **{**context["plan_kwargs"], "config": bad_config}, output_root=root
        )
    assert not any(root.iterdir())

    planned = next(
        item for item in context["plan_kwargs"]["folds"].manifest.folds
        if item.name == target.manifest.fold
    )
    sessions = tuple(planned.test_dates)
    with pytest.raises(ValueError):
        plan_module._formal_schedule_targets(target, context["plan_kwargs"]["folds"], sessions)


def test_formal_plan_verifier_rejects_output_and_receipt_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    target = context["target"]
    monkeypatch.setattr(plan_module, "verify_target_artifact", lambda **_: target)
    root, receipt, _ = _build_publish(context, "tamper")
    raw = (root / "cost_schedule.json").read_bytes()
    (root / "cost_schedule.json").write_bytes(raw + b"drift")
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$"):
        verify_backtest_plan_artifact(
            root=root, receipt_path=receipt, **context["plan_kwargs"]
        )
    (root / "cost_schedule.json").write_bytes(raw)
    extra = context["common"] / "decoy.txt"
    extra.write_text("decoy", encoding="utf-8")
    bad_receipt = receipt.with_name("extra.json")
    inputs = plan_module._formal_receipt_inputs(
        context["plan_kwargs"]["release"], context["plan_kwargs"]["folds"],
        context["plan_kwargs"]["experiment"], context["fresh_context"], target,
    )
    publish_stage_receipt(
        receipt_path=bad_receipt,
        stage="backtest-plan",
        scope="WORK",
        scope_key=target.manifest.work_key,
        artifact_roots=context["plan_kwargs"]["artifact_roots"],
        inputs=[*(("root", path) for path in inputs), ("root", extra)],
        outputs=_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$"):
        verify_backtest_plan_artifact(
            root=root, receipt_path=bad_receipt, **context["plan_kwargs"]
        )


def test_r2_formal_plan_g1_quality_closure_rejects_drift_alias_and_pseudo_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    kwargs = context["plan_kwargs"]
    release = kwargs["release"]
    quality = release.release.quality_path
    quality_src = (
        context["feature_bundle"][2].release.root / "contract" / "quality.json"
    )
    assert quality.is_file() and not (release.release.root / "receipt.json").exists()
    monkeypatch.setattr(plan_module, "verify_target_artifact", lambda **_: kwargs["target"])

    decoy = release.release.root / "receipt.json"
    decoy.write_bytes(b'{"stage":"backtest-plan"}')
    paths = plan_module._formal_receipt_inputs(
        release, kwargs["folds"], kwargs["experiment"],
        kwargs["fresh_context"], kwargs["target"],
    )
    assert paths[0].name == "manifest.json"
    assert paths[1] == quality and paths[1].name == "quality.json"
    assert paths[2].name == "eligible_keys.parquet"
    assert decoy not in paths and all(path.name != "receipt.json" for path in paths)
    decoy.unlink()

    missing_output = context["common"] / "formal-plan-quality-missing"
    missing_output.mkdir()
    quality.unlink()
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$") as missing:
        build_backtest_plan_artifact(**kwargs, output_root=missing_output)
    assert missing.value.__cause__ is None and missing.value.__context__ is None
    assert "TOKEN" not in repr(missing.value)
    assert not any(missing_output.iterdir())
    shutil.copyfile(quality_src, quality)
    object.__setattr__(release, "quality_sha256", _sha(quality))

    root, receipt, _ = _build_publish(context, "quality-ok")
    quality.write_bytes(b'{"schema_version":"hostile-quality","passed":false}\n')
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$") as drifted:
        verify_backtest_plan_artifact(root=root, receipt_path=receipt, **kwargs)
    assert drifted.value.__cause__ is None and drifted.value.__context__ is None
    shutil.copyfile(quality_src, quality)
    object.__setattr__(release, "quality_sha256", _sha(quality))

    manifest = release.release.manifest_path
    manifest_backup = release.release.root / "manifest.json.bak"
    shutil.copyfile(manifest, manifest_backup)
    manifest.unlink()
    try:
        os.link(quality, manifest)
    except OSError:
        shutil.copyfile(manifest_backup, manifest)
        pytest.skip("hardlink unavailable for quality same-bytes alias probe")
    with pytest.raises(ValueError, match="formal backtest plan receipt input alias"):
        plan_module._formal_receipt_inputs(
            release, kwargs["folds"], kwargs["experiment"],
            kwargs["fresh_context"], kwargs["target"],
        )
    manifest.unlink()
    shutil.copyfile(manifest_backup, manifest)
    manifest_backup.unlink()

    object.__setattr__(
        release,
        "release",
        SimpleNamespace(
            root=release.release.root,
            manifest_path=release.release.manifest_path,
            quality_path=release.release.root / "receipt.json",
        ),
    )
    pseudo_output = context["common"] / "formal-plan-pseudo-receipt-quality"
    pseudo_output.mkdir()
    (release.release.root / "receipt.json").write_bytes(quality.read_bytes())
    object.__setattr__(release, "quality_sha256", _sha(release.release.root / "receipt.json"))
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$"):
        build_backtest_plan_artifact(**kwargs, output_root=pseudo_output)
    assert not any(pseudo_output.iterdir())
    object.__setattr__(
        release,
        "release",
        SimpleNamespace(
            root=release.release.root,
            manifest_path=release.release.manifest_path,
            quality_path=quality,
        ),
    )
    object.__setattr__(release, "quality_sha256", _sha(quality))
    (release.release.root / "receipt.json").unlink()

    fake_receipt = release.release.root / "receipt.json"
    fake_receipt.write_bytes(b'{"pseudo":true}')
    current = list(
        plan_module._formal_receipt_inputs(
            release, kwargs["folds"], kwargs["experiment"],
            kwargs["fresh_context"], kwargs["target"],
        )
    )
    legacy_paths = [current[0], fake_receipt, *current[2:]]
    assert len(legacy_paths) == 19
    legacy_receipt = (
        context["common"] / "receipts" / "backtest-plan" / "legacy-pseudo.json"
    )
    publish_stage_receipt(
        receipt_path=legacy_receipt,
        stage="backtest-plan",
        scope="WORK",
        scope_key=kwargs["target"].manifest.work_key,
        artifact_roots=kwargs["artifact_roots"],
        inputs=[("root", path) for path in legacy_paths],
        outputs=_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_BACKTEST_PLAN_ARTIFACT_INVALID$"):
        verify_backtest_plan_artifact(
            root=root, receipt_path=legacy_receipt, **kwargs
        )
