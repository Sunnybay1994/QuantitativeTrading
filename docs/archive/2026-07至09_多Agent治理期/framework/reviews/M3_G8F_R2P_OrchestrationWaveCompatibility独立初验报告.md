# M3-G8F-R2P Orchestration Wave Compatibility 独立初验报告

日期：2026-08-25<br>
身份：未参与 R2 / R2A / R2P 实现与返工的全新独立静态复验 Agent（STATIC_ONLY）<br>
task id：`M3-G8F-R2P-ORCHESTRATION-WAVE-COMPAT`<br>
exact base / HEAD：`c124ec57e254672cd371ea04a732515a59c2fad1`<br>
branch：`codex/m3-g8f-r2p-orchestration-wave-compat`<br>
worktree：`artifacts/dev_worktrees/m3-g8f-r2p-orchestration-wave-compat`<br>
唯一写入：本报告<br>
结论：**DOC_REVIEW_PASS**（文档规范化终核；§0–§6 保留第 1 轮 **REVIEW_FAIL**；§7–§10 静态 PASS；§11 **EVIDENCE_REVIEW_PASS**）<br>
终态上限声明：本报告不表示 executable handler、bridge/CLI、actual worker、真实 Qlib、retained、acceptance 或 M3 Gate 完成。

## 0. 审查边界

- 已完整阅读：根 `AGENTS.md`、任务书、交付报告、中央冻结合同（任务书 §4–§7）、exact10 实现与测试 diff/源码。
- 只读业务 exact10（1–9）；未改实现 / 测试 / 任务书 / 交付报告。
- **未运行**：Python / pytest / Ruff / mypy / cold / SQLite / 真实 I/O / 网络 / Qlib / actual worker / commit。
- exact10 写面与 working tree 一致：生产 2 + 测试（含新 `test_m3_orchestration_project_root.py`）+ 三文档；`test_m3_orchestration_waves.py` 未改；未见 `__init__.py` / roadmap / handlers / `experiment_identity` / 旧 R2·R2A dirty 现场越界写入。
- 历史 R2/R2A 事故仅作对照；不把本包表述为 handler / bridge / actual worker 完成。

## 1. 中央合同逐项敌意核对

| # | 合同点 | 静态结论 | 证据摘要 |
| --- | --- | --- | --- |
| 1 | 六 builder 可选 keyword-only `artifact_roots=None`；legacy 路径不变 | **部分通过 / 证据不足** | 六函数签名均有 `artifact_roots: ... \| None = None`（`orchestration.py`）；`None` 走 `_verified_digest` legacy 分支（`resolve` + 调用方 alias）。测试仅对 **provider** 断言 omitted≡显式 `None` 的 `asdict`；**未**对其余五 builder 做 legacy bytes/identity 逐字回归，也**无**相对 exact base 的 golden。 |
| 2 | supplied 时 `select_artifact_root` 重算 alias/relative/size/SHA；禁止只换 alias | 通过（实现面） | supplied 分支忽略入参 alias，经 `select_artifact_root` 后写 `selected_alias` + `absolute.relative_to(selected_root)` + 重读 bytes（`_verified_digest`）。PROJECT remap 测试证明 relative 相对 PROJECT 重算且与 legacy 集合不等。缺“伪造 alias 字符串置换”显式对抗单测，但静态路径无法只改 alias。 |
| 3 | successor 传 `{"PROJECT": project_root}`；input/output receipt alias 为 PROJECT | 通过 | `make_project_stage_runner` / adapter `_runner` 强制 `roots == {"PROJECT": ...}`；work 内 `StageOutputInput` 经 `_stage_output_root_alias` 在单 root 时同步为该 alias。 |
| 4 | duplicate / nested / 越界 / symlink·reparse / relative 漂移 fail-closed | 通过（实现面+定向测） | `_optional_artifact_roots`→`_validate_roots` 拒空/物理重复/嵌套；越界由 `select_artifact_root` / `_read_plain_file` 拒绝；integration 覆盖 nested/duplicate/escaped。symlink/reparse 依赖既有 root/leaf 校验（交付已记残余风险）。 |
| 5 | `select_run_plan_nodes`：全量闭包、稳定排序、无缺/多/重复、纯选择 | 通过 | 要求 `type is RunPlan`、continuation exact、`expected_node_ids` 为无重复 `tuple[str]`、集合等于 plan 全 node-id；输出 `sorted`；无 I/O。unit + project-root 测覆盖缺/多/重复/错误 continuation/非 tuple/零目录副作用。 |
| 6 | 真实 wave 顺序；experiment-artifacts / label-reconciliation / work 各一次 | 通过（同 request 内） | `_UPSTREAM_WAVES` 顺序符合任务书 §5；public builders 键为 `experiment-artifacts`（非 `folds`）；禁 `labels`/`features`/`folds` 伪键；integration 断言三 builder 跨两 fold 各调用一次。 |
| 7 | labels+folds 与全 work nodes 映射真实 receipt；跨 fold 共享；fold 过滤 | 通过（同 request 内） | `_validate_wave_receipt_closure` 校验 experiment-artifacts / label-reconciliation / work 的 stage×fold×horizon 闭包；work 经 `_work_receipt_belongs_to_fold` 过滤；共享 labels 不进本 fold work 子集。 |
| 8 | 禁止伪 features/labels builder、第二 work SSOT、handler/placeholder | 通过 | 无 `make_features_run_plan`；未复制 work builder；successor 源码无 placeholder/handler；summary 仍独立 Gate API，不并入 upstream wave。 |
| 9 | wave cache 身份闭包：跨 fold / request / resume 不得复用错误 identity | **失败** | 见 §2 P0。`_wave_cache` 仅以 `wave: str` 为键；cache hit **跳过** `_validate_wave_receipt_closure`；公开 `make_production_successor_stage_adapter` + `run_two_fold_successor` 允许同一 adapter 跨 request/resume 复用。 |

