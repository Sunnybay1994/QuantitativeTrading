# M4 P8 A2：Formal Durable Approval E2E 交付报告

日期：2026-08-25<br>
状态：`DELIVERY_READY`（STATIC_ONLY；不等于独立初验、主验或 Gate 通过）<br>
exact base：`7fe836dcfbd841c5473057d3f6e222a6081ae3fa`<br>
branch：`codex/m4-a2-formal-approval-flow`<br>
worktree：`artifacts/dev_worktrees/m4-a2-formal-approval-flow`

## 1. 结果摘要

将 A1 `VerifiedApprovalReceipt` hand-off 接入 formal PAPER operator approve 路径：受控 credential capability 签发、同一 `BEGIN IMMEDIATE` 内 recovery fence → approval-first → 既有 risk/stage/outbox/ledger 闭包；`manual_approval=true` 仅 exact verified receipt 解锁 PAPER command。未运行任何 Python/pytest/Ruff/mypy/cold/SQLite/网络/PAPER；未 commit。

## 2. exact15 变更路径

1. `src/quant/execution/approval_flow.py`（新）
2. `src/quant/execution/cli_ports.py`
3. `src/quant/execution/cli.py`
4. `src/quant/execution/reconcile.py`
5. `src/quant/execution/service.py`
6. `src/quant/execution/risk.py`
7. `src/quant/execution/paper_formal_daily.py`
8. `tests/unit/test_approval_flow.py`（新）
9. `tests/unit/test_execution_cli.py`
10. `tests/unit/test_reconcile.py`
11. `tests/unit/test_execution_service.py`
12. `tests/unit/test_pretrade_risk.py`
13. `tests/unit/test_paper_formal_daily.py`
14. `docs/framework/tasks/M4_P8_A2_FormalDurableApprovalE2E任务书.md`（未改内容）
15. `docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md`（本文件）

未修改：`approval.py`、`store.py`、migration、config、`__init__.py`、roadmap、独立初验报告。

## 3. 关键设计

- **Capability**：`FormalApprovalCredentialCapability` 为 exact 内部类型（`init=False` + module proof）；secret 不参与 repr/equality；factory 只接受 caller bytes-like secret + opaque ids + trusted session。
- **签发**：仅 canonical `approve` challenge；`issued_at` 取 challenge；nonce = HMAC(secret, domain‖challenge_id)；exact challenge+credential 确定性同一 receipt。
- **Source 绑定**：approve challenge/receipt 使用可由 `OrderPlan` 复算的 source map（target/market/account/planner/trading），service 在事务内重算 digest。
- **Recovery**：公开 `recover_repository_state(repo)`；`recover_local_state` 仅作 transaction wrapper；approval 不进入 `RecoveryResult` identity。
- **Service**：`plan_and_stage(..., approval=None)` 缺省兼容；带 approval 时事务内：证明 hand-off → source/plan/session → 既有 business-key exact replay 或 recovery fence → `put_verified_approval_receipt` → 既有 stage 写路径。
- **Risk**：`evaluate_pretrade(..., approval=None)`；PAPER+manual 仅 `unpack_verified_approval_receipt` 且 plan/session 匹配才发 command；SHADOW 永远零 command。
- **CLI/formal daily**：approve 缺 capability/trusted operator/session 稳定失败；confirm 前不调用 capability；成功输出含 `receipt_id`/`plan` 非敏感 identity。

## 4. 合同/边界说明

- 首次注入的 capability 即本进程 credential authority；wrong-secret 仅适用于已有 receipt 重验签或另一 capability 冲突，不虚构首次 key 真实性 Gate。
- CLI 在状态变更后无法用“新 challenge”重放旧 receipt；exact replay 以同一 `VerifiedApprovalReceipt` 再次 `plan_and_stage` 为准（service 测覆盖）。新鲜 challenge 对已占用 business-key 映射为 conflict/CONFIRMATION_DRIFT。

