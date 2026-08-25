# M2-EVAL-R17 classic 冗余对称闭包独立初验报告

## Review identity and boundary

- task id: `M2-EVAL-R17-CLASSIC-REDUNDANCY-SYMMETRY`
- reviewer: same independent reviewer as the initial `REVIEW_FAIL`; implementation agent `01a03778-d6d5-7ae2-84de-fd53c8abd922` was not reused
- exact base: `a063f56651ab3af6380a4c07a5ea3bf38fcffb8c`
- worktree: `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-eval-r17-classic-redundancy-symmetry`
- reviewed inputs: the frozen taskbook, delivery report, roadmap hunk, production/test diff, and adjacent unchanged evaluator logic
- evidence boundary: static diff and source inspection only. No Python, pytest, Ruff, mypy, import, real run, network, data I/O, process/resource inspection, or commit was performed.
- the only review write is this report. `docs/CODEX_HANDOFF.md` was not present in this worktree.

The worktree HEAD remains the requested exact base. The rework diff still contains the manager-owned roadmap plus the implementation source, tests, taskbook, and delivery report; this re-review modifies only this existing review report.

## Initial exact-base diff contract mapping (pre-rework)

1. **Symmetric aggregation and maximum incident.**

   The added helper in `src/quant/research/run_classic_factors.py:124-211` (exact-base diff hunk `@@ -120,6 +121,96 @@`) iterates both `factor_a` and `factor_b` at lines `192-196` and stores the maximum correlation per summary factor. The added test at `tests/unit/test_run_classic_factors.py:63-96` covers a candidate appearing on either endpoint and a reordered/reversed input. Static evidence supports this contract for valid distinct pairs.

2. **Candidate-candidate two-sided constraint and reference-only row set.**

   `run_classic_factors.py:169-169, 192-196, 198-210` derives the candidate set from summary, updates both endpoints, and constructs output only from `summary_factors`. The tests at `:98-151` cover absent reference/control endpoints and no-incident candidates; `:283-333` covers one candidate-candidate pair constraining both candidates. This preserves the summary row set and does not add reference rows, subject to the self-pair finding below.

3. **One shared helper at all four classic call sites.**

   The exact-base diff removes the four `group_by("factor_a")` implementations and replaces them with the helper at `run_classic_factors.py:472-474` (generic entry), `:1253` (market-risk), `:1346` (fourth-batch), and `:1780` (fifth-batch). `tests/unit/test_run_classic_factors.py:379-386` statically checks one definition plus four calls and the absence of the old grouping. No new module or `run_*` cross-import is present in the diff. PASS on static evidence.

4. **Strict identifiers/status and correlation value validation.**

   `run_classic_factors.py:150-164` requires exact `pl.String` for `factor`, `research_status`, `factor_a`, and `factor_b`, and rejects null/empty/non-`str` values. `:156-158` restricts status values to `RESEARCH_ONLY` and `REJECTED`; `:166-168` rejects duplicate summary factors. `:175-186` explicitly rejects bool, non-numeric values, and non-finite values. Built-in complex values reach `float(...)` and are rejected by the guarded conversion; arbitrary `object()` values are rejected by the numeric type check; finite `Decimal` is accepted as a finite real, consistent with the taskbook wording. The added tests at `:180-279` cover the implemented null, string, bool, NaN, and infinity branches. No runtime result is claimed, and the tests do not independently exercise Object/Decimal/complex values.

5. **Fail-closed malformed input, no incident, and pair uniqueness.**

   Missing/empty input tables and required fields fail at `run_classic_factors.py:140-148`; invalid identifiers/status fail at `:150-164`; duplicate summary factors fail at `:166-168`; exact and reverse duplicate pairs fail at `:188-191`. A candidate absent from the incident aggregation receives `None` at `:198-203`, which the three admission gates turn into a false redundancy condition at `:1300-1305`, `:1380-1385`, and `:1866-1871`. Tests at `tests/unit/test_run_classic_factors.py:117-177` and `:231-333` provide static evidence for these cases.

   **FAIL for the candidate self-pair edge:** the pair canonicalization at `run_classic_factors.py:188-196` never rejects `factor_a == factor_b`. A single `(candidate, candidate)` row is therefore treated as a valid incident and can satisfy the redundancy gate. The required fail-closed correction is documented below.

6. **Endpoint/input-order invariance and summary ordering.**

   The helper returns rows from the original `summary_factors` sequence at `run_classic_factors.py:198-210`; the generic join explicitly uses `maintain_order="left"` at `:475-480`. The three gate join chains use the same left-order preservation at `:1265-1291`, `:1357-1376`, and `:1824-1857`, while their existing final factor sorting remains at `:1321`, `:1399`, and `:1888`. The test at `tests/unit/test_run_classic_factors.py:63-96` swaps endpoint and row order and asserts the same legal aggregation. PASS for valid distinct pairs.

