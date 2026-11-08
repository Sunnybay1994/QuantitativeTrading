| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION3 之 Ruff / mypy / cold / scope | **仍为 UNRUN** |
| VALIDATION4 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION4 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 11.6 F6 结论

**F6_REVIEW_PASS**（taskbook §13 test-only authority 缝闭合）。可申请**新的完整 VALIDATION4**；**不**继承 VALIDATION3 / 本轮为整包 PASS。

---

## 12. VALIDATION4_F7_REVIEW（对照 taskbook §14）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F6 同一独立初验者；未参与实现<br>
范围：只读 taskbook §14、delivery §12、exact F7 diff（`tests/integration/test_m3_successor_upstream_stage.py`）；production / 其他 tests / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / stage / commit

### 12.1 写范围核对

| 路径 | F7 轮次 | 结论 |
| --- | --- | --- |
| `tests/integration/test_m3_successor_upstream_stage.py` | 允许 | **命中**：`_install_shared_subprocess_run`；B 段 feature worker ownership；移除 `verify_target_artifact` stub |
| delivery / taskbook §14 | 允许（实现侧已写） | **只读复验** delivery §12 |
| production 三文件 | 冻结 | **通过**：SHA256 与 F4–F6 指纹一致 |
| 其他 tests | 冻结 | **通过** |

### 12.2 VALIDATION4 证据复述（未重跑；只读核对日志）

| 项 | 状态 |
| --- | --- |
| exact unit | **`84 passed`**（`02-unit.stdout.log`） |
| exact integration | **`41 passed / 1 failed`**（`03-integration.stdout.log`；仍失败于同测 Authority B 路径） |
| Ruff / mypy / cold / exact12 scope | **UNRUN**（stage-summary 仅至 integration exit=1） |
| 本轮 F7 复验命令 | **全部 UNRUN** |

证据根：`artifacts/agent_runs/m3-r2w-rebuilt-validation4-20260826T152000Z/`。delivery 如实写 84 / 41p1f / 后续 UNRUN；未把 VALIDATION4 冒充整包 PASS。

### 12.3 F7 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | F6「A 退出后 original exact 恢复」保留 | **通过** | A 末 `_restore` + A 外泄漏 `AssertionError` + bridge pin（L802–819） |
| 2 | B 单独在 `_context` 前安装 exact `_fake_feature_worker` | **通过** | `plan_mp` 内 `_install_shared_subprocess_run(plan_mp, feature_fake)` 后才 `plan_support._context`（L832–840） |
| 3 | dump fake ≠ feature fake；feature ≠ original | **通过** | `assert dump_fake is not feature_fake`；`feature_fake is not original_subprocess_run` |
| 4 | B 前三别名 exact `is` feature fake | **通过** | `_assert_shared_subprocess_run(feature_fake)`（stdlib/provider/provider_validation） |
| 5 | `_context` 后立即恢复 original，再真实 `build_backtest_plan_artifact` | **通过** | `_restore` + 多处 `is original` / `is not feature_fake` 后才 builder（L841–862） |
| 6 | 禁止 patch production builder/verifier（含移除既有 `verify_target` stub） | **通过** | diff 删除 `plan_mp.setattr(...verify_target_artifact...)`；当前文件无 `verify_target` / `plan_module` setattr；builder 为真实 `build_backtest_plan_artifact` |
| 7 | feature/dump fake 不得留到 builder 之后 | **通过** | builder 后与 `plan_mp`/`bridge` 出口均 `_assert_shared_subprocess_run(original)` |

### 12.4 发现分级（F7）

**无 P0/P1。**

### 12.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION4 之 Ruff / mypy / cold / scope | **仍为 UNRUN** |
| VALIDATION5 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION5 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 12.6 F7 结论

**F7_REVIEW_PASS**（taskbook §14 Authority B feature-worker ownership 闭合）。可申请**新的完整 VALIDATION5**；**不**继承 VALIDATION4 / 本轮为整包 PASS。

---

## 13. VALIDATION8_F8_REVIEW（对照 taskbook §15）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F7 同一独立初验者；未参与实现<br>
范围：只读 taskbook §15、delivery §13、exact F8 diff（`tests/unit/test_m3_successor_upstream_stage.py`）；production / 其他 tests / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 13.1 写范围与证据边界

