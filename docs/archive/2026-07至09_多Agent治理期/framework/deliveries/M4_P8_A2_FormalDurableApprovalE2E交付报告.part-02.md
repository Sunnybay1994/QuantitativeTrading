- **现象：** `payload || X'00'` 被 SQLite 表达为 TEXT，先撞 `typeof(payload)='blob'` CHECK，未进入预期 fail-closed。
- **根因：** 拼接结果未显式 CAST，触发 affinity/typeof 与 migration CHECK 冲突。
- **规则：** 用 `CAST(payload || X'00' AS BLOB)` 合法篡改；先证 logical snapshot 变，再拒绝且现场不变；不放宽 CHECK。
- **最小复现：** reconcile/service 的 `approval_raw_payload` 独立 case：CAST 更新 → snapshot≠before → recover/replay 拒绝 → snapshot exact。
- **新增/强化测试：** `test_recover_zero_approval_rejects_approval_or_stage_structure_drift[approval_raw_payload]`；`test_approval_zero_replay_rejects_stage_and_approval_structure_drift[approval_raw_payload]`。
- **通过条件：** 进入结构漂移 fail-closed，而非 CHECK/`OperationalError`。

#### F15：approval 专属读取失败映射 risk closure

- **现象：** `approval_index_identity` 漂移得到 `RECOVERY_LOCAL_INVALID`，合同要 `RECOVERY_RISK_CLOSURE_INVALID`。
- **根因：** `read_recovery_rows()` 内 `_row_to_stored_approval` 先抛，未进入 `_verify_risk_closure`。
- **规则：** 同事务先公开 API 读/验 approval；失败→`_RiskRecoveryClosureError`；再读完整 recovery rows，两次 approval tuple exact，否则同归 risk closure；其他族不漂移；不改 store/decoder/identity。
- **最小复现：** index/raw 漂移 → 两次 recover API 均 `RECOVERY_RISK_CLOSURE_INVALID`；既有 orphaned/local invalid 与 cancel 族保持原错误码。
- **新增/强化实现与测试：** `recover_repository_state` 先 `query_approval_receipts()` 再比对 `rows.approval_receipts`；既有 F12 参数化继续覆盖。
- **通过条件：** approval raw/index → risk closure；commands/ledger/cancel 解析失败仍 LOCAL/cancel 族。

#### F16：delivery orphan 使用真实 schema

- **现象：** `UPDATE outbox_deliveries SET identity=...` 列不存在 → `OperationalError`。
- **根因：** `identity` 来自 join 的 `outbox`，delivery 表无该列。
- **规则：** orphan 直接 DELETE delivery row（或真实列等价构造）；先证 snapshot 变，再 replay fail-closed 不补完；不改 v002。
- **最小复现：** DELETE delivery → snapshot 变 → `plan_and_stage` 拒绝 → snapshot 不变且不重建 delivery。
- **新增/强化测试：** `test_approval_replay_orphan_closure_fail_closed[delivery]`。
- **通过条件：** 以真实 schema 构造孤儿并稳定 fail-closed。

#### F17：pretrade source fixture 真实、排序、值唯一

- **现象：** `_plan` 默认 planner=`trading` 同值，六 source unique 断言先失败。
- **根因：** fixture 未提供互异且与 plan/intent 绑定的 planner identity。
- **规则：** `_plan` 增加默认不变的可选 `planner_config_identity`；PAPER/SHADOW 各自稳定独立 planner；intent 共享；不虚构 source map、不放宽 A1。
- **最小复现：** PAPER/SHADOW 分别传入独立 planner hex；`dict(sorted)` + `len(set(values))==len(sources)`；`config_identity!=trading_config_identity`。
- **新增/强化测试：** `test_verified_approval_unlocks_manual_gate_for_paper_only`；其他 `_plan` 调用默认行为不变。
- **通过条件：** 六值唯一且与 plan/intent 真实绑定；默认路径仍 planner=trading。

### 13.2 Reviewer P2/P3 / review E 残留边界（明确保留）

进程内 capability 字段级 `object.__new__` 克隆、CLI approve 事务间隙并发面，以及既有 review E 边界不变；本轮未扩大或宣称消除。

### 13.3 REWORK4 未运行项 / 阻塞

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite / 网络 / PAPER | 未运行（STATIC_ONLY） |
| Git commit | 未执行 |
| 独立复验报告 | 未修改（只读） |
| Gate / UA-M4-006/007 | 不声称 |
| STOP | 无 |

### 13.4 F14 合同漏项（主 Agent 发现；追加；不改写 §13.1 CAST 历史）

状态：`DELIVERY_READY`（STATIC_ONLY；仍不等于独立复验/主验/Gate）<br>
约束：仅改两测试 + 任务书/本交付报告；生产代码与独立初验报告只读；零 Python/pytest/Ruff/mypy/cold/SQLite
probe/网络/提交；未扩围。

- **现象：** `approval_raw_payload` 已 `CAST(... AS BLOB)`，但 commit 后无显式 `SELECT typeof(payload)`
  且断言精确等于 `blob`。