## 2. 发现分级

### [P0] wave cache 仅按 wave 名缓存，跨 request/resume 可复用错误 identity — `src/quant/research/m3/successor_runtime.py`

`ProductionSuccessorStageAdapter._wave_cache: dict[str, tuple[StageReceiptRef, ...]]`，`_cached_wave` 在 hit 时直接返回，不绑定 `two_fold_identity` / `project_root` / fold 集合 / config·release 摘要 / `resume`，也不对**新** `context.request` 重跑闭包校验。

同一次 `run_two_fold_successor(request=A)` 内跨 fold 共享是合同要求且测试已覆盖；但公开 API 允许：

1. `adapter = make_production_successor_stage_adapter(...)`
2. `run_two_fold_successor(request=A, api=adapter, resume=True)` → 填满 cache
3. `run_two_fold_successor(request=B, api=adapter, resume=False)` → **整袋 wave receipt 来自 A**，且 B 的 `resume` 被忽略

`FoldExecution` 会把 **B 的** `config_*` / `g1_release_*` 与 **缓存自 A 的** snapshot/experiment/work receipts 拼在一起；`_validate_fold_execution` 只校验 execution 字段与 fold_request 自洽、receipt 与 execution 内 scope_key 自洽，**不**把 receipt 链重新绑到 B 的 release/config/project 身份。同 project、同 fold 名、不同 experiment/release 时，错误 identity 可穿过 fold 校验。

`run_production_two_fold_successor` 每次新建 adapter，不能豁免公开 `make_production_successor_stage_adapter` / `run_two_fold_successor` 组合面。

### [P1] 六 builder legacy bytes/identity「逐字回归」证据不闭合 — 测试面

任务书 §7.1 要求六个 builder 在 `artifact_roots=None` 时 canonical bytes/plan identity 逐字回归。交付与测试仅证明 provider 的 omitted≡`None`；其余五 builder 无对等 `asdict`/canonical 断言，亦无相对 exact base 的 frozen golden。STATIC_ONLY 下测试即主证据，该强制反例未闭合。

### 无其他 P0/P1（在「同 adapter ≡ 同 request」前提下）

select API、PROJECT remap 主路径、伪 builder 拒绝、单次 wave 发布、summary Gate 边界、无 handler/placeholder 的静态阅读通过。

## 3. 实现者未使用的对抗反例（新增）

### 反例 W1（wave cache × 跨 request × resume；实现者未覆盖）

**最小静态复现（未执行）：**

1. 构造同一 `dependencies` 下的 `adapter = make_production_successor_stage_adapter(...)`。
2. `run_two_fold_successor(request=A, api=adapter, resume=True)`，使 `_wave_cache` 含 `experiment-artifacts` / `label-reconciliation` / `work` 等键。
3. 再 `run_two_fold_successor(request=B, api=adapter, resume=False)`，其中 B 与 A 同 `project_root`、同 fold 名，但不同 `two_fold_identity`（不同 config/release/experiment 上游）。
4. 观察：`run_upstream_wave` 对 B **不再**被调用（cache hit）；返回的 fold receipts 的 scope_key 仍属 A，而 `FoldExecution.config_*` / `g1_release_*` 来自 B。
5. 预期（合同）：要么拒绝跨 request 复用 adapter（fail closed），要么 cache 键包含 `two_fold_identity(+resume)` 且 hit 时对 B 重验闭包；**不得**静默混用 A 的 wave identity 与 B 的请求元数据。

**通过条件：** 新增定向测试断言 (a) 同 adapter 第二 request 必重建或拒绝；(b) 不同 `resume` 不得命中错误 cache；(c) 同 request 跨 fold 仍只调用三 builder 各一次。

