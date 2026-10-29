"""Reference contract regressions with shared verified synthetic inputs."""
from __future__ import annotations

from tests.unit.test_m3_reference import (
    Any,
    BaostockConnector,
    CrossSourceSamplePlan,
    G1Candidate,
    G1CrossSourcePolicy,
    M3ReferenceError,
    Path,
    RawStore,
    ReferenceRawCandidateV1,
    ReferenceRequestIntentV1,
    ReferenceRequestPlanV1,
    ReferenceRequestSpec,
    VerifiedReferenceResponse,
    _D0,
    _ExplodingClient,
    _HEX,
    _JournalFakeClient,
    _base_policy_kwargs,
    _make_verified_reference,
    _perfect_reference_responses,
    _policy,
    _rebind_identity,
    _reference_frame,
    _reference_rows_for_symbol,
    _require_fifo,
    _require_symlink,
    _restrict_bar_symbols,
    _sample_dates_by_symbol,
    _sample_reference_frame,
    _simple_intent,
    asdict,
    audit_g1_candidate,
    dt,
    execute_baostock_reference_plan,
    happy_candidate,
    happy_inputs,
    io,
    json,
    os,
    pl,
    plan_baostock_reference_requests,
    plan_cross_source_reconciliation,
    pytest,
    reconcile_cross_source,
    ref,
    replace,
    request_plan,
    sample_plan,
    sys,
    verify_reference_receipt,
)


@pytest.mark.parametrize(
    "overrides",
    [
        {"reference_source": "tushare"},
        {"reference_source": "BAOSTOCK"},
        {"sample_symbols": 31},
        {"sample_symbols": True},
        {"sample_symbols": 30.0},
        {"dates_per_symbol": 19},
        {"dates_per_symbol": False},
        {"price_atol": -0.001},
        {"price_atol": float("nan")},
        {"price_atol": float("inf")},
        {"price_atol": 1},
        {"price_atol": True},
        {"price_rtol": -0.1},
        {"price_rtol": 1.1},
        {"price_rtol": float("nan")},
        {"price_rtol": float("inf")},
        {"price_rtol": 1},
        {"price_rtol": False},
        {"volume_rtol": -0.1},
        {"volume_rtol": 1.1},
        {"volume_rtol": float("nan")},
        {"volume_rtol": float("inf")},
        {"max_mismatch_rate": -0.1},
        {"max_mismatch_rate": 1.1},
        {"max_mismatch_rate": float("nan")},
        {"max_mismatch_rate": float("inf")},
    ],
)
def test_policy_rejects_illegal_values(overrides: dict[str, Any]) -> None:
    kwargs = _base_policy_kwargs()
    kwargs.update(overrides)
    with pytest.raises(ValueError):
        G1CrossSourcePolicy(**kwargs)


def test_policy_accepts_boundary_values() -> None:
    policy = G1CrossSourcePolicy(
        reference_source="baostock",
        sample_symbols=30,
        dates_per_symbol=20,
        price_atol=0.0,
        price_rtol=0.0,
        volume_rtol=1.0,
        max_mismatch_rate=1.0,
    )
    assert policy.price_atol == 0.0
    assert policy.max_mismatch_rate == 1.0


def test_happy_candidate_audit_passes(happy_candidate: G1Candidate) -> None:
    audit = audit_g1_candidate(candidate=happy_candidate)
    assert audit.passed is True
    assert audit.issues == ()


def test_sample_plan_has_exact_shape_and_is_deterministic(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan
) -> None:
    assert sample_plan.sample_symbols == 30
    assert sample_plan.dates_per_symbol == 20
    assert len(sample_plan.keys) == 600
    by_symbol: dict[str, list[dt.date]] = {}
    for symbol, day in sample_plan.keys:
        by_symbol.setdefault(symbol, []).append(day)
    assert len(by_symbol) == 30
    assert all(len(days) == 20 for days in by_symbol.values())
    assert sample_plan.keys == tuple(sorted(sample_plan.keys))

    again = plan_cross_source_reconciliation(candidate=happy_candidate, policy=_policy())
    assert again == sample_plan


def test_sample_plan_rejects_non_candidate_type() -> None:
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate="not-a-candidate", policy=_policy())  # type: ignore[arg-type]
    assert excinfo.value.code == "G1_REFERENCE_INPUT_INVALID"


