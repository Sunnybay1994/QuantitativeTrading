- default-empty 拒绝 zero ORDER；合法 approved zero no-intent 通过；多余 allow id 拒绝；wrong subject 拒绝；
- zero decision 带 approved intents、`requires_manual_approval=true` 或 `accepted=false` 均拒绝；
- stage bytes/identity drift、approval raw/index drift 均拒绝；
- reconcile 结构闭包通过但不冒充 credential reverify；
- formal approval service 仅 PAPER 持久化；SHADOW risk 零命令且 service 全表零写；
- 普通 nonzero ORDER 与 CANCEL chain 保持；F6/F7/F9 的最小复现全部回归。

交付报告必须追加 VALIDATION1 的原生阶段结果、F6–F10 的“现象—根因—规则—最小复现—新增测试—通过条件”、
本次 exact17 扩围理由，以及 reviewer P2/P3 仍为明确的进程内 authority 残留边界。不得改写首轮或 REWORK1
历史。完成后先由经理核 exact17，再交同一独立审查角色复验；未经新资源授权不得运行任何检查。

## 15. REWORK3：持久化结构篡改反例补齐

状态：经理对 REWORK2 静态交付核对未通过；仍为 `STATIC_ONLY`，范围保持 exact17，独立 review 报告只读。

### F11：service 只覆盖 stage payload 与 approval index，未完整覆盖中央反例矩阵

- **现象：** `test_approval_zero_replay_rejects_stage_or_approval_index_drift` 先篡改 stage payload，再恢复并
  篡改 approval identity；没有分别证明 stage identity-only、approval raw payload 与 approval 其他 canonical
  index 漂移。测试名也把不完整矩阵表述成已覆盖。
- **根因：** 把“一次 payload 改动自然导致 digest 不一致”当作 bytes/identity 两类独立反例，并遗漏
  stored approval raw decode/canonical closure 的负向路径。
- **规则：** 在互相隔离的新 fixture/参数化 case 中分别篡改：stage payload、stage identity、approval raw
  payload、approval canonical index（至少 identity；宜增加 action/plan/session 中一项）。每项必须先证明
  logical snapshot 已改变，再调用 live replay，稳定 fail closed，失败后 logical snapshot exact 不变。
- **通过条件：** service 的 stage bytes/identity 与 approval raw/index 四族均有独立、可归因断言，不依赖前一
  case 的手工恢复或共享污染现场。

### F12：reconcile 只有正向结构闭包，缺少 approval/stage drift 反例

- **现象：** `test_recover_zero_approval_structural_closure_without_hmac_claim` 只证明合法 zero receipt 可恢复；
  未证明 reconcile 在 approval raw/index 或 stage bytes/identity 漂移时拒绝。
- **根因：** 将 service live replay 的负向测试误当成 reconcile structural ownership 的替代证据。
- **规则：** 为 `recover_repository_state` / `recover_local_state` 增加窄参数化反例，分别覆盖 approval raw、
  approval index、stage payload、stage identity；稳定映射为 recovery risk/closure failure，不得恢复成 trusted
  capability，不得修改持久化现场。
- **通过条件：** reconcile 正向仍明确“只证明结构、不 HMAC”；四类 drift 均 fail closed，调用前后 logical
  snapshot exact 不变。

### F13：RecoveryResult 新增 allow-set 字段的身份边界必须诚实复核

- **现象：** REWORK2 给 `RecoveryResult` 增加 `allowed_zero_order_subject_ids`，并声明其不进入
  `recovery_id`。该集合应当由已进入 identity 的 risk receipts 唯一确定，不能成为 caller 可自由改变但保持
  同 `recovery_id` 的第二状态维度。
- **规则：** 保持既有“approval rows 不进入 recovery identity”。若保留该字段，必须测试：它与观察到的合法
  zero receipt subject 集合 exact equality；多余/遗漏集合不能构造合法 `RecoveryResult`；同 recovery identity
  不可能对应两个不同 allow-set。若无法证明，应改成 reconcile 内部局部 witness，不扩大公共结果状态。
- **通过条件：** 不改变 recovery digest 语义，同时不存在可伪造的非身份化 allow-set 状态；交付报告如实记录
  选择及理由。

REWORK3 不允许改生产业务语义，除非 F13 证明当前公共字段确有合同漏洞；若需要超出 exact17，立即 STOP
申请，不得自行扩围。交付报告追加 F11–F13 六段证据，完成后再交同一独立 reviewer 复验。

## 16. REWORK4：VALIDATION4 focused 五项失败最小返工

