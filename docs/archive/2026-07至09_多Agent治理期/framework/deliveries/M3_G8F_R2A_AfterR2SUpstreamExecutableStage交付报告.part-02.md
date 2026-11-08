### 本轮实现摘要（STATIC_ONLY）

- 生产：helpers（`_require_run_plan`/`_require_horizon`/benchmark/dump/frequency/strategy/str/int/float/tuple/path/`_require_toolchain` 等）；七处 wave 的 `_require_run_plan`；三处真实 API 修正；Optional 局部绑定；`_ReceiptNodeView`；shared labels 键为 `Literal[5,10]`；去掉 `getattr(toolchain)` 以避免 Any 流入。
- 测试：真实签名边界 + import 路径 + Literal/Optional/toolchain/frequency 拒绝；保留既有 registry/horizon-map。
- **未**引入 `Any` / `cast` / `type:ignore`；**未**触发 `CONTRACT_STOP`。

## 0F. TYPE_CONTRACT_REVIEW test-only 真实调用返工（任务书 §13）

| 字段 | 内容 |
| --- | --- |
| 现象 | 独立 reviewer `TYPE_CONTRACT_REVIEW_FAIL`（review T.3 / F-TC1 / R7）：§12.1–12.3 production 静态面大体闭合，但 §12.4 要求的 unmocked 真实调用边界未满足——既有测试仅 `inspect.signature`、源码子串与缺参/早失败。 |
| 根因 | 以 signature/source 代替「合法 kwargs 进入真实 public API 并越过 shape/identity 门禁」的正路径证据；`build_backtest_plan_artifact` 甚至零实调。 |
| 规则 | 任务书 §13；reviewer FAIL；仅改两份 upstream-stage 测试 + 本 delivery；production/runtime/taskbook/review 冻结；零 Python/验证/提交。 |
| 最小复现 | review `TYPE_CONTRACT_REVIEW_FAIL` T.3–T.4；unit 旧 `845-883` / integration 旧 `663-689` 仅 signature/source。 |
| 修正 | 见下表六要素；复用既有 formal feature/plan fixture 模块（importlib）构造合法 snapshot/provider/config/`ProviderValidationSpec` 与 plan kwargs。 |
| 通过条件 | STATIC_ONLY 交付闭合；**未**重跑 pytest/Ruff/mypy/cold；不得宣称 115→0 或 Gate；交同一 reviewer 复验后才可申请完整 validation。 |

### 六要素行

| 项 | 现象 | 根因 | 规则 | 最小复现 | 新增测试 | 通过条件 |
| --- | --- | --- | --- | --- | --- | --- |
| P1 probe 正路径 | 无 `spec=` 合法实调 | 只测缺参/签名 | §13.1 | F-TC1 / R7 | unit `test_plan_provider_probe_positive_real_call_with_valid_spec`；integration 同边界 | 返回真实 `ProviderProbePlan` 且 identity 对齐；`selected_rows==60` |
| P2 plan 正路径 | 无 PROJECT `artifact_roots` 实调 | 零 builder 调用 | §13.2 | F-TC1 | unit `test_build_backtest_plan_artifact_positive_project_only_roots`；integration 同边界 | 返回真实 `BacktestPlanManifestV1`；显式 `artifact_roots={"PROJECT": project_root}` |
| N1 缺/错 spec | 需保留负例 | 对照正路径 | §13.4 | 缺 kwargs / drifted key | unit `test_plan_provider_probe_rejects_missing_or_wrong_spec` + 正路径内 drifted key；integration 缺 spec | 稳定 `PROVIDER_VALIDATION_INPUT_INVALID` |
| N2 错 alias roots | 需与 PROJECT 分离 | 对照正路径 | §13.4 | `EXTERNAL_QLIB` roots | unit `test_build_backtest_plan_artifact_rejects_wrong_alias_roots`；integration 同 | `M3_BACKTEST_PLAN_ARTIFACT_INVALID`；无输出残留 |

### 本轮边界