def test_sample_plan_rejects_bad_policy_type(happy_candidate: G1Candidate) -> None:
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate=happy_candidate, policy="bad")  # type: ignore[arg-type]
    assert excinfo.value.code == "G1_REFERENCE_INPUT_INVALID"


def test_sample_plan_rejects_failed_audit(happy_candidate: G1Candidate) -> None:
    symbol = happy_candidate.eligible_keys["symbol"][0]
    bars = happy_candidate.bars.filter(
        ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D0))
    )
    damaged = _rebind_identity(happy_candidate, bars=bars)
    assert audit_g1_candidate(candidate=damaged).passed is False
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate=damaged, policy=_policy())
    assert excinfo.value.code == "G1_REFERENCE_INPUT_INVALID"


def test_sample_plan_rejects_fewer_than_30_symbols(happy_candidate: G1Candidate) -> None:
    keep = sorted(happy_candidate.instruments.get_column("symbol").to_list())[:10]
    damaged = _restrict_bar_symbols(happy_candidate, keep)
    assert audit_g1_candidate(candidate=damaged).passed is True
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate=damaged, policy=_policy())
    assert excinfo.value.code == "G1_REFERENCE_PLAN_INVALID"


def test_sample_plan_rejects_selected_symbol_with_fewer_than_20_dates(
    happy_candidate: G1Candidate,
) -> None:
    keep = sorted(happy_candidate.instruments.get_column("symbol").to_list())[:30]
    damaged = _restrict_bar_symbols(happy_candidate, keep, short_symbol=keep[0], short_keep=5)
    assert audit_g1_candidate(candidate=damaged).passed is True
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_cross_source_reconciliation(candidate=damaged, policy=_policy())
    assert excinfo.value.code == "G1_REFERENCE_PLAN_INVALID"


