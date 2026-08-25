# M4-B1B1 Formal Barrier Binding And Ordinary Writer Closure 独立初验报告

状态：`DOC_REVIEW_PASS / EVIDENCE_REVIEW_PASS / B1B1_WINDOWS_ENGINEERING_VALIDATED / SUBSTRATE+B1B1 / UA-M4-006 OPEN`

- task id：`M4-B1B1-FORMAL-BARRIER-BINDING`
- exact base：`57dcf2e579175ead8d7c833ed7fb4b7bccedc5c5`（变更均为未提交 working tree）
- branch / worktree：`codex/m4-b1b1-formal-barrier-binding` @ 任务书指定路径
- 审查角色：同一独立初验 Agent · DOC_REVIEW（仅规范化本报告 trailing whitespace / hard-break / LF / 自证明重签）；task/delivery/production/tests/evidence 只读
- 证据根（相对 worktree）：`artifacts/agent_runs/m4-b1b1-validation{1..6}-*/`（**非**仓库顶层 `artifacts/agent_runs/`）
- 终态上限：仅 `B1B1_WINDOWS_ENGINEERING_VALIDATED` + `SUBSTRATE+B1B1`；**不**宣称 B1B2 / all-writer / CLOSED 消费 / PAPER / soak / Linux / 单轮全绿 Gate / UA-M4-006 关闭
- 报告 SHA-256：见文末 §Z（指纹行自身不计入哈希）

---

## A–L 历史（保留）

- **A–L**：初验 FAIL → REWORK2–7 PASS（F1–F3；F20–F27）。§K/§L 正文仍见下文历史节。

---

## K. STATIC_REWORK6 复验（F26 / 任务书 §15）

### K.0 范围与方法

只读：任务书 §15；交付（`STATIC_REWORK6`）；`tests/unit/test_execution_service.py`；production SHA 对照 F25/REWORK5 冻结表。

VALIDATION4：`artifacts/agent_runs/m4-b1b1-validation4-20260826T024000/` — **本环境未找到**；边界采任务书/交付：identity PASS；focused `471 passed / 6 skipped` PASS；Ruff 唯一 F841；mypy/cold/scope UNRUN。

**全部未运行：** Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / commit。

### K.1 裁决

**`REVIEW_PASS`**

F26 仅为并发 submit fence 节点去掉无用局部绑定；`_stage(service, tmp_path)` 调用保留；后续 gateway 暂停 / close BUSY / worker join / 断言上下文静态不变；production 与其他 tests SHA 相对 F25 冻结不变。

### K.2 写集与冻结

| 检查 | 结论 |
|---|---|
| 本轮声明写集 | 仅 `tests/unit/test_execution_service.py` + delivery |
| 本轮语义变化 | `test_submit_operation_fence_blocks_closing_during_gateway`：`staged = _stage(...)` → `_stage(...)`（L2617） |
| 禁止项 | 未删调用；未赋 `_`；未加 F841 `noqa`/ignore；`_stage` helper 与 HEAD 定义一致 |
| production SHA vs F25 冻结 | **全部 True 一致**（`reconcile`/`session_barrier`/`store`/`service`/formal_*） |
| 其他 tests（含 `test_reconcile`） | 非本轮写集；未作为 F26 修改点 |

### K.3 调用上下文不变（submit fence）

| 项 | 静态结论 |
|---|---|
| 参数/次数 | 仍单次 `_stage(service, tmp_path)` |
| 后续 | `PausingSubmitGateway` → thread `dispatch_pending` → `in_submit.wait` → `BARRIER_WRITER_BUSY` on closing → `release` → `join` → `errors==[]` / claimed → 后再 CLOSING |
| cancel 对照 | `test_cancel_operation_fence_…` 仍 `staged = _stage(...)`（**需要**返回值取 `staged_command_ids`）；未误伤 |

### K.4 VALIDATION4 边界诚实性

交付如实：focused 471 PASS；Ruff 唯一 F841；mypy/cold/scope UNRUN；不得把 471 写成整包/Gate。postfix 另申请且不机械重跑 focused —— 与 §15 一致。

### K.5 复验新增对抗性反例（实现者未用）

**禁止“伪修复”形态：** 静态上不得出现 `_ = _stage(service, tmp_path)` 或 `# noqa: F841` 挂在该行——二者会消 F841 但违反 §15.2。当前为裸调用 `_stage(...)`，满足。另：cancel 节点若同样去绑定会破坏 `staged.staged_command_ids` 使用；submit 节点返回值本就未读，去绑定合法。实现者未写该对照负向清单。