| 项 | 记录 |
| --- | --- |
| 写集 | 仅 `tests/unit/test_m3_successor_upstream_stage.py`、`tests/integration/test_m3_successor_upstream_stage.py`、本 delivery |
| production / runtime / taskbook / review | **字节冻结**（本轮未改） |
| 零 Python | 未运行 Python / pytest / Ruff / mypy / cold / scripts / network / Qlib / stage / commit |
| fixture 策略 | importlib 加载既有 `test_m3_formal_feature_artifact` / `test_m3_formal_backtest_plan_artifact` canonical helpers；plan 正路径仅 stub `verify_target_artifact`（不 stub builder），以隔离 fixture receipt alias=`root` 与生产 PROJECT-only 别名差 |
| 历史 115 mypy | 仍待经理授权完整 validation 复验；本轮不宣称消除 |
| `CONTRACT_STOP` | **未触发**（exact9 测试内可构造真实调用） |

## 0G. VALIDATION4 focused fixture 父目录返工（任务书 §14）

| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION4 identity PASS；focused exact4 `73 passed / 1 failed / 373236 warnings`；唯一失败在 integration 真实 API 正向节点：`plan_support._context(tmp_path / "plan", ...)` 前未创建 `plan` 父目录，深层 support 执行 `plan/artifacts.mkdir(parents=False)` → `FileNotFoundError`。Ruff/mypy/cold/final scope **UNRUN**。 |
| 根因 | 测试夹具前置缺口：pytest `tmp_path` 存在，但调用方自建的 `tmp_path/"plan"` 子目录未 mkdir；非 production / 非真实 API 合同失败。同节点此前 `plan_provider_probe(spec=...)` 正向已通过。 |
| 规则 | test-owned 父目录由调用方先建立；不得改 support/`mkdir(parents=True)`、production builder 或错误处理掩盖前置；保持两处 unmocked 真实 API 正/负路径不变。 |
| 最小复现 | evidence `artifacts/agent_runs/m3-r2a-validation4-20260826T065000Z/`；focused stdout SHA `A9C0E7066543EE0427FB07A05E6C8F81722E387C9E7B0CE21FA24E5C72ACFA6A`；summary SHA `6CA985A9291DE2A8818F761D389E6B3771A3C123C9EA7B973027446E6B438BDC`。此前 carrier-invalid root 仅作承载失败历史，不计产品证据。 |
| 修正 | 仅 `tests/integration/test_m3_successor_upstream_stage.py`：`plan_root = tmp_path / "plan"`；`plan_root.mkdir()`；再 `_context(plan_root, ...)`。 |
| 通过条件 | STATIC_ONLY 交付闭合；production/其他 tests/taskbook/review 冻结；两真实 API 正向合同仍可达；**未**重跑验证；不宣称整包/Gate；交原 reviewer 复验后申请 VALIDATION5。 |

### 六要素行

| 项 | 现象 | 根因 | 规则 | 最小复现 | 新增/修正测试 | 通过条件 |
| --- | --- | --- | --- | --- | --- | --- |
| F-V4-1 | `_context(tmp_path/"plan")` → `FileNotFoundError` on `artifacts.mkdir` | 父目录未由测试创建 | §14.2 test-owned `plan_root` | focused 1 failed；stdout/summary SHA 如上 | integration：先 `plan_root.mkdir()` 再 `_context(plan_root)` | 父目录存在；probe+PROJECT builder 正路径与负例保持；support/production 未改 |

### 本轮边界

| 项 | 记录 |
| --- | --- |
| 写集 | 仅 integration upstream-stage 测试 + 本 delivery |
| production / unit tests / runtime / taskbook / review | **冻结** |
| 真实 API 合同 | `plan_provider_probe(spec=...)` 与 `build_backtest_plan_artifact(..., artifact_roots={"PROJECT": ...})` 实调、参数、返回断言、负向反例 **未改** |
| 零 Python | 未运行 Python / pytest / Ruff / mypy / cold / scripts / network / Qlib / stage / commit |
| 非宣称 | 73/1 非整包；不沿用本轮 focused 为 Gate；待 VALIDATION5 |

## 0H. VALIDATION5 真实 API fixture authority 隔离返工（任务书 §15）

| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION5 identity PASS；focused exact4 `73 passed / 1 failed / 374354 warnings`；§14 父目录已关闭且 `plan_provider_probe(spec=...)` 正向已通过；唯一失败仍在同一 integration 节点：provider support 之后，backtest-plan 深层 support 复用同一 monkeypatch authority，在 feature artifact 构造阶段稳定归一为 `M3_FEATURE_ARTIFACT_INVALID`，尚未进入 backtest-plan 正向调用。Ruff/mypy/cold/scope **UNRUN**。 |
| 根因 | 跨两套 formal fixture 共享单一 `monkeypatch` 生命周期，provider 侧 subprocess/runtime 替身残留污染第二套 support（与 R2S REWORK10 同类 authority 泄漏），非 production API 合同失败。 |
| 规则 | provider 真实调用与 backtest-plan 真实调用必须各置于独立 test-owned `pytest.MonkeyPatch.context()`；退出时由 pytest 精确恢复；禁止跨 fixture 共享残留 patch；不得改 production/把真实调用改回 mock/源码检查。 |
| 最小复现 | evidence `artifacts/agent_runs/m3-r2a-validation5-20260826T072447Z/`；focused stdout SHA `717DC4F54A946DF3B51BD8F27B6B0B991078CEC7E8FA9895F07BF29952A0A02B`；summary SHA `6C2815D0A0FBC5619CD3451F63B957C04C5701033D47FF5FEC956DA9F3F59017`。 |
| 修正 | 仅 `tests/integration/test_m3_successor_upstream_stage.py`：去掉外层共享 `monkeypatch` 形参；Authority A=`MonkeyPatch.context()` 承载 provider materialize + probe 正/缺 spec 负；Authority B=另一 `MonkeyPatch.context()` 承载 `plan_root.mkdir` + `_context` + PROJECT builder 正/错 alias 负（既有 `verify_target_artifact` alias 隔离 stub 仍仅在 B 内，不 stub builder）。 |
| 通过条件 | STATIC_ONLY 交付闭合；production/其他 tests/review 冻结；两真实 API 正负合同保留；**未**重跑验证；不宣称 73/1 整包；交原 reviewer 复验后申请 VALIDATION6。`CONTRACT_STOP` **未触发**（隔离本身即针对已识别 authority 泄漏，未要求扩 production）。 |

### 六要素行

| 项 | 现象 | 根因 | 规则 | 最小复现 | 修正测试 | 通过条件 |
| --- | --- | --- | --- | --- | --- | --- |
| F-V5-1 | plan support 前置 `M3_FEATURE_ARTIFACT_INVALID` | 共享 monkeypatch authority 泄漏 | §15.2 双独立 `MonkeyPatch.context()` | focused 1 failed；stdout/summary SHA 如上 | integration：provider 与 plan 分 context；离开即恢复 | 两 context 互不共享残留；probe+PROJECT 正路径与缺 spec/错 alias 负例仍在；support/production 未改 |

### 本轮边界

| 项 | 记录 |
| --- | --- |
| 写集 | 仅 integration upstream-stage 测试 + 本 delivery |
| production / unit / runtime / taskbook / review | **冻结** |
| 真实 API | `plan_provider_probe(spec=...)`、`build_backtest_plan_artifact(..., artifact_roots={"PROJECT": ...})` 仍为 unmocked 实调；返回类型/identity/负向反例保留 |
| 零 Python | 未运行 Python / pytest / Ruff / mypy / cold / scripts / network / Qlib / stage / commit |
| 非宣称 | 不得把 73/1 记为整包；M3 Gate 未关闭；待 VALIDATION6 |

## 0I. VALIDATION7 只读节点协议类型返工（任务书 §16）

| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION7 identity PASS；focused exact4 `74 passed / 374914 warnings`；Ruff production2/tests4 PASS；mypy production2 对 `successor_upstream_stage.py` 首失败 **9** 项；cold/scope **UNRUN**。§15 monkeypatch 隔离已由运行证据闭合。 |
| 根因 | `_ReceiptNodeView` Protocol 将 `_new_receipt_ref` 只读消费的 `node_id`/`fold`/`horizon` 声明为可写实例变量；真实 `StageNode`（frozen dataclass）与 `_SummaryNodeRef`（frozen dataclass）以只读属性提供这些成员，结构子类型被 mypy 拒绝。运行比较/receipt identity/发布未因此判红。 |
| 规则 | 只读消费成员须以 `@property` 抽象声明匹配只读结构子类型；不得 setter、mutable Protocol、Any/cast/type:ignore、扩大接受对象；不得改 `_new_receipt_ref` 函数体、StageNode/_SummaryNodeRef、业务语义或测试。 |
| 最小复现 | evidence `artifacts/agent_runs/m3-r2a-validation7-20260826T000444Z/`；focused SHA `5E6711F702211439E999082D6C66522B0BE976470B3CA70E4C1E7241BC21CCD8`；Ruff SHA `AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF`；mypy SHA `BF020D2F0C7741E88537FA22AB792C9B935DE4EE7CAD102C95C67541E9D5C0E0`；summary SHA `F569CABA36F3DBB64E301DADD5673D355B5497681F355E91509E4EC263A2B3CC`。 |
| 修正 | 仅 `successor_upstream_stage.py`：`_ReceiptNodeView` 三成员改为 `@property` + 精确返回类型（`str` / `str \| None` / `int \| None`）；无其他改动。 |
| 通过条件 | STATIC_ONLY 交付闭合；tests/其他 production/review 冻结；runtime/schema/identity 零变化；无 Any/cast/ignore；**未**重跑验证；交原 reviewer 复验后申请 postfix：identity→Ruff 实际修改 production→mypy production2→cold production2→exact9 scope（不重复已绿 focused74）。 |

### 六要素行

| 项 | 现象 | 根因 | 规则 | 最小复现 | 修正 | 通过条件 |
| --- | --- | --- | --- | --- | --- | --- |
| F-V7-1 | mypy 9 项拒绝 `_ReceiptNodeView` 结构子类型 | Protocol 可写字段 vs 只读 property/frozen 属性 | §16.2 `@property` 抽象声明 | mypy SHA 如上；9 errors / 1 file | `_ReceiptNodeView.node_id/fold/horizon` → `@property` | 仅注解变化；`_new_receipt_ref`/运行路径未改 |

### 本轮边界

| 项 | 记录 |
| --- | --- |
| 写集 | 仅 `src/quant/research/m3/successor_upstream_stage.py` + 本 delivery |
| tests / 其他 production / review / taskbook | **冻结** |
| 零 Python | 未运行 Python / pytest / Ruff / mypy / cold / scripts / network / Qlib / stage / commit |
| 非宣称 | 不宣称 9→0 已运行证实；不关闭 R2A/bridge/CLI/M3 Gate；待 postfix VALIDATION |

## 0J. VALIDATION1–8 Windows 工程验证组合证据闭包（任务书 §17）

经理授权 `EVIDENCE_UPDATE_READY`。本轮**仅**更新 taskbook + 本 delivery；production/tests/review **冻结**；零 Python / tools / scripts / stage / commit。

### 组合闭合（不得改写为单轮全绿）

| 组合 | 内容 |
| --- | --- |
| VALIDATION7 | focused exact4 **`74 passed`** + Ruff production2/tests4 **PASS**；修前 mypy **9 errors STOP**；cold/scope **UNRUN** |
| POSTFIX VALIDATION8 | identity、Ruff（实际 production）、mypy production2、cold production2、exact9 scope/diff/temp/process **全部 PASS** |
| 终态标签 | **`R2A_WINDOWS_ENGINEERING_VALIDATED`**（= `EXECUTABLE_STAGE_SUBSTRATE` Windows 工程闭包候选标签） |

### VALIDATION8 证据根与关键 SHA