## 5. 未运行项（强制 STATIC_ONLY）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold import | 未运行 |
| SQLite probe / 真实 I/O / 网络 / PAPER / broker | 未运行 |
| Git commit | 未执行 |
| 独立初验 / 主验 / Linux Gate / UA-M4-006/007 | 未声称 |

偶然：两次仅 `len(bytes)` 的本机 `python -c` 长度核对，不构成验证证据，亦非 focused 测试。

无 6. 阻塞 / STOP

无 A1 public API 或事务边界矛盾导致的 STOP。后续需经理授权 CPU 槽后串行 focused pytest → Ruff → mypy → cold → scope，并由未参与实现的独立初验补充对抗反例（孤儿 approval、capability copy/pickle、事务中 drift、no-op replay、secret 泄漏面）。

DELIVERY_READY docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md

## 16. VALIDATION6 final-scope cache STOP（主 Agent 追加）

状态：`VALIDATION_STOP / REGENERABLE_CACHE_RESIDUE`；产品与静态阶段通过，final-scope 未签发，仍不构成 Gate。

- evidence root：`artifacts/agent_runs/m4-a2-validation6-20260825T104636Z-971e939a/`。
- parser PASS；identity PASS；定向 pytest `5 passed in 3.10s`，stdout SHA-256=`F2D600D1769186836F5E491592B0CE5663D1DB104FD9DC82E5CD3C300A18D556`；mypy production8 PASS，stdout SHA-256=`7AEFCACC6D445354A115CF76FCDEA696165BE7AD8CF9B86A60EA98727C6E96F6`；cold production8 PASS。
- final-scope 在发现工作树根 `.mypy_cache` 后 exit=1；该缓存由 VALIDATION5/6 mypy 生成，非业务文件或正式证据。核对绝对路径后已精确删除；未删除/覆盖任何 validation evidence。
- fresh basetemp 与空 `.tmp` 已清；无 `0xF00` Python/PowerShell 残留；finance writer 未扰动。
- 按首失败规则未自行重跑 final-scope。下一步仅申请不运行 Python 的 final-scope 收口；不得把前述阶段 PASS 与整体 Gate 混同。

## 17. VALIDATION6 final-scope-1 cache STOP（主 Agent 追加）

状态：`VALIDATION_STOP / REGENERABLE_RUFF_CACHE_RESIDUE`；无 Python，尚未完成 process residue。

- evidence root：`artifacts/agent_runs/m4-a2-validation6-final-scope-20260825T104933Z-4d19245b/`。
- Parser PASS；exact18 scope PASS；cached=0 PASS；`git diff --check` PASS。
- temp/cache 阶段确认 `.tmp`、`.mypy_cache`、`.pytest_cache` 均不存在，但发现 `.ruff_cache`；其 mtime=2026-08-25 18:37:17，与 VALIDATION5 Ruff 运行一致。核对绝对路径后已精确删除；未动业务字节或 evidence。
- 按首失败规则未继续 process residue、未自行重跑。申请仅 temp/cache + process 的只读终态收口。

## 18. VALIDATION6 residue close PASS（主 Agent 追加）

状态：`VALIDATION_EVIDENCE_COMPLETE / AWAITING_INDEPENDENT_EVIDENCE_REVIEW`；不等于 SAFE_COMMIT/Gate。