### K.6 未运行边界

- 未运行任何解释器验证
- VALIDATION4 原生目录本环境未找到
- 下一步：postfix 窄验证（identity 轻量 → Ruff exact22 → mypy production11 → cold production11 → exact25 scope）；**不**机械重复 focused 471

---

## L. STATIC_REWORK7 复验（F27 / 任务书 §16）

### L.0 范围与方法

只读：任务书 §16；交付（`STATIC_REWORK7`）；`src/quant/execution/paper_formal_execution_store.py`；其余 production 对照 F25/F26 冻结 SHA；tests 相对 F26 指纹。

VALIDATION5：`artifacts/agent_runs/m4-b1b1-validation5-20260826T031000/` — **本环境未找到**；边界采任务书/交付：identity PASS；Ruff exact22 PASS；mypy production11 三处 `attr-defined`；cold/scope UNRUN。

**全部未运行：** Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / commit。

### L.1 裁决

**`REVIEW_PASS`**

F27 仅为：显式 import `SessionBarrierCapability`，并将 `_build_formal_barrier(...) -> object` 收窄为 `-> SessionBarrierCapability`。逆变换后 SHA 精确回退到 F26 冻结 `4e10f039…393611ae`，证明函数体/异常/policy/identity/descriptor/调用序无其它字节变化。capability escape 入口仍为 `object`。其他 production/tests 相对 F26 冻结不变。

### L.2 写集与冻结

| 检查 | 结论 |
|---|---|
| 本轮声明写集 | 仅 `paper_formal_execution_store.py` + delivery |
| 本轮语义变化 | L40 新增 `SessionBarrierCapability,`；L552 `-> SessionBarrierCapability` |
| 禁止项 | 无 `cast`/`Any`/`type: ignore`（返回路径）；无 Protocol 替代；函数体含 `FORMAL_CLOSURE_ONLY`/`from None` 未改 |
| `_session_barrier` / `mint(... session_barrier)` / `_bind_formal_broker_barrier(... session_barrier)` | 仍均为 `object` |
| `SessionBarrierCapability` 出现次数 | 仅 import 与返回注解两处（未扩散到字段/跨层签名） |
| 其他 production vs F25/F26 冻结 | **全部 True**（`reconcile`/`session_barrier`/`store`/`service`/`paper_formal_{gateway,service,daily}`） |
| `paper_formal_execution_store` 新 SHA | `d6b27432b9023a1139e116f6d646244e962241415d69f387a28ae7b8ed547be5` |
| tests | `test_execution_service`=`78ce81e1…`（F26）；`test_reconcile`=`4431c20e…`；非本轮写集 |

### L.3 类型合同与 mypy 缺口映射

| 项 | 静态结论 |
|---|---|
| 真实返回 | 仅 `build_session_barrier_capability(...)` → `SessionBarrierCapability`（含 `capability_identity`） |
| 三处 caller | create/open 路径对 `_build_formal_barrier` 结果读 `.capability_identity`；注解收窄后消除对 `object` 的 `attr-defined`（逻辑静态映射；本轮未跑 mypy） |
| 既有 `# type: ignore[no-untyped-def]` @ `_create_api` | 历史工厂门闩，非 F27 新增 |

### L.4 VALIDATION5 边界诚实性

交付如实：Ruff PASS；mypy 三错误；cold/scope UNRUN；分类为类型合同缺口非行为失败。postfix：identity → Ruff 本 production 文件 → mypy production11 → cold → exact25 scope；不重复 focused471 —— 与 §16 一致。

### L.5 复验新增对抗性反例（实现者未用）

1. **逆变换等价证明：** 删除 import 行并将返回注解改回 `object` 后 UTF-8 SHA ≡ F26 冻结；若曾改函数体/policy/bytes，逆变换无法命中。实现者未提供该指纹闭合。
2. **负向扩散对照：** 若将 `_session_barrier`/`mint`/`_bind_formal_broker_barrier` 也改为 `SessionBarrierCapability`，会扩大 raw capability 跨层类型面，违反 §16.3；当前三处仍为 `object`，且类型名仅出现两次。
3. **伪修复形态：** `cast`/`Any`/`type: ignore` 挂在 `.capability_identity` 可消 mypy 但违反 §16.2；当前无此类补丁。

### L.6 未运行边界

- 未运行任何解释器验证
- VALIDATION5 原生目录本环境未找到（**注：** EVIDENCE_REVIEW 轮已在 worktree 内定位到同一相对路径证据根）
- 下一步：经理申请 postfix 窄验证（§16）；**不**宣称 mypy/cold 已绿

