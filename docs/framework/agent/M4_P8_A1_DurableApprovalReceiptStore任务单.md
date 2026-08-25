# M4 P8 A1：Durable Approval Receipt Codec / Store Substrate 任务单

日期：2026-08-23
状态：任务合同已冻结；等待 Luna Worker 实现通道
exact base：`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`
branch：`codex/m4-a1-durable-approval-store`
worktree：`artifacts/dev_worktrees/m4-a1-durable-approval-store`

## 1. 目标

实现 `HMAC_SHA256_CREDENTIAL_V1` durable approval receipt 的最小领域 codec、验签能力与 OMS store migration/persistence substrate，为后续 A2 formal operator `manual=true` 和 approved no-op E2E 提供唯一持久化基础。

本包不接 CLI，不启动 PAPER，不修改 formal daily、soak 或 runtime，不声称关闭 UA-M4-005。

## 2. 唯一写白名单

1. `src/quant/execution/approval.py`（新）
2. `src/quant/execution/migrations.py`
3. `src/quant/execution/store.py`
4. `tests/unit/test_approval.py`（新）
5. `tests/unit/test_store.py`
6. `docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore任务单.md`（本文件）
7. `docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore交付报告.md`（新）

禁止修改 CLI、`paper_formal_daily.py`、service、soak/runtime、`__init__.py`、配置、roadmap 或共享 SSOT。若正确事务边界必须修改 service/CLI，留给 A2，不在 A1 扩围。

## 3. 领域与密码合同

- credential kind 精确为 `HMAC_SHA256_CREDENTIAL_V1`；只接受 bytes-like exact secret，最小长度由模块常量冻结并测试。
- secret 由受控 caller 临时提供；不得持久化、序列化、repr、日志、异常或 recovery 返回。
- canonical receipt 至少绑定：schema/classification、credential kind、opaque `credential_id`、opaque `operator_id`、session date、action、plan identity、challenge identity、store recovery identity、canonical source-identities digest、UTC issued-at、唯一 nonce、HMAC tag 与 receipt identity。
- action 本包只允许 formal approval；字段必须 exact type、非空、稳定格式。所有 datetime 统一 UTC canonical text。
- HMAC 覆盖除 tag/receipt identity 外的完整 canonical body；receipt identity 覆盖已签名 canonical envelope。验签使用 constant-time compare。
- build、encode、decode、verify 均 fail closed；future schema、未知 credential kind、非 canonical JSON、重复键、额外字段、错误 key、tag/identity tamper 必须稳定拒绝。
- 同一 plan 的零订单/no-op approval 是合法业务主题，但本包只证明 receipt 可表达与持久化；是否允许命令发送由 A2/既有风控决定。

## 4. Store / migration 合同

- 只追加一个 schema migration 和 approval receipt 表/必要索引，不重写既有表与历史 migration。
- store 持久化的是经过 caller 显式验签后的 canonical raw bytes及最小索引；repository 不持有 key，也不得把“能 decode”当成“已受信”。
- exact receipt identity + exact bytes 重放幂等；同 identity 不同 bytes、同业务唯一键冲突、索引与 payload 不一致均事务回滚并 fail closed。
- recovery/query 返回原始 canonical bytes与索引值，调用方必须重新验签；不得返回隐式 trusted approval 对象。
- migration 中断、unknown future version、tampered payload、顺序或唯一约束异常沿用现有稳定 store failure 边界。
- 旧数据库升级与新数据库创建均必须保持既有 OMS、risk receipt、outbox、reconciliation 行为不变。

## 5. 必须覆盖的反例

1. 正确 key 签发/encode/decode/verify 往返；错误 key、单字节 body/tag/identity 改动拒绝。
2. secret 不出现在 repr、encoded bytes、SQLite bytes、异常文本或 recovery DTO 中。
3. exact replay 幂等；identity collision、plan/session/operator/credential 索引漂移拒绝且无部分写入。
4. future schema、未知 credential、非 UTC、空 operator、重复/乱序 source identities、非 canonical JSON 拒绝。
5. 新库 migration 到新版本；旧 v7 库升级保留既有数据；模拟 migration 失败维持 fail-closed/可诊断状态。
6. 零订单/no-op receipt 可持久化和重验，但不能凭其直接 dispatch，也不产生 PAPER/soak artifact。

## 6. 实现与验证方式

- 实现由本地 Luna Worker 的另一独立 subagent 完成；不得与 M3 任务共享 subagent。
- 当前先允许静态实现；CPU 检查排在 GUI D2、M3-G8F-R1 之后，由根 Agent明确放槽。
- 获得 CPU 槽后的顺序：focused approval/store pytest → Ruff（白名单 Python）→ mypy（3 production modules）→ cold import → scoped diff/SQLite 临时项/进程残留检查。
- Windows：BelowNormal、affinity `0xF00`、threads ≤ 2、唯一实例。禁止真实 PAPER、broker dispatch、soak、外部凭据或 Linux Gate。