- evidence root：`artifacts/agent_runs/m4-a2-validation6-residue-close-20260825T105138Z-e4f3c46a/`。
- Parser PASS；四个精确路径 `.tmp`、`.mypy_cache`、`.pytest_cache`、`.ruff_cache` 均不存在；stdout SHA-256=`958C3C288A61106C188697DD37910C94B369BDDEDF23BD34AB1A35586AAAB174`。
- Get-Process：无 affinity `0xF00`；finance writer PID 7692 仍为 Python/BelowNormal/`0x3`；stdout SHA-256=`E174A05C8BF083FB981F7904B47C30FE93FF4CD1E9F17B774E1B05239BDC12BD`。
- 与 §14–§17 合并口径：VALIDATION5 focused 239 + Ruff PASS；VALIDATION6 定向 5 + mypy8 + cold8 PASS；scope exact18/cached0/diff-check PASS；最终 temp/cache/process PASS。
- 下一步仅由独立外部 reviewer 复核上述持久证据；复核通过后向中央申请 SAFE_COMMIT，不自行 stage/commit/merge。

## 10. VALIDATION2 运行证据收口（主 Agent 追加）

状态：`VALIDATION_STOP / EXECUTION_EVIDENCE_NOT_RETAINED`，不计实现通过或失败，不允许据此进入合流。

- 已按中央租约启动单实例 Windows carrier；carrier 自身与子进程均已退出。
- 工具返回因输出超过上下文而被截断，且本次 carrier 未将各阶段原生 stdout/stderr/exit 持久化到文件；因此无法诚实重建 focused pytest、Ruff、mypy 与 cold import 的逐阶段结果。
- 终态只读核对：项目 `.tmp` 不存在；未发现 `.pytest_cache`、`.mypy_cache`、`.ruff_cache`；未发现 affinity `0xF00` 的 Python/PowerShell 残留；受保护 finance writer 仍为 PID 7692、BelowNormal、affinity `0x3`，未被扰动。
- Git 现场仍严格位于批准的 exact18（exact17 实现/任务/交付 + 唯一独立初验报告），未发现范围外业务路径。
- 本 STOP 属于验证证据保存合同缺口，不是实现红灯；不自行重跑。下一次如获授权，carrier 必须将每阶段命令、stdout、stderr、exit 与总终态写入新的 no-clobber ignored evidence 目录，再返回摘要。
- P2/P3 与独立初验 E 继续仅作为已知进程内 authority 边界；本次运行未把它们升级为外部 credential 真实性 Gate。

## 11. VALIDATION3 carrier 解析失败收口（主 Agent 追加）

状态：`VALIDATION_STOP / CARRIER_PARSE_FAILED_BEFORE_START`，不计实现通过或失败，不允许自行重跑。

- no-clobber evidence root：`artifacts/agent_runs/m4-a2-validation3-20260825T101440Z-949068b0/`。
- runner：`run-validation3.ps1`，9,286 bytes，SHA-256=`9675EC6BAE57A5EA519E71BD87EF40AAAEC1B147475209A596E6F779F707F350`。
- PowerShell 在解析第 41 行时拒绝 `"STAGE_FAILED:$number:$name:$code"`：冒号紧随变量名导致非法变量引用。脚本主体未开始，因此没有创建 stage summary/三元证据文件，没有设置 BelowNormal/`0xF00`，没有启动 Python、pytest、Ruff、mypy 或 cold import。
- 终态未发现 `0xF00` Python/PowerShell 残留；业务 exact18 字节未因本次尝试改变（本节记录除外）。
- 若中央批准新的独立验证，须先把所有变量插值改为 `${number}` / `${name}` / `${code}` 或格式化表达式，并在启动前用 PowerShell parser 做**不执行脚本**的语法验真；不得把该语法检查冒充任何业务验证。

## 12. VALIDATION4 focused STOP（主 Agent 追加）

状态：`VALIDATION_STOP / FOCUSED_TEST_FAILED`；资源已释放，未进入 Ruff/mypy/cold，不构成 Gate。

