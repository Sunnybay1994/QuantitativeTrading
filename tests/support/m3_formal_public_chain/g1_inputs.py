"""Pure raw G1 inputs + public publish/verify (no private rename helpers)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tests.unit import test_m3_reference as ref

from quant.data.m3_g1_candidate import build_g1_candidate
from quant.data.m3_reference import (
    plan_baostock_reference_requests,
    plan_cross_source_reconciliation,
)
from quant.data.m3_release import (
    G1ReleaseInputs,
    VerifiedG1Release,
    publish_g1_release,
    verify_g1_release,
)

# train(1)+embargo(10)+val(1)+embargo(10)+test(1)=23 signal days; +10 label tail.
_HISTORY_DAYS_NEEDED = 40
_SIGNAL_END_INDEX = 22


def _execution_compatible_symbols(n: int = 300) -> list[str]:
    """Return the 300-symbol G1 fixture using valid A-share board prefixes."""
    if n != 300:
        raise ValueError("formal public chain requires exactly 300 symbols")
    sz = [f"{index:06d}.SZ" for index in range(1, 151)]
    sh = [f"{600_000 + index:06d}.SH" for index in range(1, 151)]
    return sz + sh


def build_raw_g1_release_inputs() -> G1ReleaseInputs:
    """Reuse unit raw factories with an extended history/signal window for folds/labels."""
    days = ref._weekdays(ref._D0, _HISTORY_DAYS_NEEDED)
    previous = (ref._HISTORY_DAY_COUNT, ref._HISTORY_DAYS, ref._D1, ref._symbols)
    ref._HISTORY_DAY_COUNT = _HISTORY_DAYS_NEEDED
    ref._HISTORY_DAYS = days
    ref._D1 = days[-1]
    ref._symbols = _execution_compatible_symbols
    try:
        happy = replace(ref._build_inputs(), signal_end=days[_SIGNAL_END_INDEX])
    finally:
        ref._HISTORY_DAY_COUNT, ref._HISTORY_DAYS, ref._D1, ref._symbols = previous
    candidate = build_g1_candidate(inputs=happy)
    policy = ref._policy()
    sample = plan_cross_source_reconciliation(candidate=candidate, policy=policy)
    requests = plan_baostock_reference_requests(sample_plan=sample)
    responses = ref._perfect_reference_responses(candidate, sample, requests)
    return G1ReleaseInputs(
        build_inputs=happy,
        cross_source_policy=policy,
        reference_responses=responses,
    )


def publish_mini_formal_g1(*, output_root: Path) -> VerifiedG1Release:
    """Public publish + verify; requires host no-replace capability (Windows m3chain312)."""
    output_root.mkdir(parents=True, exist_ok=True)
    release = publish_g1_release(
        output_root=output_root, inputs=build_raw_g1_release_inputs()
    )
    verified = verify_g1_release(release=release)
    entries = sorted(path.name for path in verified.release.root.iterdir())
    if len(entries) != 18 or (verified.release.root / "receipt.json").exists():
        raise RuntimeError(f"G1 tree contract broken: {entries!r}")
    return verified