| 项 | 结论 |
| --- | --- |
| 写集 | 仅 unit upstream 测试 + delivery/taskbook（审查只读）；production 三文件 SHA 与 F4–F7 指纹一致 |
| VALIDATION8 | Parser/argv/identity **PASS**；unit exact3 **`82 passed / 2 failed`**（stdout 钉两 builder 节点在 `_context`→feature 即 `M3_FEATURE_ARTIFACT_INVALID`，真实 builder **未进入**） |
| integration / Ruff / mypy / cold / scope | **UNRUN**（stage-summary：`STOP\|STAGE_FAILED:02-unit`） |
| 本轮复验命令 | **全部 UNRUN** |

证据根：`artifacts/agent_runs/m3-r2w-rebuilt-validation8-20260826T065401Z/`。

### 13.2 Feature-worker seam（两 unit 节点）— 实现面通过

`_plan_context_with_feature_worker_seam` 与两 builder 节点静态满足 §15 seam 合同：

| 检查 | 结论 |
| --- | --- |
| `_context` 前安装 exact `_fake_feature_worker` | **通过** |
| 非 provider dump fake；三 alias `is` | **通过**（`_assert_shared_subprocess_run`） |
| 正常/异常 `finally` 恢复 original | **通过** |
| 恢复后才真实 `build_backtest_plan_artifact` | **通过**（builder 前再断言非 feature/dump fake） |
| 未 stub production builder | **通过** |

### 13.3 发现分级

### [P1] 无 §15 依据移除 `verify_target_artifact` 窄 stub — 使 PROJECT-only 正测可预见撞上 legacy root-alias 漂移

**现象：** F8 在补 feature-worker seam 的同时，删除了正测原注释所载之窄 stub：

```text
# Isolate PROJECT alias binding: fixture receipts use "root"; production
# successor path is PROJECT-only. Stub only fresh target verify (not the builder).
monkeypatch.setattr(plan_module, "verify_target_artifact", lambda **_: target)
```

现 `test_build_backtest_plan_artifact_positive_project_only_roots` 在 seam 恢复后，以 `artifact_roots={"PROJECT": project_root}` 直调真实 builder，且**无**任何 `verify_target_artifact` 隔离。

