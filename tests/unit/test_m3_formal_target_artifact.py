"""Formal G7A complete-domain target artifact contract tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import os
import shutil
from dataclasses import replace
from decimal import Context, Decimal, ROUND_UP, localcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest

import quant.research.m3 as m3_public
import quant.research.m3._artifact_publication as publication_module
import quant.research.m3.targets as target_module
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.contracts import (
    TargetBuildSpec,
    TargetUpstreamPaths,
    VerifiedTargetArtifact,
)
from quant.research.m3.run_state import publish_stage_receipt
from quant.research.m3.features import canonical_row_keys_sha256
from quant.research.m3.predictions import normalize_prediction_scores
from quant.research.m3.targets import build_target_artifact, verify_target_artifact

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_formal_prediction_support_for_target",
    Path(__file__).with_name("test_m3_formal_prediction_artifact.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _formal_release(context: dict[str, Any]) -> VerifiedG1Release:
    release = context["kwargs"]["release"]
    development = context["feature_bundle"][2]
    release_id = development.manifest.release_id
    root = context["common"] / "formal-g1-release" / release_id
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    shutil.copyfile(development.release.manifest_path, root / "manifest.json")
    quality_src = development.release.root / "contract" / "quality.json"
    shutil.copyfile(quality_src, root / "quality.json")
    eligible_src = dict(development.artifact_paths)["eligible_keys.parquet"]
    shutil.copyfile(eligible_src, root / "eligible_keys.parquet")
    assert not (root / "receipt.json").exists()
    quality_path = root / "quality.json"
    quality_sha256 = _sha(quality_path)
    remapped = tuple(
        (name, (root / name) if name == "eligible_keys.parquet" else path)
        for name, path in development.artifact_paths
    )
    object.__setattr__(release, "manifest", development.manifest)
    object.__setattr__(release, "manifest_sha256", development.manifest_sha256)
    object.__setattr__(release, "quality_sha256", quality_sha256)
    object.__setattr__(release, "artifact_paths", remapped)
    object.__setattr__(
        release,
        "release",
        SimpleNamespace(
            root=root,
            manifest_path=root / "manifest.json",
            quality_path=quality_path,
        ),
    )
    return cast(VerifiedG1Release, release)


def _context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    context = _SUPPORT._context(tmp_path, monkeypatch)
    prediction_root, prediction_receipt, _ = _SUPPORT._build_and_publish(context)
    prediction = _SUPPORT._verify(context, prediction_root, prediction_receipt)
    kwargs = dict(context["kwargs"])
    release = _formal_release(context)
    prediction_upstream = context["upstream"]
    experiment_receipt = (
        prediction_upstream.feature_upstream_paths.fold_upstream_paths
        .experiment_receipt_path
    )
    upstream = TargetUpstreamPaths(
        feature_receipt_path=prediction_upstream.feature_receipt_path,
        prediction_receipt_path=prediction_receipt,
        prediction_upstream_paths=prediction_upstream,
        fold_receipt_path=prediction_upstream.fold_receipt_path,
        experiment_receipt_path=experiment_receipt,
    )
    portfolio = kwargs["config"].section("portfolio")
    features = kwargs["config"].section("features")
    spec = TargetBuildSpec(
        experiment_key=prediction.manifest.experiment_key,
        work_key=prediction.manifest.work_key,
        fold=prediction.manifest.fold,
        horizon_sessions=cast(Any, prediction.manifest.horizon_sessions),
        strategy=cast(Any, portfolio["strategy"]),
        strategy_version=cast(str, portfolio["strategy_version"]),
        top_k=cast(int, portfolio["top_k"]),
        cash_buffer=cast(float, portfolio["cash_buffer"]),
        max_weight=cast(float, portfolio["max_weight"]),
        minimum_scorable_coverage=cast(
            float, features["minimum_scorable_coverage"]
        ),
    )
    kwargs.update(
        release=release, prediction=prediction,
        prediction_spec=context["spec"], spec=spec, upstream_paths=upstream,
    )
    return {
        **context, "target_kwargs": kwargs, "release": release,
        "prediction": prediction, "prediction_receipt": prediction_receipt,
        "target_spec": spec, "target_upstream": upstream,
    }


def _inputs(context: dict[str, Any]) -> list[tuple[str, Path]]:
    kwargs = context["target_kwargs"]
    paths = target_module._formal_receipt_inputs(
        kwargs["release"], kwargs["feature"], kwargs["prediction"],
        kwargs["folds"], kwargs["experiment"], kwargs["upstream_paths"],
    )
    return [("root", path) for path in paths]


def _outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / name)
        for name in (
            "target_daily.parquet", "target_manifest.json",
            "target_weights.parquet",
        )
    ]


def _build_publish_verify(
    context: dict[str, Any], suffix: str = "base",
) -> tuple[Path, Path, Any, VerifiedTargetArtifact]:
    kwargs = context["target_kwargs"]
    root = context["common"] / f"formal-target-{suffix}"
    root.mkdir()
    manifest = build_target_artifact(**kwargs, output_root=root)
    receipt = (
        context["common"] / "receipts" / "targets"
        / f"{kwargs['spec'].work_key}-{suffix}.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    publish_stage_receipt(
        receipt_path=receipt, stage="targets", scope="WORK",
        scope_key=kwargs["spec"].work_key,
        artifact_roots=kwargs["artifact_roots"], inputs=_inputs(context),
        outputs=_outputs(root),
    )
    verified = verify_target_artifact(root=root, receipt_path=receipt, **kwargs)
    return root, receipt, manifest, verified


def _r2_seven_selected_context(context: dict[str, Any]) -> dict[str, Any]:
    kwargs = dict(context["target_kwargs"])
    planned = next(
        item for item in kwargs["folds"].manifest.folds
        if item.name == kwargs["spec"].fold
    )
    symbols = tuple(f"{index:06d}.SZ" for index in range(1, 9))
    eligible = pl.DataFrame(
        [
            {"as_of": day, "symbol": symbol}
            for day in planned.test_dates
            for symbol in symbols
        ],
        schema={"as_of": pl.Date, "symbol": pl.Utf8},
    )
    eligible.write_parquet(
        dict(kwargs["release"].artifact_paths)["eligible_keys.parquet"],
        compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
    scorable = eligible.filter(pl.col("symbol") != symbols[-1])
    template = kwargs["prediction"].predictions.row(0, named=True)
    prediction_rows = [
        {
            **template, "as_of": day, "symbol": symbol,
            "score": float(len(symbols) - index),
        }
        for day in planned.test_dates
        for index, symbol in enumerate(symbols[:-1])
    ]
    predictions = normalize_prediction_scores(
        pl.DataFrame(prediction_rows).drop("rank")
    )
    eligible_sha = canonical_row_keys_sha256(tuple(
        (day.isoformat(), symbol) for day, symbol in eligible.iter_rows()
    ))
    feature = kwargs["feature"]
    segments = tuple(
        replace(
            segment, n_eligible=eligible.height,
            n_feature_rows=scorable.height, n_scorable=scorable.height,
            eligible_keys_sha256=eligible_sha,
        ) if segment.name == "test" else segment
        for segment in feature.manifest.segments
    )
    feature = replace(feature, manifest=replace(feature.manifest, segments=segments))
    prediction = kwargs["prediction"]
    prediction = replace(
        prediction, predictions=predictions,
        manifest=replace(
            prediction.manifest, n_eligible=eligible.height,
            n_scorable=scorable.height, n_predicted=scorable.height,
            eligibility_sha256=eligible_sha,
        ),
    )
    config = kwargs["config"]
    document = dict(config.document)
    portfolio = dict(config.section("portfolio"))
    portfolio.update(top_k=7, cash_buffer=0.1, max_weight=0.2)
    document["portfolio"] = portfolio
    config = replace(config, document=document)
    spec = replace(kwargs["spec"], top_k=7, cash_buffer=0.1, max_weight=0.2)
    kwargs.update(feature=feature, prediction=prediction, config=config, spec=spec)
    return {
        **context, "target_kwargs": kwargs, "feature": feature,
        "prediction": prediction, "target_spec": spec,
        "r2_scorable": scorable,
    }


def test_formal_target_closed_loop_complete_domain_decimal_and_exact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    calls = {"prediction": 0, "inference": 0}
    real_prediction = target_module.verify_prediction_artifact
    real_inference = target_module.build_inference_segment

    def counted_prediction(**kwargs: Any) -> Any:
        calls["prediction"] += 1
        return real_prediction(**kwargs)

    def counted_inference(**kwargs: Any) -> Any:
        calls["inference"] += 1
        assert "label" not in kwargs and "label_spec" not in kwargs
        return real_inference(**kwargs)

    monkeypatch.setattr(target_module, "verify_prediction_artifact", counted_prediction)
    monkeypatch.setattr(target_module, "build_inference_segment", counted_inference)
    root, receipt, manifest, verified = _build_publish_verify(context)
    assert calls == {"prediction": 2, "inference": 2}
    assert type(verified) is VerifiedTargetArtifact
    assert verified.manifest == manifest
    assert verified.target_receipt_sha256 == _sha(receipt)
    assert len(_inputs(context)) == len({path.resolve() for _, path in _inputs(context)}) == 14
    input_paths = [path for _, path in _inputs(context)]
    assert input_paths[0].name == "manifest.json"
    assert input_paths[1] == context["release"].release.quality_path
    assert input_paths[1].name == "quality.json"
    assert input_paths[2].name == "eligible_keys.parquet"
    assert all(path.name != "receipt.json" for path in input_paths)
    assert not (context["release"].release.root / "receipt.json").exists()
    assert _sha(input_paths[1]) == context["release"].quality_sha256
    assert {path.name for path in root.iterdir()} == {
        "target_weights.parquet", "target_daily.parquet", "target_manifest.json",
    }
    assert verified.targets.height == manifest.n_eligible
    assert verified.targets.filter(pl.col("weight") == 0.0).height > 0
    for row in verified.target_daily.iter_rows(named=True):
        expected = min(
            (Decimal(1) - Decimal(str(context["target_spec"].cash_buffer)))
            / Decimal(row["n_selected"]),
            Decimal(str(context["target_spec"].max_weight)),
        ) * Decimal(row["n_selected"])
        assert row["total_target_weight"] == float(expected)
    assert m3_public.build_target_artifact is build_target_artifact
    assert m3_public.verify_target_artifact is verify_target_artifact


def test_r2_formal_target_seven_selected_decimal_build_verify_is_context_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _r2_seven_selected_context(_context(tmp_path, monkeypatch))
    prediction = context["prediction"]
    scorable = context["r2_scorable"]
    monkeypatch.setattr(
        target_module, "verify_prediction_artifact", lambda **_: prediction
    )
    monkeypatch.setattr(
        target_module, "build_inference_segment",
        lambda **_: SimpleNamespace(metadata=scorable),
    )
    baseline = target_module._target_allocation(
        cash_buffer=0.1, max_weight=0.2, n_selected=7
    )
    with localcontext(Context(prec=2, rounding=ROUND_UP)):
        hostile = target_module._target_allocation(
            cash_buffer=0.1, max_weight=0.2, n_selected=7
        )
        root, _, manifest, verified = _build_publish_verify(context, "r2-seven")
    assert hostile == baseline
    weight, total = baseline
    assert weight < Decimal("0.2") and total <= Decimal("0.9")
    assert manifest.n_dates == 2
    assert manifest.n_eligible == verified.targets.height == 16
    assert manifest.n_selected == 14
    assert verified.targets.filter(pl.col("weight") > 0).height == 14
    assert verified.targets.filter(pl.col("weight") == 0).height == 2
    assert verified.target_daily.get_column("total_target_weight").to_list() == [
        float(total), float(total),
    ]


def test_formal_target_rejects_missing_extra_duplicate_unsorted_and_date_batches() -> None:
    dates = (dt.date(2026, 1, 5),)
    eligible = pl.DataFrame({
        "as_of": [dates[0], dates[0], dates[0]],
        "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
    })
    scorable = eligible.head(2)
    predictions = scorable.with_columns(pl.Series("rank", [1, 2]))
    spec = TargetBuildSpec(
        experiment_key="1" * 64, work_key="2" * 64, fold="fold_001",
        horizon_sessions=5, strategy="topk", strategy_version="v1",
        top_k=1, cash_buffer=0.1, max_weight=0.5,
        minimum_scorable_coverage=0.5,
    )
    targets, daily = target_module._build_frames_from_layers(
        eligible=eligible, scorable=scorable, predictions=predictions,
        dates=dates, spec=spec,
    )
    assert targets.height == 3 and daily.height == 1
    variants = (
        predictions.head(1),
        pl.concat([predictions, pl.DataFrame({
            "as_of": [dates[0]], "symbol": ["999999.SZ"], "rank": [3],
        })]),
        pl.concat([predictions, predictions.head(1)]),
        predictions.reverse(),
        predictions.with_columns(pl.lit(dt.date(2026, 1, 6)).alias("as_of")),
    )
    for variant in variants:
        with pytest.raises(ValueError):
            target_module._build_frames_from_layers(
                eligible=eligible, scorable=scorable, predictions=variant,
                dates=dates, spec=spec,
            )


def test_formal_target_hostile_fresh_and_writer_are_redacted_and_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    kwargs = context["target_kwargs"]
    output = context["common"] / "formal-target-hostile-fresh"
    output.mkdir()

    def hostile(**_: Any) -> None:
        raise RuntimeError("C:/PRIVATE/TOKEN_G7A")

    monkeypatch.setattr(target_module, "verify_prediction_artifact", hostile)
    with pytest.raises(ValueError) as caught:
        build_target_artifact(**kwargs, output_root=output)
    assert str(caught.value) == "M3_TARGET_ARTIFACT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "TOKEN_G7A" not in repr(caught.value) and not any(output.iterdir())

    monkeypatch.setattr(
        target_module, "verify_prediction_artifact", lambda **_: context["prediction"]
    )
    real_write = publication_module.ArtifactPublication.write_bytes
    for fail_at in (1, 2, 3):
        target = context["common"] / f"formal-target-writer-{fail_at}"
        target.mkdir()
        calls = 0

        def hostile_write(self: Any, name: str, raw: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls == fail_at:
                raise OSError("C:/PRIVATE/WRITER_G7A")
            real_write(self, name, raw)

        monkeypatch.setattr(
            publication_module.ArtifactPublication, "write_bytes", hostile_write
        )
        with pytest.raises(ValueError, match="^M3_TARGET_ARTIFACT_INVALID$"):
            build_target_artifact(**kwargs, output_root=target)
        assert not any(target.iterdir())


def test_formal_target_rejects_path_identity_and_receipt_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    kwargs = context["target_kwargs"]
    copied = context["common"] / "copied-feature-receipt.json"
    copied.write_bytes(kwargs["upstream_paths"].feature_receipt_path.read_bytes())
    bad_upstream = replace(kwargs["upstream_paths"], feature_receipt_path=copied)
    output = context["common"] / "formal-target-path-drift"
    output.mkdir()
    with pytest.raises(ValueError, match="^M3_TARGET_ARTIFACT_INVALID$"):
        build_target_artifact(
            **{**kwargs, "upstream_paths": bad_upstream}, output_root=output
        )
    assert not any(output.iterdir())

    root, _, _, _ = _build_publish_verify(context, "receipt-drift")
    decoy = context["common"] / "unknown-input.txt"
    decoy.write_text("unknown", encoding="utf-8")
    receipt = context["common"] / "receipts" / "targets" / "extra.json"
    publish_stage_receipt(
        receipt_path=receipt, stage="targets", scope="WORK",
        scope_key=kwargs["spec"].work_key,
        artifact_roots=kwargs["artifact_roots"],
        inputs=[*_inputs(context), ("root", decoy)], outputs=_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_TARGET_ARTIFACT_INVALID$"):
        verify_target_artifact(root=root, receipt_path=receipt, **kwargs)


def test_formal_target_rejects_output_root_replacement_before_first_content_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    kwargs = context["target_kwargs"]
    output = context["common"] / "formal-target-root-replacement"
    moved = context["common"] / "formal-target-root-replacement-moved"
    output.mkdir()
    writer_calls = 0
    prediction = context["prediction"]
    real_write_stream = publication_module.ArtifactPublication.write_stream

    def replace_root(**_: Any) -> Any:
        os.rename(output, moved)
        output.mkdir()
        return prediction

    def counted_write_stream(self: Any, name: str, writer: Any) -> None:
        nonlocal writer_calls

        def counted(stream: Any) -> object:
            nonlocal writer_calls
            writer_calls += 1
            return writer(stream)

        real_write_stream(self, name, counted)

    monkeypatch.setattr(target_module, "verify_prediction_artifact", replace_root)
    monkeypatch.setattr(
        publication_module.ArtifactPublication, "write_stream", counted_write_stream
    )
    with pytest.raises(ValueError, match="^M3_TARGET_ARTIFACT_INVALID$"):
        build_target_artifact(**kwargs, output_root=output)
    assert writer_calls == 0 and not any(output.iterdir())
    if os.name == "nt":
        assert not moved.exists()
    else:
        assert not any(moved.iterdir())


def test_r3_formal_target_g1_quality_closure_rejects_drift_alias_and_pseudo_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path, monkeypatch)
    kwargs = context["target_kwargs"]
    release = kwargs["release"]
    quality = release.release.quality_path
    quality_src = (
        context["feature_bundle"][2].release.root / "contract" / "quality.json"
    )
    assert quality.is_file() and not (release.release.root / "receipt.json").exists()

    decoy = release.release.root / "receipt.json"
    decoy.write_bytes(b'{"stage":"targets"}')
    paths = target_module._formal_receipt_inputs(
        release, kwargs["feature"], kwargs["prediction"],
        kwargs["folds"], kwargs["experiment"], kwargs["upstream_paths"],
    )
    assert paths[1] == quality and decoy not in paths and paths[1].name == "quality.json"
    decoy.unlink()

    missing_output = context["common"] / "formal-target-quality-missing"
    missing_output.mkdir()
    quality.unlink()
    with pytest.raises(ValueError, match="^M3_TARGET_ARTIFACT_INVALID$"):
        build_target_artifact(**kwargs, output_root=missing_output)
    assert not any(missing_output.iterdir())
    shutil.copyfile(quality_src, quality)
    object.__setattr__(release, "quality_sha256", _sha(quality))

    root, receipt, _, _ = _build_publish_verify(context, "quality-ok")
    quality.write_bytes(b'{"schema_version":"hostile-quality","passed":false}\n')
    with pytest.raises(ValueError, match="^M3_TARGET_ARTIFACT_INVALID$"):
        verify_target_artifact(root=root, receipt_path=receipt, **kwargs)
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
    with pytest.raises(ValueError, match="formal target receipt input alias"):
        target_module._formal_receipt_inputs(
            release, kwargs["feature"], kwargs["prediction"],
            kwargs["folds"], kwargs["experiment"], kwargs["upstream_paths"],
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
    pseudo_output = context["common"] / "formal-target-pseudo-receipt-quality"
    pseudo_output.mkdir()
    (release.release.root / "receipt.json").write_bytes(quality.read_bytes())
    object.__setattr__(release, "quality_sha256", _sha(release.release.root / "receipt.json"))
    with pytest.raises(ValueError, match="^M3_TARGET_ARTIFACT_INVALID$"):
        build_target_artifact(**kwargs, output_root=pseudo_output)
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
    current = [path for _, path in _inputs(context)]
    legacy_paths = [current[0], fake_receipt, *current[2:]]
    assert len(legacy_paths) == 14
    legacy_receipt = context["common"] / "receipts" / "targets" / "legacy-pseudo.json"
    publish_stage_receipt(
        receipt_path=legacy_receipt, stage="targets", scope="WORK",
        scope_key=kwargs["spec"].work_key,
        artifact_roots=kwargs["artifact_roots"],
        inputs=[("root", path) for path in legacy_paths],
        outputs=_outputs(root),
    )
    with pytest.raises(ValueError, match="^M3_TARGET_ARTIFACT_INVALID$"):
        verify_target_artifact(root=root, receipt_path=legacy_receipt, **kwargs)