7. **Downgrade-only status semantics and unchanged threshold/economic gates.**

   The three status expressions at `run_classic_factors.py:1309-1318`, `:1389-1397`, and `:1875-1886` retain `REJECTED` because only an existing `RESEARCH_ONLY` row with every gate true can produce `RESEARCH_ONLY`; all other paths produce `REJECTED`. The generic entry only adds `combination_eligible` at `:481-485` and does not upgrade status. The threshold expression remains the existing strict `<` comparison. The test at `tests/unit/test_run_classic_factors.py:283-374` covers threshold failure, threshold pass, and an already rejected summary. PASS on static evidence.

8. **Scope and non-goals.**

   The production diff is confined to the existing classic runner and its test; no evaluator, factor formula, config, schema, output contract, or new runner/module was changed. The roadmap hunk at `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md:259-263` keeps R17 limited to classic corrective-replay and explicitly avoids claiming a global Gate. The delivery report at `docs/research/deliveries/M2_EVAL_R17_CLASSIC冗余对称闭包交付报告.md:13-25,27-44` records the same scope and the STATIC_ONLY boundary. PASS on static scope evidence.

## Finding F1 — candidate self-pair is accepted instead of rejected

- **Phenomenon:** a redundancy row whose two endpoints are the same summary candidate is accepted as an incident. If its finite correlation is below the configured threshold, the candidate can pass the redundancy condition even though no two-factor redundancy pair exists.
- **Root cause:** `run_classic_factors.py:188-196` canonicalizes with `tuple(sorted((factor_a, factor_b)))` and checks only repeated canonical keys. It does not enforce two distinct endpoints before adding the pair or aggregating both sides. The unchanged producer constructs candidate pairs from distinct ordered-factor indices at `src/quant/research/classic_factor_evaluation.py:318-324`; therefore a self-pair is malformed input at this helper boundary, not a valid evaluator pair.
- **Rule that must be followed:** the frozen taskbook requires unique redundancy pairs and fail-closed rejection of malformed input (`docs/research/tasks/M2_EVAL_R17_CLASSIC冗余对称闭包任务书.md:19-32`), while a candidate-candidate pair must constrain two candidate endpoints (`:22-23`). A self-pair cannot provide that two-sided pair contract and must be rejected before aggregation/join. This is also consistent with the roadmap's pair-gate invariant at `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md:259-263`.
- **Minimal static reproduction (not run):**

  ```python
  summary = pl.DataFrame({
      "factor": ["candidate"],
      "research_status": ["RESEARCH_ONLY"],
  })
  redundancy = pl.DataFrame({
      "factor_a": ["candidate"],
      "factor_b": ["candidate"],
      "median_abs_rank_corr": [0.10],
  })
  _aggregate_redundancy_by_factor(summary, redundancy)
  ```

  Static control-flow inspection of the pre-rework helper showed the row reached `seen_pairs`, was added once, and stored `0.10` for `candidate`; it was not rejected before the rework.
- **Added test required for rework:** add a focused test in `tests/unit/test_run_classic_factors.py` (the review is read-only and did not edit that file) asserting `ValueError` for the single candidate self-pair, before any gate join. The test should use a finite below-threshold value so accidental acceptance cannot be hidden by the threshold.
- **Pass condition:** reject every `factor_a == factor_b` row, including a candidate self-pair, with the same stable fail-closed error path; retain acceptance of ordinary non-empty reference endpoints absent from summary; rerun this independent static review after the original implementation agent adds the regression test and minimal fix.

## Initial review verification limits

The initial delivery report's static claims were checked against the exact-base diff, including the one-helper/four-call-site count and `git diff --check`. No runtime or Gate result was inferred. The initial tests did not cover the self-pair, Object/Decimal/complex values, or malformed `factor_b` endpoint positions independently; the self-pair gap was the reason for the initial failure.

## Initial conclusion (superseded by rework)

Initial result: `REVIEW_FAIL` (superseded by F1 rework)

## Re-review: F1 closure and current exact-base diff

### F1 rework evidence

- The current production diff hunk `@@ -122,0 +124,92 @@` adds the explicit guard at `src/quant/research/run_classic_factors.py:175-176`:
  `factor_a == factor_b` raises the stable `ValueError` before correlation validation, `seen_pairs`, maximum aggregation, or any join.
- The current test diff hunk `@@ -61,0 +63,342 @@` adds `tests/unit/test_run_classic_factors.py:116-129`, using exactly one candidate self-pair and finite `0.10`, below the gate threshold, and asserting `ValueError` with stable fragment `not distinct`, matching the production message.
- Ordinary distinct candidate-reference input remains legal at `tests/unit/test_run_classic_factors.py:97-113`; the symmetric candidate/reference cases remain at `:63-96`.
- Static review therefore closes the original phenomenon/root cause/rule/minimal-reproduction/test/pass-condition finding. No runtime result is claimed.