---

## M. EVIDENCE_REVIEW（VALIDATION1–6 组合收口 / 任务书 §17）

### M.0 范围与方法

只读：更新后任务书 §17 + delivery；worktree 内六份 evidence root；exact25 与当前 dirty；production/tests **冻结 SHA** 对照 F27 复验表。

**全部未运行：** Python / pytest / Ruff / mypy / cold / SQLite / network / commit。

证据物理根：`F:\…\m4-b1b1-formal-barrier-binding\artifacts\agent_runs\m4-b1b1-validation{1..6}-*`（与各 `runner.ps1` 的 `$evidence` 一致）。仓库顶层 `artifacts/agent_runs/` **无**同名目录——相对 worktree 引用，**非**路径造假。

### M.1 裁决

**`EVIDENCE_REVIEW_PASS`**

文档陈述与原生 summary/stdout/exit/SHA **一致**；有效绿为 **跨轮组合**（V4 focused471+6skip ∪ V5 Ruff exact22 ∪ V6 identity/Ruff-changed/mypy11/cold11/scope），**非**单轮全绿；历史失败与 UNRUN **未被改写**；production/tests 相对 F27 冻结；状态上限诚实。

### M.2 逐 root 关键核对

| root | summary 关键 | stdout/exit 要点 | 与文档 |
|---|---|---|---|
| **V1** `…T004700` | id=0；focused=1 | `6 failed, 465 passed, 6 skipped…38.06s`；六失败节点与 F20–F23 叙述同族 | 一致；Ruff+ 文件缺失=UNRUN |
| **V2** `…T011000` | id=0；focused=1 | `1 failed, 470 passed…34.23s`；`__context__ is None` 误断言 | 一致 |
| **V3** `…T014000` | id=0；focused=1 | `1 failed, 470 passed…33.43s`；`BROKER_SNAPSHOT_INVALID`；`as_of=2026-08-25` vs account `2026-08-02` | 与「as_of 混用」一致 |
| **V4** `…T024000` | id=0；focused=0；ruff=1 | focused stdout SHA=`a6398704…dcbb1` → `471 passed, 6 skipped, 56 warnings in 33.13s`；ruff 唯一 F841 @ `staged = _stage` | **focused 有效绿**；mypy/cold/scope 文件缺失=UNRUN |
| **V5** `…T031000` | id=0；ruff=0；mypy=1 | ruff stdout SHA=`82b3e6a6…6b4f18`=`All checks passed!`；runner=`production+tests`（11+11=exact22）；mypy 3× `attr-defined` | **Ruff 有效绿**；无 focused/cold/scope 文件 |
| **V6** `…T043000` | 五阶段全 0 | 见 M.3；无 focused 文件（沿用 V4） | **postfix 有效绿** |

### M.3 VALIDATION6 关键 SHA（对照 delivery/§17.2）

