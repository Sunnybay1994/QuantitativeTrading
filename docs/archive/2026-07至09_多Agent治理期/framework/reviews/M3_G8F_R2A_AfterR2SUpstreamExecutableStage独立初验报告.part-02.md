| API | 结论 | 证据 |
| --- | --- | --- |
| API-1 `BacktestPlanFreshVerificationContext` | **生产 PASS** | 自 `quant.backtest.a_share_plan` 导入 `1943-1947`；contracts 块 `1929-1942` **无**该名。SSOT 类定义 `a_share_plan.py:95+`。Retained mypy 曾报 L1790 attr-defined（修前）。 |
| API-2 `plan_provider_probe(..., spec=)` | **生产 PASS** | 调用 `1414-1416`：`spec=validation_spec`。Public 签名 `provider_validation.py:105-108` 要求 keyword-only `spec`（无 default）。Retained mypy L1279 call-arg（修前）。 |
| API-3 `build_backtest_plan_artifact(..., artifact_roots=)` | **生产 PASS** | 调用 `2510-2514`：`artifact_roots={"PROJECT": project_root}`。Public 签名 `a_share_plan.py:197-207` 要求 keyword-only `artifact_roots`。Retained mypy L2308 call-arg（修前）。 |

### T.2 bundle / Literal / Optional / summary / 禁令

| 项 | 结论 | 证据 |
| --- | --- | --- |
| RunPlan 收窄 | **生产面可读 PASS** | `_require_run_plan` `135-140`；provider-validation 等 wave 在 `select_run_plan_nodes` 前收窄（如 `1400-1408`）。 |
| Literal / config | **生产面可读 PASS** | `_require_horizon`/`benchmark`/`dump`/`frequency`/`strategy` `143-174`；canonical horizons→`(5,10)`。 |
| Optional 局部绑定 | **生产面可读 PASS** | work 路径对 folds/alignment/model/prediction 等先存在性再 builder（既有 `_require_path` 等）。 |
| summary node | **生产面可读 PASS** | `_ReceiptNodeView` Protocol `87-92`；`_new_receipt_ref(..., node: _ReceiptNodeView)` `700-726`；`_SummaryNodeRef` `2705-2710` 经 `3115-3118` 入账；stage/scope_key 仍取自 verified receipt。 |
| 禁 Any/cast/type:ignore | **PASS（生产 grep）** | `successor_upstream_stage.py` 无 `\bAny\b` / `cast(` / `type: ignore`。`object` 仅作收窄入口与 StageRunner build 返回，非 Any 逃逸。 |
| wave/receipt/identity/resume 语义 | **未见故意改合同** | registry seal、horizon map、toolchain 拒绝路径仍在；本 FAIL 不据此扩项。 |

### T.3 §12.4 测试真实调用边界 — **FAIL**

任务书 §12.4.1：「至少让 `plan_provider_probe(spec=...)` 与 `artifact_roots={"PROJECT": project_root}` **通过真实调用边界**；……**不能只测源码字符串**。」

| 测试 | 实际做了什么 | 缺口 |
| --- | --- | --- |
| unit `test_plan_provider_probe_signature_…` `845-868` | `inspect.signature`；源码串 `spec=validation_spec`；**缺** `spec` 的调用→`TypeError` 经 `@_boundary` 成 `PROVIDER_VALIDATION_INPUT_INVALID` | **从未**执行带 `spec=<合法/合同形状 ProviderValidationSpec>` 的真实调用路径 |
| unit `test_build_backtest_plan_artifact_signature_…` `871-883` | **仅** `inspect.signature` + 源码串 `artifact_roots={"PROJECT": project_root}` | **零** `build_backtest_plan_artifact(...)` 实调（缺参/带参皆无） |
| integration `test_integration_real_api_signatures_…` `663-689` | signature + importlib `is` + 源码串 | 同上，无真实调用边界 |

交付 §0E 称「真实签名反例」，但对照 §12.4 与用户硬条件：**inspect.signature / source-string-only 在未执行 valid real signature path 时不足**。

#### 失败项 F-TC1（六要素）