### Full current taskbook contract re-map

1. **Symmetric maximum aggregation:** `run_classic_factors.py:124-213` is the single helper; `:194-198` collects both endpoints into `maximum_by_factor`, and `:200-212` emits one row per original summary factor with the maximum value. Tests `:63-96` cover factor-a/factor-b placement and endpoint/input reordering. PASS statically.

2. **Candidate-candidate and reference/control row semantics:** `:169` derives the candidate set from summary, `:194-198` updates both distinct endpoints, and `:200-212` constructs output only from `summary_factors`. Tests `:97-113` show no reference/control row is added; `:324-393` shows one candidate-candidate pair constrains both candidates and the existing rejected state remains rejected. PASS statically.

3. **One helper at four call sites:** the exact-base diff replaces the old `factor_a` grouping at `run_classic_factors.py:474-476`, `:1255`, `:1348`, and `:1782`. The static count test at `tests/unit/test_run_classic_factors.py:396-402` asserts one definition plus four calls and no `group_by("factor_a")`; no new module or `run_*` cross-import is in the diff. PASS statically.

4. **Strict dtypes and finite numeric validation:** `run_classic_factors.py:150-164` requires exact `pl.String` and non-null/non-empty Python `str` values for summary factor/status and both endpoints; `:156-158` restricts status to `RESEARCH_ONLY`/`REJECTED`; `:166-168` rejects duplicate summary factors. `:177-188` rejects bool, non-numeric values, complex values whose float projection raises, and non-finite values. Finite `Decimal` is accepted as a finite real; arbitrary `object()` values and strings are rejected. Tests `tests/unit/test_run_classic_factors.py:216-295` cover strict summary/status, missing fields, endpoint, null, bool, string, NaN, and infinity branches. PASS on static evidence; no runtime checks were run.

5. **Fail-closed no-incident and pair validation:** missing/empty inputs fail at `run_classic_factors.py:140-148`; self-pairs fail before aggregation at `:172-176`; exact/reverse duplicates fail at `:190-193`; a candidate without an incident remains `None` at `:200-205`, then fails the redundancy predicates at `:1302-1307`, `:1382-1387`, and `:1868-1873`. Tests `:132-172`, `:174-214`, `:306-322`, and `:116-129` cover no incident, duplicate summary, duplicate/reverse pair, and the reworked self-pair. PASS statically.

6. **Endpoint/input order and summary row/order stability:** the helper preserves the input summary factor sequence at `run_classic_factors.py:200-212`; the generic join uses `maintain_order="left"` at `:477-482`, and the three gates use it throughout their left joins at `:1267-1293`, `:1359-1378`, and `:1826-1859`. Existing final factor ordering remains at `:1323`, `:1401`, and `:1890`. Test `tests/unit/test_run_classic_factors.py:63-96` covers swapped endpoints and reordered input. PASS for legal distinct pairs.

7. **Downgrade-only status and preserved economic gates:** the gate transitions at `run_classic_factors.py:1311-1320`, `:1391-1400`, and `:1877-1888` retain `REJECTED`; only an existing `RESEARCH_ONLY` row with all existing gates true remains `RESEARCH_ONLY`. The generic entry only derives `combination_eligible` at `:483-487` and does not upgrade status. The strict threshold comparison remains unchanged. Test `tests/unit/test_run_classic_factors.py:324-393` covers reject, pass, and already-rejected cases. PASS statically.

8. **Scope and non-goals:** the exact-base diff changes only the existing classic runner/test plus the manager-owned roadmap and task/delivery records; evaluator, factor formulas, config, schema, output contract, other gates, and historical runs are untouched. The roadmap boundary is `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md:259-263`; the rework delivery evidence is `docs/research/deliveries/M2_EVAL_R17_CLASSIC冗余对称闭包交付报告.md:27-72`. No real run, data, network, or global Gate is claimed. PASS statically.

## Mypy typing rework re-review and exact-six scope

### Numeric typing and pair-shape evidence

- The current helper declares `maximum_by_factor` as `dict[str, int | float | Decimal]` at `src/quant/research/run_classic_factors.py:170`, rejects `bool` first at `:177`, then accepts only `int | float | Decimal` at `:179` and casts to that same narrow union at `:181`. This current evidence supersedes the earlier shorthand in contract item 4 above: values outside the requested union, including complex/object/string values, remain fail-closed.
- Finite semantics remain at `:183-188`: the narrow numeric value is converted for the existing `math.isfinite` check, and conversion failures remain invalid. Maximum aggregation still compares numeric values at `:198-200`; the helper still emits the same summary-keyed column and dtype at `:202-213`.
- The canonical pair is explicitly typed and constructed as `pair: tuple[str, str]` at `:189-192`, while the self-pair guard and duplicate/reverse-duplicate rejection remain before aggregation. No threshold, correlation calculation, economic gate, or status-transition expression changed in the exact-base production diff; prior contract item 7 remains satisfied.