def test_sample_plan_constructor_rejects_drift(sample_plan: CrossSourceSamplePlan) -> None:
    with pytest.raises(ValueError):
        replace(sample_plan, keys=sample_plan.keys[:-1])
    with pytest.raises(ValueError):
        replace(sample_plan, keys=tuple(reversed(sample_plan.keys)))
    with pytest.raises(ValueError):
        replace(sample_plan, sample_plan_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(sample_plan, primary_candidate_key="not-hex")
    with pytest.raises(ValueError):
        replace(sample_plan, sample_symbols=29)


def test_request_plan_matches_sample_and_symbol_derivation(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1
) -> None:
    assert len(request_plan.requests) == 30
    assert request_plan.sample_plan_sha256 == sample_plan.sample_plan_sha256
    assert [spec.request_id for spec in request_plan.requests] == sorted(
        spec.request_id for spec in request_plan.requests
    )
    symbols = {spec.symbol for spec in request_plan.requests}
    assert len(symbols) == 30
    by_symbol_dates = _sample_dates_by_symbol(sample_plan)
    for spec in request_plan.requests:
        params = dict(spec.parameters)
        assert set(params) == {"fields", "frequency", "adjustflag", "start_date", "end_date"}
        assert params["fields"] == ref._FIELDS
        assert params["frequency"] == "d"
        assert params["adjustflag"] == "3"
        days = by_symbol_dates[spec.symbol]
        assert params["start_date"] == days[0].isoformat()
        assert params["end_date"] == days[-1].isoformat()
        assert "symbol" not in params
        assert "code" not in params


def test_request_plan_rejects_bad_sample_plan_type() -> None:
    with pytest.raises(M3ReferenceError) as excinfo:
        plan_baostock_reference_requests(sample_plan="not-a-plan")  # type: ignore[arg-type]
    assert excinfo.value.code == "G1_REFERENCE_INPUT_INVALID"


def test_request_spec_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    with pytest.raises(ValueError):
        replace(spec, endpoint="query_history_k_data")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(spec, symbol="000001.BJ")
    with pytest.raises(ValueError):
        replace(spec, request_id="0" * 64)
    params = dict(spec.parameters)
    with pytest.raises(ValueError):
        replace(spec, parameters=tuple(sorted({**params, "extra": "x"}.items())))
    with pytest.raises(ValueError):
        replace(
            spec,
            parameters=tuple(sorted({k: v for k, v in params.items() if k != "fields"}.items())),
        )
    with pytest.raises(ValueError):
        replace(spec, parameters=tuple(sorted({**params, "adjustflag": "1"}.items())))
    with pytest.raises(ValueError):
        replace(spec, parameters=tuple(sorted({**params, "frequency": "w"}.items())))
    swapped = {**params, "start_date": params["end_date"], "end_date": params["start_date"]}
    with pytest.raises(ValueError):
        replace(spec, parameters=tuple(sorted(swapped.items())))


def test_request_plan_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    with pytest.raises(ValueError):
        replace(request_plan, requests=request_plan.requests[:-1])
    with pytest.raises(ValueError):
        replace(request_plan, requests=tuple(reversed(request_plan.requests)))
    with pytest.raises(ValueError):
        replace(request_plan, requests=request_plan.requests + (request_plan.requests[0],))
    with pytest.raises(ValueError):
        replace(request_plan, request_plan_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(request_plan, sample_plan_sha256="1" * 64)


def test_intent_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    intent = ReferenceRequestIntentV1(
        "m3-g1-baostock-intent-v1", spec.request_id, spec.endpoint, spec.symbol,
        spec.parameters, ref._parameters_hash(spec.parameters),
    )
    with pytest.raises(ValueError):
        replace(intent, parameters_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(intent, symbol="000002.SZ")


def test_candidate_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    frame = _sample_reference_frame(spec, dt.date.fromisoformat(dict(spec.parameters)["start_date"]))
    content = ref._reference_response_content_sha256(frame)
    candidate = ReferenceRawCandidateV1(
        "m3-g1-baostock-candidate-v1", spec.request_id, spec.endpoint, spec.symbol,
        ref._parameters_hash(spec.parameters), spec.request_id,
        f"baostock/query_history_k_data_plus/request={spec.request_id}/data.parquet",
        f"baostock/query_history_k_data_plus/request={spec.request_id}/metadata.json",
        _HEX, _HEX, content, 1, frame.height, tuple(frame.columns),
    )
    with pytest.raises(ValueError):
        replace(candidate, raw_snapshot_id="0" * 64)
    with pytest.raises(ValueError):
        replace(candidate, raw_data_path="/abs/data.parquet")
    with pytest.raises(ValueError):
        replace(candidate, raw_data_path="../escape/data.parquet")
    with pytest.raises(ValueError):
        replace(candidate, raw_data_path="a\\b\\data.parquet")
    with pytest.raises(ValueError):
        replace(candidate, columns=("date", "code"))
    with pytest.raises(ValueError):
        replace(candidate, raw_size_bytes=-1)


def test_receipt_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    frame = _sample_reference_frame(spec, dt.date.fromisoformat(dict(spec.parameters)["start_date"]))
    updated = _make_verified_reference(spec, frame)
    receipt = updated.receipt
    with pytest.raises(ValueError):
        replace(receipt, stable_response_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(receipt, parameters_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(receipt, raw_snapshot_id="0" * 64)
    with pytest.raises(ValueError):
        replace(receipt, columns=("date",))


def test_verified_reference_constructor_rejects_drift(request_plan: ReferenceRequestPlanV1) -> None:
    spec = request_plan.requests[0]
    frame = _sample_reference_frame(spec, dt.date.fromisoformat(dict(spec.parameters)["start_date"]))
    verified = _make_verified_reference(spec, frame)
    with pytest.raises(ValueError):
        VerifiedReferenceResponse(verified.spec, verified.receipt, "0" * 64, verified.frame)
    changed = verified.frame.with_columns(pl.lit("999.0").alias("close"))
    with pytest.raises(ValueError):
        VerifiedReferenceResponse(verified.spec, verified.receipt, verified.receipt_sha256, changed)
    with pytest.raises(ValueError):
        VerifiedReferenceResponse(
            verified.spec, verified.receipt, verified.receipt_sha256, "not-a-frame"  # type: ignore[arg-type]
        )


def test_executor_happy_path_produces_30_sorted_receipts(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    client = _JournalFakeClient()
    receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
        raw_store=RawStore(tmp_path / "raw"), journal_root=tmp_path / "journal",
    )
    assert len(receipts) == 30
    assert [item.request_id for item in receipts] == sorted(item.request_id for item in receipts)
    assert {item.request_id for item in receipts} == {
        spec.request_id for spec in request_plan.requests
    }
    assert client.logout_calls == 30
    assert len(client.calls) == 30
    lock_path = tmp_path / "journal" / ".writer.lock"
    assert lock_path.is_file()
    assert os.lstat(lock_path).st_nlink == 1


def test_executor_stale_lock_file_allows_repeat_run(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal = tmp_path / "journal"
    journal.mkdir()
    lock_path = journal / ".writer.lock"
    lock_path.write_bytes(b"stale-nonempty")
    first = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(tmp_path / "raw"), journal_root=journal,
    )
    second = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(tmp_path / "raw"), journal_root=journal,
    )
    assert [item.request_id for item in first] == [item.request_id for item in second]
    for item in first:
        payload = (journal / item.request_id / "receipt.json").read_bytes()
        assert payload == (journal / item.request_id / "receipt.json").read_bytes()
    assert lock_path.exists()


def test_fsync_directory_and_write_dataclass_once_without_monkeypatch(tmp_path: Path) -> None:
    """Product path must run on both platforms without replacing ``_fsync_directory``."""
    ref._fsync_directory(tmp_path)
    _spec, intent = _simple_intent()
    target = tmp_path / "intent.json"
    ref._write_dataclass_once(target, intent)
    assert target.is_file()
    expected = ref._canonical_json(asdict(intent)).encode("utf-8")
    assert target.read_bytes() == expected
    assert ref._strict_json(target.read_bytes())["request_id"] == intent.request_id
    leftovers = list(tmp_path.glob(".intent.json.*.tmp"))
    assert leftovers == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX directory fsync contract")
def test_linux_fsync_directory_invokes_open_fsync_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    real_open, real_fsync, real_close = os.open, os.fsync, os.close

    def spy_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        calls.append(("open", path, flags))
        return real_open(path, flags, *args, **kwargs)

    def spy_fsync(fd: int) -> None:
        calls.append(("fsync", fd))
        real_fsync(fd)

    def spy_close(fd: int) -> None:
        calls.append(("close", fd))
        real_close(fd)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "close", spy_close)
    ref._fsync_directory(tmp_path)
    kinds = [item[0] for item in calls]
    assert kinds == ["open", "fsync", "close"]
    assert calls[0][2] == os.O_RDONLY


def test_write_dataclass_once_file_fsync_failure_leaves_no_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spec, intent = _simple_intent()
    target = tmp_path / "intent.json"

    def boom_fsync(fd: int) -> None:
        raise OSError(5, "injected file fsync failure")

    monkeypatch.setattr(os, "fsync", boom_fsync)
    with pytest.raises(M3ReferenceError) as caught:
        ref._write_dataclass_once(target, intent)
    assert caught.value.code == "G1_REFERENCE_IO_FAILED"
    assert not target.exists()
    assert list(tmp_path.glob(".intent.json.*.tmp")) == []


def test_write_dataclass_once_link_file_exists_is_journal_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spec, intent = _simple_intent()
    target = tmp_path / "intent.json"
    target.write_bytes(b"preexisting")
    with pytest.raises(M3ReferenceError) as caught:
        ref._write_dataclass_once(target, intent)
    assert caught.value.code == "G1_REFERENCE_JOURNAL_INVALID"
    assert target.read_bytes() == b"preexisting"
    assert list(tmp_path.glob(".intent.json.*.tmp")) == []


def test_write_dataclass_once_link_oserror_is_io_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spec, intent = _simple_intent()
    target = tmp_path / "intent.json"

    def boom_link(src: str | bytes, dst: str | bytes) -> None:
        raise OSError(1, "injected link failure")

    monkeypatch.setattr(os, "link", boom_link)
    with pytest.raises(M3ReferenceError) as caught:
        ref._write_dataclass_once(target, intent)
    assert caught.value.code == "G1_REFERENCE_IO_FAILED"
    assert not target.exists()
    assert list(tmp_path.glob(".intent.json.*.tmp")) == []


def test_write_dataclass_once_dir_fsync_fail_after_link_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Complete hardlinked target retained after directory persist confirmation failure."""
    spec, intent = _simple_intent()
    target = tmp_path / "intent.json"
    expected = ref._canonical_json(asdict(intent)).encode("utf-8")

    def boom_dir(_directory: Path) -> None:
        raise OSError(5, "injected directory fsync failure")

    monkeypatch.setattr(ref, "_fsync_directory", boom_dir)
    with pytest.raises(M3ReferenceError) as caught:
        ref._write_dataclass_once(target, intent)
    assert caught.value.code == "G1_REFERENCE_IO_FAILED"
    assert target.is_file()
    assert target.read_bytes() == expected
    assert list(tmp_path.glob(".intent.json.*.tmp")) == []

    # Same-spec retry recovers via existing intent verification (not re-publish).
    ref._ensure_intent(target, spec)

    other_spec, _other = _simple_intent(symbol="000002.SZ")
    with pytest.raises(M3ReferenceError) as mismatch:
        ref._ensure_intent(target, other_spec)
    assert mismatch.value.code == "G1_REFERENCE_JOURNAL_INVALID"

    target.write_bytes(b'{"schema_version":"corrupt"}')
    with pytest.raises(M3ReferenceError) as corrupt:
        ref._ensure_intent(target, spec)
    assert corrupt.value.code == "G1_REFERENCE_JOURNAL_INVALID"


def test_executor_active_flock_and_sigkill_recovery(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    import subprocess
    import sys
    import textwrap
    import time

    from quant.data._journal_lock import hold_journal_writer_lock

    journal = (tmp_path / "journal").resolve()
    journal.mkdir()
    with hold_journal_writer_lock(journal_root=journal):
        client = _JournalFakeClient()
        with pytest.raises(M3ReferenceError) as held:
            execute_baostock_reference_plan(
                sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
                raw_store=RawStore(tmp_path / "raw"), journal_root=journal,
            )
        assert held.value.code == "G1_REFERENCE_JOURNAL_INVALID"
        assert client.calls == []

    ready = tmp_path / "ready"
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2] / "src")!r})
        from quant.data._journal_lock import hold_journal_writer_lock
        with hold_journal_writer_lock(journal_root=Path({str(journal)!r})):
            Path({str(ready)!r}).write_text("1", encoding="utf-8")
            time.sleep(60)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script])
    try:
        # Windows cold import of quant.lock stack often exceeds 2s; match journal_lock budget.
        for _ in range(1000):
            if ready.exists():
                break
            time.sleep(0.01)
        assert ready.exists(), (
            f"holder subprocess did not signal ready; poll={child.poll()}"
        )
        blocked = _JournalFakeClient()
        with pytest.raises(M3ReferenceError) as active:
            execute_baostock_reference_plan(
                sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(blocked),
                raw_store=RawStore(tmp_path / "raw2"), journal_root=journal,
            )
        assert active.value.code == "G1_REFERENCE_JOURNAL_INVALID"
        assert blocked.calls == []
        child.kill()
        child.wait(timeout=5)
        receipts = execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan,
            connector=BaostockConnector(_JournalFakeClient()),
            raw_store=RawStore(tmp_path / "raw3"), journal_root=journal,
        )
        assert len(receipts) == 30
        assert (journal / ".writer.lock").exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_executor_rejects_forged_plan_with_same_sample_hash_zero_io(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    """Sample-hash-only equality must not bypass full-plan closure comparison."""
    specs = list(request_plan.requests)
    idx_a, idx_b = 0, 1
    for i in range(len(specs)):
        for j in range(i + 1, len(specs)):
            if dict(specs[i].parameters) != dict(specs[j].parameters):
                idx_a, idx_b = i, j
                break
        else:
            continue
        break
    params_a, params_b = dict(specs[idx_a].parameters), dict(specs[idx_b].parameters)
    assert params_a != params_b
    swapped_a = ReferenceRequestSpec(
        specs[idx_a].schema_version,
        ref._request_id(symbol=specs[idx_a].symbol, parameters=tuple(sorted(params_b.items()))),
        specs[idx_a].endpoint, specs[idx_a].symbol, tuple(sorted(params_b.items())),
    )
    swapped_b = ReferenceRequestSpec(
        specs[idx_b].schema_version,
        ref._request_id(symbol=specs[idx_b].symbol, parameters=tuple(sorted(params_a.items()))),
        specs[idx_b].endpoint, specs[idx_b].symbol, tuple(sorted(params_a.items())),
    )
    untouched = [spec for k, spec in enumerate(specs) if k not in {idx_a, idx_b}]
    new_specs = tuple(sorted([swapped_a, swapped_b, *untouched], key=lambda item: item.request_id))
    forged_hash = ref._request_plan_sha256(
        sample_plan_sha256=request_plan.sample_plan_sha256, requests=new_specs
    )
    forged_plan = ReferenceRequestPlanV1(
        request_plan.schema_version, request_plan.sample_plan_sha256, new_specs, forged_hash,
    )
    assert forged_plan.requests != request_plan.requests

    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    client = _JournalFakeClient()
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=forged_plan, connector=BaostockConnector(client),
            raw_store=RawStore(raw_root), journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_PLAN_INVALID"
    assert client.calls == []
    assert not journal_root.exists()
    assert not raw_root.exists()


def test_executor_rejects_request_plan_from_different_sample_plan_zero_io(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, tmp_path: Path,
) -> None:
    keep = sorted(happy_candidate.instruments.get_column("symbol").to_list())[-30:]
    other_candidate = _restrict_bar_symbols(happy_candidate, keep)
    other_sample_plan = plan_cross_source_reconciliation(candidate=other_candidate, policy=_policy())
    other_request_plan = plan_baostock_reference_requests(sample_plan=other_sample_plan)
    assert other_sample_plan.sample_plan_sha256 != sample_plan.sample_plan_sha256

    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    client = _JournalFakeClient()
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=other_request_plan, connector=BaostockConnector(client),
            raw_store=RawStore(raw_root), journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_PLAN_INVALID"
    assert client.calls == []
    assert not journal_root.exists()


def test_executor_plan_wide_preflight_conflict_blocks_all_requests_before_any_io(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    target = request_plan.requests[-1]
    conflict_dir = journal_root / target.request_id
    conflict_dir.mkdir(parents=True)
    (conflict_dir / "unexpected.txt").write_text("x", encoding="utf-8")

    client = _JournalFakeClient()
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
            raw_store=RawStore(tmp_path / "raw"), journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_JOURNAL_INVALID"
    assert client.calls == []
    for spec in request_plan.requests:
        if spec.request_id == target.request_id:
            continue
        assert not (journal_root / spec.request_id / "intent.json").exists()
    assert not (tmp_path / "raw").exists()


@pytest.mark.parametrize(
    "layout",
    ["request_is_file", "request_symlink", "unknown_file_symlink", "unknown_directory", "fifo"],
)
def test_executor_journal_layout_is_strictly_checked_before_network(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path, layout: str,
) -> None:
    journal_root = tmp_path / "journal"
    journal_root.mkdir(parents=True)
    target = request_plan.requests[0]
    request_dir = journal_root / target.request_id
    outside = tmp_path / "outside"
    if layout == "request_is_file":
        request_dir.write_text("not-a-dir", encoding="utf-8")
    elif layout == "request_symlink":
        outside.mkdir()
        _require_symlink(request_dir, outside, target_is_directory=True)
    else:
        request_dir.mkdir()
        entry = request_dir / "extra"
        if layout == "unknown_file_symlink":
            outside.write_text("x", encoding="utf-8")
            _require_symlink(entry, outside)
        elif layout == "unknown_directory":
            entry.mkdir()
        else:
            _require_fifo(entry)

    client = _JournalFakeClient()
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
            raw_store=RawStore(tmp_path / "raw"), journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_JOURNAL_INVALID"
    assert client.calls == []


def test_executor_journal_state_machine_full_lifecycle(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"

    first_client = _JournalFakeClient()
    first_receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(first_client),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    assert len(first_receipts) == 30
    assert len(first_client.calls) == 30

    # Full receipt replay: zero network for every request.
    replay_receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_ExplodingClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    assert replay_receipts == first_receipts

    # Candidate recovery: delete only receipts, keep intent+candidate+raw.
    for spec in request_plan.requests:
        (journal_root / spec.request_id / "receipt.json").unlink()
    recover_receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_ExplodingClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    assert recover_receipts == first_receipts
    for spec in request_plan.requests:
        assert (journal_root / spec.request_id / "receipt.json").exists()

    # Network failure mid-plan keeps earlier commits and the failing intent,
    # and a later retry resumes only the unfinished requests.
    fresh_journal = tmp_path / "journal2"
    fresh_raw = tmp_path / "raw2"
    failing_target = request_plan.requests[5]
    failing_client = _JournalFakeClient()
    failing_client.fail_codes = {ref._symbol_to_baostock_code(failing_target.symbol)}
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(failing_client),
            raw_store=RawStore(fresh_raw), journal_root=fresh_journal,
        )
    assert excinfo.value.code == "G1_REFERENCE_NETWORK_FAILED"
    for spec in request_plan.requests[:5]:
        assert (fresh_journal / spec.request_id / "receipt.json").exists()
    failed_dir = fresh_journal / failing_target.request_id
    assert (failed_dir / "intent.json").exists()
    assert not (failed_dir / "candidate.json").exists()
    assert not (failed_dir / "receipt.json").exists()
    for spec in request_plan.requests[6:]:
        assert not (fresh_journal / spec.request_id).exists()

    retry_client = _JournalFakeClient()
    retry_receipts = execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(retry_client),
        raw_store=RawStore(fresh_raw), journal_root=fresh_journal,
    )
    assert len(retry_receipts) == 30
    assert len(retry_client.calls) == 25


def test_executor_detects_candidate_raw_and_receipt_drift(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    target = request_plan.requests[0]
    receipt_path = journal_root / target.request_id / "receipt.json"

    original = receipt_path.read_bytes()
    payload = json.loads(original)
    payload["row_count"] = payload["row_count"] + 1
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(M3ReferenceError):
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan,
            connector=BaostockConnector(_ExplodingClient()),
            raw_store=RawStore(raw_root), journal_root=journal_root,
        )
    receipt_path.write_bytes(original)

    data_path, _metadata_path = RawStore(raw_root).request_paths(
        source="baostock", table="query_history_k_data_plus", request_id=target.request_id,
    )
    original_raw = data_path.read_bytes()
    data_path.write_bytes(b"corrupted-bytes")
    with pytest.raises(M3ReferenceError):
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan,
            connector=BaostockConnector(_ExplodingClient()),
            raw_store=RawStore(raw_root), journal_root=journal_root,
        )
    data_path.write_bytes(original_raw)


def test_no_replace_or_rename_used_in_reference_module() -> None:
    source = Path(ref.__file__).read_text(encoding="utf-8")
    assert "os.replace(" not in source
    assert "os.rename(" not in source


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":"x","schema_version":"y"}',
        b"\xff\xfe",
        b'{"row_count":"1"}',
        b'{"unknown":1}',
        b'{"row_count":NaN}',
    ],
)
def test_verify_reference_receipt_rejects_strict_json_violations(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
    payload: bytes,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    target = request_plan.requests[0]
    receipt_path = journal_root / target.request_id / "receipt.json"
    receipt_path.write_bytes(payload)
    with pytest.raises(M3ReferenceError) as excinfo:
        verify_reference_receipt(
            spec=target, receipt_path=receipt_path, raw_root=raw_root, journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_RECEIPT_INVALID"


def test_verify_reference_receipt_rejects_absolute_or_escaping_raw_path(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    target = request_plan.requests[0]
    receipt_path = journal_root / target.request_id / "receipt.json"
    original = receipt_path.read_bytes()
    payload = json.loads(original)
    for bad_path in ("/etc/passwd", "../escape/data.parquet", "a\\b\\data.parquet"):
        payload["raw_data_path"] = bad_path
        receipt_path.write_bytes(json.dumps(payload).encode("utf-8"))
        with pytest.raises(M3ReferenceError) as excinfo:
            verify_reference_receipt(
                spec=target, receipt_path=receipt_path, raw_root=raw_root, journal_root=journal_root,
            )
        assert excinfo.value.code == "G1_REFERENCE_RECEIPT_INVALID"
    receipt_path.write_bytes(original)


def test_verify_reference_receipt_rejects_raw_content_drift(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    raw_root = tmp_path / "raw"
    execute_baostock_reference_plan(
        sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(_JournalFakeClient()),
        raw_store=RawStore(raw_root), journal_root=journal_root,
    )
    target = request_plan.requests[0]
    data_path, _metadata_path = RawStore(raw_root).request_paths(
        source="baostock", table="query_history_k_data_plus", request_id=target.request_id,
    )
    original = data_path.read_bytes()
    frame = pl.read_parquet(data_path)
    tampered = frame.with_columns(pl.lit("999.0").alias("close"))
    buffer = io.BytesIO()
    tampered.write_parquet(buffer)
    data_path.write_bytes(buffer.getvalue())
    with pytest.raises(M3ReferenceError) as excinfo:
        verify_reference_receipt(
            spec=target,
            receipt_path=journal_root / target.request_id / "receipt.json",
            raw_root=raw_root, journal_root=journal_root,
        )
    assert excinfo.value.code == "G1_REFERENCE_RECEIPT_INVALID"
    data_path.write_bytes(original)


def test_validate_reference_frame_row_limit_boundaries() -> None:
    empty = pl.DataFrame(schema={c: pl.Utf8 for c in ref._FIELD_COLUMNS})
    ref._validate_reference_frame(empty)
    at_limit_minus_one = pl.DataFrame({c: ["x"] * 5999 for c in ref._FIELD_COLUMNS})
    ref._validate_reference_frame(at_limit_minus_one)
    at_limit = pl.DataFrame({c: ["x"] * 6000 for c in ref._FIELD_COLUMNS})
    with pytest.raises(M3ReferenceError) as excinfo:
        ref._validate_reference_frame(at_limit)
    assert excinfo.value.code == "G1_REFERENCE_RESPONSE_INVALID"


def test_executor_rejects_response_at_row_limit(
    sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1, tmp_path: Path,
) -> None:
    client = _JournalFakeClient(row_count=6000)
    with pytest.raises(M3ReferenceError) as excinfo:
        execute_baostock_reference_plan(
            sample_plan=sample_plan, plan=request_plan, connector=BaostockConnector(client),
            raw_store=RawStore(tmp_path / "raw"), journal_root=tmp_path / "journal",
        )
    assert excinfo.value.code == "G1_REFERENCE_RESPONSE_INVALID"


def test_reconcile_cross_source_happy_path_full_closure(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    assert bundle.passed is True
    assert bundle.issues == ()
    assert bundle.detail.height == 3000
    assert bundle.summary.missing_primary_rows == 0
    assert bundle.summary.missing_reference_rows == 0
    assert bundle.summary.mismatch_cells == 0
    assert bundle.summary.mismatch_rate == 0.0
    assert len(bundle.reference_receipts) == 30
    assert bundle.summary.sample_symbol_count == 30
    assert bundle.summary.dates_per_symbol == 20
    assert bundle.summary.key_count == 600
    assert bundle.summary.field_count == 5
    assert bundle.summary.comparison_count == 3000
    for stats in bundle.summary.field_stats:
        assert stats.mismatch_count == 0
        assert stats.max_abs_diff == 0.0


def test_reconcile_ignores_extra_reference_dates_within_range(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    bar_days_by_symbol: dict[str, set[dt.date]] = {}
    for row in happy_candidate.bars.iter_rows(named=True):
        bar_days_by_symbol.setdefault(row["symbol"], set()).add(row["trade_date"])
    target_spec, extra_day = None, None
    for spec in request_plan.requests:
        params = dict(spec.parameters)
        start = dt.date.fromisoformat(params["start_date"])
        end = dt.date.fromisoformat(params["end_date"])
        sampled = set(by_symbol[spec.symbol])
        candidates = sorted(
            day for day in bar_days_by_symbol[spec.symbol] if start <= day <= end and day not in sampled
        )
        if candidates:
            target_spec, extra_day = spec, candidates[0]
            break
    assert target_spec is not None and extra_day is not None

    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    rows = _reference_rows_for_symbol(
        happy_candidate, target_spec.symbol, by_symbol[target_spec.symbol] + [extra_day]
    )
    index = next(i for i, s in enumerate(request_plan.requests) if s.request_id == target_spec.request_id)
    responses[index] = _make_verified_reference(target_spec, _reference_frame(rows))

    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
        policy=_policy(),
    )
    assert bundle.passed is True
    assert bundle.detail.height == 3000


def test_reconcile_missing_reference_row_produces_incomplete_only(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    target_spec = request_plan.requests[0]
    remaining_days = by_symbol[target_spec.symbol][1:]
    rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, remaining_days)
    responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))

    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
        policy=_policy(max_mismatch_rate=0.01),
    )
    assert bundle.passed is False
    assert {issue.code for issue in bundle.issues} == {"CROSS_SOURCE_INCOMPLETE"}
    assert bundle.summary.missing_reference_rows == 1
    assert bundle.summary.mismatch_cells == 5
    assert bundle.summary.mismatch_rate == pytest.approx(5 / 3000)
    assert bundle.detail.height == 3000


@pytest.mark.slow
def test_reference_fixed_candidate_matches_fresh_full_builder(happy_inputs, happy_candidate):
    from quant.data.m3_g1_candidate import _TABLE_ATTRS, build_g1_candidate

    fresh = build_g1_candidate(inputs=happy_inputs)
    assert fresh.primary_candidate_key == happy_candidate.primary_candidate_key
    assert fresh.table_content_digests == happy_candidate.table_content_digests
    assert fresh.input_receipts == happy_candidate.input_receipts
    for attr in _TABLE_ATTRS.values():
        assert getattr(fresh, attr).equals(getattr(happy_candidate, attr))