- evidence root：`artifacts/agent_runs/m4-a2-validation4-20260825T101729Z-73e6e516/`（保留，未覆盖 VALIDATION3）。
- parser PASS：stderr 0 bytes，exit=0；identity PASS：stderr 0 bytes，exit=0，三模块来自 exact worktree。
- focused pytest：`234 passed / 5 failed / 56 warnings in 13.65s`，stderr 0 bytes，exit=1；stdout 14,851 bytes，SHA-256=`6724CA226001C1A69E77AD6713BED9628CFD50E04EFA4B0EAE199C6E7B0BC73E`。
- 五项失败：reconcile approval raw BLOB 篡改先撞 CHECK；reconcile approval identity 漂移错误码为 `RECOVERY_LOCAL_INVALID`；service delivery case 使用不存在的 `identity` 列；service approval raw BLOB 篡改先撞 CHECK；pretrade source fixture 的 planner/trading identity 重复。
- fresh basetemp 与空 `.tmp` 已清理；终态无 `0xF00` Python/PowerShell；finance writer PID 7692/BelowNormal/`0x3` 未扰动。
- 返工合同见任务书 §16 F14–F18；本次运行不改变 P2/P3/review E 的既有边界。

## 14. VALIDATION5 mypy STOP（主 Agent 追加）

状态：`VALIDATION_STOP / STATIC_TYPE_FAILED`；资源已释放，未进入 cold/final-scope，不构成 Gate。

- evidence root：`artifacts/agent_runs/m4-a2-validation5-20260825T103620Z-e53a68e4/`。
- parser PASS；identity PASS；focused 七文件 `239 passed / 56 warnings in 13.10s`，stdout SHA-256=`A80E40E9647E566D82A31A15F9F6C336ED258A576937B7987C4BB6E36F3DC440`；Ruff exact15 PASS。
- mypy production8 exit=1：`src/quant/execution/service.py:453: error: "RecoveryError" has no attribute "code" [attr-defined]`；stdout SHA-256=`EC5AF65F17AA4753412B87646447CDCB7AC84A0B83C0F7D37466E4179E777D2C`。
- fresh basetemp 与空 `.tmp` 已清；无 `0xF00` Python/PowerShell 残留；受保护 writer 未扰动。
- 根因与最小返工合同见任务书 §17 F19；本轮不改变 P2/P3/review E 边界。

---

## 7. REWORK1 问题闭环（追加；不改写首轮历史）

状态：`DELIVERY_READY`（REWORK1 STATIC_ONLY 完成；仍不等于独立初验/主验/Gate）<br>
约束：未运行 Python/pytest/Ruff/mypy/cold/SQLite/网络/PAPER；未 commit；未创建或修改独立初验报告。

### F1：approve source identity 被弱化

- **现象：** 首轮把 approve challenge 换成 plan 可推导弱集合，删除 `target_receipt_identity` / `target_verification_identity`。
- **根因：** 为 service 内复算 source digest，错误替换既有 CLI planning-source 语义。
- **规则：** approve 恢复 `_planning_sources`；service 新增 `approval_source_identities`，digest exact 一致并对 account/market/planner/trading 子集复算，不删除已验 target 来源。
- **最小复现：** 同 target values/plan 但替换 target receipt/verification → challenge/receipt 必须漂移。
- **新增/恢复测试：** `test_plan_and_approve_challenges_keep_full_planning_source_keys`；`test_approval_source_map_requires_target_receipt_and_verification_keys`；service weak-map `APPROVAL_SOURCE_DRIFT`。
- **通过条件：** plan/approve 既有 source keys 不退化；receipt/service exact closure 同时成立。

### F2：fresh post-completion approve 丢失既有幂等 replay

- **现象：** fresh post-completion 被改成 `CONFIRMATION_DRIFT`/exit 20。
- **根因：** 每次新 challenge 新签不同 receipt，未对 stored raw 做 capability 重新验签后走 exact replay。
- **规则：** fresh challenge 确认后查询 plan/session 唯一 stored raw，用同一 capability HMAC 重验签并交叉验证 operator/session/source，再把 exact `VerifiedApprovalReceipt` 交给 service；不新签第二 receipt。
- **最小复现：** 首次 approve 后 fresh challenge 再确认 → exit 0、同 receipt id、`APPROVAL_STAGED_REPLAY`、无第二经济影响。
- **新增/恢复测试：** CLI/formal-daily fresh replay 断言恢复；`test_approve_fresh_replay_rejects_wrong_capability`；`reverify_stored_approval_receipt` wrong-secret。
- **通过条件：** 既有 CLI 幂等行为恢复，且 stored receipt 必须经 credential fresh reverify。