| 项 | 记录 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m3-r2a-postfix-validation8-20260826T003929Z/` |
| identity | **PASS** |
| Ruff（实际修改 production） | **PASS** |
| mypy production2 | **PASS**；stdout SHA `07A5CA23E5D39B2565C0C1361F0556B8C3C75484BBA05841F400436D190BB660` |
| cold production2 | **PASS**；stdout SHA `FDB6604E0E2D6BA154D20B746709F7BE55A421A390955F144ECD8611E0E3B0EB` |
| exact9 scope/diff/temp/process | **PASS**；scope SHA `95BD7969B952C1C62269C0F63203BB9834D5759B3D6785C382960E0EE1AB5F17` |
| stage-summary SHA | `7BEE5B9B623FBDD6CA61DEDC59F6D170BE7A6477D6496BA7711DAFB5DCC71B51` |
| dirty / cache / residue | **actual8 ⊆ exact9**；**cached0**；diff/residue 按 summary **PASS** |

### VALIDATION7 联立证据（focused/Ruff；mypy 由 V8 postfix 闭合）

| 项 | 记录 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m3-r2a-validation7-20260826T000444Z/` |
| focused exact4 | `74 passed`；SHA `5E6711F702211439E999082D6C66522B0BE976470B3CA70E4C1E7241BC21CCD8` |
| Ruff production2/tests4 | **PASS**；SHA `AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF` |
| mypy production2（修前） | **9 errors** STOP；SHA `BF020D2F0C7741E88537FA22AB792C9B935DE4EE7CAD102C95C67541E9D5C0E0` |
| stage-summary SHA | `F569CABA36F3DBB64E301DADD5673D355B5497681F355E91509E4EC263A2B3CC` |
| cold / scope | **UNRUN**（首失败；V8 闭合） |

### VALIDATION1–8 真实失败/通过链与 UNRUN（历史保留）

| 轮次 | 边界 |
| --- | --- |
| VALIDATION1 | identity PASS；`61 passed / 3 failed`；Ruff/mypy/cold/scope **UNRUN**；空 carrier `CARRIER_INVALID_BEFORE_PRODUCT_EVIDENCE` |
| VALIDATION2 | identity PASS；`64 passed`；Ruff STOP；mypy/cold/scope **UNRUN** |
| VALIDATION3 | identity+Ruff PASS；mypy **115** STOP；cold/scope **UNRUN** |
| VALIDATION4 | identity PASS；`73 passed / 1 failed`；Ruff/mypy/cold/scope **UNRUN** |
| VALIDATION5 | identity PASS；`73 passed / 1 failed`；Ruff/mypy/cold/scope **UNRUN** |
| VALIDATION6 | §15 后授权完整 validation；focused74+Ruff 组合与 V7 证据根联立；不臆造独立产品 root |
| VALIDATION7 | focused74 + Ruff PASS；mypy 9 STOP；cold/scope **UNRUN** |
| VALIDATION8 | identity/Ruff/mypy/cold/scope **PASS**；actual8⊆exact9 / cached0 |

### 未验证边界（强制）

**不得宣称**：production bridge、CLI、actual worker、真实 Qlib、new root、retained、acceptance、更高 Gate 终态、**M3 Gate**。本状态仅 Windows 工程验证组合闭包；待原独立 reviewer `EVIDENCE_REVIEW` PASS 后方可申请安全提交。

## 7. 建议 Windows 验证顺序（经理授权后）

1. identity / exact9 dirty / `git diff --check`
2. focused：`tests/unit/test_m3_successor_upstream_stage.py`
3. focused：`tests/integration/test_m3_successor_upstream_stage.py`
4. focused：`tests/unit/test_m3_successor_runtime.py` + `tests/integration/test_m3_successor_runtime.py`
5. Ruff exact production+tests → mypy production2 → cold import `successor_upstream_stage`/`successor_runtime`
6. 不得宣称 Gate / bridge / actual worker

## 8. 边界与非宣称

- 未实现 production bridge / CLI / actual worker。
- 未跑真实 Qlib dump / provider materialization。
- formal backtest/tracking 与 reproducibility/readiness/acceptance 仍由既有 public formal API + 注入 callback 承担顺序；本包只绑定 upstream + R2S summary。
- 终态：`R2A_WINDOWS_ENGINEERING_VALIDATED`（VALIDATION7 focused74+Ruff ⊕ VALIDATION8 identity/Ruff/mypy/cold/scope；actual8⊆exact9 / cached0）。**不是** production bridge / CLI / actual worker / 真实 Qlib / new root / retained / acceptance / M3 Gate 闭合。
- 历史 VALIDATION1–7 首失败、carrier-invalid 与 UNRUN 边界永久保留于 §0C–§0I；不得改写为单轮全绿。
- 下一步：原独立 reviewer 仅写 review 执行 `EVIDENCE_REVIEW`；PASS 后方可申请安全提交。