### 反例 W2（补充：六 builder legacy 全覆盖；实现者未覆盖）

对 `make_provider_validation_run_plan` / `make_experiment_artifact_run_plan` / `make_label_reconciliation_run_plan` / `make_work_run_plan` / `make_summary_run_plan` 在相同 fixture 下断言 omitted ≡ `artifact_roots=None` 的 plan `asdict`（或 canonical bytes）相等，并与 exact base 行为对齐；仅 provider 不足。

## 4. 失败项（现象—根因—规则—最小复现—通过条件）

### F1 — wave cache 跨 request/resume 错误 identity

| 字段 | 内容 |
| --- | --- |
| 现象 | 同一 `ProductionSuccessorStageAdapter` 上后继 request/resume 可吃到前序 wave receipts |
| 根因 | `_wave_cache` 键仅为 wave 名；hit 跳过闭包重验与 identity 绑定 |
| 规则 | 任务书 §5 跨 fold 共享必须在**同一** runtime request 身份下；不得跨 request 复用；resume 语义不得被无键 cache 吞掉 |
| 最小复现 | 反例 W1 |
| 新增测试 | 跨 request cache poison；跨 resume；同 request 双 fold 仍单次 builder |
| 通过条件 | 错误混用 fail closed 或 cache 键含 request identity+resume，且 hit 路径重验闭包 |

### F2 — 六 builder legacy 逐字回归证据缺口

| 字段 | 内容 |
| --- | --- |
| 现象 | 仅 provider 有 omitted/`None` 相等断言 |
| 根因 | 测试未覆盖其余五 builder；无 base golden |
| 规则 | 任务书 §7.1 |
| 最小复现 | 反例 W2 |
| 新增测试 | 五 builder +（建议）相对 base 的 identity 快照 |
| 通过条件 | 六 builder 全部证明 legacy 逐字不变 |

## 5. 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| SQLite / 网络 / Qlib / actual worker / retained | **未运行** |
| commit / 改实现·测试·任务·交付 | **未做** |

## 6. 总判

**REVIEW_FAIL**

同 request 内真实 wave 顺序、单次 builder、receipt 形状闭包、`select_run_plan_nodes`、PROJECT remap 主路径静态可读且大体贴合合同；但 **wave cache 身份键缺失**构成可演示的跨 request/resume 错误 identity 复用，且强制 legacy 六 builder 逐字回归证据未闭合。须返工并经新独立初验复验后，方可申请 CPU8–11 与 `ORCHESTRATION_WAVE_COMPAT_VALIDATED` 相关推进。

返工不得扩大为 handler / bridge / actual worker / 第二 work SSOT 实现。

---

## 7. 第 2 轮静态复验（返工后 · 2026-08-25）

身份：未参与实现/返工的全新独立静态复验者。<br>
已完整阅读：根 `AGENTS.md`、任务书、交付（含 F1/F2 返工段）、本报告 §0–§6 历史 FAIL、exact10 现行源码与测试。<br>
只读业务 exact10（1–9）；**仅**追加本报告。<br>
**未运行**：Python / pytest / Ruff / mypy / cold / SQLite / 真实 I/O / 网络 / Qlib / actual worker / commit。<br>
未改生产 / 测试 / 任务书 / 交付。<br>
工作树 exact10：生产 2 + 测试（含新 `test_m3_orchestration_project_root.py`）+ 三文档；`test_m3_orchestration_waves.py` 仍无本包 diff；未见 `__init__.py` / roadmap / handlers / `experiment_identity` 模块 / 旧 R2·R2A dirty 越界写入。

### 7.1 F1 复验 — wave session 绑定与 cache

| 检查点 | 静态结论 | 证据 |
| --- | --- | --- |
| 单 canonical binding | **通过** | `ProductionSuccessorStageAdapter` 持 `_wave_binding: (two_fold_identity, project_root, resume, expected_folds)`；首 fold 冻结，其后不等则 `_fail("SUCCESSOR_INPUT_INVALID")`（`successor_runtime.py` `_bind_runtime_wave_session` / `_assert_wave_binding`） |
| exact `project_root` | **通过** | 经 `_real_directory` 解析后比较；非调用方生 Path 字符串 |
| 两不同 fold 各消费一次 | **通过** | `_consumed_folds`；重复 fold / 已满两折后再调 → `SUCCESSOR_STAGE_INVALID` |
| 跨 request / resume | **通过** | 测试 `test_wave_cache_rejects_cross_request_poison_and_resume_drift`：同 request `resume=True`→`False` 拒；完成后同 adapter 喂 request B 拒 `SUCCESSOR_INPUT_INVALID` |
| 重复 / 第三 fold | **通过** | `test_wave_cache_rejects_duplicate_and_third_fold_consumption`；且三 builder 仍各一次 |
| cache hit 重跑 closure | **通过** | `_cached_wave` hit 路径调用 `_validate_wave_receipt_closure` + node_id 排序/去重/类型校验，**禁止**裸 return |
| 不混 A/B receipts | **通过** | 异 binding 在进入 cache 前失败；同 binding 下 hit 仍按**当前** `context.request` 重验闭包形状 |
| 失败中途 | **评估通过（fail-closed）** | `_bind_runtime_wave_session` 在 wave 执行前即 `add(fold)`；中途失败后同 fold 再入 → `SUCCESSOR_STAGE_INVALID`，不得清 binding 吞异 request。属显式消费一次语义，非静默跨 identity 复用 |
| 同 identity 不同对象 | **评估通过** | 绑定比较 `two_fold_identity(...)` 字符串与 resolved project / resume / expected_folds，不依赖 Python 对象 id；同 identity 会话共享 cache 为合同允许，异 identity 拒绝 |
| 折顺序攻击 | **评估通过** | `SuccessorRuntimeRequest` 强制 folds 名字典序；消费顺序 fold_002→fold_001 仍受同一 binding/`_consumed_folds` 约束，不能借乱序打开第三折或换 identity |

