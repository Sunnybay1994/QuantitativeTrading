"""G8F strict fake 2-fold x 2-horizon full DAG integration."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from quant.research.m3.config import M3ConfigError, load_m3_config
from quant.research.m3.orchestration import (
    ExternalInput,
    M3StageRunnerError,
    OutputSpec,
    RunPlan,
    STAGE_SPEC_REGISTRY,
    StageBuildReport,
    StageContext,
    StageNode,
    StageOutputInput,
    StageRunner,
    StaticDirectoryPublication,
)
from quant.research.m3.run_state import ArtifactDigest


@dataclass(frozen=True)
class _FakeDag:
    root: Path
    plan: RunPlan
    nodes: tuple[StageNode, ...]
    runner: StageRunner


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _primary_output(spec_name: str) -> str:
    output = STAGE_SPEC_REGISTRY[spec_name].outputs[0]
    if output.kind == "FILE":
        return output.relative_path
    assert output.closure_manifest is not None
    return output.closure_manifest


def _digest(path: Path, root: Path) -> ArtifactDigest:
    raw = path.read_bytes()
    return ArtifactDigest(
        root_alias="G8",
        relative_path=path.relative_to(root).as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _build_dag(tmp_path: Path) -> _FakeDag:
    root = tmp_path / "stage"
    root.mkdir()
    seed = root / "seed.json"
    seed.write_bytes(b"{}\n")
    config = load_m3_config(
        Path(__file__).resolve().parents[2] / "configs/research/m3_qlib_example.toml"
    )
    nodes: list[StageNode] = []

    def add(
        node_id: str,
        spec_name: str,
        dependencies: tuple[str, ...] = (),
        *,
        fold: str | None = None,
        horizon: int | None = None,
    ) -> str:
        spec = STAGE_SPEC_REGISTRY[spec_name]
        inputs: list[ExternalInput | StageOutputInput] = []
        if not dependencies:
            inputs.append(ExternalInput(_digest(seed, root)))
        for dependency in sorted(dependencies):
            producer = next(node for node in nodes if node.node_id == dependency)
            inputs.append(
                StageOutputInput(
                    producer_node_id=dependency,
                    root_alias="G8",
                    relative_path=_primary_output(producer.spec_name),
                )
            )
        node = StageNode(
            node_id=node_id,
            spec_name=spec_name,
            scope=spec.scope,
            scope_key=_key(node_id),
            fold=fold,
            horizon=horizon,
            dependencies=tuple(sorted(dependencies)),
            inputs=tuple(inputs),
            publication=StaticDirectoryPublication(f"fake/{node_id}"),
            output_specs=spec.outputs,
            receipt_path=f"receipts/fake/{node_id}.json",
        )
        nodes.append(node)
        return node_id

    provider = add("provider", "provider")
    validation = add("provider-validation", "provider-validation", (provider,))
    experiment = add("experiment", "experiment-identity", (provider, validation))
    folds = add("folds", "folds", (experiment,))
    labels: dict[int, str] = {}
    reconciliations: dict[int, str] = {}
    for horizon in (5, 10):
        labels[horizon] = add(f"labels-h{horizon}", "labels", (experiment,), horizon=horizon)
        reconciliations[horizon] = add(
            f"label-reconciliation-h{horizon}",
            "label-reconciliation",
            (labels[horizon], validation),
            horizon=horizon,
        )
    features: dict[str, str] = {}
    for fold in ("fold-000", "fold-001"):
        features[fold] = add(f"features-{fold}", "features", (folds, validation), fold=fold)

    evaluations: dict[int, list[str]] = {5: [], 10: []}
    for fold in ("fold-000", "fold-001"):
        for horizon in (5, 10):
            suffix = f"{fold}-h{horizon}"
            alignment = add(
                f"alignment-{suffix}",
                "alignment",
                (features[fold], labels[horizon], reconciliations[horizon]),
                fold=fold,
                horizon=horizon,
            )
            train = add(f"train-{suffix}", "train", (alignment,), fold=fold, horizon=horizon)
            predictions = add(
                f"predictions-{suffix}",
                "predictions",
                (train, features[fold]),
                fold=fold,
                horizon=horizon,
            )
            evaluation = add(
                f"evaluation-{suffix}",
                "evaluation",
                (predictions, labels[horizon]),
                fold=fold,
                horizon=horizon,
            )
            evaluations[horizon].append(evaluation)
            targets = add(
                f"targets-{suffix}",
                "targets",
                (predictions, evaluation),
                fold=fold,
                horizon=horizon,
            )
            backtest_plan = add(
                f"backtest-plan-{suffix}",
                "backtest_plan",
                (targets,),
                fold=fold,
                horizon=horizon,
            )
            backtest = add(
                f"backtest-{suffix}",
                "backtest",
                (backtest_plan,),
                fold=fold,
                horizon=horizon,
            )
            add(
                f"tracking-{suffix}",
                "tracking",
                (backtest, evaluation),
                fold=fold,
                horizon=horizon,
            )
            add(
                f"reproducibility-{suffix}",
                "reproducibility",
                (evaluation,),
                fold=fold,
                horizon=horizon,
            )
    for horizon in (5, 10):
        add(
            f"summary-h{horizon}",
            "research-summary",
            tuple(evaluations[horizon]),
            horizon=horizon,
        )
    plan = RunPlan(continuation="WORK", nodes=tuple(nodes))
    runner = StageRunner(stage_root=root, artifact_roots={"G8": root}, config=config)
    return _FakeDag(root=root, plan=plan, nodes=tuple(nodes), runner=runner)


def _write_outputs(context: StageContext) -> StageBuildReport:
    root = context.temp_output_root
    for output in context.node.output_specs:
        _write_output(root, output, context.node.node_id)
    paths = tuple(
        sorted(
            (
                (Path(current) / name).relative_to(root).as_posix()
                for current, _directories, files in os.walk(root)
                for name in files
            )
        )
    )
    return StageBuildReport(paths)


def _write_output(root: Path, output: OutputSpec, node_id: str) -> None:
    if output.kind == "FILE":
        path = root / output.relative_path
    else:
        assert output.closure_manifest is not None
        (root / output.relative_path).mkdir(parents=True, exist_ok=True)
        path = root / output.closure_manifest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{node_id}:{path.relative_to(root).as_posix()}\n", encoding="utf-8")


def _run_available(
    dag: _FakeDag,
    *,
    calls: Counter[str],
    fail_once: set[str],
) -> dict[str, str]:
    results: dict[str, str] = {}
    for node in dag.nodes:

        def handler(context: StageContext, *, current: str = node.node_id) -> StageBuildReport:
            calls[current] += 1
            if current in fail_once:
                fail_once.remove(current)
                raise RuntimeError("planned fake failure")
            return _write_outputs(context)

        try:
            result = dag.runner.run_static(
                node=node,
                handler=handler,
                closure_verifier=lambda _root: None,
                plan=dag.plan,
            )
            results[node.node_id] = "reused" if result.reused else "built"
        except M3StageRunnerError as error:
            results[node.node_id] = error.code
    return results


def test_fake_full_dag_isolates_failure_and_resume_runs_only_missing_work(
    tmp_path: Path,
) -> None:
    dag = _build_dag(tmp_path)
    calls: Counter[str] = Counter()
    failed_prediction = "predictions-fold-001-h5"

    first = _run_available(dag, calls=calls, fail_once={failed_prediction})

    assert first[failed_prediction] == "STAGE_BUILD_FAILED"
    assert first["backtest-plan-fold-001-h5"] == "STAGE_INPUT_INVALID"
    for suffix in ("fold-000-h5", "fold-000-h10", "fold-001-h10"):
        assert first[f"backtest-plan-{suffix}"] == "built"
        assert first[f"tracking-{suffix}"] == "built"
        assert first[f"reproducibility-{suffix}"] == "built"
    shared = (
        "provider",
        "provider-validation",
        "experiment",
        "folds",
        "labels-h5",
        "labels-h10",
        "features-fold-000",
        "features-fold-001",
    )
    assert all(calls[node_id] == 1 for node_id in shared)
    before = calls.copy()

    second = _run_available(dag, calls=calls, fail_once=set())

    assert all(second[node_id] == "reused" for node_id in shared)
    assert all(calls[node_id] == before[node_id] for node_id in shared)
    assert second[failed_prediction] == "built"
    assert second["backtest-plan-fold-001-h5"] == "built"
    assert second["tracking-fold-001-h5"] == "built"
    assert second["reproducibility-fold-001-h5"] == "built"
    assert sum(node_id.startswith("backtest-plan-") for node_id in second) == 4


def test_completed_artifact_tamper_fails_closed_without_handler(
    tmp_path: Path,
) -> None:
    dag = _build_dag(tmp_path)
    calls: Counter[str] = Counter()
    results = _run_available(dag, calls=calls, fail_once=set())
    assert all(value == "built" for value in results.values())
    target_id = "backtest-plan-fold-000-h5"
    target = next(node for node in dag.nodes if node.node_id == target_id)
    publication = target.publication
    assert isinstance(publication, StaticDirectoryPublication)
    manifest = dag.root / publication.final_directory / "manifest.json"
    manifest.write_text("tampered\n", encoding="utf-8")
    before = calls[target_id]

    with pytest.raises(M3StageRunnerError):
        dag.runner.run_static(
            node=target,
            handler=lambda context: _write_outputs(context),
            closure_verifier=lambda _root: None,
            plan=dag.plan,
        )
    assert calls[target_id] == before


def test_plan_outputs_are_relative_and_imports_remain_lightweight(tmp_path: Path) -> None:
    dag = _build_dag(tmp_path)
    assert len(dag.nodes) == 48
    assert all(
        not PurePosixPath(node.publication.final_directory).is_absolute()
        for node in dag.nodes
        if isinstance(node.publication, StaticDirectoryPublication)
    )
    project = Path(__file__).resolve().parents[2]
    code = (
        "import sys;"
        f"sys.path.insert(0,{str(project / 'src')!r});"
        "import quant.domain,quant.strategies,quant.backtest;"
        "assert not {'qlib','lightgbm','mlflow'} & set(sys.modules);"
        "print('G8F_IMPORT_ISOLATION_PASS')"
    )
    completed = subprocess.run(
        (sys.executable, "-I", "-c", code),
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert completed.stdout.splitlines() == [b"G8F_IMPORT_ISOLATION_PASS"]


def test_config_changes_invalidate_only_the_owned_identity_layer(tmp_path: Path) -> None:
    source = (
        Path(__file__).resolve().parents[2] / "configs/research/m3_qlib_example.toml"
    ).read_text("utf-8")

    def loaded(name: str, before: str, after: str):
        assert before in source
        path = tmp_path / f"{name}.toml"
        path.write_text(source.replace(before, after, 1), encoding="utf-8")
        return load_m3_config(path)

    base_path = tmp_path / "base.toml"
    base_path.write_text(source, encoding="utf-8")
    base = load_m3_config(base_path)
    tracking = loaded(
        "tracking",
        'tracking_uri = "sqlite:///artifacts/research/m3/mlflow.db"',
        'tracking_uri = "sqlite:///artifacts/research/m3/other.db"',
    )
    assert tracking.tracking_target_key != base.tracking_target_key
    assert tracking.scientific_config_sha256 == base.scientific_config_sha256
    assert tracking.provider_config_sha256 == base.provider_config_sha256

    cost = loaded("cost", "commission_rate = 0.00025", "commission_rate = 0.00026")
    model = loaded("model", "num_boost_round = 500", "num_boost_round = 501")
    for changed in (cost, model):
        assert changed.scientific_config_sha256 != base.scientific_config_sha256
        assert changed.snapshot_config_sha256 == base.snapshot_config_sha256
        assert changed.provider_config_sha256 == base.provider_config_sha256

    with pytest.raises(M3ConfigError):
        loaded(
            "provider-validation",
            "sample_dates_per_symbol = 20",
            "sample_dates_per_symbol = 19",
        )

    label_tolerance = loaded(
        "label-tolerance", "label_return_atol = 5e-6", "label_return_atol = 6e-6"
    )
    assert (
        label_tolerance.label_reconciliation_config_sha256
        != base.label_reconciliation_config_sha256
    )
    assert label_tolerance.scientific_config_sha256 == base.scientific_config_sha256

    acceptance = loaded(
        "acceptance",
        "reproducibility_score_atol = 1e-12",
        "reproducibility_score_atol = 2e-12",
    )
    assert acceptance.acceptance_config_sha256 != base.acceptance_config_sha256
    assert acceptance.scientific_config_sha256 == base.scientific_config_sha256
