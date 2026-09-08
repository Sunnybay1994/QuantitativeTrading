# M3-G8F-R2A After-R2S Upstream Executable Stage 独立初验报告

日期：2026-08-26<br>
身份：未参与实现 / 授权重实现采用的全新独立初验者（STATIC_ONLY；无 subagent / 委派）<br>
task id：`M3-G8F-R2A-AFTER-R2S-UPSTREAM-EXECUTABLE-STAGE`<br>
exact base / HEAD：`d525770ac9deb78e414098308b34acbd0773c099`<br>
branch：`codex/m3-g8f-r2a-upstream-executable-stage-after-r2s`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2a-upstream-executable-stage-after-r2s`<br>
唯一写入：本报告<br>
结论：**REVIEW_FAIL**<br>
终态上限声明：本报告不表示 `EXECUTABLE_STAGE_SUBSTRATE_WINDOWS_VALIDATED`、production bridge、CLI、actual worker、真实 Qlib、new root、retained、acceptance 或 M3 Gate 完成；亦不构成运行态验证。

## 0. 审查边界

- 已完整阅读：根 `AGENTS.md`、`.ai/README.md`、任务书、交付报告（含 §0 历史 Python 违规永久记录与 §0A 授权采用）、exact9 业务文件 1–6。
- production / tests / taskbook / delivery：**只读**；未改实现、未改测试、未改任务书、未改交付。
- **STATIC_ONLY 遵守**：未运行 Python / 脚本 / `ast.parse` / pytest / Ruff / mypy / cold / 真实 Qlib / network / commit；未创建或调用 subagent。
- dirty 观察（只读）：`M successor_runtime.py`、`M tests/integration/test_m3_successor_runtime.py`；未跟踪 `successor_upstream_stage.py`、两份 upstream 测试、task/delivery；HEAD 仍为 exact base。
- 承认交付 §0：历史实现曾用 `python -c` 文本替换（**不构成验证**）；§0A 声称本轮零 Python 重实现采用——本审查不复验该执行面，只审当前源码/测试合同闭合。

## 1. 中央合同逐项静态核

| # | 合同点 | 静态结论 | 行号证据摘要 |
| --- | --- | --- | --- |
| 1 | R2P：完整 wave plan / PROJECT-only / `select_run_plan_nodes` / `StageRunner` | **通过（实现面）** | 七 wave handler 均 `plan_builder` + `select_run_plan_nodes` 全闭包（如 `successor_upstream_stage.py` 900–904、1452–1455、1768–1771、2308+）；`SuccessorStageContext.artifact_roots` 仅 `{"PROJECT": ...}`（`successor_runtime.py` 630–633）；adapter `_runner` 强制 PROJECT-only（1350–1378）。 |
| 2 | R2S summary binding | **通过（实现面）** | `run_successor_formal_summary_gate` 本地 import `run_formal_summary_stage`（2695、2781–2786）；`stage_root=project_stage_root(...)`（2774–2782），无 `parents[2]`；`CANONICAL_RUN_SUMMARY_GATE` 别名（2808）。 |
| 3 | `SuccessorToolchainBinding` exact Path / DEFAULT dump / tool spec / twofold identity | **通过（实现面）** | 类型 SSOT：`successor_runtime.py` 239–260；校验：`validate_successor_toolchain_binding` 178–244（concrete Path、绝对、ISLNK/reparse、`DEFAULT_TARGET_PATH`、两 fold `build_qlib_dump_tool_spec` exact、bytes/sha、`type is float`）；`two_fold_identity` 嵌入 toolchain 分量（1650–1692）。 |
| 4 | 显式 prior / fresh closure / 无 scan 消费 | **部分失败** | 入口强制 sorted+unique `node_id`（1582–1588）；`_verify_prior_receipt`→`verify_stage_receipt_with_bytes`（429–447）；`_group_prior_refs_by_stage` 拒缺/多 stage（459–471）。**但**多 count stage（labels / label-reconciliation）**不**校验 horizon 唯一，见 F1。 |
| 5 | 同 request 两 fold：物理 publish exact1、fresh closure 两次 | **通过（实现面）** | registry hit 只抬 `effective_resume`（1616–1621），仍调用 handler + 产出后逐 ref fresh verify（1646–1648）；不直返内存 tuple。 |
| 6 | 跨 request / resume / fold 漂移 | **部分通过** | adapter `_bind_runtime_wave_session` 绑 identity+project+resume+folds（1154–1185）；registry 键含 `two_fold_identity`+root+wave+toolchain（337–347）。**但** registry **存在性**即可强制 resume，见 F2。 |
| 7 | canonical callable `is` identity | **通过（实现面）** | adapter `__init__` 要求 `run_upstream_wave is run_successor_upstream_wave` 且 summary 同理（1045–1051）；`make_canonical_successor_production_dependencies`（1535–1566）。 |
| 8 | 无 placeholder / 第二 receipt schema / 复制 Gate 顺序 | **通过（实现面）** | summary 返回真实 `GateExecution`+`_new_receipt_ref`（2790–2800）；formal backtest/tracking 仍由 runtime adapter 循环调用（1104–1118）；terminal schema 仍 `m3-successor-terminal-v1`。 |
| 9 | 任务书 §5 强制反例落地 | **失败** | 实现者覆盖 prior 缺多、unsorted、resume 强制、失败不登记、sha 漂移、wrapper、`two_fold` dump 漂移、R2S 源码绑定；**缺失** symlink/reparse toolchain 测试与 duplicate-horizon / registry pre-seed poison（见 §3）。 |

## 2. 发现分级

### [P1] 多 horizon prior 允许重复 horizon 静默覆盖 — `successor_upstream_stage.py:459-471,700-730,777-823`

`_group_prior_refs_by_stage` 只检查 `len(by_stage[stage]) == count`，不要求 `labels` / `label-reconciliation` 的 `horizon` 两两不同。`_reconstruct_shared_upstream` 以 `result.labels[horizon] = label`（及 reconciliations 同理）写入，后写覆盖前写。

这直接违背任务书 §4.2 / §5.1「重复 prior → `SUCCESSOR_STAGE_INVALID`」的唯一闭包语义：调用方可提交两个 `stage="labels"`、`horizon=5`、不同 `node_id`/`sha256` 的 prior，分组“通过”，字典塌缩为单 horizon，后续 work/summary 晚失败或少节点发布，而不是在 prior 闭包入口 fail closed。

### [P1] 进程内 `_WAVE_REGISTRY` 仅凭键存在强制 `effective_resume=True` — `successor_upstream_stage.py:1616-1621,1650-1664`

成功路径在 handler+fresh verify 之后才登记（1650–1653）；失败路径不登记（1633–1635）——这点正确。但读侧：

```text
cached = _WAVE_REGISTRY.get(key)
effective_resume = True if cached is not None else resume
```

**不**在抬 resume 前 fresh 校验 cached refs，也**不**区分“本进程成功 publish 写入”与“同进程预植入的 poison 条目”。若在本进程首次真实 publish 之前向 `_WAVE_REGISTRY[key]` 写入与盘上旧产物一致的 refs，则即使 caller `resume=False`，也会对 StageRunner 生效 `resume=True`，从而可能采纳**跨进程/历史**盘面产物——违反任务书 §4.2「caller 原始 `resume=false` 不允许跨进程采用旧产物」。

实现者测试只覆盖：成功后第二次强制 resume、handler 抛错不登记、二次登记 sha 漂移；**未**覆盖 pre-seed poison。

### [P1] 任务书强制的 toolchain symlink/reparse 反例未落地 — 测试面

实现面 `_require_concrete_absolute_regular_file`（138–157）静态可读且拒绝 ISLNK/reparse/resolve 漂移。但 exact9 测试（`tests/unit|integration/test_m3_successor_upstream_stage.py` 与 runtime 相关改动）**无** python/dump symlink 或 Windows reparse 对抗用例。交付 §4 亦未宣称覆盖 symlink/reparse。任务书 §5.4 为强制反例清单项；对照 R2S 初验先例，强制 symlink/reparse 未落地构成证据 FAIL。

### [P2] 失败 wave 部分物理 publish 的定向对抗不足 — 测试面

`test_failed_wave_is_not_registered_for_reuse` 仅在 handler 入口抛错。多 node wave（experiment-artifacts / work）中“已 publish N-1 节点后失败、registry 空、`resume=False` 不得复用部分结果”缺少定向静态/桩测。依赖 StageRunner `resume=False`→`STAGE_ALREADY_COMPLETE` 的外部行为，本包测试未钉死。

### 无其他 P0

R2S `project_stage_root` 接线、adapter 删除内存 `_wave_cache`、canonical `is` 绑定、`backtest_plan` 命名、terminal/`two_fold_identity` 纳入 toolchain 的主路径静态可读且大体贴合。

## 3. 实现者未使用的对抗反例（新增）

### 反例 R1 — 进程内 registry poison × caller `resume=False` × 盘面旧产物

**最小静态复现（未执行）：**

1. 准备与目标 `two_fold_identity`/project/wave/toolchain 键匹配的盘面旧 snapshot 产物（可来自先前进程）。
2. 本进程**尚未**成功调用 `run_successor_upstream_wave` 前执行：
   `_WAVE_REGISTRY[key] = (matching_StageReceiptRef,...)`（测试可直接写模块 dict）。
3. 以 `resume=False` 调用 `run_successor_upstream_wave(wave="snapshot", ...)`。
4. 观察：`effective_resume` 变为 `True`（见 1621），StageRunner 走 resume 复用旧盘面；若返回 refs 与 poison 元组在 `(node_id, relative_path, sha256, stage, scope_key)` 上一致，则二次登记比较通过（1654–1664）。
5. 预期（合同）：无本进程成功 publish 时，caller `resume=False` 必须拒绝旧产物；registry 不得仅凭预植入条目授权 resume。

**通过条件：** 抬 `effective_resume` 前证明条目来自本进程成功闭包（例如拒绝非本函数写入、或先 fresh verify cached 且要求与“无 resume 时 StageRunner 将拒绝”的语义一致的密封），并新增定向测试锁定 poison→`SUCCESSOR_STAGE_INVALID` 或等价 fail closed。

### 反例 R2 — sorted prior 跨 stage 表面合法、重复 horizon 歧义

**最小静态复现（未执行）：**

1. 构造 work/label-reconciliation 所需 prior，其中 `labels` 两条均 `horizon=5`，`node_id` 不同且整体 `sorted(node_id)` 有序、无重复 node_id。
2. 调用 `_group_prior_refs_by_stage(..., wave="work")` → 当前实现**通过**。
3. 再经 `_reconstruct_shared_upstream` → `shared.labels` 仅含 key `5`（后写覆盖）。
4. 预期：在分组或重建入口即 `SUCCESSOR_STAGE_INVALID`；不得静默塌缩。

**通过条件：** 对 count>1 且按 horizon 索引的 stage，断言 `len({ref.horizon for ref in ...}) == count` 且 horizon 集合等于配置 horizons；新增 unit 覆盖。

### 反例 R3 — toolchain python/dump symlink（或 Windows reparse）

**最小静态复现（未执行）：**

1. 真实文件落在 `project/DEFAULT_TARGET_PATH` 与绝对 python 路径。
2. 另建 symlink（或 junction/reparse）叶指向上述文件，将 `SuccessorToolchainBinding` 的 Path 指向 symlink 叶。
3. 调用 `validate_successor_toolchain_binding`。
4. 预期：`SUCCESSOR_INPUT_INVALID`（与 145–149 实现一致），且 exact9 测试必须覆盖该路径（宿主不支持 symlink 时 skip 并保留 reparse 属性注入等价物）。

## 4. 失败项（现象—根因—规则—最小复现—测试—通过条件）

### F1 — 重复 horizon prior 未 fail closed

| 字段 | 内容 |
| --- | --- |
| 现象 | 两个同 horizon 的 labels（或 reconciliations）prior 可通过分组并被字典覆盖 |
| 根因 | `_group_prior_refs_by_stage` 只计数量；重建用 `dict[horizon]=` 覆盖 |
| 规则 | 任务书 §4.2 / §5.1：重复 prior → `SUCCESSOR_STAGE_INVALID`；唯一闭包匹配 |
| 最小复现 | 反例 R2 |
| 新增测试 | unit：duplicate horizon labels/reconciliations → 稳定错误码 |
| 通过条件 | 入口拒绝；不得依赖下游晚失败 |

### F2 — registry poison 可迫使跨进程旧产物 resume

| 字段 | 内容 |
| --- | --- |
| 现象 | 预植入 `_WAVE_REGISTRY` 条目使 `resume=False` 仍 `effective_resume=True` |
| 根因 | 以键存在性作为“本进程已成功 publish”的充分条件 |
| 规则 | 任务书 §4.2：第二 fold exact resume 仅当本进程首 fold 已成功发布；caller `resume=false` 禁止跨进程旧产物 |
| 最小复现 | 反例 R1 |
| 新增测试 | pre-seed registry + 盘面旧产物 + `resume=False` 必拒绝 |
| 通过条件 | poison 无法授权 resume；仅成功闭包写入可抬 resume |

### F3 — symlink/reparse toolchain 强制反例缺失

| 字段 | 内容 |
| --- | --- |
| 现象 | 实现有拒绝逻辑，exact9 测试与交付清单未覆盖 |
| 根因 | §5.4 反例未编码为可回归测试 |
| 规则 | 任务书 §5.4；STATIC_ONLY 下测试即主证据 |
| 最小复现 | 反例 R3 |
| 新增测试 | symlink 叶 +（Windows）reparse/junction 注入 |
| 通过条件 | 定向测试红/绿钉死 `SUCCESSOR_INPUT_INVALID` |

## 5. 快速回扫（未构成独立 FAIL 的通过项）

- 七 upstream wave 完整 plan，不拆发布；experiment-artifacts / label-reconciliation / work 单 plan 多 node。
- adapter `prior_refs=tuple(sorted(..., key=node_id))`（`successor_runtime.py` 1093）；无 adapter 内存 `_wave_cache`。
- summary 走 R2S public runner；`project_stage_root` 替代路径猜测。
- `two_fold_identity` 含 python/dump/size/sha/timeout；`verify_terminal_attestation` 比较 identity（1881–1884）→ toolchain 漂移拒绝旧 terminal 的机制存在（缺专用终端复用测，记为残余风险，不单列 P1）。
- formal 顺序与四 Gate 未迁入 upstream 模块。

## 6. 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / ast.parse | **未运行** |
| 真实 Qlib / network / actual worker / new root / retained | **未运行** |
| commit / 改实现·测试·任务·交付 | **未做** |

## 7. 总判

**REVIEW_FAIL**

主路径（完整 wave plan、PROJECT-only StageRunner、R2S summary + `project_stage_root`、toolchain 校验实现面、canonical `is` 绑定、同进程二次 fresh closure）静态可读且大体贴合合同；但 **重复 horizon prior 静默覆盖**、**registry 存在性即可强制 resume（poison→跨进程旧产物）**、以及任务书强制的 **toolchain symlink/reparse 反例未落地** 构成独立初验阻断。须在 exact9 内最小返工，并由未参与该轮实现的全新会话复验通过后，方可申请 Windows 验证资源与 `EXECUTABLE_STAGE_SUBSTRATE_WINDOWS_VALIDATED` 相关推进。

本审查 **不修改实现**。FAIL ≠ 授权扩大白名单或宣称 Gate 完成。

---

## R1 复验（2026-08-26）— 另一全新独立 reviewer

身份：未参与实现 / §0A 采用 / 此前初验的全新独立复验者（STATIC_ONLY；无 subagent / 委派）<br>
唯一写入：本报告（**追加**；上方首轮 `REVIEW_FAIL` / F1–F3 / 反例 R1–R3 **完整保留、不覆盖**）<br>
只读：AGENTS、任务书（含 §9）、delivery（含 §0A/§0B）、exact9 生产/测试<br>
结论：**R1_REVIEW_PASS**

### R1.0 审查边界

- exact9（任务书 §3）：1–6 生产/测试 + 7 任务书 + 8 delivery + 9 本 review；本会话只写 9。
- **STATIC_ONLY**：零 Python / 脚本 / pytest / Ruff / mypy / cold / Qlib / network / commit；未改 production/tests/taskbook/delivery。
- 对照：任务书 §9 F1–F3 六要素、delivery §0B 采用声明、首轮 FAIL 行号（实现已漂移，以下为复验时现行行号）。

### R1.1 F1–F3 闭合核（现行证据）

| 项 | 结论 | 证据行号 |
| --- | --- | --- |
| F1 多 horizon 唯一闭包 | **闭合** | `_unique_horizon_ref_map` `successor_upstream_stage.py:546-571`：长度≠canonical、`None`/非 int、不在集合、`horizon in mapping`（duplicate）、最终 `set` 不等均 `SUCCESSOR_STAGE_INVALID`。dict 写入前调用：labels `801-804`→`828`；reconciliation `877-879`→`926`；summary `2534-2538`。测试：unit `465-515`；integration `476-493`。 |
| F2 sealed registry 授权 resume | **闭合** | `_CanonicalWaveSuccess`+`_WAVE_SUCCESS_SEAL` `330-351`；`_effective_resume_from_registry` `386-400`（非 sealed→`SUCCESSOR_STAGE_INVALID`；仅 sealed→`True`）；登记仅在 handler 成功 + fresh verify 后 `_seal_wave_success` `1738-1765`。plain tuple preseed 拒：unit `570-598`；integration `541-568`。partial 不登记：unit `601-702`。canonical 成功后第二 fold resume+verify×2：integration `571-660`。 |
| F3 symlink/reparse 回归 | **闭合** | 实现 `_require_concrete_absolute_regular_file` `138-157`（ISLNK / 非 REG / reparse / resolve 漂移）。测试：`test_toolchain_rejects_python_and_dump_symlink_or_link_guard` `705-784`（真实 symlink；`OSError` 时 ISLNK lstat 注入，**无** `pytest.skip`/`skipif`）；`test_toolchain_rejects_windows_reparse_attribute_injection` `787-842`（`st_file_attributes=0x400` 窄注入，python+dump）。 |

### R1.2 实现者未使用的新对抗反例（复验新增）

#### 反例 R4 — 伪造 sealed marker（无 canonical publish）

| 六要素 | 内容 |
| --- | --- |
| 现象 | 测试可 ` _CanonicalWaveSuccess(refs, seal=_WAVE_SUCCESS_SEAL)` 预植入 registry，使 `resume=False` 抬升，**不**经 handler/fresh closure。 |
| 根因 | 模块级 `_WAVE_SUCCESS_SEAL`（`327`）与可调用构造器（`339-348`）对同进程 import 者可读；seal 证明类型真实性，不另证“本 request 生命周期已 publish”。 |
| 规则 | 任务书 §9 F2：不可伪造成功状态；外部/测试预植入不得抬 resume。本包以 module seal 为能力边界（等价于调用 `_seal_wave_success` `403-404`）。 |
| 最小复现（静态，未执行） | `_WAVE_REGISTRY[key]=_CanonicalWaveSuccess((ref,), seal=_WAVE_SUCCESS_SEAL)` → `run_successor_upstream_wave(..., resume=False)` → `_effective_resume_from_registry` 返回 `True`（`398-400`）。对照组：`object.__new__`+错 seal / plain tuple / 非该 type → `399` fail closed（与 unit poison 一致）。 |
| 新增测试 | 实现者未覆盖“带真 seal 的预植入”；已覆盖 plain tuple。 |
| 通过条件 / 本复验判定 | **不构成 R1 FAIL**：真 seal 预植入与生产 `_seal_wave_success` 同能力；F2 原 FAIL 的 plain/存在性 poison 已拒。残余：若经理要求“即使持有 seal 的预植入亦拒”，需 exact9 内不可重放 mint（超出本轮已采用 seal 类型证明）。 |

#### 反例 R5 — 同进程跨 request registry 键碰撞

| 六要素 | 内容 |
| --- | --- |
| 现象 | registry 键=`(two_fold_identity, normcase(project_root), wave, toolchain_identity)`（`364-374`）。`two_fold_identity`（`successor_runtime.py:1650-1692`）含 folds/config/release/horizons/toolchain，**不含** `controlled_output_root` / `runtime_identity` / `now`。 |
| 根因 | 进程内物理 wave 复用按 two-fold identity 对齐，非按 Python request 对象身份。 |
| 规则 | §4.2 / §9 F2：错 request/root/toolchain/fold 不得抬；同 identity 第二 fold 可 exact resume。 |
| 最小复现（静态） | (a) 两 request `two_fold_identity` 不同 → 键不同 → 不得抬（无碰撞）。(b) identity/root/wave 全同、仅 `controlled_output_root` 不同 → 共享键，第二 request 的 `resume=False` 仍可被抬。 |
| 新增测试 | 实现者有不同 identity 的 adapter poison（runtime integration）；无“同 identity、异 controlled_output_root”定向测。 |
| 通过条件 / 本复验判定 | **(a) 通过**；(b) 记残余风险（与 §4.2 identity 共享语义一致，非 R1 F2 plain-poison 回归）。错 identity/root/toolchain 不抬：键分量静态可读。 |

#### 反例 R6 — 多 node 部分 publish 后 registry / resume

| 六要素 | 内容 |
| --- | --- |
| 现象 | multi-node handler 在返回前抛错时，不得登记、不得抬后续 `resume=False`。 |
| 根因 | 登记点在 handler 成功与全量 fresh verify 之后（`1738-1759`）；`except` 只 re-raise（`1738-1740`）。 |
| 规则 | §9 F2：失败 wave 部分结果不得登记成功 / 不得抬 resume。 |
| 最小复现 | unit `test_partial_multi_node_failure_does_not_register_or_elevate` `601-702`：首呼 raise → `key not in _WAVE_REGISTRY`；次呼 `resume=False` 且 `observed==[False,False]`，成功后才 sealed。 |
| 新增测试 | 已有；桩在 handler 层模拟“部分节点后失败”，未驱动真实 StageRunner 落盘 N-1 节点（盘面 `STAGE_ALREADY_COMPLETE` 仍依赖 runner+`resume=False`）。 |
| 通过条件 / 本复验判定 | **registry/resume 语义通过**。残余：真实多 node 落盘 partial 的 runner 交互仍属 Windows 主验/外部行为，不单独阻断 R1（首轮 P2 同类残余）。 |

### R1.3 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / 脚本 | **未运行** |
| Qlib / network / worker / new root / retained | **未运行** |
| commit / 改实现·测试·任务·交付 | **未做**（仅追加本 R1 节） |

### R1.4 R1 总判

**R1_REVIEW_PASS**

首轮 F1（dict 前 horizon 唯一闭包）、F2（plain/非 sealed poison 不抬 resume；仅 sealed canonical 成功授权第二 fold）、F3（python/dump symlink + Windows reparse 窄注入、无条件 skip）在 exact9 现行源码与测试面静态闭合。新对抗 R4–R6 未发现需再次返工的合同阻断；R4 真 seal 预植入与 R5 同 identity 跨 request 粘性记为残余，不回退为 R1 FAIL。

本复验 **不修改实现**。`R1_REVIEW_PASS` ≠ `EXECUTABLE_STAGE_SUBSTRATE_WINDOWS_VALIDATED` / production bridge / Gate 完成；仅表示可申请经理侧 Windows 验证资源推进。

---

## VALIDATION1 fixture 复验（2026-08-26）— 同一独立 reviewer

身份：与 R1 相同之独立 reviewer；本轮仅审任务书 §10 / delivery §0C 的 **test-only fixture** 最小 diff<br>
唯一写入：本报告（**追加**；首轮 `REVIEW_FAIL`、R1 `R1_REVIEW_PASS` 及全部历史结论 **完整保留、不覆盖**）<br>
只读：AGENTS、任务书 §10、delivery §0C、两份 upstream-stage 测试；**production / runtime 冻结未读改**<br>
结论：**FIXTURE_REVIEW_PASS**

### F.0 审查边界

- 允许写集（实现者）：`tests/unit/test_m3_successor_upstream_stage.py`、`tests/integration/test_m3_successor_upstream_stage.py`、delivery；本会话只写本 review。
- **STATIC_ONLY**：零 Python / pytest / Ruff / mypy / cold / scripts / commit；未宣称 focused 复跑。
- 权威 VALIDATION1 计数（只读引用任务书 §10 / delivery §0C）：identity **PASS**；focused exact4 **`61 passed / 3 failed`**；Ruff/mypy/cold/scope **UNRUN**；空 evidence carrier 仅 `CARRIER_INVALID_BEFORE_PRODUCT_EVIDENCE`。

### F.1 逐项静态核

| # | §10 冻结修正 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 真逆序 `unsorted=(snapshot, provider)` | **PASS** | unit `344-350`：`("snapshot","provider")` 且 `!= sorted(node_id)`（lexicographic 正序为 provider&lt;snapshot）。integration `61-64`：同构自证。unit `351-361` 以该 unsorted 调 `run_successor_upstream_wave` → `SUCCESSOR_STAGE_INVALID`。 |
| 2 | partial 成功 refs=`folds, labels.h10, labels.h5` | **PASS** | unit handler 成功返回 `618-622`；`folds`&lt;`labels.h10`&lt;`labels.h5`（`h10` 在 `h5` 前因 `'1'`&lt;`'5'`）符合 `node_id` stable-sort。 |
| 3 | 首次失败不登记；第二次仍 `resume=False`；仅完整成功+fresh 后封存 | **PASS** | 首呼 raise `615-617` + `resume=False` `682` → `key not in _WAVE_REGISTRY` `684-685`。次呼仍 `resume=False` `695` → `observed == [False, False]` `697`。成功后 `sealed` 为 `_CanonicalWaveSuccess` 且 `authorized()` `699-702`（经 monkeypatched fresh verify 路径 `646-649`）。未改异常类型/registry 合同结构。 |

### F.2 未运行 / 非宣称

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / scripts | **未运行** |
| production / runtime tests / taskbook | **未改** |
| VALIDATION2 / Gate / Windows 绿 | **不宣称** |

### F.3 总判

**FIXTURE_REVIEW_PASS**

VALIDATION1 三项 fixture 排序修正与 §10/§0C 通过条件静态对齐；历史 `REVIEW_FAIL` 与 `R1_REVIEW_PASS` 保持原状。本结论仅放行申请从 identity→focused exact4 起的 **VALIDATION2**，不等于运行态验证或 Gate 完成。

---

## VALIDATION2 Ruff-only 复验（2026-08-26）— 同一独立 reviewer

身份：与 R1 / fixture 复验相同之独立 reviewer<br>
唯一写入：本报告（**追加**；`REVIEW_FAIL` / `R1_REVIEW_PASS` / `FIXTURE_REVIEW_PASS` **完整保留**）<br>
只读：任务书 §11、delivery §0D、现行 `successor_upstream_stage.py`；production 其余 / tests / taskbook / delivery **只读未改**<br>
结论：**RUFF_REWORK_REVIEW_PASS**

### R.0 边界

- 写集（实现者宣称）：仅 `successor_upstream_stage.py` + delivery；本会话只写本 review。
- **STATIC_ONLY**：零 Python / scripts / pytest / Ruff / mypy / cold / subagent / commit。
- 文件相对 HEAD 为未跟踪整文件，无 `git diff` 基线；以 §11/§0D 点名删除项对照现行源码 + 历史审查已记录之 `label_refs` 行作等价核。
- VALIDATION2 证据（只读引用 §0D，未重跑）：root `artifacts/agent_runs/m3-r2a-validation2-20260826T061000Z/`；focused **`64 passed`**；Ruff 首失败 STOP；mypy/cold/final scope **UNRUN**；空 carrier `…T060803Z` → `CARRIER_INVALID_BEFORE_PRODUCT_EVIDENCE`。

### R.1 语义 diff 核（仅 import/binding 收敛）

| # | §11 项 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 删未用 `ProviderValidationSpec` import | **PASS** | TYPE_CHECKING contracts 块 `37-61` **无** `ProviderValidationSpec`。运行时仍于需要处局部 import（如 `753`、`1206`、`1310`、`1426`），校验构造未删。 |
| 2 | 删未用 `StageContext` 局部 import | **PASS** | `_run_static_node_with_proof` `437-477` 仅 `from … import StageBuildReport`（`453`）；无局部 `StageContext` import。注解仍用 TYPE_CHECKING 的 `StageContext`（`62`、`457`），属使用中导入。 |
| 3 | 删未用 `StageReceiptRef` 局部 import | **PASS** | `run_successor_formal_summary_gate` 局部 import `2795-2803` **不含** `StageReceiptRef`；函数体校验/调用链（`2805+`）仍在。他处 `_new_receipt_ref` 等仍按需 import。 |
| 4 | 删未用 `label_refs`；RHS 无副作用则整行删 | **PASS** | 现行 `_run_label_reconciliation_wave` 在 `experiment_ref=…`（`2420`）后直接 `refs: list…`（`2422`），**无** `label_refs`。历史审查曾录 RHS=`{item.horizon: item for item in by_stage["labels"]}`：纯 dictcomp，无函数调用/IO/verify；删除不跳过 validation。闭包仍走 `_reconstruct_shared_upstream`→`_unique_horizon_ref_map` 与 `shared.label_receipt_paths[horizon]`（`2433`）。 |
| 5 | 无分支/调用序/异常码/receipt/wave/identity/resume/registry/API 改动 | **PASS（静态）** | 上述位点邻接控制流、`run_static`/`verify_*`/`run_formal_summary_stage` 调用与 fail 码路径仍在；未见额外语义编辑面。 |

### R.2 未运行 / Gate 边界

| 项 | 状态 |
| --- | --- |
| 本复验 Python / Ruff / mypy / cold / scripts | **未运行** |
| focused64 复跑 | **未做**（§11 放行 postfix 时不重复已绿 focused64） |
| Gate / bridge / `EXECUTABLE_STAGE_SUBSTRATE_WINDOWS_VALIDATED` | **不宣称** |
| focused `64 passed` ≠ 整包通过 | **明确** |

### R.3 总判

**RUFF_REWORK_REVIEW_PASS**

仅确认三 unused import + 无副作用 `label_refs` 删除之行为等价收敛；可申请 postfix：identity→Ruff prod2/tests4→mypy prod2→cold prod2→exact9 scope/residue（不重复已绿 focused64）。历史结论均不覆盖。

---

## VALIDATION3 type-contract 复验（2026-08-26）— 同一独立 reviewer

身份：与 R1 / fixture / Ruff 复验相同之独立 reviewer（完整对抗复验，非 diff 摘要）<br>
唯一写入：本报告（**追加**；`REVIEW_FAIL` / `R1_REVIEW_PASS` / `FIXTURE_REVIEW_PASS` / `RUFF_REWORK_REVIEW_PASS` **完整保留**）<br>
只读：AGENTS、任务书 §12、delivery §0E、exact9 生产/测试、retained evidence `artifacts/agent_runs/m3-r2a-postfix-validation3-20260826T061827Z/`<br>
结论：**TYPE_CONTRACT_REVIEW_FAIL**

### T.0 边界

- 实现者写集：`successor_upstream_stage.py` + 两份 upstream tests + delivery；本会话只写本 review；**未改** production/tests/taskbook/delivery。
- **STATIC_ONLY**：零 Python / scripts / pytest / Ruff / mypy / cold / subagent / commit。
- Retained VALIDATION3：identity/Ruff PASS；`03-mypy.stdout.log` **Found 115 errors**；`VALIDATION_STOP=STAGE_FAILED:03-mypy:1`；cold/final scope **UNRUN**（与 §0E 一致）。

### T.1 三项真实 API（生产 SSOT / 现行行号）

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