| 字段 | 内容 |
| --- | --- |
| 现象 | provider/backtest 的「真实调用边界」测试未执行带 required kwargs 的有效签名路径；backtest 甚至无任何实调 |
| 根因 | 以 signature 自省 + 生产源码子串代替 unmocked 真实调用；缺 spec 负例只证明 TypeError 包装，不证明 `spec=` 接线 |
| 规则 | 任务书 §12.4.1；用户 TYPE_CONTRACT 硬条件 |
| 最小复现 | 见反例 R7；静态阅读 unit `845-883`、integration `663-689` |
| 新增测试（应有） | 至少一次实调 `plan_provider_probe(..., spec=…)` 与一次实调 `build_backtest_plan_artifact(..., artifact_roots={"PROJECT": …})`（可用最小非法上游在 public API 入口 fail-closed，但 **kwargs 必须在实参列表中出现并被绑定**）；不得只靠读源码 |
| 通过条件 | 两边界均有 unmocked 实调证据；源码串可作辅证不可作唯一证据 |

### T.4 新对抗反例 R7 — 源码子串伪装 × 无正路径实调

**最小静态复现（未执行）：**

1. 在生产中保留字符串 `spec=validation_spec` / `artifact_roots={"PROJECT": project_root}`（甚至写入注释），同时让实参列表漏传上述 keyword → 现行 unit/integration **仍绿**（只扫子串 + signature）。
2. 对照：缺 `spec` 的 probe 调用（unit `863-867`）只覆盖「kwargs 不完整→TypeError→boundary」；**不**覆盖「`spec=` 已传入且进入 `_plan_probe` / 类型门」。
3. `build_backtest_plan_artifact` 在 exact9 测试中 **零调用**：漏传 `artifact_roots` 不会被这些测试抓住。
4. 预期（合同）：至少各有一条 unmocked 实调，keyword 出现在绑定实参中；仅 source/signature **不够**。

### T.5 未运行 / Gate 边界

| 项 | 状态 |
| --- | --- |
| 本复验 Python/pytest/Ruff/mypy/cold/scripts | **未运行** |
| VALIDATION3 cold / final scope | **UNRUN**（retained） |
| 115→0 / 整包 / Gate / bridge | **不宣称** |
| 本审查改实现 | **未做** |

### T.6 总判

**TYPE_CONTRACT_REVIEW_FAIL**

生产侧三项真实 API 与 Literal/Optional/RunPlan/summary Protocol、无 Any/cast/ignore 的静态面大体对齐 §12.1–12.3；但 **§12.4 强制的 unmocked 真实调用边界未满足**（probe 无 `spec=` 正路径实调；backtest 无任何实调；依赖 signature/源码串）。须在 exact9 测试白名单内补真实调用反例后由独立上下文复验。历史结论均不覆盖。

---

## §13 真实调用返工复验（2026-08-26）— 同一独立 reviewer

身份：与 TYPE_CONTRACT 复验相同之独立 reviewer<br>
唯一写入：本报告（**追加**；含 `TYPE_CONTRACT_REVIEW_FAIL` 在内全部历史结论 **完整保留**）<br>
只读：任务书 §13、delivery §0F、最终两份 upstream-stage 测试；production/runtime/taskbook/delivery **只读**<br>
结论：**REAL_CALL_REVIEW_PASS**

### C.0 边界与 production 字节冻结

| 项 | 证据 |
| --- | --- |
| 写集（实现者） | 仅两份 upstream tests + delivery（§13 / §0F） |
| production 未改 | `successor_upstream_stage.py` mtime `2026-08-26T06:34:49+08:00`（早于 tests `06:42:23` / delivery `06:42:42`）；SHA256=`BEA73E90A1D1E2D78BF390B367464744DE53B56A6B257B7BA5FE58D4EBC1F646`；`successor_runtime.py` mtime `05:15:48` 更早 |
| 生产调用位点仍在 | `plan_provider_probe(..., spec=validation_spec)` `1414-1416`；`artifact_roots={"PROJECT": project_root}` `2513` |
| STATIC_ONLY | 本复验零 Python/scripts/pytest/Ruff/mypy/cold/subagent/commit |

### C.1 正向 unmocked 实调