**F1 历史 P0 已闭合。** 无新 P0/P1。

残余（不阻断本轮静态 PASS，供 CPU 阶段留意）：binding 键集合按返工合同**不含** `controlled_output_root` / `runtime_identity` / `now`；同 `two_fold_identity`+同 project+同 resume 下不同 output root 的对象会被视为同一 wave session。闭包校验仍偏 stage×fold×horizon 形状，深度 scope/path 绑定依赖既有 fold/terminal 校验链。

### 7.2 F2 复验 — 六 builder legacy omitted ≡ None

| 检查点 | 静态结论 | 证据 |
| --- | --- | --- |
| 六 builder keyword-only default None | **通过** | `test_six_builders_accept_optional_artifact_roots_keyword_only` |
| provider omitted≡None | **通过** | `test_m3_orchestration_project_root.py` 中 provider `asdict` 相等 |
| 其余五 builder omitted≡None | **通过** | `test_remaining_five_builders_legacy_omitted_equals_explicit_none`：`asdict` + dataclass `==` |
| 不读 Git / 无第二 serialization | **通过** | 测试无 git/subprocess/golden/第二套 codec；仅 plan 对象等价 |
| legacy 源码分支保留 | **通过** | `_verified_digest`：`artifact_roots is None` 仍走 `resolve` + 调用方 alias；supplied 才 `select_artifact_root` 重算 |

**F2 历史 P1 已按返工通过条件闭合**（dataclass/canonical identity 等价，非 Git base golden）。

### 7.3 快速回扫（非夸大）

| 项 | 结论 |
| --- | --- |
| PROJECT 重算 | supplied 经 `select_artifact_root` 重算 relative/size/SHA；integration 覆盖 nested/duplicate/escaped 与 PROJECT alias |
| wave 一次 | `_UPSTREAM_WAVES` 含 experiment-artifacts / label-reconciliation / work；同 request 双 fold 测试断言三 builder 各一次 |
| 无伪 builder/handler/第二 SSOT | 无 `make_features_run_plan`；禁 `labels`/`features`/`folds` 伪键；本包未新增 placeholder handler；未复制第二 work builder；summary 仍独立 Gate |
| 终态上限 | **不**宣称 executable handler / bridge/CLI / actual worker / 真实 Qlib / Linux 或 M3 Gate |

### 7.4 实现者未覆盖的对抗反例（本轮新增）

#### 反例 W3（同 project · identity 漂移 · 失败中途消费；实现者未单测）

实现者 poison 测用 `tmp_path / "poison-b"`（**异 project**）触发拒绝。本轮补充：

1. **同 `project_root`、同 `resume`、同 fold 名，但不同 config/release → 不同 `two_fold_identity`：** 第一 request 填满 cache 后，同 adapter 喂第二 request。预期：`_wave_binding` 因 identity 不等 → `SUCCESSOR_INPUT_INVALID`；**不得** cache hit 混入 A 的 receipts。静态路径：`_bind_runtime_wave_session` 在 `_cached_wave` 前比较 binding，已闭合。
2. **失败中途：** 第一 fold 在某 upstream wave 抛错前已写入 `_consumed_folds` 与部分 `_wave_cache`。再 `run_fold` 同 fold → `SUCCESSOR_STAGE_INVALID`；另起异 identity request → `SUCCESSOR_INPUT_INVALID`。不得借“重试”清 session 或拼接异 identity receipts。静态路径已闭合。
3. **折逆序：** 同 binding 下先 `fold_002` 再 `fold_001` 仍只允许两折、三 builder 各一次（与正序同构）。

