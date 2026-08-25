# M2-EVAL-R16 PIT 冗余日期覆盖对称闭包独立初验报告

## Verdicts

- Initial review: `REVIEW_FAIL`.
- R4 rework re-review: `REVIEW_PASS` (static-only; no runtime/Gate result claimed).

## Review boundary

- Reviewer role: same unique independent static reviewer as the initial review; implementation agent `01a03736-31f9-75f0-a798-7ee59df1fc82` was not reused.
- Worktree: `artifacts/dev_worktrees/m2-eval-r16-pit-redundancy-coverage`.
- Reviewed only the requested implementation, unit-test, task/ delivery record, and roadmap hunk.
- Per the frozen `STATIC_ONLY` boundary, no Python, pytest, Ruff, mypy, import, data I/O, network, or commit was run. The findings below are static findings, not runtime claims.

## Contract mapping

The two-sided aggregation itself is correctly shaped: lines 711-726 of `src/quant/research/run_pit_quality_factors.py` project both `factor_a` and `factor_b` into one incident stream and aggregate strict Boolean values with `.all()`. Lines 727-736 use a left join with `validate="1:1"`, `maintain_order="left"`, and `fill_null(False)`, so the static path preserves summary rows/order, does not add absent references, and rejects a factor with no incident. The tests at lines 519-611 exercise factor-b incidents, reversed pairs, duplicate/reverse-duplicate rows, absent references, no incidents, and one-false aggregation.

The strict coverage input check is also present at lines 700-709: both endpoints must be `pl.String` and non-null, and `signal_date_coverage_passed` must be non-null `pl.Boolean`. The output-column collision guard is present at line 687, and duplicate summary factors are rejected at lines 693-699. The status transition at lines 738-745 preserves an existing `REJECTED` and only changes an exact `RESEARCH_ONLY` value when the aggregate is false.

These parts align with the frozen contract in the task record at lines 22-26 and the roadmap hunk at lines 250-254. They do not cure the two failures below.

## Initial findings (addressed in R4 rework)

### F1 — `research_status` has no frozen-domain validation and invalid values survive

Evidence: `src/quant/research/run_pit_quality_factors.py:683-709` validates the presence of `research_status` only indirectly through the required-column check; it never validates the column dtype, nullability, or allowed values. At `:738-745`, every value other than the exact string `RESEARCH_ONLY` takes `otherwise(pl.col("research_status"))`, including an unexpected value or null.

Adversarial cases not used by the implementation tests (`tests/unit/test_run_pit_quality_factors.py:503-515` constructs only the two expected status strings):

```python
summary = pl.DataFrame(
    {"factor": ["candidate"], "research_status": ["PAUSED"]},
    schema={"factor": pl.String, "research_status": pl.String},
)
redundancy = _redundancy_coverage_rows((("candidate", "control", False),))
```

The condition at `:740-741` is false, so the `PAUSED` value is preserved instead of being rejected or downgraded. The analogous `research_status=[None]` case also has no explicit fail-closed branch and can remain null through `otherwise(pl.col("research_status"))`. A string-valued `pl.Categorical`/`pl.Enum` status column is likewise not rejected before the comparison and branch coercion; the gate delegates the frozen status-domain decision to Polars rather than enforcing it.

This violates the frozen status domain implied by the task contract (`RESEARCH_ONLY` and `REJECTED` only) and the requirement that malformed input fail closed. It also makes output status behavior dependent on implicit Polars coercion for non-string status columns.

Required minimal rework: before the join, explicitly require `research_status` to be a non-null `pl.String` column whose values are exactly `RESEARCH_ONLY` or `REJECTED`; raise the existing gate `ValueError` for any other dtype/value. Add adversarial tests for unexpected string, null, and non-string/categorical status values, plus an existing `REJECTED` row with an all-true incident to prove it never upgrades.

### F2 — Empty-string pair endpoints are accepted as incidents

Evidence: `src/quant/research/run_pit_quality_factors.py:700-706` checks only endpoint dtype and null count. It does not reject `""` (or otherwise validate that an endpoint is a non-empty factor identifier) before the symmetric projection at `:711-726`.

Minimal reproduction to add to the rework tests:

```python
summary = _redundancy_factor_summary(("candidate",))
redundancy = _redundancy_coverage_rows((("", "candidate", True),))
```

The left join at `:727-736` can match the valid `candidate` summary row, ignore the empty endpoint as an absent reference, and return a passing candidate row. That is different from the explicitly allowed non-empty absent reference case tested at `:568-578`: an empty endpoint is malformed input, so the task record's fail-closed requirement at lines 22-25 is not met. The same gap exists when the empty string is in `factor_b`, or when the summary itself contains an empty factor.