| # | §13 要求 | 结论 | 行号证据 |
| --- | --- | --- | --- |
| P1 | `plan_provider_probe` + 合法 `ProviderValidationSpec` → 真实 `ProviderProbePlan` | **PASS** | unit `857-924`：formal fixture 得 `VerifiedSnapshotArtifact`/`VerifiedProviderArtifact`；`ProviderValidationSpec`+`compute_provider_validation_key` `891-906`；实调 `spec=validation_spec` `913-918`；断言 `type is ProviderProbePlan`、key/snapshot/provider identity、`selected_rows==60`、3 symbols。integration `733-741` 同构。 |
| P2 | `build_backtest_plan_artifact` + `artifact_roots={"PROJECT": project_root}` → 真实 manifest | **PASS** | unit `1006-1020`：实调 builder（**未** monkeypatch builder）；显式 PROJECT roots `1013`；返回 `BacktestPlanManifestV1` 且 work/experiment key 对齐；落盘 `manifest.json` / `scheduled_targets.parquet`。integration `763-775` 同。 |

### C.2 负例 fail-closed（与正路径分离）

| # | 反例 | 结论 | 证据 |
| --- | --- | --- | --- |
| N1a | missing `spec` | **PASS** | unit `949-955`；integration `743-749` → `PROVIDER_VALIDATION_INPUT_INVALID` |
| N1b | wrong/drifted `spec` | **PASS** | unit 正路径内 drifted key `928-939`（真实 snapshot/provider）；unit `957-972` 错 shape+spec（早失败包装同码） |
| N2 | wrong alias roots | **PASS** | unit `1037-1048` / integration `781-792`：`artifact_roots={"EXTERNAL_QLIB": …}` → `M3_BACKTEST_PLAN_ARTIFACT_INVALID`；输出目录空 |

### C.3 残余（不阻断）

正路径 plan 仅 stub `verify_target_artifact`（unit `996`；integration `760`），**不** stub builder；§0F 已披露为隔离 fixture `root` alias 与生产 PROJECT-only。错 alias 负例未 stub verify，仍 fail closed。符合 §13.2「不得把 builder 打成桩」。

### C.4 未运行 / Gate

| 项 | 状态 |
| --- | --- |
| pytest / Ruff / mypy / cold | **未运行** |
| 历史 115 mypy →0 | **不宣称**（待完整 validation） |
| Gate / bridge / WINDOWS_VALIDATED | **不宣称** |

### C.5 总判

**REAL_CALL_REVIEW_PASS**

F-TC1 / R7 所指两处 unmocked 正路径实调已在 exact9 测试落地；缺/错 spec 与错 alias 仍 fail closed；production 相对 TYPE_CONTRACT 审查后的字节冻结成立。可申请完整 validation：identity→focused exact4→Ruff→mypy→cold→exact9 scope。历史结论均不覆盖。

---

## VALIDATION4 fixture 父目录复验（2026-08-26）— 同一独立 reviewer

身份：与 REAL_CALL 复验相同之独立 reviewer<br>
唯一写入：本报告（**追加**；全部历史结论 **完整保留**）<br>
只读：AGENTS、任务书 §14、delivery §0G、exact9；business/production/tests（除本轮宣称写集外）只读<br>
结论：**FIXTURE_PARENT_REVIEW_PASS**

### P.0 写集与 production 字节

| 项 | 结论 | 证据 |
| --- | --- | --- |
| production 不变 | **PASS** | `successor_upstream_stage.py` SHA256 仍 `BEA73E90A1D1E2D78BF390B367464744DE53B56A6B257B7BA5FE58D4EBC1F646`；mtime `2026-08-26T06:34:49+08:00`（相对 REAL_CALL 审查未变）。`successor_runtime.py` mtime `05:15:48` 未动。 |
| 本轮仅意图文件 | **PASS** | integration `test_m3_successor_upstream_stage.py` mtime `07:15:28`；delivery `07:15:39`。unit upstream 测试仍 `06:42:23`（§13 态）。 |
| STATIC_ONLY | **遵守** | 本复验零 Python/pytest/Ruff/mypy/cold/scripts/Qlib/network/stage/commit |

### P.1 fixture 父目录修正

| §14 项 | 结论 | 证据 |
| --- | --- | --- |
| test-owned `plan_root` 先 mkdir 再 `_context` | **PASS** | integration `757-759`：`plan_root = tmp_path / "plan"`；`plan_root.mkdir()`；`plan_support._context(plan_root, monkeypatch)`。注释说明 support `artifacts.mkdir(parents=False)` 合同。 |
| 未改 support/production/自动建目录语义 | **PASS** | 未触 formal support / production；仅调用方前置。 |

### P.2 真实 API 正/负合同仍可达

