| 项 | 内容 |
|---|---|
| 现象 | mypy 21 错：七个 stage/audit 调用结果为 `object` → 无 `receipt_path`/`receipt`/`report`/`decision` 等；`float(acceptance[...])` 对 `object` 报 `arg-type` |
| 根因 | `SuccessorPublicApiBundle` 将结果 callable 标成 `Callable[..., object]`；容差用裸 `float()`，与 config exact-float/finite 语义不一致 |
| 类型 SSOT | 仅收窄七字段：`formal_backtest_stage`→`FormalBacktestStageResult`；`formal_tracking_stage`→`FormalTrackingStageResult`；`reproducibility_stage`→`FormalReproducibilityResult`；`readiness_stage`/`readiness_verifier`→`VerifiedReadinessEvidenceArtifact`；`acceptance_stage`→`FormalAcceptanceStageResult`；`acceptance_audit`→`AcceptanceDecisionV1`。`TYPE_CHECKING` + quoted concrete types；无 `Any`/`cast`/`type:ignore`/wrapper/duplicate DTO |
| 最小复现 | VALIDATION10 mypy production3 → 21 错全在 `successor_downstream_stage.py`；`float(True)` / 非有限值可越过 |
| 测试 | `test_public_api_bundle_seven_stage_return_annotations_are_canonical`；`test_require_finite_config_float_accepts_exact_finite_rejects_invalid`；`test_formal_backtest_rejects_marker_wrapper_wrong_return_types` |
| 通过条件 | factory `is` 身份/字段序/运行校验/执行不变；非法 float 与错误返回稳定 `SUCCESSOR_GATE_FAILED`/`SUCCESSOR_STAGE_INVALID`；receipt/schema/Gate 顺序未改 |

### 16.3 本轮退出

`DELIVERY_READY`（VALIDATION10_F11_STATIC_ONLY_REWORK）。同一独立 reviewer 只读复验；PASS 后申请**完整 VALIDATION11**（须含 mypy），不继承 VALIDATION10 部分绿或本轮静态改动为整包 PASS。本轮 STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit。

## 17. VALIDATION11 证据与 F12 局部名分离（taskbook §19）

### 17.1 VALIDATION11 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| identity | **PASS** |
| identity stdout SHA-256 | `e153b441b2ea26573f19f362ecfc7459cbebd3f62417d104936fd3cc195962a3` |
| exact unit | **`57 passed`** |
| unit stdout SHA-256 | `950b983df9bc36fc9520e19f5238edde01ddeae0cb49d41d027031cbf0cd252c` |
| exact integration | **`29 passed`** |
| integration stdout SHA-256 | `26493122892adaae25d16d33635b4c2ffae7bbf597cbb13840512f75b13b2059` |
| Ruff | **PASS** |
| Ruff stdout SHA-256 | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` |
| mypy production3 | **STOP**：`successor_downstream_stage.py:214` 1× `assignment` |
| mypy stdout SHA-256 | `4a4108d58e9a7ea26f6d987a91f5ad79b2cb023b04885fcda912936440475fa2` |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c/` |
| stage-summary SHA-256 | `034cd671d26bac97ab1f4e0f6865a0ea3214add9c7f760b2eb63edeaac35ae64` |
| cold / scope | **UNRUN** |

### 17.2 F12 — backtest/tracking 结果局部名

| 项 | 内容 |
|---|---|
| 现象 | mypy：`result = formal_tracking_stage(...)` 与先前 `FormalBacktestStageResult` 赋值冲突 |
| 根因 | F11 收窄后，同一 `try` 共享局部名 `result` 跨不相容返回类型 |
| 修正 | `backtest_result` / `tracking_result`；调用/参数/顺序/`receipt_path`/`receipt`/分支/`SUCCESSOR_STAGE_INVALID` 归一不变；无 `cast`/`Any`/`type:ignore`/union/wrapper/API 变更 |
| 最小复现 | VALIDATION11 mypy → `:214 FormalTrackingStageResult` vs `FormalBacktestStageResult` |
| 通过条件 | 仅标识符分离；行为等价；本轮只改 `successor_downstream_stage.py` + taskbook + delivery |