### F3：existing receipt 的 command/outbox/ledger 闭包不完整

- **现象：** replay 未逐 command 证明 aggregate/outbox/delivery exact join。
- **根因：** 复用旧 helpers，未补齐任务书要求的完整闭包。
- **规则：** exact approval replay 必须证明 command/aggregate/outbox/delivery/ledger context，以及 ORDER receipt、counter、checkpoint；任一缺失/篡改 fail closed，不补完。
- **最小复现：** 保留 exact approval+stage，分别删除上述任一项 → 新写前拒绝且 store bytes 不变。
- **新增测试：** `test_approval_replay_orphan_closure_fail_closed` 参数化覆盖 8 类。
- **通过条件：** 仅完整 economic/storage closure 才返回 replay。

### F4：强制 no-op、rollback 与 formal composition 证据缺失

- **现象：** 缺 zero-command 闭包、approval 后 stage 失败整事务 rollback、CLI confirm 前 fail-on-call、formal 参数透传证据。
- **规则：** zero-command 仍写 approval+ORDER risk/stage/checkpoint/counter；insert 后失败全回滚；无 confirm 不触碰 capability；formal builder/operator exact 透传 capability/operator/session。
- **新增测试：** `test_approval_zero_command_closure_and_exact_replay`；`test_approval_insert_then_stage_failure_rolls_back_entire_tx`；`test_approve_confirm_gate_leaves_fail_on_call_capability_untouched`；`test_operator_forwards_approval_capability_and_trusted_anchors`；`test_build_dependencies_rejects_trusted_session_mismatch`。
- **通过条件：** no-op/replay/rollback/confirm-order/formal forwarding 均有窄断言。

### F5：最小变更与时钟一致性

- 恢复 `test_pretrade_risk.py` 尾部既有 `build_execution_event,` / `evaluate_cancel_risk,` 表达式。
- CLI 一次 approve 只读一次 trusted clock，同一 `now` 用于 challenge 与 capability issuance。
- 本段为追加闭环；首轮第 1–6 节未改写。

### REWORK1 未运行项 / 阻塞

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite / 网络 / PAPER | 未运行（STATIC_ONLY） |
| Git commit | 未执行 |
| 独立初验报告 | 未创建/未修改 |
| STOP | 无 |

DELIVERY_READY docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md

---

## 8. REWORK2 问题闭环（追加；不改写首轮/REWORK1 历史）

状态：`DELIVERY_READY`（REWORK2 STATIC_ONLY 完成；仍不等于独立复验/主验/Gate）<br>
约束：未运行 Python/pytest/Ruff/mypy/cold/SQLite/网络/PAPER；未 commit；未修改独立初验报告。<br>
身份：exact base/HEAD=`7fe836dcfbd841c5473057d3f6e222a6081ae3fa`；branch=`codex/m4-a2-formal-approval-flow`。

### 8.1 VALIDATION1 原生阶段结果（经理授权 focused 运行证据摘要）

- identity preflight：通过。
- focused 六文件测试：`200 passed / 12 failed` 后按资源合同 STOP。
- Ruff、mypy、cold import：未运行。
- fresh basetemp 与空 `.tmp` 已清理；未见 0xF00 Python 残留。
- 此前静态 `REVIEW_PASS` 已被本次运行证据推翻；返工后须重新独立复验。

### 8.2 exact17 扩围理由