状态：`STATIC_ONLY / DELIVERY_READY（等待独立复验 F14–F17）`。VALIDATION4 的 parser、identity 与证据承载闭合；focused pytest
为 `234 passed / 5 failed`，随后按首失败规则停止，Ruff/mypy/cold 未运行。证据根：
`artifacts/agent_runs/m4-a2-validation4-20260825T101729Z-73e6e516/`；pytest stdout SHA-256=
`6724CA226001C1A69E77AD6713BED9628CFD50E04EFA4B0EAE199C6E7B0BC73E`。

本轮只允许修改既有 exact17 中：`src/quant/execution/reconcile.py`、`tests/unit/test_reconcile.py`、
`tests/unit/test_execution_service.py`、`tests/unit/test_pretrade_risk.py`、本任务书与既有交付报告。其他生产
模块及独立初验报告只读；不得运行 Python/SQLite/测试/静态检查或提交。

### F14：approval raw 篡改必须保持 SQLite BLOB 类型

- **现象：** reconcile 与 service 两个 `approval_raw_payload` case 的 `payload || X'00'` 被 SQLite 表达为
  TEXT，先触发 `typeof(payload)='blob'` CHECK，未进入预期 replay/recovery fail-closed 路径。
- **规则：** 测试须以 `CAST(payload || X'00' AS BLOB)` 或等价、明确保持 BLOB 类型的合法 SQL 篡改；先证明
  logical snapshot 改变，再证明 service/recovery 拒绝且现场不再变化。不得放宽 migration CHECK。
- **REWORK4 处置：** 两处测试改为 `CAST(payload || X'00' AS BLOB)`；不改 v008 CHECK。

### F15：approval index 解码失败必须归入 risk closure

- **现象：** reconcile 的 `approval_index_identity` 实际为 `RECOVERY_LOCAL_INVALID`，合同要求
  `RECOVERY_RISK_CLOSURE_INVALID`。
- **根因：** `read_recovery_rows()` 在 approval row 解码阶段先抛通用异常，尚未进入 `_verify_risk_closure`。
- **规则：** `recover_repository_state` 应在同一既有事务内先通过公开 repository API 读取并验证 approval rows；
  此专属读取失败映射为 `_RiskRecoveryClosureError`。随后读取完整 recovery rows，并要求两次观察到的 approval
  tuple exact 相同，否则同样按 risk closure 拒绝。不得把其他 commands/ledger/cancel 解析失败误归类，不得修改
  store/schema/recovery identity，也不得复制 approval decoder。
- **通过条件：** approval raw/index 漂移稳定 `RECOVERY_RISK_CLOSURE_INVALID`；其他既有
  `RECOVERY_LOCAL_INVALID` / cancel 错误族不漂移。
- **REWORK4 处置：** `recover_repository_state` 先 `query_approval_receipts()`，失败→risk closure；再
  `read_recovery_rows()` 并要求 `rows.approval_receipts == observed_approvals`。

### F16：delivery orphan 必须使用真实 schema

- **现象：** 测试更新不存在的 `outbox_deliveries.identity` 列，得到 `OperationalError`。
- **规则：** 该 case 是 orphan closure，直接删除对应 delivery row（或采用现有真实列且满足迁移约束的等价
  孤儿构造）；先证明 snapshot 改变，再证明 exact replay fail closed 且不补完孤儿。不得改 v002/schema。
- **REWORK4 处置：** `delivery` case 改为 `DELETE FROM outbox_deliveries WHERE outbox_key = ?`。

### F17：pretrade source fixture 必须同时真实、排序且值唯一

- **现象：** `_plan` 默认把 `config_identity` 与 `trading_config_identity` 设为同一值，测试却直接要求六个
  approval source values 唯一，断言先失败。
- **规则：** 仅在该定向测试为 `_plan` 增加默认行为不变的窄可选 planner/config identity 参数，使该 plan 的
  `config_identity` 与 trading config identity 均真实且互异；intent 与 plan 必须共享该 planner identity。
  PAPER 与 SHADOW 两个 fixture 均使用各自稳定的独立 planner identity。不得用与 plan 不绑定的虚构 source map
  绕过，也不得放宽 A1 stable-sorted/unique-values 合同。
- **REWORK4 处置：** `_plan(..., planner_config_identity=None)` 默认仍 planner=trading；PAPER/SHADOW 分别传入
  `_hex64("pretrade-planner-paper")` / `_hex64("pretrade-planner-shadow")`。