| 产物 | 实测 SHA256 | 文档 | exit |
|---|---|---|---|
| `stage-summary.log` | `d4c44f8610b6cc611a4b440f0a1afe6cf3c52055c3e064425ebf932a02e3f7cf` | 匹配 | 全 0 |
| `01-identity.stdout.log` | `4630a9835997dcab87ec9e27a2aca1ab14b7c511b877a828efa971f937ca26d2` | 匹配 | 0 |
| `03-ruff.stdout.log` | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` | 匹配（单文件复跑；文案同 V5 PASS） | 0 |
| `04-mypy.stdout.log` | `ce32e21ee307d2da61637151f2f239cf8568be270711ff04e8e3025805ab7f57` | 匹配（`Success: no issues found in 11 source files`） | 0 |
| `05-cold.stdout.log` | `3d7eb1f1cbc189e0b56f320f769d6918982875771d61679db270db7671180b79` | 匹配（11 modules） | 0 |
| `06-final-scope.stdout.log` | `e10206e0d6d98aa6a2c996f0bb874fd205d9b427993d8dd4d4a0bb5fdf570e7c` | 匹配 | 0 |

### M.4 scope / 资源

| 项 | 证据 | 结论 |
|---|---|---|
| `ACTUAL_COUNT=16` | scope L1 + 16×`PATH=` | 全部 ∈ exact25（7 prod + 6 tests + 3 docs） |
| `CACHED_COUNT=0` / `DIFF_CHECK=PASS` | scope L18–19；runner 抛错门禁 | 一致 |
| temp residue | scope 前 runner 断言无 basetemp/mypy/pytest/ruff/mypy_cache；当前 worktree **无** `.tmp` | 清 |
| **PID37448** | scope：`pwsh`/`BelowNormal`/`0xF00`；`Write-FinalScope` 在 `finally` **之前** | **finally 前 carrier** 成立 |
| 退出后无 `0xF00` | `finally` 恢复 `$oldAffinity`；runner `exit 0`；**无**第二份 post-exit 亲和性快照文件 | 与脚本合同一致；无反证残留；**非**独立二次采样日志 |
| **PID7692** | `python`/`0x3` | writer 未扰动陈述成立 |

### M.5 production/tests 冻结（相对 F27）

| 路径 | SHA 命中 |
|---|---|
| `reconcile`/`session_barrier`/`store`/`service`/`paper_formal_{gateway,service,daily}` | True（F25 表） |
| `paper_formal_execution_store` | True = `d6b27432…547be5`（F27） |
| `test_execution_service` / `test_reconcile` | True（F26） |
| 本轮 grant | 仅 taskbook §17 + delivery；**零改码**陈述与 dirty 集合（实现遗留 M + 三 docs）一致 |

### M.6 独立证据矛盾检查（实现/经理未列）

1. **同 SHA 不同范围：** V5/V6 `03-ruff.stdout` SHA 相同，因二者成功文案均为 `All checks passed!\n`；V5 runner=`prod+tests`（22），V6=`paper_formal_execution_store.py` 单文件。文档已区分「exact22」vs「changed file」，**无夸大矛盾**。
2. **顶层 vs worktree evidence：** 顶层 `artifacts/agent_runs` 无 V1–6；worktree 内存在且 runner 硬编码 worktree 路径 → **相对路径诚实**。
3. **历史失败未漂白：** V1–V3 focused exit=1 与 summary 仍在；V4 ruff=1、V5 mypy=1 仍在；未出现后写“全绿 summary”。
4. **状态边界：** task/delivery 均为 `B1B1_WINDOWS_ENGINEERING_VALIDATED` + `SUBSTRATE+B1B1` + `UA-M4-006 OPEN`；明确禁止 B1B2/all-writer/CLOSED/PAPER/soak/Linux/单轮全绿。
5. **F1–F27 链：** 静态复验 PASS 史与 V1→V6 首失败→修复→有效绿表对齐；本轮无新码。

### M.7 未运行边界

- 本轮未执行任何解释器/静态检查/网络/提交
- 不把组合工程验证升级为业务 Gate 或 Linux 终验

---

## N. DOC_REVIEW（whitespace / hard-break / 自证明重签）

### N.0 范围

- 本轮仅改本报告；task SHA=`63336080…e63c`、delivery SHA=`68bfd411…5e65` 只读核验命中；production/tests 冻结 SHA 未变；evidence 未清。
- 零 Python / stage / commit。

### N.1 规范化

| 项 | 处理 |
|---|---|
| trailing whitespace | 清除；原 3 处行尾双空格 markdown hard-break（K.0/L.0/M.0）改为自然空行分段 |
| 换行 | CRLF→LF；文件恰好单一末尾 LF |
| 语义/边界 | task/delivery 仍为组合证据、`B1B1_WINDOWS_ENGINEERING_VALIDATED` / `SUBSTRATE+B1B1` / `UA-M4-006 OPEN`；证据结论未漂移 |

### N.2 自证明

- 旧指纹因换行/空白规范化失效，按正文顺序重算：哈希范围为指纹行之前的 UTF-8 正文（截断于指纹行行首），写入新指纹。
- 裁决：`DOC_REVIEW_PASS`；**已重签**自证明字段。

---

## Z. 交接与报告指纹

- 裁决：`DOC_REVIEW_PASS`（报告规范化）+ 既有 `EVIDENCE_REVIEW_PASS`（组合 VALIDATION1–6）
- 状态上限：`B1B1_WINDOWS_ENGINEERING_VALIDATED` / `SUBSTRATE+B1B1` / `UA-M4-006 OPEN`
- 下一步：经理/统筹按组合证据推进合流申请（本 reviewer 不合流、不改 production）
- 报告路径：`docs/framework/reviews/M4_B1B1_FormalBarrierBindingAndOrdinaryWriterClosure独立初验报告.md`
- **报告 SHA-256（UTF-8 正文，不含本行）：** `d9738e429948fd8a1b856a4319f427e60f86e94b6a1a95ee262b362f5a65b67b`