中央裁定 F8 必须扩展唯一 semantic verifier / stage codec，不能在 service 内复制第二套 risk-chain 或 skip verifier。白名单由 exact15 精确扩为 exact17，新增：

16. `src/quant/execution/risk_wire.py`
17. `tests/unit/test_risk_wire.py`

未扩 `store.py` / schema / migration / config / `__init__.py` / roadmap / 共享 SSOT / 独立 review 报告。

### 8.3 F6–F10 六段证据

#### F6：capability Guard 与 source drift

- **现象：** issue API 对伪 capability 在 exact-type guard 即拒绝，`__getattr__` 不被触碰；stored source map 重验签返回 A1 `APPROVAL_SOURCE_IDENTITIES_INVALID`。
- **根因：** 测试混淆 confirm-order 与 issue exact-type；A2 未把底层 source codec 错误归一为业务 drift。
- **规则：** exact-type 拒绝不读属性；stored source mismatch 对外 `APPROVAL_SOURCE_DRIFT`。
- **最小复现：** `__getattr__` Guard；另一合法 exact6 source map 重验签。
- **新增测试：** `test_exact_type_guard_rejects_fake_capability_without_getattr`；`test_reverify_source_map_mismatch_normalizes_to_source_drift`；CLI confirm 前 untouched 保持。
- **通过条件：** Guard untouched + 稳定 capability error；source drift 稳定映射，CLI 为 drift 类退出。

#### F7：orphan 注入与 WAL bytes

- **现象：** FK 拒绝 DELETE commands/outbox；WAL 下主库文件 bytes 比较不可靠。
- **根因：** 用物理主文件 bytes 与破坏 FK 的删除制造孤儿。
- **规则：** payload/index tamper + 事务内 logical snapshot。
- **最小复现：** UPDATE payload/identity；replay 失败后 snapshot exact 不变。
- **新增/修复测试：** `test_approval_replay_orphan_closure_fail_closed` 改为 UPDATE + `_logical_execution_snapshot`。
- **通过条件：** 每类孤儿先证明逻辑行已篡改，再 fail closed，失败后逻辑状态不变。

#### F8：zero-command ORDER 与 semantic verifier

- **现象：** zero-command 首次写入成功，exact replay 在 `verify_risk_receipt_semantic_closure` 失败。
- **根因：** verifier 拒绝空 `command_ids` ORDER，与 A2 approved no-command 闭包冲突。
- **规则：** keyword-only `allowed_zero_order_subject_ids` 默认空；仅 subject∈allow-set 且 empty intents/commands、accepted、!manual、chain/counter/wire 完整且 allow-set exact 消费时允许；service/reconcile 构造 allow-set 前证明 approval 结构 + stage encoder bytes。
- **最小复现：** default-empty 拒绝；合法 zero no-intent 通过；多余/wrong allow 拒绝。
- **新增测试：** `test_risk_wire` zero allow-set 套件；`test_approval_zero_command_closure_and_exact_replay`（改为 zero-intent）；reconcile 结构闭包测试。
- **通过条件：** zero 首次+replay 通过；无主/非法 zero 拒绝；nonzero/CANCEL 不回归。

#### F9：pretrade source fixture

- **现象：** 直测被 A1 `canonical_source_identities_digest` 拒绝。
- **根因：** 未排序/弱 key/`target_identity` 非 canonical。
- **规则：** stable-sorted keys + unique values 的合法 A1 map。
- **新增测试：** 修复 `test_verified_approval_unlocks_manual_gate_for_paper_only` fixture。
- **通过条件：** PAPER unlock / manual 无 receipt / SHADOW 零命令 / bool 拒绝均进入 risk body。

#### F10：资源 carrier

- **现象：** finally 猜全核 affinity bitmask 在当前拓扑参数错误。
- **规则：** carrier 只精确清理临时目录；短命 shell 退出即释放 affinity。
- **本包：** 实现侧无 carrier 代码变更；交付仅记录经理规则，供后续授权验证遵循。
- **通过条件：** 验证终态无 0xF00 Python、无本包 basetemp（待授权运行核验）。