| 合同 | 结论 | 证据 |
| --- | --- | --- |
| unmocked `plan_provider_probe(spec=...)` | **PASS** | integration `733-741`：合法 `ProviderValidationSpec` 实调 → `ProviderProbePlan` / `selected_rows==60`。unit 正路径 `913-918` 未改。 |
| missing spec 负例 | **PASS** | integration `743-749` → `PROVIDER_VALIDATION_INPUT_INVALID` |
| unmocked `build_backtest_plan_artifact(..., artifact_roots={"PROJECT": ...})` | **PASS** | integration `767-778`：显式 PROJECT roots；返回 `BacktestPlanManifestV1`。unit `1006-1014` 未改。 |
| wrong alias 负例 | **PASS** | integration `785-796`：`EXTERNAL_QLIB` → `M3_BACKTEST_PLAN_ARTIFACT_INVALID`；空输出。unit `1037-1048` 未改。 |
| 未退回 signature/source-only | **PASS** | signature/source 仅辅证 `798-804`；正路径仍为实调。 |

### P.3 证据 / 非宣称

| 项 | 状态 |
| --- | --- |
| retained root | `artifacts/agent_runs/m3-r2a-validation4-20260826T065000Z/`；focused stdout SHA=`A9C0E706…CFA6A` 与 stage-summary 一致；`VALIDATION_STOP=STAGE_FAILED:02-focused:1` |
| 73 passed / 1 failed | **不**沿用为整包通过（§14.5 / §0G） |
| Gate / bridge / WINDOWS_VALIDATED | **不宣称** |
| 本审查改实现 | **未做** |

### P.4 总判

**FIXTURE_PARENT_REVIEW_PASS**

本轮仅为 integration 测试创建 test-owned `plan_root` 父目录；production 字节相对 REAL_CALL 冻结；两处 unmocked 真实 API 正/负合同仍在。可申请完整 **VALIDATION5**：identity→focused exact4→Ruff prod2/tests4→mypy prod2→cold prod2→exact9 scope/residue。历史结论均不覆盖。

---

## VALIDATION5 monkeypatch authority 隔离复验（2026-08-26）— 同一独立 reviewer

身份：与 FIXTURE_PARENT 复验相同之独立 reviewer<br>
唯一写入：本报告（**追加**；全部历史结论 **完整保留**）<br>
只读：AGENTS、任务书 §15、delivery §0H、exact9；business 只读<br>
结论：**MONKEYPATCH_AUTHORITY_REVIEW_PASS**

### M.0 写集与 production 字节

| 项 | 结论 | 证据 |
| --- | --- | --- |
| production 不变 | **PASS** | `successor_upstream_stage.py` SHA256 仍 `BEA73E90A1D1E2D78BF390B367464744DE53B56A6B257B7BA5FE58D4EBC1F646`；mtime `2026-08-26T06:34:49+08:00`。`successor_runtime.py` `05:15:48` / SHA `1E0164E1…1D79` 未动。 |
| 本轮仅意图文件 | **PASS** | integration `07:50:11`；delivery `07:50:42`。unit upstream 仍 `06:42:23`（未改）。 |
| STATIC_ONLY | **遵守** | 零 Python/pytest/Ruff/mypy/cold/scripts/Qlib/network/stage/commit |

### M.1 双独立 `MonkeyPatch.context()` 生命周期

| §15 项 | 结论 | 证据 |
| --- | --- | --- |
| 去掉共享外层 `monkeypatch` 形参 | **PASS** | `test_integration_real_api_positive_probe_and_project_roots(tmp_path)` 仅 `tmp_path`（`674-676`） |
| Authority A = provider 独立 context | **PASS** | `with pytest.MonkeyPatch.context() as provider_mp:` `710-758`：仅 `_verified_g1`/`_provider(..., provider_mp)` + unmocked `plan_provider_probe(spec=...)` 正路径与缺 `spec` 负例；离开即恢复 |
| Authority B = plan 独立 context | **PASS** | 另一 `with pytest.MonkeyPatch.context() as plan_mp:` `762-805`：`plan_root.mkdir` + `_context(plan_root, plan_mp)` + PROJECT builder 正/错 alias 负；与 A 串行、不共享同一 authority |
| 精确恢复 | **PASS（静态）** | 两 context 各自 `with` 退出由 pytest MonkeyPatch undo；A 结束后 B 才进入（`760` 注释） |

### M.2 正/负合同未弱化；未改回 mock/源码替代