**根因：** 实现者把 F7/§14「禁止 patch builder/**verifier**」与 delivery 表述过宽套用到 §15；§15 明文只禁 **stub production builder**，并要求真实 builder——**未**要求删除该窄 verifier stub，也未授权用「去 stub」替代 seam 修复。

**规则：**

1. taskbook §15：只禁止 stub builder / fake 泄漏 / 放宽 identity；合同目标是 unit 节点获得与 F7 同类的 feature-worker seam。
2. 既有 formal plan 夹具大量对 `verify_target_artifact` 使用 `lambda **_: target`，因 fixture receipt 使用 `alias="root"`，而本测刻意传 PROJECT-only roots——正是为隔离该已知 legacy root-alias 漂移，才能检验「PROJECT-only `artifact_roots`」这一测试目的。
3. `build_backtest_plan_artifact` 入口路径会调用真实 `verify_target_artifact(..., artifact_roots=...)`（`a_share_plan.py`）；去掉窄 stub 后，正测在达到「PROJECT-only roots 语义」前，可静态预见先撞 target 侧 root/PROJECT alias 不匹配，从而偏离本测目的（甚至在 seam 修好后仍可能下一失败）。

**最小复现（静态，未执行）：**

1. 经 `_plan_context_with_feature_worker_seam` 得到 `plan_kwargs` + `common`（fixture 侧 target/receipt 仍为 root alias 世界）。
2. 不安装 `verify_target_artifact` 窄 stub。
3. 调用 `build_backtest_plan_artifact(..., artifact_roots={"PROJECT": project_root}, ...)`。
4. 预期：失败或漂移落在 target fresh-verify / receipt alias 闭合，而非稳定证明 PROJECT-only builder roots 合同。

**新增/恢复测试要求：**

- **恢复**正测上的窄 `verify_target_artifact` stub（保留「只 stub fresh target verify，不 stub builder」注释）。
- **保留** `_plan_context_with_feature_worker_seam` 全部断言（seam 进入、非 dump、三别名、finally 恢复、builder 前无 fake）。
- wrong-alias 负测：若同样依赖 fixture target 闭合，按同一窄 stub 规则处理；不得 stub `build_backtest_plan_artifact` 本身。

**通过条件：** §15 seam 绿路径可达真实 builder；PROJECT-only 正测目的不被 legacy root-alias 漂移淹没；delivery 不再把「移除 verify_target stub」写成 §15 通过条件。

### 无 P0；seam 主修复方向正确

### 13.4 失败项六段式（F8）

| 字段 | 内容 |
| --- | --- |
| 现象 | 正测删除 `verify_target_artifact` 窄 stub；delivery 将其列为 F8「修正」 |
| 根因 | 误用 §14 verifier 禁令 / 过度净化；§15 未要求删除该 stub |
| 规则 | §15 仅禁 stub **builder**；窄 verifier stub 用于隔离 fixture `root` vs PROJECT-only 测试目的 |
| 最小复现 | 见 §13.3 |
| 测试 | 恢复窄 stub + 保留 feature-worker seam helper |
| 通过条件 | 见 §13.3；再交同一 reviewer 只读复验后才可申请 VALIDATION9 |

### 13.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION8 integration / Ruff / mypy / cold / scope | **仍为 UNRUN** |
| VALIDATION9 / 整包 Windows PASS | **未授予**；须 F8 返工复验 PASS 后再申请 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 13.6 F8 结论

**F8_REVIEW_FAIL**（P1：无 §15 依据移除 `verify_target_artifact` 窄 stub，可静态预见 PROJECT-only 正测偏离目的）。实现者最小返工仅限 `tests/unit/test_m3_successor_upstream_stage.py`（+delivery 修正表述）；**不得**改 production。审查者未改实现、未跑 Python。

---

## 14. F8_P1_REVIEW（对照 taskbook §16）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F8 同一独立初验者；未参与实现<br>
范围：只读 taskbook §16、delivery §14、exact unit 返工；production / 其他 tests / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 14.1 写范围与冻结

| 项 | 结论 |
| --- | --- |
| 返工写集 | 仅 `tests/unit/test_m3_successor_upstream_stage.py` + delivery/taskbook（审查只读） |
| production 三文件 | **冻结**：SHA256 与 F4–F8 指纹一致 |
| 其他 tests | **冻结** |

### 14.2 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | positive 仅恢复 `plan_module.verify_target_artifact` 窄 stub | **通过** | L1072–1076：注释恢复；`setattr(..., lambda **_: target)` |
| 2 | stub 返回 context 真实 `target`（非伪造） | **通过** | `target = kwargs["target"]`，`kwargs` 来自 `_plan_context_with_feature_worker_seam` |
| 3 | §15 feature-worker seam 保留 | **通过** | 正测/负测均经 `_plan_context_with_feature_worker_seam`（安装非 dump fake、三别名、`finally` 恢复） |
| 4 | 真实 `build_backtest_plan_artifact` 保留；未 stub builder | **通过** | 正测 L1091+ 直调；builder 前仍断言 subprocess 非 feature/dump fake |
| 5 | wrong-alias **无** verifier stub | **通过** | 全文件仅一处 `verify_target_artifact` setattr（正测）；wrong-alias L1110–1153 无 stub，真实路径拒 `EXTERNAL_QLIB` |
| 6 | delivery §14 / §13.2 表述闭合 | **通过** | §14 六段式齐全；§13.2 已改为**保留**正测窄 stub、wrong-alias 不加 stub |

### 14.3 发现分级

**无 P0/P1。** 前轮 P1 已按 §16 最小面闭合。

### 14.4 六段式（本轮闭合记录）

| 字段 | 内容 |
| --- | --- |
| 现象 | 前轮删除正测窄 stub → F8_REVIEW_FAIL |
| 根因 | 无 §15 授权；偏离 PROJECT-only roots 测试目的 |
| 规则 | §16：仅正测恢复 stub→真实 context target；seam 保留；wrong-alias 不加 stub |
| 最小复现 | 已由前轮 §13.3 给出；本轮静态确认 stub 已回 |
| 测试 | `test_build_backtest_plan_artifact_positive_project_only_roots` 含窄 stub；wrong-alias 无 stub |
| 通过条件 | 本表 §14.2 全通过；可申请完整 VALIDATION9（**不**继承本轮为整包 PASS） |

### 14.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION9 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION9 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 14.6 F8_P1 结论

**F8_P1_REVIEW_PASS**（taskbook §16 窄 verifier stub 最小返工闭合）。可申请**完整 VALIDATION9**；**不**继承本轮 / VALIDATION8 部分结果为整包 PASS。

---

## 15. VALIDATION9_F10_REVIEW（对照 taskbook §17）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F8_P1 同一独立初验者；未参与实现<br>
范围：只读 taskbook §17、delivery §15、exact integration F10 diff；production / unit / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 15.1 写范围与证据边界

| 项 | 结论 |
| --- | --- |
| F10 写集 | 仅 `tests/integration/test_m3_successor_upstream_stage.py`（+delivery/taskbook）；unit/production 审查冻结：production SHA 与 F4–F8 指纹一致 |
| VALIDATION9 | Parser/argv/identity **PASS**；unit **`84 passed`**（stdout SHA=`be6268c9…`）；integration **`41 passed / 1 failed`**（717.01s；stdout SHA=`7c256850…`） |
| 唯一失败 | 已过 Authority-B feature fixture，真实进入 `build_backtest_plan_artifact` → `M3_BACKTEST_PLAN_ARTIFACT_INVALID`（legacy root vs PROJECT） |
| Ruff / mypy / cold / scope | **UNRUN** |
| 本轮复验命令 | **全部 UNRUN** |

证据根：`artifacts/agent_runs/m3-r2w-rebuilt-validation9-20260826T073552Z/`（与 delivery 一致）。

### 15.2 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | feature original 恢复后再装窄 verifier stub | **通过** | L841–846 restore subprocess；L860+ 才 `positive_mp` |
| 2 | 更窄 `positive_mp` 仅 stub `verify_target_artifact`→context 真实 `target` | **通过** | `target = kwargs["target"]`；`lambda **_: target`；`verify_target_artifact(**{}) is target` |
| 3 | 真实 `build_backtest_plan_artifact` 保留；未 stub builder | **通过** | positive 内直调 builder |
| 4 | positive 退出后 identity 恢复为 `real_verify_target` | **通过** | L881 `assert plan_module.verify_target_artifact is real_verify_target` |
| 5 | wrong-alias 在 stub 撤销后真实拒绝 `EXTERNAL_QLIB` | **通过** | L889–903 进入前/后均 `is real_verify_target`；期望 `M3_BACKTEST_PLAN_ARTIFACT_INVALID` |
| 6 | F6/F7 subprocess + feature-worker seam 不漂移 | **通过** | A 捕获/恢复、bridge pin、B 安装 `_fake_feature_worker`、非 dump、三别名、`_context` 后 restore original 均保留 |
| 7 | delivery §15 六段式 + 证据 SHA 闭合 | **通过** | 与只读哈希一致 |

### 15.3 发现分级

**无 P0/P1。**

### 15.4 六段式（本轮闭合记录）

| 字段 | 内容 |
| --- | --- |
| 现象 | V9 integration 41/1：feature seam 已通后 builder 因缺窄 verifier stub 撞 alias |
| 根因 | F7 删除 integration positive 的 `verify_target_artifact` 窄 stub |
| 规则 | §17：更窄 `positive_mp` 生命周期；wrong-alias 无 stub；保留 F6/F7 seam + 真实 builder |
| 最小复现 | 见 delivery §15.2 / V9 stdout |
| 测试 | `test_integration_real_api_positive_probe_and_project_roots` 已补 stub 生命周期断言 |
| 通过条件 | §15.2 全通过；可申请完整 VALIDATION10（**不**继承本轮为整包 PASS） |

### 15.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION10 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION10 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 15.6 F10 结论

**F10_REVIEW_PASS**（taskbook §17 integration positive verifier seam 闭合）。可申请**完整 VALIDATION10**；**不**继承 VALIDATION9 / 本轮部分绿为整包 PASS。

---

## 16. VALIDATION10_F11_REVIEW（对照 taskbook §18）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F10 同一独立初验者；未参与实现<br>
范围：只读 taskbook §18、delivery §16、exact12 内 F11 静态 diff（runtime 七注解 + downstream float helper + unit 三测）；production/tests/taskbook/delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 16.1 写范围、指纹与 VALIDATION10 证据边界

| 项 | 结论 |
| --- | --- |
| exact12 / base | dirty 仅 exact12；HEAD=`1d9b4e09…`；`git diff --check` PASS；cached=0 |
| F11 写集（实现侧） | `successor_runtime.py` 七字段返回注解；`successor_downstream_stage.py` `_require_finite_config_float`；unit：`test_public_api_bundle_seven_stage_return_annotations_are_canonical` / `test_require_finite_config_float_*` / `test_formal_backtest_rejects_marker_wrapper_wrong_return_types` |
| upstream | **冻结未漂**：SHA256=`2adb24f040cf191ea7f28855b8d4b56e35350c69cd455f387aacc0f16be5a51c`（与 F4 指纹一致） |
| runtime / downstream 指纹（F11 后只读） | runtime=`272c42f63612e2ce4e927460c1885e95cdab9c17e3d13f52bd82d9734caf608b`；downstream=`452270df1a30df56d88379e77b3c32e3574bc6f76434ef894ce4ff34bd7d48e6`（相对 F4 变更符合写集） |
| VALIDATION10（未重跑） | Parser/argv/identity **PASS**；unit **`84 passed`**（stdout SHA=`7469e724…`）；integration **`42 passed`**（SHA=`1cda2fd0…`）；Ruff exact9 **PASS**（SHA=`af352a86…`）；mypy production3 **STOP** 21 errors 全在 `successor_downstream_stage.py`（SHA=`e539f47c…`）；cold/scope **UNRUN** |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation10-20260826T080935Z/`；stage-summary SHA=`c4986776…`；与 delivery §16.1 逐项一致 |
| 本轮复验命令 | **全部 UNRUN** |

### 16.2 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 仅七处返回注解收窄为 canonical concrete（TYPE_CHECKING + quoted） | **通过** | `SuccessorPublicApiBundle`：`formal_backtest_stage`→`FormalBacktestStageResult`；`formal_tracking_stage`→`FormalTrackingStageResult`；`reproducibility_stage`→`FormalReproducibilityResult`；`readiness_stage`/`readiness_verifier`→`VerifiedReadinessEvidenceArtifact`；`acceptance_stage`→`FormalAcceptanceStageResult`；`acceptance_audit`→`AcceptanceDecisionV1`。其余 callable 仍 `Callable[..., object]`。类型名仅在 `TYPE_CHECKING` 块 import |
| 2 | 无 Any/cast/type:ignore/wrapper/duplicate DTO（本轮 SSOT 路径） | **通过** | 七字段注解无 Any/`cast`/`type: ignore`；无 wrapper/新 DTO。runtime 既有 `stage_runner_type: type[Any]` 与 terminal 解析 `cast` **非本轮新增、非七字段收窄** |
| 3 | callable `is` 绑定、字段序、运行校验、执行分支不变 | **通过** | `make_public_successor_api_bundle` 字段序与 dataclass 一致；`_require_canonical_public_api_bundle` 仍 `is` 比对 `_PUBLIC_API_CALLABLE_FIELDS`；unit 钉七 callable `is` 真实 public 函数；Gate 顺序仍 `_GATES=(summary, reproducibility, readiness, acceptance)`；formal/repro/readiness/acceptance 执行体仍直调 public API + `_stage_receipt_ref` |
| 4 | downstream 直接消费 canonical 结果属性 | **通过** | 无中间 DTO；消费 `receipt_path`/`receipt`/`comparison_key`/`report`/`decision` 等；summary verifier 仍 exact `type(verified) is VerifiedResearchSummaryArtifact` |
| 5 | `_require_finite_config_float` exact-float + finite；拒 bool/int/str/NaN/Inf；稳定 gate fail | **通过** | `type(value) is not float or not math.isfinite(value)` → `SUCCESSOR_GATE_FAILED`；repro verify 容差仅经该 helper；裸 `float(...)` 已自 acceptance atol 路径移除 |
| 6 | wrong marker/wrapper/return 仍 fail-closed | **通过** | unit：`marker`/`wrapper`/`_MarkerResult` → `SUCCESSOR_STAGE_INVALID`（canonical apis 旁路后仍拒） |
| 7 | receipt/schema/identity/Gate 顺序未改 | **通过** | 未见 schema/identity helper 改动；upstream 指纹冻结；Gate prior 基数与 `_GATES` 不变 |
| 8 | task§18 ↔ delivery§16 证据一致 | **通过** | 84/42/Ruff PASS/mypy 21 STOP/SHA/evidence root 一致 |

### 16.3 审查者新增对抗性静态反例（实现者未专测）

| 反例 | 静态判定 | 不信任注解的依据 |
| --- | --- | --- |
| **Lying annotation**：callable 注解声称返回 `FormalBacktestStageResult`，运行时返回 `object()` / 伪 namespace | **仍 fail-closed** | `from __future__ import annotations` + `TYPE_CHECKING`：注解不参与运行；路径走属性访问 + `_stage_receipt_ref` 的 `type(receipt) is StageReceipt` / verify bytes；异常归一 `SUCCESSOR_STAGE_INVALID`（与 unit marker/wrapper 同门禁）。**不**存在“因注解为真而放行”的分支 |
| **float 子类 / `Decimal`**：`class F(float): pass` 的 `F(1e-3)` 或 `Decimal("0.1")` 作为 atol | **仍 fail-closed** | `type(value) is not float` 拒绝子类与 Decimal；有限性检查不会被碰到。unit 列表覆盖 bool/int/str/None/NaN/±Inf，**未列**子类/Decimal，但源码 exact-type 合同已静态闭合本反例 |

### 16.4 发现分级

**无 P0/P1。**（mypy 绿须由新完整 VALIDATION11 证明；本轮 STATIC_ONLY 不洗白 V10 mypy STOP。）

### 16.5 六段式（本轮闭合记录）

| 字段 | 内容 |
| --- | --- |
| 现象 | V10 mypy production3：七 stage/audit 结果为 `object` → 21× attr-defined/arg-type；裸 `float` 可接受 bool/非有限 |
| 根因 | bundle 统一 `Callable[..., object]`；config 容差未 enforce exact float |
| 规则 | §18：仅七字段 canonical quoted 注解；`TYPE_CHECKING`；禁 Any/cast/type:ignore/wrapper/DTO；`_require_finite_config_float`；`is`/字段序/执行不变 |
| 最小复现 | V10 `05-mypy.stdout.log`（21 errors）；`float(True)` 语义（交付陈述） |
| 测试 | 注解/`is` 绑定；exact float 拒非法；marker/wrapper/wrong-type fail-closed；审查者追加 lying-annotation 与 float-subclass/Decimal 静态反例 |
| 通过条件 | §16.2–16.3 全通过；可申请**完整 VALIDATION11**（须含 mypy）；**不**继承 V10 部分绿或本轮静态改动为整包 PASS |

### 16.6 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION11 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION11（含 mypy） |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 16.7 F11 结论

**F11_REVIEW_PASS**（taskbook §18 七处 canonical 返回类型 SSOT 与 config exact-float 收窄闭合）。可申请**完整 VALIDATION11**（须含 mypy）；**不**继承 VALIDATION10 / 本轮静态改动为整包 PASS。

---

## 17. VALIDATION11_F12_REVIEW（对照 taskbook §19）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F11 同一独立初验者；未参与实现<br>
范围：只读 taskbook §19、delivery §17、`run_successor_formal_stage` 授权局部名 diff；production/tests/taskbook/delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 17.1 写范围、指纹与 VALIDATION11 证据边界

| 项 | 结论 |
| --- | --- |
| exact12 / base | dirty 仅 exact12；HEAD=`1d9b4e09…`；`git diff --check` PASS；cached=0 |
| F12 授权写集 | 仅 `successor_downstream_stage.py` 内 formal stage 两局部名（+ taskbook/delivery）；tests/review **冻结**（本审查只写 review） |
| runtime / upstream | **未漂**：runtime=`272c42f6…`（同 F11）；upstream=`2adb24f0…`（同 F4） |
| downstream 指纹（F12 后只读） | `02bae1d1779fc04f8486cf32bb4467486a4418d9ef680a11f46cbb5f5c109acd`（相对 F11 仅本授权改动） |
| VALIDATION11（未重跑） | identity **PASS**（stdout SHA=`e153b441…`）；unit **`57 passed`**（SHA=`950b983d…`）；integration **`29 passed`**（SHA=`26493122…`）；Ruff **PASS**（SHA=`af352a86…`）；mypy production3 **STOP** 单错 `:214 assignment`（SHA=`4a4108d5…`）；cold/scope **UNRUN** |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c/`；stage-summary SHA=`034cd671…`；与 task§19 / delivery§17.1 逐项一致 |
| 本轮复验命令 | **全部 UNRUN** |

### 17.2 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 仅分离 `backtest_result` / `tracking_result` | **通过** | backtest 分支赋 `backtest_result` 并消费 `.receipt_path`/`.receipt` 后 `return`；tracking 赋 `tracking_result` 后同形消费 |
| 2 | 调用/参数/顺序/receipt/分支/错误归一不变 | **通过** | `formal_backtest_stage` / `formal_tracking_stage` 关键字实参表、`_stage_receipt_ref` 节点构造、`except`→`SUCCESSOR_STAGE_INVALID` 与 F11 语义等价；无 API/schema/Gate 改动 |
| 3 | 无 cast/Any/type:ignore/union/wrapper/API 变更 | **通过** | formal stage 函数体内未见 `cast`/`Any`/`type: ignore`/union 合并类型；无 wrapper；runtime 指纹冻结 |
| 4 | task/delivery 准确绑定 V11 57+29+Ruff PASS / 单 mypy STOP / cold·scope UNRUN | **通过** | 只读 stdout/exit/stage-summary 与 delivery 表及 task§19 数字一致 |

### 17.3 审查者新增对抗性静态反例

| 反例 | 静态判定 | 依据 |
| --- | --- | --- |
| **跨分支局部泄漏**：`backtest_result` 是否可在 tracking 路径被读取，或 `tracking_result` 是否可回指 backtest 结果 | **不能泄漏** | `if stage == "backtest":` 块在消费 `backtest_result` 后立即 `return`，控制流不落入 tracking；`tracking_result` 仅在该 `if` 之外绑定与消费；两名互不出现在对方分支。无共享 `result`、无跨分支赋值/别名 |

### 17.4 发现分级

**无 P0/P1。**（mypy 绿须由新完整 VALIDATION12 证明；本轮不洗白 V11 mypy STOP。）

### 17.5 六段式（本轮闭合记录）

| 字段 | 内容 |
| --- | --- |
| 现象 | V11 mypy：同一 `try` 内共享 `result` 先 `FormalBacktestStageResult` 再赋 `FormalTrackingStageResult` → `:214 assignment` 单错 |
| 根因 | F11 收窄返回类型后共享局部名跨不相容类型；非行为/API 错误 |
| 规则 | §19：仅 `backtest_result`/`tracking_result`；调用/参数/顺序/receipt/分支/错误归一逐字等价；禁 cast/Any/type:ignore/union/wrapper/API |
| 最小复现 | V11 `05-mypy.stdout.log` 单行 assignment |
| 测试 | 本轮 tests 冻结；审查者追加跨分支局部不泄漏静态反例 |
| 通过条件 | §17.2–17.3 全通过；可申请**完整 VALIDATION12**（须含 mypy）；**不**继承 V11 部分绿或本轮静态改动为整包 PASS |

### 17.6 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION12 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION12（含 mypy） |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 17.7 F12 结论

**F12_REVIEW_PASS**（taskbook §19 formal backtest/tracking 结果局部名分离闭合）。可申请**完整 VALIDATION12**（须含 mypy）；**不**继承 VALIDATION11 / 本轮静态改动为整包 PASS。

---