### 8.4 §14 中央合同实现要点

- `risk_wire.encode_execution_stage`：唯一 public canonical stage encoder；接受 `RiskDecision`/`DurableOrderRiskDecision`；`service._encode_stage` 委托之。
- `verify_risk_receipt_semantic_closure(..., allowed_zero_order_subject_ids=frozenset())`。
- service：PAPER-only 写前拒绝（`APPROVAL_PAPER_ONLY`）；`_prove_zero_order_allow_set` 证明 approval decode/index + stage bytes；live replay 仍逐字段比对 `VerifiedApprovalReceipt`。
- reconcile：同结构 allow-set；**不** HMAC reverify；`RecoveryResult.allowed_zero_order_subject_ids` 不进入 `recovery_id`。
- reporting/soak 默认空 allow-set 行为不变。

### 8.5 Reviewer P2/P3 残留边界（明确保留）

独立初验既有 P2/P3 **未在本包关闭**，仍为进程内 authority 已知面：

- **P2：** 对已由 factory 签发的真实 capability，字段级 `object.__new__`+`setattr` 克隆仍可通过 unpack；copy/deepcopy/pickle/`replace` 硬失败面保留。持有引用即持有 authority。
- **P3：** capability `__eq__` 忽略 `_secret`/`_proof`；鉴权路径走 unpack/HMAC 而非 `==`。

### 8.6 REWORK2 未运行项 / 阻塞

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite / 网络 / PAPER | 未运行（STATIC_ONLY） |
| Git commit | 未执行 |
| 独立复验报告 | 未修改（只读） |
| Gate / UA-M4-006/007 | 不声称 |
| STOP | 无 |

DELIVERY_READY docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md

## 9. REWORK3 问题闭环（追加；不改写首轮/REWORK1/REWORK2 历史）

状态：`DELIVERY_READY`（REWORK3 STATIC_ONLY 完成；仍不等于独立复验/主验/Gate）<br>
约束：未运行 Python/pytest/Ruff/mypy/cold/SQLite/网络/PAPER；未 commit；未修改独立初验报告。<br>
身份：exact base/HEAD=`7fe836dcfbd841c5473057d3f6e222a6081ae3fa`；branch=`codex/m4-a2-formal-approval-flow`。<br>
范围：exact17 未扩围；未改 store/schema/migration/config/`__init__`/roadmap。

### 9.1 F11–F13 六段证据

#### F11：service 中央反例矩阵隔离覆盖

- **现象：** `test_approval_zero_replay_rejects_stage_or_approval_index_drift` 先改 stage payload，再手工恢复后改 approval identity；未独立覆盖 stage identity-only、approval raw payload，也未覆盖其他 canonical index；测试名把不完整矩阵表述成已覆盖。
- **根因：** 把一次 payload 改动自然导致的 digest 不一致，当成 bytes/identity 两类独立反例；并遗漏 stored approval raw decode/canonical index 负向路径。
- **规则：** 互相隔离的新 fixture/参数化 case 分别篡改 stage payload、stage identity、approval raw payload、approval canonical index（identity + session）；每项先证明 logical snapshot 已变，再 live replay fail closed，失败后 snapshot exact 不变。
- **最小复现：** 各 case 独立 `UPDATE` 后 `plan_and_stage` 必 `ExecutionServiceError`，前后 `_logical_execution_snapshot` exact。
- **新增测试：** `test_approval_zero_replay_rejects_stage_and_approval_structure_drift`（参数：`stage_payload` / `stage_identity` / `approval_raw_payload` / `approval_index_identity` / `approval_index_session`）；删除旧合并测试名。
- **通过条件：** 四族（含 index 的 identity 与 session）均可归因、无共享污染现场。

#### F12：reconcile approval/stage drift 反例