## 7. 通过与停止条件

通过：exact 七路径、migration/codec/store 反例全部通过、无凭据泄露、无真实运行产物、worktree clean 安全提交、交付报告明确 A2 未完成。

立即停止：需要修改 CLI/service/formal daily/soak；需要把 secret 写入配置或数据库；需要扩大白名单；migration 无法保持旧数据；base/HEAD 漂移；资源槽未授权。

## 8. R2 历史证据与重新冻结（追加，不删除上文）

以下记录保留原任务书与前轮派发证据；本节只为 R2 纠正路径、角色和当前执行边界，不覆盖或删除上文历史。

- **既有 M4-A1 STOP：** 原任务书指定的 `src/quant/execution/migrations.py` 与
  `tests/unit/test_store.py` 不是当前树中的实际生产/测试路径；实现 Agent 按 no-clobber 规则停止，未形成可接受的
  M4-A1 业务实现。R2 改用现存的 migrations package、`v001`–`v007`、`store.py` 和
  `tests/unit/test_execution_store.py`，并新增本任务书列明的 v008、approval codec 与测试。
- **R1 unauthorized-worker STOP / reassignment：** R1 派发的 worker/身份不在本 R2 实现授权闭包内；中央记录其
  unauthorized-worker STOP，未接受其业务文件或把其自报结果作为证据，随后撤销该执行分配并重新指派给本 R2
  `IMPLEMENTATION_AGENT`（runtime reference `01a031fe-025e-7ec0-a933-ca0dac31d0f6`）。本记录不读取、恢复或使用
  R1 retained history；只保留该 STOP/reassignment 结论。
- **R2 re-freeze：** exact base 为 `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`，branch 为
  `codex/m4-a1-durable-approval-store`，worktree 为
  `artifacts/dev_worktrees/m4-a1-durable-approval-store`；当前模式为 `STATIC_ONLY`，仅在中央发送
  `STATIC_RESUME` 后继续。R2 唯一写白名单（取代上文原始路径清单）为：
  1. `src/quant/execution/approval.py`
  2. `src/quant/execution/migrations/__init__.py`
  3. `src/quant/execution/migrations/v008_approval_receipts.py`
  4. `src/quant/execution/store.py`
  5. `tests/unit/test_approval.py`
  6. `tests/unit/test_execution_store.py`
  7. `docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore任务单.md`
  8. `docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore交付报告.md`
- **R2 资源与状态边界：** 不运行 Python、pytest、Ruff、mypy、cold import、SQLite probe、网络、浏览器、实际
  worker、CLI/PAPER/formal daily/service/soak/runtime，不提交或暂存，不修改配置、roadmap、其他 `__init__.py` 或共享
  SSOT；不声称关闭 UA-M4-005。A2 的 `manual=true` 与 no-op E2E 仍是独立任务。secret 只由 caller 提供，永不进入
  持久化、序列化、日志、异常、repr 或 recovery；in-process hand-off proof 也不进入这些边界，store 仅保存 caller
  显式验签后的 canonical raw bytes 与最小索引。

## 9. R2 实现交接状态

- REWORK1 F1 静态改动已完成，但最终 guard 检出禁止进程，当前交接状态为 `STOPPED_PENDING_ROOT_RESUME`；这是
  exact8 continuation 的停止状态，不是 focused pytest、独立初验、主验或任何 Gate 通过声明。前一轮历史与独立
  审查结论保留在下节。
- 交付报告：[`M4_P8_A1_DurableApprovalReceiptStore交付报告.md`](M4_P8_A1_DurableApprovalReceiptStore交付报告.md)。
- Python、pytest、Ruff、mypy、cold import、SQLite/真实 migration、网络、浏览器、worker、PAPER、formal daily、soak/runtime 均按 `STATIC_ONLY` 明确未运行；剩余风险和下一步验证保留在交付报告中。

## 10. R2 proof-forgery 合同返工记录（前一轮；F1 见 §11）