### F18：验证与复验条件

返工报告逐项补齐“现象—根因—规则—最小复现—新增测试—通过条件”，保留 P2/P3/review E 为进程内
authority 边界。完成后由原独立 reviewer 只读复验 F14–F17；复验 PASS 后再申请新的受控 validation。

## 17. REWORK5：RecoveryError 稳定 code 类型合同

状态：`STATIC_ONLY / DELIVERY_READY（等待独立复验 F19）`。VALIDATION5 已证明 parser、identity、focused 七文件（239 passed）与
Ruff exact15 通过；mypy production8 在 `service.py:453` 首失败后停止，cold/final-scope 未运行。证据根：
`artifacts/agent_runs/m4-a2-validation5-20260825T103620Z-e53a68e4/`；mypy stdout SHA-256=
`EC5AF65F17AA4753412B87646447CDCB7AC84A0B83C0F7D37466E4179E777D2C`。

### F19：RecoveryError 的运行时与类型合同不一致

- **现象：** `service.plan_and_stage` 将 `RecoveryError.code` 转为 `ExecutionServiceError`，但
  `RecoveryError` 当前只是空 `ValueError` 子类；mypy 报 `attr-defined`。正常路径 focused 测试未触发该异常分支。
- **根因：** recovery 错误已按稳定单一 code 字符串构造，却没有像 `ApprovalFlowError` /
  `ExecutionServiceError` 一样把该 code 暴露为显式属性。
- **规则：** 只在 `RecoveryError` 增加最窄 `__init__(code: str)`：`self.code = code` 后
  `super().__init__(code)`。保持所有既有 raises、`args`、`str(error)`、detached cause/context 与错误码不变；
  不在 service 用 `str()`/`args[0]` 旁路类型合同，不改变 ReconciliationError 或其他异常族。
- **新增测试：** `test_recovery_error_exposes_stable_code_without_context` 或等价定向测试，断言
  `error.code == error.args[0] == str(error)`，且 detached 语义不变；宜使用现有真实 recovery fail-closed 路径，
  不伪造新的业务错误码。
- **范围：** 仅 `src/quant/execution/reconcile.py`、`tests/unit/test_reconcile.py`、本任务书与既有交付报告；
  其他 exact17 路径及独立初验报告只读。零 Python/SQLite/检查/提交。
- **通过条件：** 外部实现静态交付后，独立外部 reviewer 确认 API 仅兼容性增强、异常字符串/脱敏/分类零漂移；
  再申请 post-fix validation。VALIDATION5 已绿 focused/Ruff 不自动冒充最终通过。
- **REWORK5 处置：** `RecoveryError.__init__(code: str)` 已落地；全部既有构造点仍传稳定 str literal；
  定向测试经真实 hostile-command → `RECOVERY_LOCAL_INVALID` 路径断言 code/args/str、detached，
  以及两独立实例不共享状态。未改 service/ReconciliationError/错误码。


### F14 合同漏项（主 Agent 发现；REWORK4 追加；保留 CAST 历史）

状态：`STATIC_ONLY`；本轮仅允许写 `tests/unit/test_reconcile.py`、`tests/unit/test_execution_service.py`
与本任务书/既有交付报告；生产代码、独立初验报告及其他文件只读；零 Python/pytest/Ruff/mypy/cold/SQLite
probe/网络/提交。

- **现象：** 两处 `approval_raw_payload` 已用 `CAST(... AS BLOB)`，但 commit 后未显式
  `SELECT typeof(payload)` 并断言精确等于 `blob`，F14 storage-class 合同仍缺可观察证据。
- **根因：** REWORK4 首轮只闭合了合法 BLOB 篡改 SQL，未把 commit 后 storage class 观察写入测试断言。
- **规则：** 仅在 `approval_raw_payload` 参数分支、且在该分支 commit 之后，显式查询
  `typeof(payload)` 并 `assert == "blob"`；其他 tamper 分支不得执行该断言；不改 v008 CHECK/生产代码。
- **最小复现：** reconcile/service 的 `approval_raw_payload` case：CAST 更新 → commit →
  `SELECT typeof(payload)` → 精确 `blob` → 再进入既有 snapshot≠before → fail-closed → snapshot exact。
- **新增/强化测试：** 同上两参数化 case 各补一条 commit 后 typeof 断言（仅该分支）。
- **通过条件：** 静态可见 commit 后 `typeof(payload)=="blob"` 断言仅挂在 `approval_raw_payload`；
  不扩围、不改生产、不宣称 runtime/Gate。