- **现象：** `test_recover_zero_approval_structural_closure_without_hmac_claim` 只证明合法 zero 可恢复；未证明 approval raw/index 或 stage bytes/identity 漂移时拒绝。
- **根因：** 把 service live replay 负向测试误当成 reconcile structural ownership 的替代证据。
- **规则：** `recover_local_state` / `recover_repository_state` 窄参数化反例覆盖 approval raw、approval index、stage payload、stage identity；稳定 `RECOVERY_RISK_CLOSURE_INVALID`；不得改持久化现场；正向继续明确只结构、不 HMAC。
- **最小复现：** 合法 zero 先恢复；再分别 `UPDATE` 四类漂移 → 两次 recover API 均 fail closed，snapshot 不变。
- **新增/强化测试：** `test_recover_zero_approval_rejects_approval_or_stage_structure_drift`；正向测试改为 exact allow-set equality，并交叉 `recover_repository_state`。
- **通过条件：** 正向结构闭包 + 四类 drift fail closed + 调用前后 logical snapshot exact。

#### F13：RecoveryResult allow-set 身份边界诚实复核

- **现象：** REWORK2 给 `RecoveryResult` 增加 `allowed_zero_order_subject_ids` 且不进入 `recovery_id`；若 caller 可自由改该集合而保持同 identity，则形成第二状态维度。
- **根因：** 公共字段若不经 `__post_init__`/`_valid_recovery_receipts`→semantic verifier 的 exact-consume 约束，会与“approval 不进 identity”叠加成可伪造旁路。
- **规则：** 保持 approval rows 不进 recovery identity、也不改 recovery digest。若保留该字段，必须证明：与观察到的合法 zero receipt subject 集合 exact equality；extra/missing/wrong 不能构造合法 `RecoveryResult`；同 `recovery_id` 不可能对应两个不同合法 allow-set。
- **最小复现：** 合法 zero 恢复后 allow-set == `{plan_id}` == 观察 zero subjects；legal rebuild 同 `recovery_id`；forged set 虽 `_recovery_identity` 仍等于原 id，但 `RecoveryResult(...)` 稳定 `RECOVERY_RESULT_INVALID`。
- **新增测试：** `test_recovery_result_allow_set_exact_with_observed_zero_subjects`（`extra`/`missing`/`wrong`）。
- **通过条件 / 选择理由：** 已证明 allow-set 由已进入 identity 的 risk receipts 经 semantic verifier exact 消费唯一确定，故**保留公共字段**作导出 witness，**不**收回为 reconcile 内部局部变量，**不**改 `_recovery_identity` / recovery digest。无法用不同 allow-set 构造两个合法同 id 结果。

### 9.2 REWORK3 未运行项 / 阻塞

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite / 网络 / PAPER | 未运行（STATIC_ONLY） |
| Git commit | 未执行 |
| 独立复验报告 | 未修改（只读） |
| Gate / UA-M4-006/007 | 不声称 |
| STOP | 无 |

DELIVERY_READY docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md

---

## 13. REWORK4 问题闭环（追加；不改写首轮/REWORK1–3 / VALIDATION4 历史）

状态：`DELIVERY_READY`（REWORK4 STATIC_ONLY 完成；仍不等于独立复验/主验/Gate）<br>
约束：未运行 Python/pytest/Ruff/mypy/cold/SQLite/网络/PAPER；未 commit；未修改独立初验报告。<br>
身份：exact base/HEAD=`7fe836dcfbd841c5473057d3f6e222a6081ae3fa`；branch=`codex/m4-a2-formal-approval-flow`。<br>
范围：exact17 未扩围；仅改 `reconcile.py` + 三测试文件 + 任务书/本交付报告；未改 store/schema/migration/config/`__init__`/roadmap。

### 13.1 F14–F17 六段证据

#### F14：approval raw 篡改保持 BLOB

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