- **现象：** `VerifiedApprovalReceipt` 原为 caller 可直接构造的 public dataclass；`ExecutionRepository.put_approval_receipt(..., verified=True)` 也把 caller 的布尔值当作验签证明，因此自造 body/tag、重算自洽 `receipt_id` 的 HMAC-invalid payload 可绕过验签并落库。
- **根因：** store 的 public boundary 同时接受 raw bytes、caller indexes 和可信布尔标志；credential-free hand-off 没有 construction gate，且仅靠 private-field 约定无法阻止 `object.__new__`/`object.__setattr__` 伪造 exact class。
- **应遵循规则：** store 只接受 `verify_approval_receipt_for_store` 产生的 credential-free hand-off；禁止 raw+bool/index 写入；hand-off 携带 module-start random-key HMAC proof，proof 绑定 exact payload bytes 与 receipt identity，且由 approval-module unpack 函数在 store 获得 receipt/payload 前验证；proof 不进入 repr、wire、store、recovery 或错误，store 不持有 proof key。
- **最小复现：** caller 先 decode 自洽但 HMAC-invalid payload，再用 `object.__new__(VerifiedApprovalReceipt)`/`object.__setattr__` 填入 decoded receipt 与 payload；旧 exact-type/parsed-equality boundary 会错误落库；复用一个合法 proof 到另一 payload/receipt 也必须拒绝。
- **新增测试：** direct hand-off construction fail-closed；HMAC-invalid/self-consistent `receipt_id` 的 verify-for-store 拒绝；decoded forged receipt + `object.__new__` exact class 无法落库；raw bytes 传入唯一 public hand-off entry 被拒绝；合法 proof replay、missing/wrong proof、canonical/index drift 被拒绝；原有 verify→store、exact replay、business/identity conflict、recovery drift 与 migration coverage 保留。
- **返工结果：** `CONTRACT_REWORK_IN_PROGRESS` 已通过本轮 exact8 静态修复关闭；runtime proof、approval-module unpack、direct/object-new/replay 对抗性测试与文档记录已补齐。
- **前一轮结果：** direct/object-new proof forgery 与 raw+bool bypass 已封闭；独立审查随后发现 raw/index candidate helper F1，当前由 §11 REWORK1 继续修复，不能把前一轮 `STATIC_DONE` 当作当前最终结论。

## 11. REWORK1 F1 独立审查返工记录

- **审查链接与边界：** [`M4_P8_A1_DurableApprovalReceiptStore独立初验报告.md`](M4_P8_A1_DurableApprovalReceiptStore独立初验报告.md) 为只读输入，本轮不修改；其结论为 `REVIEW_FAIL`，仅修复 F1，不扩大范围。
- **现象：** `ExecutionRepository._put_approval_receipt_candidate(StoredApprovalReceipt)` 可由普通 caller 直接调用；该入口没有 `unpack_verified_approval_receipt`、HMAC/proof 或 canonical/index 对账，能直接 INSERT 自洽但 HMAC-invalid 的 raw/index candidate。
- **根因：** proof 只位于 `put_verified_approval_receipt` 前置边界，repository 仍暴露一个可手工构造 `StoredApprovalReceipt` 的下划线写 helper；下划线命名不构成访问控制。
- **应遵循规则：** `put_verified_approval_receipt(VerifiedApprovalReceipt)` 是唯一 repository persistence boundary；candidate 校验、唯一键检查和 INSERT 只能 inline/nest 在该方法内；不得存在任何 repository/module-addressable raw/index persistence helper。既有 module-private proof 仍必须在 approval-module unpack 中校验。
- **最小复现：** 构造 self-consistent HMAC-invalid raw，再用其 decoded 字段建立 `StoredApprovalReceipt` 并调用旧 `_put_approval_receipt_candidate(candidate)`；修复后 repository/class 不再有该 callable，唯一 public hand-off method 对 candidate 返回 `APPROVAL_RECEIPT_NOT_VERIFIED` 且不写入。
- **新增测试：** exact candidate dataclass adversary 检查无 callable helper/bypass；保留 direct construction、object-new forged receipt、HMAC-invalid、missing/wrong/replayed proof 和 index drift；新增非空 approval close/reopen，recovery 仅 canonical raw/index，recovered row 不能直接 trusted persist/use，caller 必须重新 credential verify。测试源码已补充但按 STATIC_ONLY 未运行。
- **返工结果：** F1 helper 已删除，唯一 hand-off boundary 保持，业务幂等/冲突/rollback 语义不变；close/reopen reverify 已作为静态测试源码覆盖，但没有运行证据。
- **通过条件：** production 无 repository/module raw/index persistence bypass，candidate 只能在 hand-off method 内产生并插入；REWORK1 只有在 root 清除禁止进程并重新确认后才可恢复 `STATIC_DONE`，仍待独立初验与主验。

## 12. REWORK1 STOP 记录

- 最终静态 guard 发现外部活动 `python` 进程：PID `7692`，路径 `D:\Miniforge3\python.exe`；本 Agent 未启动、未检查、未终止该进程，也未与其并行执行。
- 按 STATIC_ONLY fail-closed 规则，本轮不运行 Python、pytest、Ruff、mypy、cold import、SQLite、网络、浏览器或 worker；不把源码静态覆盖写成运行证据。
- exact8 F1 改动、对抗性 candidate 测试、非空 close/reopen reverify 测试和文档记录保留；REWORK1 durable status 为 `STOPPED_PENDING_ROOT_RESUME`，M4-A1/R1/R2 identity histories 与独立 review report 均未改写。

