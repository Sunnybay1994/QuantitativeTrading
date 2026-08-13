from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import quant.research.run_m3 as run_m3
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.readiness import ReadinessIssue
from quant.research.m3.runtime_identity import M3RuntimeIdentityV1
from quant.research.run_m3 import CommandFailure, CommandSummary, main


def _argv(root: Path) -> list[str]:
    path_options = (
        "project-root",
        "config",
        "g1-release-root",
        "snapshot-artifact-root",
        "snapshot-root",
        "snapshot-request-path",
        "snapshot-receipt-path",
        "provider-artifact-root",
        "provider-root",
        "provider-receipt-path",
        "provider-validation-artifact-root",
        "provider-validation-root",
        "provider-validation-receipt-path",
        "external-qlib-root",
        "stage-root",
    )
    args = ["experiment-identity"]
    for option in path_options:
        args.extend((f"--{option}", str(root)))
    args.extend(("--provider-validation-code-version", "m3-g2c-v1"))
    return args


def test_cli_emits_one_canonical_json_with_injected_execution(
    tmp_path: Path, capsys
) -> None:
    code = main(
        _argv(tmp_path),
        execute=lambda _args: {"command": "experiment-identity", "reused": False},
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == {
        "command": "experiment-identity",
        "ok": True,
        "reused": False,
    }
    assert captured.out == json.dumps(
        json.loads(captured.out),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ) + "\n"


def test_cli_redacts_internal_exception_and_usage_errors(capsys) -> None:
    secret = "TOKEN=should-not-appear"

    def fail(_args):
        raise RuntimeError(secret)

    code = main(_argv(Path("fixture")), execute=fail)
    output = capsys.readouterr().out
    assert code == 5
    assert secret not in output
    assert json.loads(output) == {"error_code": "M3_COMMAND_FAILED", "ok": False}

    code = main(["experiment-identity"])
    output = capsys.readouterr().out
    assert code == 2
    assert json.loads(output) == {"error_code": "M3_CLI_USAGE_INVALID", "ok": False}


_ID = "1" * 64


@pytest.mark.parametrize(
    ("command", "identity_args", "stop_stage"),
    [
        ("readiness", ["--g1-release-id", _ID], "readiness"),
        ("snapshot", ["--g1-release-id", _ID], "snapshot"),
        (
            "train",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "5"],
            "train",
        ),
        (
            "evaluate",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "10"],
            "evaluation",
        ),
        (
            "backtest",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "5"],
            "backtest",
        ),
        ("run-all", ["--snapshot-id", _ID], "tracking"),
        (
            "verify-reproducibility",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "10"],
            "comparison",
        ),
        ("acceptance-audit", ["--snapshot-id", _ID], "acceptance"),
    ],
)
def test_public_commands_have_strict_identity_args_and_stop_points(
    command: str,
    identity_args: list[str],
    stop_stage: str,
    tmp_path: Path,
    capsys,
) -> None:
    observed: list[tuple[str, Path, str]] = []

    def dispatch(args):
        observed.append((args.command, args.config, args.stop_stage))
        return {"reused": True}

    config_arg = str(tmp_path / "m3.toml")
    code = main(
        [command, "--config", config_arg, *identity_args],
        dispatcher=dispatch,
    )
    output = capsys.readouterr().out
    assert code == 0
    expected_config: object = config_arg if command == "backtest" else tmp_path / "m3.toml"
    assert observed == [(command, expected_config, stop_stage)]
    assert json.loads(output) == {
        "command": command,
        "failures": [],
        "ok": True,
        "reused": True,
    }
    assert output.count("\n") == 1
    assert output == json.dumps(
        json.loads(output), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ) + "\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["run-all", "--config", "m3.toml"],
        [
            "run-all",
            "--config",
            "m3.toml",
            "--g1-release-id",
            _ID,
            "--snapshot-id",
            _ID,
        ],
        ["train", "--config", "m3.toml", "--snapshot-id", _ID],
        [
            "train",
            "--config",
            "m3.toml",
            "--snapshot-id",
            _ID,
            "--fold",
            "fold_01",
            "--horizon",
            "5",
        ],
        [
            "train",
            "--config",
            "m3.toml",
            "--snapshot-id",
            _ID,
            "--fold",
            "fold_001",
            "--horizon",
            "20",
        ],
    ],
)
def test_public_usage_errors_are_code_two_before_dispatch(argv: list[str], capsys) -> None:
    calls = 0

    def dispatch(_args):
        nonlocal calls
        calls += 1
        return {}

    code = main(argv, dispatcher=dispatch)
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert calls == 0
    assert payload["ok"] is False
    assert payload["failures"] == [
        {
            "error_code": "M3_CLI_USAGE_INVALID",
            "exit_code": 2,
            "node_id": argv[0],
            "scope": "command",
        }
    ]