| 合同 | 结论 | 证据 |
| --- | --- | --- |
| probe 正路径 | **PASS** | `742-750`：合法 `ProviderValidationSpec` + `spec=validation_spec` → `ProviderProbePlan` / key / `selected_rows==60` |
| probe 缺 spec | **PASS** | `752-758` → `PROVIDER_VALIDATION_INPUT_INVALID` |
| plan PROJECT 正路径 | **PASS** | `776-789`：unmocked `build_backtest_plan_artifact` + `artifact_roots={"PROJECT": project_root}` → `BacktestPlanManifestV1` |
| plan 错 alias | **PASS** | `794-805`：`EXTERNAL_QLIB` → `M3_BACKTEST_PLAN_ARTIFACT_INVALID`；空输出 |
| 未退回 signature/source-only | **PASS** | `807-813` 仅辅证；正路径仍为实调 |

### M.3 verifier / 最终结果

| 项 | 结论 | 说明 |
| --- | --- | --- |
| 未 stub builder / 最终返回 | **PASS** | builder 实调返回真实 `BacktestPlanManifestV1`；未 patch 错误码 |
| `verify_target_artifact` | **残余（不阻断）** | 仅 Authority B 内既有 PROJECT↔`root` alias 隔离 stub（`771-773`；错 alias 前手动恢复 `791`）；§0H / REAL_CALL C.3 已披露；**非**本轮新增、**非** final-result patch。本复验不据此 FAIL。 |

### M.4 证据 / 非宣称