## 13. REWORK2 codec validation STOP 与 issue closure

- **验证 STOP 证据：** 中央提供的身份验证为 PASS；focused `test_approval` 证据为 `10 passed / 2 failed`。失败集中在 canonical receipt round-trip 与 no-op 可表达性，均在 `decode_approval_receipt` 返回 `APPROVAL_RECEIPT_INVALID`。本轮受 `STATIC_ONLY` 边界约束，没有重新运行 Python、pytest、Ruff、mypy、cold import、SQLite 或其他检查，因此不把该证据写成当前 Agent 的运行通过。
- **现象：** 合法 canonical wire 已包含必需的 `receipt_id`，但 decode 在进入 HMAC/identity 后的结构入口即拒绝；因此合法 receipt 和可表示的 no-op receipt 不能完成 decode。
- **根因：** `require_wire_root` 的 `keys` 参数错误地传入了 `_WIRE_KEYS - {"receipt_id", "schema_version"}`。`_WIRE_KEYS` 本来就不含 `schema_version`，该表达式实际遗漏了合法且必需的 `receipt_id`。
- **应遵循规则：** wire root 的 required-key 集必须使用完整 `_WIRE_KEYS`；随后仍须执行包含 `schema_version` 的 exact-object 检查、canonical re-encode、future-version distinction，以及既有 HMAC/tag/receipt-identity 验证。缺失、重复或额外键必须 fail closed。
- **最小复现：** `raw = encode_approval_receipt(_receipt())` 后调用 `decode_approval_receipt(raw)`；修复前即使 `raw` canonical 且 `receipt_id` 自洽也返回 `APPROVAL_RECEIPT_INVALID`。移除 `receipt_id` 或在原始 wire 中追加第二个 `receipt_id` 仍必须拒绝。
- **窄修复与回归：** `approval.py` 仅将 `require_wire_root(..., keys=...)` 改为完整 `set(_WIRE_KEYS)`，没有改动 store、migration、schema、HMAC 或 identity 算法；`test_approval.py` 新增 `test_receipt_id_is_required_and_duplicate_receipt_id_fails_closed`，覆盖 canonical 合法 receipt_id、缺失 receipt_id 和 duplicate/extra receipt_id，既有 future-version/extra-key 回归保留。
- **issue closure / 通过条件：** 本次 codec root-cause 已在 exact8 源码与文档中闭环；静态通过条件是合法 receipt_id 可进入 canonical decode，而缺失、重复/额外 receipt_id 继续 fail closed，future-version distinction 与后续密码学检查不回退。验证状态仍为 STOP/未运行，不能声称 focused pytest、独立初验、主验或任何 Gate 通过；A2/PAPER/no-op E2E 仍是独立范围。

## 14. REWORK3 Ruff import cleanup

- **现象：** §11 的 VALIDATION2 证据显示 focused approval `13 passed`、focused store/v008 `8 passed`，但 Ruff exact6 在 `src/quant/execution/store.py` 首个静态失败处 STOP，报告四个 `F401`：`APPROVAL_RECEIPT_CLASSIFICATION`、`APPROVAL_RECEIPT_SCHEMA_VERSION`、`FORMAL_APPROVAL_ACTION`、`HMAC_SHA256_CREDENTIAL_V1`。
- **根因：** approval persistence boundary 已使用 `ApprovalReceiptError`、`VerifiedApprovalReceipt`、decode/unpack API；上述四个旧的契约常量仍留在 import block，但当前 store 逻辑没有引用它们，形成 stale unused imports。该问题不涉及 receipt 行为、proof、数据库 schema 或测试语义。
- **应遵循规则：** import 集合必须与实际引用一致；返工只删除被 Ruff 明确确认未使用的四个名称，不重排或替换 API，不改变 store 行为、测试、migration 或 schema。
- **最小复现：** 对 §11 同一 exact6 Ruff 范围检查当前 `store.py`，其 import block 的四个名称各自产生 `F401`；删除四行后，预期不再出现这四个 `F401`。本轮未运行 Ruff，保留既有证据边界。
- **窄修复：** `store.py` 仅移除上述四个 import；`ApprovalReceiptError`、`VerifiedApprovalReceipt`、`decode_approval_receipt` 和 `unpack_verified_approval_receipt` 保留，未修改任何生产逻辑、测试、schema 或 migration。
- **通过条件：** 四个 F401 名称不再出现在 store import block；existing focused-test evidence（approval 13 passed、store/v008 8 passed）对应行为保持不变；允许的 post-fix Ruff exact6 与独立复验应确认无该 import failure。未运行的新验证不得被写成通过或 A1 Gate 关闭。