def test_failure_summary_is_sorted_and_uses_minimum_exit_code(capsys) -> None:
    def dispatch(_args):
        return CommandSummary(
            command="run-all",
            failures=(
                CommandFailure("work", "fold_002:10", "TRACKING_FAILED", 6),
                CommandFailure("shared", "provider", "DEPENDENCY_MISSING", 4),
                CommandFailure("work", "fold_001:5", "STAGE_FAILED", 5),
            ),
        )

    code = main(
        ["run-all", "--config", "m3.toml", "--snapshot-id", _ID],
        dispatcher=dispatch,
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 4
    assert [
        (item["scope"], item["node_id"], item["error_code"])
        for item in payload["failures"]
    ] == [
        ("shared", "provider", "DEPENDENCY_MISSING"),
        ("work", "fold_001:5", "STAGE_FAILED"),
        ("work", "fold_002:10", "TRACKING_FAILED"),
    ]


@pytest.mark.parametrize(
    "unsafe",
    [
        {"message": "Bearer private-value"},
        {"nested": [{"token": "private-value"}]},
        {"artifact": "C:\\private\\candidate.json"},
        {"artifact": "/private/candidate.json"},
        {"artifact": "//server/私有/candidate.json"},
    ],
)
def test_public_summary_and_exceptions_are_sanitized(unsafe: object, capsys) -> None:
    code = main(
        ["snapshot", "--config", "m3.toml", "--g1-release-id", _ID],
        dispatcher=lambda _args: unsafe,  # type: ignore[arg-type,return-value]
    )
    output = capsys.readouterr().out
    assert code == 5
    assert "private" not in output.lower()
    assert json.loads(output)["failures"][0]["error_code"] == "M3_COMMAND_FAILED"

    def fail(_args):
        raise RuntimeError("TOKEN=C:\\private\\candidate.json")

    code = main(
        ["snapshot", "--config", "m3.toml", "--g1-release-id", _ID],
        dispatcher=fail,
    )
    output = capsys.readouterr().out
    assert code == 5
    assert "private" not in output.lower()
    assert "TOKEN" not in output


def test_dispatcher_diagnostics_are_discarded_from_public_streams(capsys) -> None:
    def dispatch(_args):
        print("TOKEN=/private/handler")
        return {"snapshot_id": _ID}

    code = main(
        ["snapshot", "--config", "m3.toml", "--g1-release-id", _ID],
        dispatcher=dispatch,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.count("\n") == 1
    assert "TOKEN" not in captured.out
    assert "private" not in captured.out
    assert captured.err == ""


def test_dispatcher_exception_cannot_forge_error_code(capsys) -> None:
    class FakeGateError(RuntimeError):
        code = "ACCEPTANCE_GATE_PASSED"

    def fail(_args):
        raise FakeGateError("TOKEN=C:\\private\\candidate.json")

    code = main(
        ["snapshot", "--config", "m3.toml", "--g1-release-id", _ID],
        dispatcher=fail,
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 5
    assert payload["failures"][0]["error_code"] == "M3_COMMAND_FAILED"


@pytest.mark.parametrize(
    ("command", "identity_args"),
    [
        (
            "train",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "5"],
        ),
        (
            "evaluate",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "10"],
        ),
        ("run-all", ["--snapshot-id", _ID]),
        (
            "verify-reproducibility",
            ["--snapshot-id", _ID, "--fold", "fold_001", "--horizon", "10"],
        ),
    ],
)
def test_unimplemented_public_handler_is_explicit_and_does_not_fake_artifacts(
    command: str, identity_args: list[str], capsys
) -> None:
    code = main([command, "--config", "m3.toml", *identity_args])
    payload = json.loads(capsys.readouterr().out)
    assert code == 5
    assert payload == {
        "command": command,
        "failures": [
            {
                "error_code": "M3_COMMAND_HANDLER_UNAVAILABLE",
                "exit_code": 5,
                "node_id": command,
                "scope": "command",
            }
        ],
        "ok": False,
    }


def test_acceptance_audit_public_handler_resolves_audits_and_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    import quant.research.m3.acceptance as acceptance_module
    import quant.research.m3.acceptance_stage as stage_module
    import quant.research.m3.formal_cli_resolve as resolve_module
    import quant.research.m3.quality_gate as quality_module
    import quant.research.m3.readiness_evidence as readiness_module

    config_path = tmp_path / "m3.toml"
    config_path.write_text("fixture=true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = SimpleNamespace(
        section=lambda name: {"horizons_sessions": (5, 10)}
        if name == "labels"
        else {},
    )
    monkeypatch.setattr(run_m3, "load_m3_config", lambda path: config)
    first = SimpleNamespace(release=object(), artifact_roots={"G8": tmp_path})
    monkeypatch.setattr(
        resolve_module,
        "resolve_formal_reproducibility_cli_inputs",
        lambda **kwargs: first,
    )
    monkeypatch.setattr(
        readiness_module,
        "resolve_readiness_evidence_artifact",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        acceptance_module, "resolve_acceptance_subject", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        acceptance_module, "build_acceptance_evidence_plan", lambda **kwargs: object()
    )
    monkeypatch.setattr(quality_module, "run_quality_gate", lambda **kwargs: object())
    decision = SimpleNamespace(overall_status="PASS")
    monkeypatch.setattr(
        stage_module, "audit_formal_m3_acceptance", lambda **kwargs: decision
    )
    monkeypatch.setattr(
        stage_module,
        "run_formal_acceptance_stage",
        lambda **kwargs: SimpleNamespace(
            decision=SimpleNamespace(acceptance_key="a" * 64), reused=False
        ),
    )

    code = main([
        "acceptance-audit",
        "--config",
        str(config_path),
        "--snapshot-id",
        _ID,
    ])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload == {
        "acceptance_key": "a" * 64,
        "command": "acceptance-audit",
        "failures": [],
        "ok": True,
        "overall_status": "PASS",
        "reused": False,
        "snapshot_id": _ID,
        "stop_stage": "acceptance",
    }


@pytest.mark.parametrize(
    ("gate", "issue_code", "expected"),
    [
        ("G0", "CONFIG_DISABLED", 2),
        ("G1", "RELEASE_LINEAGE_INVALID", 3),
        ("G6", "DEPENDENCY_INVALID", 4),
        ("G7", "WORK_INVALID", 5),
        ("G8", "TRACKING_REMOTE_INVALID", 6),
        ("G8", "REPRODUCIBILITY_INVALID", 7),
        ("G9", "QUALITY_INVALID", 8),
    ],
)
def test_acceptance_issue_exit_categories_are_stable(
    gate: str, issue_code: str, expected: int
) -> None:
    assert run_m3._acceptance_issue_exit_code(
        gate=gate, issue_code=issue_code
    ) == expected


def test_backtest_parser_defaults_resume_and_accepts_no_resume() -> None:
    parser = run_m3.build_parser()
    default = parser.parse_args(
        [
            "backtest",
            "--config",
            "configs/research/m3.toml",
            "--snapshot-id",
            _ID,
            "--fold",
            "fold_001",
            "--horizon",
            "5",
        ]
    )
    assert default.no_resume is False
    flagged = parser.parse_args(
        [
            "backtest",
            "--config",
            "configs/research/m3.toml",
            "--snapshot-id",
            _ID,
            "--fold",
            "fold_001",
            "--horizon",
            "5",
            "--no-resume",
        ]
    )
    assert flagged.no_resume is True


@pytest.mark.parametrize("command", ["train", "evaluate", "verify-reproducibility"])
def test_other_snapshot_work_commands_reject_no_resume(command: str, capsys) -> None:
    code = main(
        [
            command,
            "--config",
            "m3.toml",
            "--snapshot-id",
            _ID,
            "--fold",
            "fold_001",
            "--horizon",
            "5",
            "--no-resume",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["failures"][0]["error_code"] == "M3_CLI_USAGE_INVALID"


def test_backtest_missing_config_is_usage_not_unavailable(capsys) -> None:
    code = main(
        [
            "backtest",
            "--snapshot-id",
            _ID,
            "--fold",
            "fold_001",
            "--horizon",
            "5",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["failures"][0]["error_code"] == "M3_CLI_USAGE_INVALID"


def _public_config(tmp_path: Path) -> Path:
    target = tmp_path / "configs" / "research" / "m3_qlib_example.toml"
    target.parent.mkdir(parents=True)
    source = Path(__file__).parents[2] / "configs" / "research" / "m3_qlib_example.toml"
    shutil.copyfile(source, target)
    return target


def test_default_readiness_rejects_missing_verified_release_before_any_stage_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config = _public_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        ["readiness", "--config", str(config), "--g1-release-id", _ID]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["failures"][0]["error_code"] == "G1_RELEASE_INVALID"
    assert not (tmp_path / "artifacts").exists()


def test_default_snapshot_dispatches_identity_readiness_then_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config = _public_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    release = SimpleNamespace(release=SimpleNamespace(release_id=_ID))

    def verify_requested_release(**_kwargs):
        calls.append("identity")
        return release

    def audit_verified_release(**_kwargs):
        calls.append("readiness")
        return ()

    def compute_runtime(**_kwargs):
        calls.append("runtime")
        return SimpleNamespace(code_version="m3-test-code-v1")

    def run_snapshot_stage(**_kwargs):
        calls.append("snapshot")
        return SimpleNamespace(
            reused=False,
            build=SimpleNamespace(manifest=SimpleNamespace(snapshot_id="2" * 64)),
        )

    monkeypatch.setattr(run_m3, "_verify_requested_release", verify_requested_release)
    monkeypatch.setattr(run_m3, "_audit_verified_release", audit_verified_release)
    monkeypatch.setattr(run_m3, "compute_m3_runtime_identity", compute_runtime)
    monkeypatch.setattr(run_m3, "_run_snapshot_stage", run_snapshot_stage)

    code = main(["snapshot", "--config", str(config), "--g1-release-id", _ID])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls == ["identity", "readiness", "runtime", "snapshot"]
    assert payload["snapshot_id"] == "2" * 64
    assert payload["stop_stage"] == "snapshot"


def test_default_snapshot_uses_one_frozen_config_across_readiness_and_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = _public_config(tmp_path).resolve()
    (tmp_path / "src" / "quant").mkdir(parents=True)
    (tmp_path / "src" / "quant" / "module.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='fixture'\n", encoding="utf-8"
    )
    original = config_path.read_bytes()
    original_sha256 = hashlib.sha256(original).hexdigest()
    replacement_bytes = original + b"\n# atomic replacement after readiness\n"
    monkeypatch.chdir(tmp_path)
    release = SimpleNamespace(release=SimpleNamespace(release_id=_ID))
    monkeypatch.setattr(
        run_m3, "_verify_requested_release", lambda **_kwargs: release
    )
    real_read_bytes = Path.read_bytes
    config_reads = 0
    observed: dict[str, object] = {}

    def counted_read_bytes(path: Path) -> bytes:
        nonlocal config_reads
        if path == config_path:
            config_reads += 1
        return real_read_bytes(path)

    def audit_verified_release(**kwargs):
        observed["loaded"] = kwargs["config"]
        replacement = config_path.with_suffix(".next")
        replacement.write_bytes(replacement_bytes)
        replacement.replace(config_path)
        return ()

    real_compute = run_m3.compute_m3_runtime_identity

    def compute_runtime(**kwargs):
        observed["frozen"] = kwargs["frozen_config_digests"]
        result = real_compute(**kwargs)
        observed["runtime"] = result
        return result

    def run_snapshot_stage(**kwargs):
        observed["stage_config"] = kwargs["config"]
        observed["stage_code_version"] = kwargs["code_version"]
        return SimpleNamespace(
            reused=False,
            build=SimpleNamespace(manifest=SimpleNamespace(snapshot_id="2" * 64)),
        )

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    monkeypatch.setattr(run_m3, "_audit_verified_release", audit_verified_release)
    monkeypatch.setattr(run_m3, "compute_m3_runtime_identity", compute_runtime)
    monkeypatch.setattr(run_m3, "_run_snapshot_stage", run_snapshot_stage)

    code = main(
        ["snapshot", "--config", str(config_path), "--g1-release-id", _ID]
    )

    payload = json.loads(capsys.readouterr().out)
    loaded = observed["loaded"]
    runtime = observed["runtime"]
    frozen = observed["frozen"]
    assert isinstance(loaded, LoadedM3Config)
    assert isinstance(runtime, M3RuntimeIdentityV1)
    assert isinstance(frozen, tuple)
    assert code == 0 and payload["ok"] is True
    assert config_reads == 1
    assert loaded is observed["stage_config"]
    assert loaded.raw_config_sha256 == original_sha256
    assert frozen == (
        run_m3.M3SourceDigestV1(
            "configs/research/m3_qlib_example.toml", original_sha256
        ),
    )
    assert frozen[0] in runtime.source_files
    assert observed["stage_code_version"] == runtime.code_version
    assert hashlib.sha256(config_path.read_bytes()).hexdigest() != original_sha256
    assert not (tmp_path / "artifacts").exists()


def test_default_snapshot_readiness_error_blocks_runtime_and_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config = _public_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    release = SimpleNamespace(release=SimpleNamespace(release_id=_ID))
    monkeypatch.setattr(
        run_m3, "_verify_requested_release", lambda **_kwargs: release
    )
    monkeypatch.setattr(
        run_m3,
        "_audit_verified_release",
        lambda **_kwargs: (
            ReadinessIssue("CROSS_SECTION_TOO_SMALL", "ERROR", "fixture"),
        ),
    )
    monkeypatch.setattr(
        run_m3,
        "compute_m3_runtime_identity",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    monkeypatch.setattr(
        run_m3,
        "_run_snapshot_stage",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    code = main(["snapshot", "--config", str(config), "--g1-release-id", _ID])

    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["failures"][0]["error_code"] == "CROSS_SECTION_TOO_SMALL"
    assert not (tmp_path / "artifacts").exists()


def test_default_snapshot_readiness_warning_does_not_block_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config = _public_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    release = SimpleNamespace(release=SimpleNamespace(release_id=_ID))
    monkeypatch.setattr(
        run_m3, "_verify_requested_release", lambda **_kwargs: release
    )
    monkeypatch.setattr(
        run_m3,
        "_audit_verified_release",
        lambda **_kwargs: (ReadinessIssue("FIXTURE_WARNING", "WARNING", "fixture"),),
    )
    monkeypatch.setattr(
        run_m3,
        "compute_m3_runtime_identity",
        lambda **_kwargs: SimpleNamespace(code_version="m3-test-code-v1"),
    )
    monkeypatch.setattr(
        run_m3,
        "_run_snapshot_stage",
        lambda **_kwargs: SimpleNamespace(
            reused=True,
            build=SimpleNamespace(manifest=SimpleNamespace(snapshot_id="2" * 64)),
        ),
    )

    code = main(["snapshot", "--config", str(config), "--g1-release-id", _ID])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["reused"] is True
    assert payload["snapshot_id"] == "2" * 64