Required minimal rework: reject empty-string `factor_a` and `factor_b` values (and empty summary factor identifiers if they are presented to this gate) before projection, with focused tests for both endpoint positions. Do not reject ordinary non-empty references merely because they are absent from summary; those must continue to add no output row.

## Test adequacy and non-findings

- The current tests cover the principal symmetric aggregation mechanics and strict Boolean/null coverage inputs (`:519-657`), but do not cover F1, F2, the existing output-column collision guard at implementation line 687, preservation of arbitrary numeric/diagnostic columns, or an existing `REJECTED` with a passing incident.
- Static inspection finds no row-expansion defect for duplicate/reverse pairs: grouping by the projected factor produces one gate row per factor and the left `1:1` join prevents reference rows from being emitted.
- Static inspection finds no numeric/economic formula change in this hunk; the only intended data addition is the redundancy coverage result column and the intended status downgrade.

## Initial disposition (superseded by R4 rework re-review)

Do not mark the R16 independent initial review passed until F1 and F2 are minimally repaired and independently re-reviewed. No test or Gate result is claimed here.

`REVIEW_FAIL`

## R4 rework re-review — final

### F1 closure: frozen `research_status` domain

Resolved. `src/quant/research/run_pit_quality_factors.py:693-709` now checks the status column before any join or status expression: it must be exact `pl.String`, have no nulls, and have no values outside `{"RESEARCH_ONLY", "REJECTED"}`. This rejects unexpected strings, nulls, integer/non-string columns, and string-valued `pl.Categorical`/`pl.Enum` columns without delegating the decision to Polars coercion. The transition at `:754-762` still changes only exact `RESEARCH_ONLY` when aggregate coverage is false; an existing `REJECTED` remains `REJECTED` even when its aggregate is true.

The rework tests isolate all requested status cases at `tests/unit/test_run_pit_quality_factors.py:676-719` (`HOLD`, null, integer, categorical, and enum), and the symmetric test supplies `already_rejected` with a true incident at `:529-552`.

### F2 closure: identifier type/null/empty contract

Resolved. `src/quant/research/run_pit_quality_factors.py:693-702` requires `summary.factor` to be exact `pl.String`, non-null, unique, and non-empty. `:710-722` applies exact `pl.String`, non-null, and non-empty checks to both `factor_a` and `factor_b`. Thus an empty identifier at any of the three positions fails before projection, while the ordinary non-empty absent reference remains allowed by the left join; the latter is isolated at `tests/unit/test_run_pit_quality_factors.py:569-579`.

The three empty-identifier positions are independently parameterized at `tests/unit/test_run_pit_quality_factors.py:722-748`, covering empty summary factor, empty `factor_a`, and empty `factor_b`.

### Original-contract verification

- Symmetric all-incident aggregation: `:727-742` concatenates both endpoint projections and groups all incident coverage values by factor. The tests cover a factor incident only through `factor_b`, reversed pairs, duplicate/reverse-duplicate pairs, and a false incident at `:519-612`.
- Strict Boolean true-only coverage: `:723-725` requires exact non-null `pl.Boolean`; `.all()` at `:740-742` means every collected incident must be true. Null, integer, and missing coverage cases remain covered at `:615-657`.
- No incident fail-closed: an empty, correctly typed redundancy table produces no grouped factor; the left join fills its gate value with false at `:743-753`, and the test asserts `REJECTED` at `:582-590`.
- Duplicate/reverse duplicate and absent references: grouping yields one gate row per factor, while the left `1:1` join emits only summary rows. The tests assert no extra rows and all-incident behavior at `:593-612` and absent-reference preservation at `:569-579`.
- Input order and row set: `maintain_order="left"` is explicit at `:743-748`; the test asserts the deliberately non-sorted summary order and equivalent swapped/reversed input at `:519-566`.
- Unrelated diagnostic columns and output collision: the join/`with_columns` path changes only the intended gate/status fields, and the guard at `:683-689` rejects a pre-existing `redundancy_signal_coverage_passed`. Focused regression evidence is at `:751-773`.
- No implicit type coercion or numeric/economic drift is introduced in this hunk: all four identity/status columns and the coverage column are checked before concatenation/join, join keys are both exact `pl.String`, and the diagnostic-column test confirms the unrelated numeric value is retained.

The rework record documents the same closure contract at `docs/research/agent/M2_EVAL_R16_PIT冗余日期覆盖对称闭包任务与交付记录.md:41-55`; the roadmap remains within `STATIC_DONE`/`STATIC_ONLY` and does not claim runtime or Gate completion at `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md:250-254`.

### Verification boundary and final verdict

This is a static re-review only. No Python, pytest, Ruff, mypy, cold import, data I/O, network, or commit was run or claimed. The implementation and focused tests now satisfy F1, F2, and the frozen R16 contract on static evidence.

`REVIEW_PASS`