| 项 | 状态 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m3-r2a-validation5-20260826T072447Z/` |
| focused stdout SHA | `717DC4F54A946DF3B51BD8F27B6B0B991078CEC7E8FA9895F07BF29952A0A02B`（文件哈希一致） |
| stage-summary SHA | `6C2815D0A0FBC5619CD3451F63B957C04C5701033D47FF5FEC956DA9F3F59017`（文件哈希一致）；`VALIDATION_STOP=STAGE_FAILED:02-focused:1`；历史失败 `M3_FEATURE_ARTIFACT_INVALID` |
| 73/1 非整包 / Gate | **不宣称** |
| 本审查改实现 | **未做** |

### M.5 总判

**MONKEYPATCH_AUTHORITY_REVIEW_PASS**

provider 与 backtest-plan 真实调用已分属独立 `pytest.MonkeyPatch.context()` 并在退出时恢复；production/其他 tests 本轮冻结；正负合同未弱化为 mock/源码检查。可申请完整 **VALIDATION6**：identity→focused exact4→Ruff→mypy→cold→exact9 scope。历史结论均不覆盖。

---

## VALIDATION7 只读节点协议复验（2026-08-26）— 同一独立 reviewer

身份：与 MONKEYPATCH 复验相同之独立 reviewer<br>
唯一写入：本报告（**追加**；全部历史结论 **完整保留**）<br>
只读：AGENTS、任务书 §16、delivery §0I、exact9；business 只读<br>
结论：**RECEIPT_NODE_PROTOCOL_REVIEW_PASS**

### N.0 写集范围

| 项 | 结论 | 证据 |
| --- | --- | --- |
| 本轮仅 Protocol + delivery | **PASS** | `successor_upstream_stage.py` mtime `2026-08-26T08:30:57`；SHA256=`986680198FFD855C6240C840DB3827650589CC159720B221F19161711E3A680A`（相对 MONKEYPATCH 冻结的 `BEA73E90…` 仅本轮注解变更）。delivery `08:31:17`。 |
| runtime / tests 未改 | **PASS** | `successor_runtime.py` SHA 仍 `1E0164E1…1D79` / mtime `05:15:48`。unit `06:42:23`、integration `07:50:11` 未动。 |
| STATIC_ONLY | **遵守** | 零 Python/pytest/Ruff/mypy/cold/scripts/Qlib/network/stage/commit |

### N.1 `_ReceiptNodeView` 只读 `@property`

| §16 项 | 结论 | 证据 |
| --- | --- | --- |
| 成员改为 `@property` 抽象声明 | **PASS** | `87-97`：`node_id`→`str`；`fold`→`str \| None`；`horizon`→`int \| None`；均为 `def …: ...` |
| 精确返回类型保留 | **PASS** | 与既有 `_new_receipt_ref` 只读消费及 `_SummaryNodeRef`/`StageNode` 字段一致（`horizon` 非任务书笔误 `horizon_sessions`） |
| 无 setter / Any / cast / type:ignore | **PASS** | Protocol 块无 setter；全文件无 `\bAny\b` / `cast(` / `type: ignore`（本轮 grep） |
| 未扩大接受对象 | **PASS** | 仍三成员最小视图；无新增 Protocol 成员 |

### N.2 runtime / schema / identity 零变化

| 项 | 结论 | 证据 |
| --- | --- | --- |
| `_new_receipt_ref` 函数体 | **PASS（静态）** | `706-732`：仍只读 `node.node_id`/`fold`/`horizon`；`verify_stage_receipt_with_bytes` + `StageReceiptRef` 构造未改 |
| `_SummaryNodeRef` | **PASS** | `2710-2716`：frozen dataclass，字段集未改 |
| 业务/错误码/测试 | **PASS** | 测试文件 mtime 冻结；未见分支/schema 语义编辑面 |

### N.3 VALIDATION7 证据与边界调和

| 项 | 状态 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m3-r2a-validation7-20260826T000444Z/` |
| identity | PASS（stage-summary） |
| focused | **74 passed**；stdout SHA=`5E6711F702211439E999082D6C66522B0BE976470B3CA70E4C1E7241BC21CCD8` **match** |
| Ruff prod2/tests4 | PASS；stdout SHA=`AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF` **match** |
| mypy prod2 | exit=1；**Found 9 errors**；stdout SHA=`BF020D2F0C7741E88537FA22AB792C9B935DE4EE7CAD102C95C67541E9D5C0E0` **match**；notes 为修前「Protocol … expected settable variable, got read-only attribute」 |
| stage-summary SHA | `F569CABA36F3DBB64E301DADD5673D355B5497681F355E91509E4EC263A2B3CC` **match**；`VALIDATION_STOP=STAGE_FAILED:04-mypy:1` |
| cold / exact9 scope | **UNRUN** |
| 9→0 已运行证实 | **不宣称**（本轮 STATIC_ONLY；待 postfix mypy） |
| Gate / bridge / WINDOWS_VALIDATED | **不宣称** |

### N.4 总判

**RECEIPT_NODE_PROTOCOL_REVIEW_PASS**

本轮仅为 `_ReceiptNodeView` 只读 `@property` 注解对齐结构子类型；`_new_receipt_ref`/runtime/schema/identity/tests 未改。可申请 postfix：identity→Ruff 实际修改 production→mypy production2→cold production2→exact9 scope（不重复已绿 focused74）。历史结论均不覆盖。

---

## EVIDENCE_REVIEW（2026-08-26）— 同一独立 reviewer · 任务书 §17

身份：与 RECEIPT_NODE 复验相同之独立 reviewer<br>
唯一写入：本报告（**追加**；全部历史结论 **完整保留**）<br>
只读：AGENTS、任务书 §17/§18、delivery §0J、exact9 dirty、`artifacts/agent_runs` 证据根<br>
结论：**EVIDENCE_REVIEW_PASS**

### E.0 审查边界

- business / taskbook / delivery：**只读**；本会话只追加本 review。
- **未运行** Python / pytest / Ruff / mypy / cold / scripts / Qlib / network / stage / commit。
- 组合口径：VALIDATION7 focused74+Ruff ⊕ POSTFIX VALIDATION8 identity/Ruff/mypy/cold/scope；**不得**改写为单轮全绿。

### E.1 VALIDATION7 ⊕ VALIDATION8 组合闭合

| 组合件 | 结论 | 证据 |
| --- | --- | --- |
| V7 focused exact4 `74 passed` | **PASS** | root `m3-r2a-validation7-20260826T000444Z/`；`02-focused.stdout.log` SHA=`5E6711F7…CCD8` **match**；summary 含 focused exit=0 |
| V7 Ruff production2/tests4 | **PASS** | 同根 `03-ruff.stdout.log` SHA=`AF352A86…D9AF` **match**；exit=0 |
| V7 mypy（修前） | **如实 STOP** | `04-mypy` exit=1；**Found 9 errors**；SHA=`BF020D2F…C0E0` **match**；cold/scope **UNRUN**；summary SHA=`F569CABA…B3CC` **match** |
| V8 identity | **PASS** | root `m3-r2a-postfix-validation8-20260826T003929Z/`；`01-identity` exit=0；stdout SHA=`3D4E770B…D788` **match**；**无** `02-focused`（postfix 不重复 focused74） |
| V8 Ruff（实际 production） | **PASS** | `03-ruff` exit=0；stdout SHA=`AF352A86…D9AF` **match** |
| V8 mypy production2 | **PASS** | `04-mypy` exit=0；`Success: no issues found in 2 source files`；SHA=`07A5CA23…B660` **match** |
| V8 cold production2 | **PASS** | `05-cold` exit=0；SHA=`FDB6604E…B0EB` **match**；导入两 production 路径 |
| V8 exact9 scope/diff/temp/process | **PASS** | `06-scope` exit=0；SHA=`95BD7969…5F17` **match** |
| V8 stage-summary | **PASS** | SHA=`7BEE5B9B…1B51` **match**；正文 `VALIDATION_PASS` |

### E.2 actual8 ⊆ exact9 / cached0 / residue

`06-scope.stdout.log`：`ACTUAL_COUNT=8`、`ALLOWED_COUNT=9`、`CACHED_COUNT=0`、`DIFF_CHECK=PASS`、`TEMP_PROCESS_RESIDUE=PASS`。

ACTUAL 八路径均为 exact9 白名单成员：delivery、review、taskbook、`successor_runtime.py`、`successor_upstream_stage.py`、两份 upstream-stage 测试、`test_m3_successor_runtime` integration。未出现白名单外 dirty。`06-cached.raw` 空；`cached0` 成立。**actual8 ⊆ exact9** 成立（exact9 中 `tests/unit/test_m3_successor_runtime.py` 本轮可不在 ACTUAL）。

现行 `git status --short` 与 V8 ACTUAL 集合一致（8 项）。production upstream SHA 仍 `98668019…680A`（§16 Protocol 后态）。

### E.3 VALIDATION1–8 历史失败 / UNRUN（不改写）

| 轮次 | 复核 |
| --- | --- |
| V1 | 无独立 durable product root；任务书/delivery 保留 identity PASS + focused `61/3` + 后续 **UNRUN**；空 carrier 规则成立 |
| V2 | 产品根 `…validation2-20260826T061000Z/`：focused `64 passed`；Ruff exit=1（Found 4）；mypy/cold/scope **UNRUN**。空 carrier `…T060803Z/` 仅 `runner.ps1` → **CARRIER_INVALID_BEFORE_PRODUCT_EVIDENCE** |
| V3 | `…postfix-validation3-…061827Z/`：identity+Ruff PASS；mypy **115 errors** STOP；cold/scope **UNRUN** |
| V4 | `…validation4-…065000Z/`：focused `73 passed / 1 failed`；后续 **UNRUN**。早根 `…T064739Z/` 仅 `runner.ps1` → carrier-invalid |
| V5 | `…validation5-…072447Z/`：focused `73/1`；后续 **UNRUN** |
| V6 | 根 `…validation6-…000031Z/` 存在但 summary 损坏/非完整产品证据（identity 后即停）；**不以该根冒充 focused74**；focused74+Ruff 与 **V7** 联立（与 §18.3 / §0J 一致） |
| V7 | focused74+Ruff PASS；mypy 9 STOP；cold/scope **UNRUN**（上表） |
| V8 | identity/Ruff/mypy/cold/scope **全部 PASS**；actual8⊆exact9 / cached0 |

### E.4 非宣称 / 终态上限

| 项 | 状态 |
| --- | --- |
| 允许标签 | **`R2A_WINDOWS_ENGINEERING_VALIDATED`**（= EXECUTABLE_STAGE_SUBSTRATE Windows 工程闭包） |
| **不得宣称** | production bridge、CLI、actual worker、真实 Qlib、new root、retained、acceptance、更高 `EXECUTABLE_STAGE_SUBSTRATE_WINDOWS_VALIDATED`（若区分）、**M3 Gate** |
| 本审查改实现 | **未做** |

### E.5 总判

**EVIDENCE_REVIEW_PASS**

VALIDATION7 focused74+Ruff 与 VALIDATION8 identity/Ruff/mypy/cold/scope 关键 SHA/exit 可复核且组合闭合；历史首失败与 UNRUN/carrier-invalid 未被改写为单轮全绿；actual8⊆exact9 与 cached0/diff/residue PASS。可申请安全提交。历史结论均不覆盖。