### 17.3 本轮退出

`DELIVERY_READY`（VALIDATION11_F12_STATIC_ONLY_REWORK）。同一独立 reviewer 只读复验；PASS 后申请**完整 VALIDATION12**（须含 mypy），不继承部分绿或本轮静态改动为整包 PASS。本轮 STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit。

## 18. VALIDATION12 终态与组合证据（taskbook §20）

### 18.1 历史 STOP 保留（不得改写）

| 验证 | 结果（如实） |
|---|---|
| VALIDATION10 | unit **84 PASS**；integration **42 PASS**；Ruff **PASS**；mypy **21 STOP**；cold/scope **UNRUN**（触发 F11） |
| F11 → VALIDATION11 | identity **PASS**；unit **57 PASS**；integration **29 PASS**；Ruff **PASS**；mypy **1 局部名 assignment STOP**（`:214`）；cold/scope **UNRUN**（触发 F12） |
| VALIDATION11 证据根 | `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c/` |
| unit stdout SHA-256 | `950b983df9bc36fc9520e19f5238edde01ddeae0cb49d41d027031cbf0cd252c` |
| integration stdout SHA-256 | `26493122892adaae25d16d33635b4c2ffae7bbf597cbb13840512f75b13b2059` |
| Ruff stdout SHA-256 | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` |
| mypy stdout SHA-256 | `4a4108d58e9a7ea26f6d987a91f5ad79b2cb023b04885fcda912936440475fa2` |
| stage-summary SHA-256 | `034cd671d26bac97ab1f4e0f6865a0ea3214add9c7f760b2eb63edeaac35ae64` |

### 18.2 VALIDATION12 PASS（F12 后；组合口径）

| 项 | 结果 |
|---|---|
| classification | **PASS**（`reused_validation11=unit57_integration29_other_ruff`） |
| identity | **PASS** |
| Ruff（changed source） | **PASS** |
| Ruff stdout SHA-256 | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` |
| mypy production3 | **PASS**（`Success: no issues found in 3 source files`） |
| mypy stdout SHA-256 | `f6af9a428ef63a271aa2234de6ce89a03776a74b2b986ece71bae5015648259c` |
| cold production3 | **PASS** |
| cold stdout SHA-256 | `30fe42e7ddd9409d2ac7944edf21099ba249f5380428435c8633658584029023` |
| exact12 / cached0 / diff / temp / process | **PASS**（`ACTUAL_COUNT=12`，`CACHED_COUNT=0`，`DIFF_CHECK=PASS`） |
| scope stdout SHA-256 | `1f4605b9d564203e5fb3cdf182ea60cbf3fbd86dc76d960919070c3b1408f13f` |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation12-20260826T180000Z-c18d/` |
| stage-summary SHA-256 | `2e0e2038cf3a90ad825f51a59ee8237e5ef057d9d277d5ccfeeb41d89fc06405` |

组合说明：VALIDATION12 复用 VALIDATION11 已绿的 unit57 / integration29（及其他 Ruff 口径），并在 F12 后对变更源重跑 identity、Ruff、mypy production3、cold production3 与 exact12 scope；**不**把 VALIDATION10 mypy21 STOP 或 VALIDATION11 局部名 STOP 改称为 PASS。

### 18.3 终态边界

- 终态：`R2W_WINDOWS_ENGINEERING_VALIDATED` / 可执行 package-owned successor downstream wiring。
- **明确不**表示：actual worker、真实 Qlib、new root、retained、acceptance 或 M3 Gate。

### 18.4 本轮退出（证据更新 only）

`DELIVERY_READY`（EVIDENCE_UPDATE；仅 taskbook + delivery）。production / tests / review 只读；零 Python / check / stage / commit。