### Delivery evidence for this rework

The delivery report's `## Mypy typing rework evidence` records all required fields: phenomenon (three post-P1 mypy errors), root cause (the former `Number | Decimal` and inferred variadic tuple), governing rule (bool-first `int | float | Decimal` and explicit `tuple[str, str]`), minimal mypy reproduction, tests (production-only typing correction; tests not modified), and pass condition (preserve finite/duplicate semantics and become mypy-valid). It explicitly records that mypy and all other prohibited checks were not run; this review makes no runtime or mypy-pass claim.

### Exact-six scope and round-specific isolation

- The taskbook exact-six ownership list remains: taskbook, roadmap, `src/quant/research/run_classic_factors.py`, `tests/unit/test_run_classic_factors.py`, delivery report, and this review report. The existing static scope inventory contains exactly these six paths and no seventh production, test, or documentation path.
- For this numeric-typing rework round, the delivery evidence states that only `src/quant/research/run_classic_factors.py` and the delivery report were modified: tests were not modified, and the manager-owned taskbook/roadmap were not modified. The existing test/roadmap changes in the uncommitted exact-base worktree belong to the already-reviewed R17 rounds; this reviewer writes only the existing review report.

### Full prior contract reaffirmation

1. Symmetric maximum aggregation remains in the one helper, collecting both endpoints and taking the maximum while emitting the original summary row set/order.
2. Candidate-candidate pairs constrain both candidates; reference/control endpoints outside summary do not create rows.
3. The generic entry plus market-risk, fourth-batch, and fifth-batch admission gates still call the same single helper; old `factor_a`-only grouping remains absent.
4. Strict summary/status/endpoint String contracts, null/empty rejection, bool-first narrow numeric validation, and non-finite rejection remain fail-closed.
5. No-incident, self-pair, exact duplicate, reverse duplicate, missing-field, invalid-type, and duplicate-summary cases remain rejected before a misleading admission result.
6. Endpoint order and input row order remain invariant for legal distinct pairs; helper output preserves the summary row set/order and joins retain left order.
7. The generic entry and all three admission gates remain downgrade-only; existing `REJECTED` cannot upgrade, and threshold/economic/other admission semantics are unchanged.
8. Scope remains classic corrective-replay redundancy only, with no evaluator/config/schema/output/history/global-Gate expansion and no runtime/data/network claim.

Static result: PASS for the numeric typing rework and exact-six scope. The full prior contract remains satisfied on static evidence.

## TEST_ONLY_P1 re-review evidence

- The production behavior remains read-only and unchanged from the F1 re-review: `src/quant/research/run_classic_factors.py:175-176` raises `ValueError("classic redundancy pair endpoints are not distinct")` before aggregation. The current self-pair assertion at `tests/unit/test_run_classic_factors.py:128` is now `match="not distinct"`, a stable substring of that existing production message.
- Comparing the current test file with the prior same-review snapshot recorded above isolates the P1 edit to that one `pytest.raises` match fragment: the prior evidence said `match="distinct endpoints"`; the current evidence says `match="not distinct"`. The self-pair fixture, finite below-threshold `0.10` value, exception type, and test body are unchanged.
- No production hunk was added or changed for TEST_ONLY_P1. The current exact-base diff still includes the earlier F1 production/test implementation, so this statement is about the P1 delta, not a claim that the complete uncommitted diff is test-only. No unrelated test change was added in this P1 rework; the other current test changes belong to the already-reviewed R17 implementation/rework.
- The delivery report at `docs/research/deliveries/M2_EVAL_R17_CLASSIC冗余对称闭包交付报告.md:55-66` records all required P1 fields: phenomenon, root cause, rule, minimal reproduction, added test, and pass condition. It explicitly states that the production message was retained, only the focused assertion changed, and forbidden runtime/static-tool checks were not run.
- Static result: PASS for TEST_ONLY_P1. The assertion matches the stable existing message, the F1 fail-closed behavior remains covered, and production plus unrelated tests remain outside this P1 delta.

## Re-review verification limits

This is a STATIC_ONLY / CPU NONE re-review. I did not run Python, pytest, Ruff, mypy, cold import, real run, network, data I/O, or commit. `git diff --check` and the helper/call-site/source-count checks are static evidence only; no runtime or Gate status is inferred.

## Final conclusion

REVIEW_PASS

DELIVERY_READY
Review report: `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-eval-r17-classic-redundancy-symmetry\docs\research\reviews\M2_EVAL_R17_CLASSIC冗余对称闭包独立初验报告.md`