**通过条件（建议 CPU 阶段补测，非本轮 STATIC 阻断）：** 定向测覆盖同 project identity 漂移 + 中途失败后再入同 fold / 异 request。

### 7.5 历史 FAIL 映射

| 历史项 | 本轮 |
| --- | --- |
| F1 P0 wave cache 无 identity | **已修复并复验通过** |
| F2 P1 五 builder legacy 证据缺口 | **已修复并复验通过** |
| 反例 W1 / W2 | 已由返工测试覆盖；本轮另增 W3 |

### 7.6 第 2 轮未运行边界

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| SQLite / 网络 / Qlib / actual worker / retained | **未运行** |
| commit / 改实现·测试·任务·交付 | **未做** |

### 7.7 第 2 轮总判

**REVIEW_PASS**

F1 adapter 单 session 绑定（`two_fold_identity` + exact `project_root` + `resume` + `expected_folds`）、两折一次消费、跨 request/resume/重复/第三折拒绝、cache hit 重验 closure、不混 A/B；F2 六 builder omitted≡显式 `None` 的 RunPlan 等价且 legacy `_verified_digest` 分支保留、无 Git/第二 serialization。快速回扫 PROJECT / 单次 wave / 无伪 builder·本包 handler·第二 SSOT 通过。历史 §6 **REVIEW_FAIL** 原文保留。

本结论仅静态合同闭合；**不**表示 CPU8–11、executable handler、bridge/CLI、actual worker 或 M3 Gate 已完成。可向中央申请后续定向动态验证。

---

## 8. 第 3 轮静态复验（VALIDATION1-FIXTURE / F3 · 2026-08-25）

身份：未参与实现/返工的独立静态复验者。<br>
已读：任务书 §9（F3）、交付 §0 F3 / §0.1、exact10 现行 plans 测试与 boundary 生产签名；对照 §7 W3。<br>
只读业务 exact10 / 任务 / 交付；**仅**追加本报告。<br>
**未运行**：Python / pytest / Ruff / mypy / cold / 网络 / 提交。

### 8.1 本轮写面（F3）

| 声明 | 静态核对 |
| --- | --- |
| 仅改 `tests/unit/test_m3_orchestration_plans.py` 两失败测 stub + 任务书 + 交付 | **通过（合同面）**：两测 stub 已改为 `lambda *_args, artifact_roots=None: (_external(),)`；任务书 §9、交付 F3/0.1 补 VALIDATION1 证据。工作树仍含既有 F1/F2 生产与其他测试 diff，**非**本轮 F3 新增。 |
| production / 其他测试本轮不变 | **通过**：F3 未改 `orchestration.py` / `successor_runtime.py` / successor·project-root·waves 测试；review 此前只读。 |

### 8.2 F3 — 两失败测 stub 与断言

| 测试 | stub | 返回值 / 身份断言 / legacy |
| --- | --- | --- |
| `test_work_scope_keys_only_use_verified_experiment_and_work_identity` | `_fold/_experiment/_label/_reconciliation_boundary_inputs` → 显式 keyword-only `artifact_roots=None` | 仍返回 `(_external(),)`；`scope_key`/`compute_work_key`/`receipt_path`/`expected_stages`/foreign identity `ValueError` 断言未改；调用仍为默认 omit（legacy `roots is None`） |
| `test_development_summary_uses_verifier_receipt_stage` | `_experiment/_evaluation_boundary_inputs` → 同上 | 仍返回 `(_external(),)`；node 数/horizon/`development-research-summary` receipt 前缀/inputs 长度/verifier 源码断言未改；默认 omit legacy |

生产 boundary 签名均为 `*, artifact_roots: ... \| None = None`；`make_work_run_plan` / `make_summary_run_plan` 以 `artifact_roots=roots` keyword 转发。stub 现可接受该 keyword，消除 VALIDATION1 所示 `TypeError`。

同文件 `test_summary_rejects_single_fold_and_foreign_example_identity` 仍为 `lambda *_args`（无 `artifact_roots`）。静态读 `make_summary_run_plan`：fold closure / example identity 在调用 boundary **之前** fail-closed，故该测不触达 stub；**非**本轮合同缺口，不构成 FAIL。建议后续一并改签名以免将来路径漂移。

### 8.3 W3 动态覆盖核对（中央要求）

| W3 节点 | 现有动态测 | 结论 |
| --- | --- | --- |
| 同 project identity 漂移 | poison 测用 `tmp_path/"poison-b"`（**异 project**） | **缺失显式节点** → 验证建议 |
| 失败中途再入同 fold / 异 request | 无定向 mid-fail 后再 `run_fold` | **缺失** → 验证建议 |
| fold 逆序（002→001） | 现测均为 `folds[0]`→`folds[1]` | **缺失** → 验证建议 |

生产路径（§7.1）仍静态闭合上述攻击；按中央口径：**仅记验证建议，不因缺失动态节点 FAIL**。无新真实合同缺口。