- **根因：** 首轮 REWORK4 只修合法篡改 SQL，未把 storage class 观察写入测试合同证据。
- **规则：** 仅在该 tamper 分支、commit 之后断言 `typeof(payload) == "blob"`；其他分支不执行；不放宽 CHECK。
- **最小复现：** CAST → commit → `SELECT typeof(payload)` → `blob` → 既有 snapshot/fail-closed 链不变。
- **新增/强化测试：**
  `test_recover_zero_approval_rejects_approval_or_stage_structure_drift[approval_raw_payload]`；
  `test_approval_zero_replay_rejects_stage_and_approval_structure_drift[approval_raw_payload]`。
- **通过条件：** 两处静态可见 commit 后精确 `blob` 断言且仅挂在该参数分支。

DELIVERY_READY docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md

---

## 15. REWORK5 问题闭环（追加；不改写首轮/REWORK1–4 / VALIDATION5 历史）

状态：`DELIVERY_READY`（REWORK5 STATIC_ONLY 完成；仍不等于独立复验/主验/Gate）<br>
约束：未运行 Python/pytest/Ruff/mypy/cold/SQLite/网络/PAPER；未 commit；未修改独立初验报告或 service.py。<br>
身份：exact base=`7fe836dcfbd841c5473057d3f6e222a6081ae3fa`；branch=`codex/m4-a2-formal-approval-flow`。<br>
范围：仅 `reconcile.py`、`test_reconcile.py`、任务书与本交付报告；未扩围、未新增错误码/包装层。

### 15.1 F19 六段证据

#### F19：RecoveryError 暴露稳定 code

- **现象：** `service.plan_and_stage` 读取 `RecoveryError.code`，但类无该属性；mypy `attr-defined` 于 `service.py:453`。
- **根因：** 稳定单一 code 字符串已用于全部 raises，却未像 `ApprovalFlowError`/`ExecutionServiceError` 暴露显式 `.code`。
- **规则：** 仅增最窄 `__init__(code: str)`：`self.code = code`；`super().__init__(code)`。既有 raises、`args`、`str`、detached、错误码零漂移；不旁路 service 类型合同；不改 ReconciliationError。
- **最小复现：** 真实 hostile command payload → `recover_local_state` → `RECOVERY_LOCAL_INVALID`；断言 `code == args[0] == str` 且 cause/context detached；两独立实例互不影响。
- **新增/强化测试：** `test_recovery_error_exposes_stable_code_without_context`。
- **通过条件：** 静态可见全部构造点传稳定 str literal/code；API 仅兼容性增强；未宣称 runtime/Gate。

### 15.2 构造点静态核对（只读）

| 位置 | 构造 | 结论 |
| --- | --- | --- |
| `RecoveryIssue.__post_init__` | `RecoveryError("RECOVERY_RESULT_INVALID")` | 稳定 literal |
| `RecoveryResult.__post_init__` | `RecoveryError("RECOVERY_RESULT_INVALID") from None` | 稳定 literal |
| `_recover_from_rows` cancel 闭包 | `RecoveryError("CANCEL_RECOVERY_CLOSURE_INVALID") from None` | 稳定 literal |
| `_recover_from_rows` risk 闭包 | `RecoveryError("RECOVERY_RISK_CLOSURE_INVALID") from None` | 稳定 literal |
| `_recover_from_rows` local | `RecoveryError("RECOVERY_LOCAL_INVALID") from None` | 稳定 literal |
| `recover_local_state` 外层 | `RecoveryError("RECOVERY_LOCAL_INVALID") from None` | 稳定 literal |

`service.py:453` 仍为只读消费点 `ExecutionServiceError(error.code)`；本轮未改。

### 15.3 REWORK5 未运行项 / 阻塞

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite / 网络 / PAPER | 未运行（STATIC_ONLY） |
| Git commit | 未执行 |
| 独立复验报告 | 未修改（只读） |
| Gate / UA-M4-006/007 | 不声称 |
| STOP | 无 |

DELIVERY_READY docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md

## 16. DOC-WHITESPACE 记录

- **现象：** 任务书与交付报告元数据/状态块使用 Markdown 行尾双 ASCII 空格硬换行，导致文档行尾空白非零，`git diff --check` 会报 trailing whitespace。
- **根因：** 历史交付用行尾双空格表达强制换行，与仓库文档行尾空白必须为 0 的卫生合同冲突。
- **规则：** 仅规范化行尾双空格；确有强制换行语义者改为显式 `<br>`，其余改正常段落/列表；不得改措辞、业务合同、状态、证据 SHA 或路径；review/生产/测试/evidence 只读；STATIC_ONLY。
- **处置：** 两白名单文档全部行尾双空格改为显式 `<br>`（元数据强制换行语义）；本段追加；行尾空白静态计数归零。
- **通过条件：** 两路径行尾空白静态计数均为 0；本新增段无行尾空白；未改 review/SHA/业务合同。