### 8.4 第 3 轮未运行边界

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| 网络 / 提交 / 改生产·其他测试·任务·交付 | **未做**（本报告除外） |

### 8.5 第 3 轮总判

**REVIEW_PASS**

F3 stub 签名与两失败测身份/legacy 断言静态对齐；本轮写面限于 plans 两测 + 任务/交付；W3 三节点仍缺显式动态覆盖，记入后续授权复跑建议，不阻断。历史 §6 FAIL 与 §7 PASS 原文保留。不宣称 handler / bridge / actual worker / Gate 完成。

---

## 9. 第 4 轮静态复验（VALIDATION2-F4 · 2026-08-25）

身份：同一独立外部 reviewer（未参与实现/F4 返工）。<br>
已读：任务书 §10、交付 F4/§0.2、exact10 现行 `orchestration.py`、VALIDATION2 evidence root。<br>
只读 exact10 / 任务 / 交付 / evidence；**仅**追加本报告。<br>
**未运行**：Python / pytest / Ruff / mypy / cold / 提交。

### 9.1 写面与证据绑定

| 项 | 静态结论 |
| --- | --- |
| F4 生产改动 | **通过**：`_release_label_inputs` 将 `manifest = next(...)` 改为无绑定 `next(...)`（现 L2284–2287）；其后 `entries`/bytes-drift 循环与 `sorted` 返回未改 |
| 无其他生产/测试越界（本轮） | **通过（合同面）**：F4 声称仅该赋值 + 任务书/交付；未改 successor、测试断言语义；同文件其余仍使用结果的 `manifest = next(...)`（L1967/2135/2246）保留 |
| evidence root | **通过**：`artifacts/agent_runs/m3-r2p-validation2-20260825T142500Z-a7f3` 存在于本 worktree |
| `06-ruff` stdout SHA | **通过**：重算 SHA-256=`355b0a73f1069325fa56ef30c15effa373eba02bf3f137d0b92a4b07244720ec`，与任务书/交付一致；日志正文为 F841 @ `orchestration.py:2284` `manifest = next(` + `sha256 == release.manifest_sha256`；`06-ruff.exit`=`1` |

### 9.2 失败语义与 bytes/控制流

| 检查 | 结论 |
| --- | --- |
| 匹配不存在 → `StopIteration` | **通过**：裸 `next(...)` 在 generator 空时仍抛 `StopIteration`；无新增 swallow/`except` |
| 外层稳定失败 | **通过**：`make_experiment_artifact_run_plan` 直接展开 `*_release_label_inputs(...)`，无改包装；失败模式与 F4 前（已为 sha256 谓词的 `next`）一致 |
| digest / wave / receipt | **通过**：`_verified_digest` 构造、`inputs` 元组、entries 校验、返回排序均未因去绑定而变；仅消除未使用局部名 |

### 9.3 实现者未使用的对抗检查（本轮新增）

**反例 W4（误伤其他 `manifest = next` / 静默吞失败）：**

1. 若把 L1967/2135/2246 等**仍消费** `manifest.artifact.sha256` 的赋值也改成裸 `next`，会改变后续 drift 断言控制流。静态确认 F4 **未**改动这些位点。
2. 若用 `# noqa: F841` 或 `_ = next(...)` 掩盖而未保留校验，属合同偏离。现行为显式语句级 `next(...)`，校验副作用保留。
3. sha256 谓词下「无匹配」与「全不匹配」均走 `StopIteration`（相对 exact base 曾用 path+`ValueError` 的分流，属本包更早 R2P 语义，**非** F4 引入）；F4 未再削弱该校验。

### 9.4 第 4 轮未运行边界

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| 提交 / 改实现·测试·任务·交付 | **未做**（本报告除外） |

### 9.5 第 4 轮总判

**REVIEW_PASS**

F4 仅为消除 `_release_label_inputs` F841 未使用赋值并保留 `next` 校验副作用；digest/wave/receipt 与后续控制流除去未使用绑定外不变；VALIDATION2 evidence root 与 Ruff stdout SHA 核对一致；无本轮越界。历史 FAIL/PASS 轮次原文保留。不宣称 Ruff 复跑绿、handler/bridge/actual worker 或 M3 Gate 完成。

---

## 10. 第 5 轮静态复验（VALIDATION3-F5 · 2026-08-25）

身份：同一独立外部 reviewer（未参与实现/F5）。<br>
已读：任务书 §11、交付 F5/§0.3、`successor_runtime.py` 现行闭包、VALIDATION3 evidence。<br>
只读 exact10 / 任务 / 交付 / evidence；**仅**追加本报告。<br>
**未运行**：Python / Ruff / mypy / cold / 提交。

### 10.1 证据与写面

| 项 | 静态结论 |
| --- | --- |
| evidence root | **通过**：`artifacts/agent_runs/m3-r2p-postfix-validation3-20260825T151500Z-d42b` 存在 |
| mypy stdout SHA | **通过**：重算 `03-mypy.stdout.log` SHA-256=`c348414b6fce19d607a2a9c518ba4a15bc528a40b9a13edeeeeee96a11615c93`；正文为四错：`expected` no-redef + 二元/三元 `add`/comprehension 冲突（修复前现场） |
| F5 写面 | **通过（合同面）**：仅 `successor_runtime.py` 引入 `_WaveReceiptKey` + `_validate_wave_receipt_closure` 分波命名；任务/交付绑定；测试未因 F5 改断言 |

### 10.2 `_WaveReceiptKey` 与集合统一

| 检查 | 结论 |
| --- | --- |
| 窄三元类型 | **通过**：`_WaveReceiptKey = tuple[str, str \| None, int \| None]`（L50）≡ stage / fold / horizon |
| expected/actual/推导/add | **通过**：三波均为 `set[_WaveReceiptKey]`；actual 均自 `(item.stage, item.fold, item.horizon)`；work 侧 `add(("features", fold, None))` / `add((stage, fold, horizon))` |
| 两语义 expected 改名 | **通过**：不再复用 `expected`；`expected_experiment_artifact_keys` / `expected_label_reconciliation_keys` / `expected_work_keys`（及对应 `actual_*`）分波清晰 |
| 共享 wave fold=`None` | **通过**：experiment-artifacts / label-reconciliation 期望键显式第三/第二元为 `None` |
| `fold is not None` 分支 | **通过**：两共享 wave 在集合比较后仍保留 `any(item.fold is not None)` fail-closed |
| 运行分支 / 集合内容 / 排序 / 错误码 / identity / schema | **通过**：`_SHARED_SINGLE_WAVES` 早退未改；比较仍为集合相等 + `len(refs)`；失败仍裸 `ValueError`（外层既有 `SUCCESSOR_STAGE_INVALID`）；未改 receipt/terminal schema 或 identity 函数 |
| 无 `type: ignore` / 本面无 `Any` | **通过**：F5 改动区无 ignore、无 `Any`；文件既有 JSON/`Protocol` 处 `Any`/`cast` **非**本轮引入 |

### 10.3 实现者未使用的对抗检查（本轮新增）

**反例 W5（fold/horizon 错位与二元回归）：**

1. labels receipt 带非空 `fold`：旧二元 `observed=(stage,horizon)` 可能先集合命中再靠 `fold is not None` 拒绝；现三元键直接集合不等 + 仍保留 fold 检查 → 仍 fail-closed，错误类型不变。
2. features 误带 `horizon=int` 或 work stage 误带 `horizon=None`：三元键与 `expected_work_keys` 不等 → `ValueError`，与改名前语义同构。
3. 若再次把不同波的 expected 压回同名局部变量，将重现 evidence 中 `no-redef`/宽度冲突；现分波命名阻断该回归。

### 10.4 第 5 轮未运行边界

| 项 | 状态 |
| --- | --- |
| Python / Ruff / mypy / cold | **未运行** |
| 提交 / 改实现·测试·任务·交付 | **未做**（本报告除外） |

### 10.5 第 5 轮总判

**REVIEW_PASS**

F5 以统一 `_WaveReceiptKey` 与分波 `expected_*`/`actual_*` 闭合 VALIDATION3 mypy 四错；fold/horizon None 与错位比较仍 fail-closed；evidence root 与 mypy SHA 核对一致。历史轮次原文保留。不宣称 mypy 复跑绿、handler/bridge/actual worker 或 M3 Gate 完成。

---

## 11. 组合证据终核（EVIDENCE_REVIEW · 2026-08-25）

身份：同一独立外部 reviewer。<br>
只读 exact10 实现路径、任务书 §12、交付 §0.4、VALIDATION2 / VALIDATION4 evidence；**仅**追加本报告。<br>
**未运行**：Python / pytest / Ruff / mypy / cold；未改 production / tests / taskbook / delivery；未提交。

### 11.1 VALIDATION2 focused `13+15+5+36` PASS

| 项 | 核对 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m3-r2p-validation2-20260825T142500Z-a7f3` **存在** |
| stage-summary | `02`–`05` 均为 `exit=0`；`06-ruff exit=1` + `STOP`（与任务/交付「focused 绿、当时 Ruff F841」一致；lint 不以本根宣称通过） |
| plans | stdout「`13 passed`」；SHA-256=`8bef482a74e60bb036d3682550b6c1e7b7569e121a61903533c9f4461f131af3`；exit=`0` |
| waves | stdout「`15 passed`」；SHA-256=`0b82745ad1631da413af63e532a3ecaf33694f2ca738b25117d6be3540fcbe55`；exit=`0` |
| project-root | stdout「`5 passed`」；SHA-256=`77d0f1dea53f2d4f9b83426ab55c2f7845e1da2f6f132b237d80b9d01f46ffc2`；exit=`0` |
| successor | stdout「`36 passed`」；SHA-256=`0b2305b0da161bb87ba671ff9765877f9faf337892cf56e3bc7547fcb664045d`；exit=`0` |

**结论：focused 13+15+5+36 PASS 原生证据闭合。**

### 11.2 POSTFIX VALIDATION4 全 PASS

| 项 | 核对 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m3-r2p-postfix-validation4-20260825T160000Z-f19a` **存在** |
| stage-summary | `01-identity`…`07-process-residue` **全部 exit=0**；summary SHA-256=`f43b88a6b1c033e4b165aa71657fc1606a39f1c4a32fa84429bc5d894b65f275`（与任务/交付一致） |
| Ruff stdout | 「All checks passed!」；SHA-256=`82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` **匹配** |
| mypy stdout | 「Success: no issues found in 2 source files」；SHA-256=`0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2` **匹配** |
| cold stdout | 仅两生产路径；SHA-256=`85b01af69016a727b65564a6669e32fa364c216cf51e3276cdd140e88a661138` **匹配** |
| scope stdout | SHA-256=`505d79fd5baea8c04dc1530a513bf778723e7e906b21923f09e2bdf4f465d0bd` **匹配** |
| runner | SHA-256=`3c147c5156a8822987918961069d5386d003edef666ab5b0848e4cf8b0bd801d` **匹配** |
| diff / process | `06-scope-diff-check` exit=0（stdout 空）；`07-process-residue` exit=0 |

**结论：identity / Ruff / mypy2 / cold / scope / diff / process 全 PASS。**

### 11.3 exact10 scope

VALIDATION4 `05-scope-status` 与当前工作树一致：**9/10** dirty/untracked（生产 2 + plans/successor unit·integration + 新 project-root + 任务/交付/本 review）；**`tests/unit/test_m3_orchestration_waves.py` 未改**。`artifacts/agent_runs/**` 证据属 ignored，**不属提交面**。

### 11.4 终态边界诚实性

任务书 §12 / 交付 §0.4：**Windows 定向开发闭合**已写明；同时明确 **未**验证 executable handler、bridge/CLI、actual worker、真实 Qlib、new root、retained、Gate。与证据及前序静态轮次一致，**无夸大**。

### 11.5 本轮未运行 / 未改

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| production / tests / taskbook / delivery | **未改** |
| 提交 | **未做** |

### 11.6 证据审查总判

**EVIDENCE_REVIEW_PASS**

VALIDATION2 focused 原生 PASS + VALIDATION4 post-fix 关键 SHA 全绿 + exact10 9/10（waves 未改）+ 终态边界诚实。历史静态 FAIL/PASS 原文保留。本判仅组合证据复核，**不**把本包升格为 handler/bridge/actual worker/Gate 完成。

---

## 12. DOC_REVIEW（文档规范化 · 2026-08-25）

身份：同一独立 reviewer。仅规范化本报告；未改 taskbook / delivery / production / tests；零 Python / 测试 / 提交。

### 12.1 规范化动作

- 全部行尾空白归零（规范化前 37 处）。
- 连续行强制换行（原行尾双空格）改为显式 `<br>`；列表/表格项仅去空白、不加 `<br>`。
- 未改结论语义、证据路径、证据 SHA、未验证边界表述。
- 无 whole-file / prefix / section SHA 自证明字段，故无回填。

### 12.2 三文档静态核对（未漂移）

| 文档 | SHA-256（规范化后只读核对） | 行尾空白 |
| --- | --- | --- |
| 任务书 | `879fcadac33e3d8c2dedde780021883248210a0982746e21f8fbed611ba15020`（与实现者声明一致） | 0 |
| 交付 | `86eec053b246b41a86dab9de31ea143b34247b8361cb3e6d2c99346467931976`（与实现者声明一致） | 0 |
| 本报告 | 会话回报 SHA（无整文件自证字段，不回填本文） | 0 |

关键证据边界仍一致：VALIDATION2 root `m3-r2p-validation2-20260825T142500Z-a7f3`；VALIDATION4 root `m3-r2p-postfix-validation4-20260825T160000Z-f19a`；Ruff/mypy/cold/scope/summary/runner 关键 SHA 与任务书 §12 / 交付 §0.4 一致；三文档均保留 Windows 定向闭合与 handler/bridge/CLI/actual worker/真实 Qlib/new root/retained/Gate **未**验证边界。§11 **EVIDENCE_REVIEW_PASS** 原文保留。

### 12.3 DOC_REVIEW 总判

**DOC_REVIEW_PASS**
