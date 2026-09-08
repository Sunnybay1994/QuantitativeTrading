# M4 P8 A1-R2：Durable Approval Receipt Codec / Store Substrate 交付报告

日期：2026-08-24
状态：`DELIVERY_READY`（REWORK3 仅清理四个 Ruff-confirmed unused imports；post-fix validation 未运行，仍不等于独立初验、主验或 Gate 通过）
exact base：`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`
branch：`codex/m4-a1-durable-approval-store`
worktree：`artifacts/dev_worktrees/m4-a1-durable-approval-store`

## 1. 结果与范围

本轮仅实现冻结的 A1 codec、v008 migration、ExecutionStore 持久化/恢复 substrate 和聚焦测试。没有接入 CLI、PAPER、formal daily、service、soak/runtime、dispatch 或任何真实 worker；不声称关闭 UA-M4-005，A2 `manual=true` 与 approved no-op E2E 仍未完成。

唯一业务写白名单为 exact8；原任务书中的旧路径和历史 STOP 证据保留在任务书中，并由其 R2 追加节明确 supersede。

## 2. 修改文件及目的

- `src/quant/execution/approval.py`：新增 `HMAC_SHA256_CREDENTIAL_V1` canonical approval receipt 数据类、严格 JSON codec、HMAC-SHA256 签发/constant-time 验签、source-identities digest、credential-free verified hand-off 和 module-private runtime proof。
- `src/quant/execution/migrations/__init__.py`：注册有序 v8 migration。
- `src/quant/execution/migrations/v008_approval_receipts.py`：只新增 `approval_receipts` 表及 plan/session、recovery、operator/session 查询索引；新增业务唯一键、nonce 唯一约束和 SQLite 类型/固定值约束。
- `src/quant/execution/store.py`：schema version 7→8；新增 proof-validated hand-off 写入、仅在唯一 public boundary 内完成 raw/index candidate validation+insert、exact replay 幂等、receipt identity/business-key/nonce 冲突、索引与 canonical payload 对账、raw recovery/query；不持有 credential/proof key，不返回 trusted approval object。
- `tests/unit/test_approval.py`：覆盖 canonical 往返、正确/错误 key、body/tag/identity tamper、非 canonical/重复/额外/future/unknown credential/非 UTC、source identities 顺序/重复、secret 边界和 no-op 可表达性。
- `tests/unit/test_execution_store.py`：覆盖 v8 round-trip/raw recovery/exact replay、raw/bool/index candidate bypass、direct/object-new forged hand-off、missing/wrong/replayed proof、index drift、business-key 冲突无部分写入、非空 close/reopen 后 caller reverify 和 v7→v8 保留旧行。
- `docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore任务单.md`：追加既有 M4-A1 STOP、R1 unauthorized-worker STOP/reassignment 结论与 R2 exact8 re-freeze；没有删除上文历史。
- 本报告：记录实现、静态检查边界和未运行验证。

## 3. 合同证据

- canonical receipt 固定 schema/classification/action/credential kind，并绑定 credential/operator/session/plan/challenge/store-recovery/source digest/UTC issued-at/nonce/tag/receipt identity。
- HMAC 覆盖不含 tag/receipt identity 的 canonical body；receipt identity 覆盖含 tag 的 canonical envelope；验签使用 `hmac.compare_digest`。
- decode 使用 canonical JSON、duplicate-key 拒绝、exact-key 拒绝和 future-version fail-closed；错误 key、tag、identity、未知 credential、非 UTC 和字段/顺序漂移均返回脱敏稳定错误。
- secret 只在 build/verify caller 边界作为 bytes-like 输入，最小长度为模块常量 `MIN_SECRET_BYTES=32`；不在 dataclass、encoded bytes、store indexes/payload、异常或 recovery value 中保存。
- store 只接受 `verify_approval_receipt_for_store` 返回的无 credential hand-off；不存在 raw bytes、caller indexes 或 `verified=True` bypass；recovery/query 返回 `StoredApprovalReceipt` 的 raw payload 和索引字段，不返回 `ApprovalReceipt` trusted object。
- zero-order/no-op 主题没有 command/dispatch 字段，因此可签发、验签和持久化；A1 没有任何 dispatch 路径。

## 4. Proof-forgery 合同返工（前一轮已完成；F1 见 §5）

- **现象：** public `VerifiedApprovalReceipt` dataclass 可由 caller 直接构造，且旧 public `put_approval_receipt(..., verified=True)` 信任 caller 布尔值；body/tag 自造并重算自洽 `receipt_id` 的 HMAC-invalid payload 可在旧路径落库。
- **根因：** persistence boundary 接受 raw bytes、索引和非密码学布尔标志，缺少 credential-free hand-off 的 construction gate；结构 decode 通过不等于 HMAC 已验证，且 Python private-field convention 单独不足以抵御 `object.__new__`。
- **规则：** `verify_approval_receipt_for_store` 是唯一 production hand-off factory；`VerifiedApprovalReceipt` 使用 `init=False`，并携带不进 repr/wire/store/recovery 的 module-start random-key HMAC proof，proof 绑定 exact payload bytes+receipt identity；approval-module unpack 函数先验证 exact type、canonical pair 和 proof，store 不持有 proof key/credential。
- **最小复现：** 直接 `VerifiedApprovalReceipt(receipt, payload)`，或 decode self-consistent/HMAC-invalid raw payload 后用 `object.__new__`/`object.__setattr__` 填入 exact class；复用合法 proof 到另一 payload/receipt 也必须失败；旧 raw+`verified=True` entry 已删除。
- **新增测试：** direct hand-off construction rejection；decoded forged receipt + object-new exact class rejection；HMAC-invalid/self-consistent `receipt_id` 的 verify-for-store 与 public store-entry rejection；missing/wrong/replayed proof、canonical/index drift rejection；合法 verify→store、exact replay、business/identity collision、recovery drift 与 migration tests 保留。
- **前一轮结果：** direct/object-new proof forgery 与 raw+bool bypass 已封闭；独立审查随后发现 raw/index candidate helper F1，当前由 REWORK1 §5 继续修复，不能把前一轮 `STATIC_DONE` 作为当前最终结论。

## 5. REWORK1 F1 合同返工（已完成）

- **审查链接：** [`M4_P8_A1_DurableApprovalReceiptStore独立初验报告.md`](M4_P8_A1_DurableApprovalReceiptStore独立初验报告.md)；该报告只读，本轮不修改。
- **现象：** 独立审查发现 `ExecutionRepository._put_approval_receipt_candidate(StoredApprovalReceipt)` 可被普通 caller 直接调用；它绕过 `unpack_verified_approval_receipt`、HMAC/proof 和 canonical/index 对账，直接 INSERT HMAC-invalid raw/index candidate。
- **根因：** proof 只保护了一个 public method，repository 仍暴露可手工构造 `StoredApprovalReceipt` 的下划线写入口；Python 下划线不是访问控制。
- **规则：** `put_verified_approval_receipt(VerifiedApprovalReceipt)` 是唯一 repository persistence boundary；candidate validation、唯一键检查和 INSERT 必须 inline/nest 于该方法，不能再由 repository/module-addressable raw/index helper 接收 `StoredApprovalReceipt`。
- **最小复现：** 用 self-consistent HMAC-invalid raw 构造 `StoredApprovalReceipt`，直接调用旧 `_put_approval_receipt_candidate(candidate)` 即可绕过 proof；修复后该属性不可调用，唯一 public method 接收 candidate 也稳定返回 `APPROVAL_RECEIPT_NOT_VERIFIED`。
- **新增测试：** adversarial raw/index candidate 检查 repository 无 candidate helper 且 public boundary 拒绝 candidate；保留 direct/object-new/HMAC-invalid/replayed-proof 测试；新增非空 approval close/reopen，recovery 只返回 canonical raw/index，recovered row 不能直接持久化，caller 必须重新 credential-verify 后再作 trusted persistence/use。测试按 STATIC_ONLY 未执行。
- **通过条件：** F1 helper 已删除、无 repository/module raw/index write bypass，唯一 hand-off boundary 与既有 proof/幂等/回滚语义保持；close/reopen 测试源码覆盖 reverify，但未形成运行证据。

## 6. 验证记录

| 命令/检查 | 结果 | 证据或边界 |
| --- | --- | --- |
| applicable `AGENTS.md` 与 `.ai` 规则阅读 | 完成 | 修改前已完整阅读项目规则、coding/high-risk/multi-agent/review 规则和任务书 |
| HEAD/branch/dirty guard | 通过 | `HEAD=ac57ce9e40dc6731e1106b2fa2398f4013fa19da`；branch 正确；实现前唯一既有 worktree dirty item 为原始任务书 untracked |
| prohibited process check | 通过 | 单次只读检查未发现 python/pytest/ruff/mypy/cursor-agent 进程 |
| proof-forgery/F1 static contract review | 完成 | runtime proof 保留；raw/index candidate repository boundary 已移除；close/reopen source coverage 已补充 |
| `git diff --check` | 通过 | 静态 whitespace 检查无输出；不代表 Python 可导入 |
| focused approval/store pytest | 未运行（强制） | `STATIC_ONLY` 资源/授权边界；不能声称测试通过 |
| Ruff / mypy / cold import / Python | 未运行（强制） | 用户明确禁止 |
| SQLite probe、真实迁移、真实数据/网络/浏览器/worker | 未运行（强制） | 用户明确禁止；migration/runtime 行为待独立初验和主验 |
| Linux Gate、Windows 运行验证、PAPER/soak/formal daily | 未运行（范围外） | A1 不接入这些路径 |

## 7. 风险与交接

- 本报告是实现者静态交付，不是独立初验或主 Agent 最终验收；需要未参与实现的独立审查补充对抗性反例，并由主 Agent 在允许资源槽后运行 focused pytest、Ruff、mypy、cold import 和 SQLite/迁移验证。
- 由于未执行 Python/SQLite，当前不能证明语法、类型、migration rollback、旧 v7 数据升级和平台行为；这些保持待验收。
- REWORK1 新 dispatcher status 已改为 `STOPPED_PENDING_ROOT_RESUME`，保留该轮 mapping/status 与既有 M4-A1/R1/R2 identity histories。
- 范围外改动：无。未修改 CLI、PAPER/formal daily、service、soak/runtime、其他 `__init__.py`、配置、roadmap、共享 SSOT、R1 retained worktree 或 R1 retained history。

## 8. REWORK1 STOP 证据

- 最终静态 guard 发现外部活动进程 `python`，PID `7692`，解释器路径 `D:\Miniforge3\python.exe`；本 Agent 未启动该进程，不检查、不终止、不与其并行运行。
- 按 STATIC_ONLY fail-closed 边界，本轮不再执行任何 Python、pytest、Ruff、mypy、cold import、SQLite、网络、浏览器或 worker；因此不能提交 `STATIC_DONE`。
- exact8 业务改动与 F1 测试/文档源码已保留；REWORK1 durable status 已改为 `STOPPED_PENDING_ROOT_RESUME`。待 root 清除并重新确认禁止进程后再决定是否恢复，不覆盖 M4-A1/R1/R2 历史。

## 9. REWORK2 codec validation STOP 与 issue closure

- **验证证据与边界：** 中央提供身份 PASS，以及 focused `test_approval` 的 `10 passed / 2 failed`；两项失败为 canonical round-trip 和 no-op 场景在 `decode_approval_receipt` 返回 `APPROVAL_RECEIPT_INVALID`。本轮没有运行 Python、pytest、Ruff、mypy、cold import、SQLite 或其他检查，故不声称任何运行通过。
- **现象与根因：** `decode_approval_receipt` 将 `_WIRE_KEYS - {"receipt_id", "schema_version"}` 传给 `require_wire_root`；而 `_WIRE_KEYS` 已经排除 `schema_version`，导致合法 wire 的必需 `receipt_id` 被错误遗漏，合法 receipt/no-op 因而在结构 decode 阶段被拒绝。
- **规则与窄修复：** `require_wire_root` 现在接收完整 `set(_WIRE_KEYS)`。`require_exact_object` 仍要求 `_WIRE_KEYS | {"schema_version"}`，canonical re-encode、future-version distinction、HMAC/tag/receipt-identity 检查均未改变；没有扩展 store、migration 或 schema。
- **最小复现与新增测试：** `encode_approval_receipt(_receipt())` 产生的合法 canonical raw 现在以完整 `receipt_id` 进入 decode；缺失 `receipt_id` 的 canonical object 和原始 wire 中追加的 duplicate/extra `receipt_id` 均由新增 `test_receipt_id_is_required_and_duplicate_receipt_id_fails_closed` 断言 `ApprovalReceiptError`。既有 generic extra、duplicate、future-version 回归保留。
- **issue closure / 交付条件：** 本轮 root cause 已在 exact8 的 `approval.py`、`test_approval.py`、任务书和本报告闭环，REWORK2 交付状态为 `DELIVERY_READY`。验证仍是 STOP/未运行；后续仍需允许的 focused pytest 与独立初验/主验，不能将本报告写成 `STATIC_DONE`、Gate 通过或 UA-M4-005/A2/PAPER 完成。

## 10. REWORK2 exact8 变更与未运行验证

- 本轮实际变更路径仅为：`src/quant/execution/approval.py`、`tests/unit/test_approval.py`、`docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore任务单.md`、`docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore交付报告.md`；独立审查报告及其余 exact8 文件未改动。
- 未运行：Python、pytest、Ruff、mypy、cold import、SQLite probe/真实 migration、网络、浏览器、worker、CLI/PAPER/formal daily/service/soak/runtime、commit/stage。没有运行证据可用于宣称语法、类型、数据库或平台行为已验证。

## 11. VALIDATION2 STOP 证据

- **身份预检：PASS。** `quant`、`quant.execution.approval`、`quant.execution.store` 均精确来自当前
  `m4-a1-durable-approval-store` worktree；承载为 Windows Miniforge、BelowNormal、affinity `0xF00`、
  数值线程不超过 2。
- **focused approval：PASS。** `tests/unit/test_approval.py` 为 `13 passed in 1.93s`。
- **focused store/migration：PASS。** 冻结的 8 个 `test_execution_store.py` approval/v008 节点为
  `8 passed in 3.00s`。
- **Ruff exact6：STOP。** `src/quant/execution/store.py` 导入但未使用
  `APPROVAL_RECEIPT_CLASSIFICATION`、`APPROVAL_RECEIPT_SCHEMA_VERSION`、`FORMAL_APPROVAL_ACTION`、
  `HMAC_SHA256_CREDENTIAL_V1`，产生 4 个 `F401`。这是静态源码问题，不是 carrier、pytest、SQLite
  或业务合同失败；按授权在首个失败处停止，未自动修复或扩大范围。
- **未运行：** mypy 四个 production 模块、cold import、最终 exact8/scope 检查；不得将 focused pytest
  通过表述为 A1 Gate 已通过。
- **资源终态：** 两个本轮 basetemp 已精确删除，未见 affinity `0xF00` 的 Python 残留；未启动
  PAPER、A2/manual E2E、网络、浏览器或真实 worker。
- **返工条件：** 同一实现者仅删除上述四个确认为未使用的 import，并补本节所要求的现象、根因、规则、
  最小复现、测试和通过条件；随后由同一独立 reviewer 复验，再申请新的 post-fix validation，不继承本租约。

## 12. REWORK3 Ruff import cleanup

- **现象：** VALIDATION2 已有证据为 `tests/unit/test_approval.py` `13 passed in 1.93s`，冻结的 approval/v008 store 节点 `8 passed in 3.00s`；随后 Ruff exact6 在首个失败处 STOP，并指出 `store.py` 中四个未使用 import 的 `F401`：`APPROVAL_RECEIPT_CLASSIFICATION`、`APPROVAL_RECEIPT_SCHEMA_VERSION`、`FORMAL_APPROVAL_ACTION`、`HMAC_SHA256_CREDENTIAL_V1`。
- **根因：** 当前 `store.py` 只实际使用 approval error、verified hand-off 类型及 decode/unpack API；四个常量是旧 import 残留，不参与控制流、canonical codec、proof、持久化或 migration。
- **规则：** 只清理工具明确确认的未使用 import；不改变公共 API、持久化行为、测试、数据库 schema、migration 或其他 import。
- **最小复现：** 在 §11 的同一 exact6 Ruff 范围中读取 `store.py` import block，即可得到四个 `F401`；移除这四行是该失败的最小修复。本轮遵守 `STATIC_ONLY/zero Python`，没有重跑 Ruff 或任何测试。
- **实现：** `src/quant/execution/store.py` 仅删除四个名称；`ApprovalReceiptError`、`VerifiedApprovalReceipt`、`decode_approval_receipt`、`unpack_verified_approval_receipt` 保持不变。没有修改测试、migration、schema 或业务逻辑。
- **现有 focused-test 证据：** approval `13 passed` 与 store/v008 `8 passed` 为 §11 提供的既有结果，本轮未重新执行，不能扩写为本轮验证结果。
- **通过条件：** store import block 不再包含四个 F401 名称；既有 focused 行为证据不因该纯 import cleanup 改变；同一独立 reviewer 后续复验 Ruff exact6 无该失败，再申请 post-fix validation。当前交付仅表示窄返工源码已就绪，不表示 Python、Ruff、Gate 或独立验收已通过。

DELIVERY_READY docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore交付报告.md

## 13. VALIDATION3 carrier STOP 证据

- **结果：STOP（不构成实现绿/红证据）。** 首个 identity preflight 尚未完成模块身份断言，PowerShell 将传给 `python -c` 的换行分隔参数展开为物理换行，Python 因此以 `SyntaxError: unterminated string literal`、exit `1` 退出。
- **边界：** 失败发生在承载命令解析阶段，不是 `quant.execution.approval`、migration、store 或测试代码的 import/行为失败；不得据此判断 A1 实现通过或失败。
- **停止语义：** 按授权的“首个 identity/focused 失败即 STOP”执行，未运行 Ruff exact6、mypy production4、cold imports 或最终 exact8/scope 检查，也未自动重试或扩大范围。
- **资源终态：** 本轮没有启动 PAPER、A2/manual E2E、网络、浏览器或真实 worker；承载进程已退出。后续若需验证，必须由中央重新冻结新的 carrier 合同与资源租约，不能继承 VALIDATION3。

## 14. VALIDATION4 post-fix 验证证据

- **identity preflight：PASS。** `quant`、`quant.execution.approval` 与 `quant.execution.store` 均精确从当前 `m4-a1-durable-approval-store` worktree 导入；carrier 为 direct-call Windows Miniforge、BelowNormal、affinity `0xF00`、数值线程不超过 2。单行 `python -c` payload 仅用分号并逐项 `print(path)`，未使用反引号或换行转义。
- **Ruff exact6：PASS。** `approval.py`、migration registry、v008、`store.py`、`test_approval.py` 与 `test_execution_store.py` 返回 `All checks passed!`；VALIDATION2 的四个 F401 已关闭。
- **mypy production4：PASS。** 上述四个 production Python 文件返回 `Success: no issues found in 4 source files`。
- **cold imports：PASS。** approval、migration registry、v008 与 store 四个模块均精确指向当前 worktree。
- **scope/diff：PASS。** Git dirty 集仍仅为批准的 exact8 加独立初验报告；`git diff --check` 无错误，仅有既有 LF/CRLF 提示；未生成 mypy/Ruff cache 或其他临时路径。
- **证据边界：** VALIDATION4 按中央裁定未重复 VALIDATION2 已绿的 focused approval `13 passed` 与 store/migration `8 passed`。本节与既有 focused 证据合并支持 A1 开发验收，但不等于 A2/manual E2E、PAPER、Linux Gate 或 UA-M4-005 已关闭。

## 15. REWORK4 v3 upgrade fixture correction

- **现象：** 集成回归既有证据为 `229 passed / 5 skipped / 1 failed`；`test_v3_upgrade_adds_empty_ledger_tables_without_forging_context` 在 reopen 时以 `MIGRATION_FAILED` 失败。
- **根因：** fixture 先打开当前 v8 数据库，再只删除 v4–v7 表并把 `schema_version` 改为 3，却保留 v8 才有的 `approval_receipts`。重开时 v8 migration 正确执行不带 `IF NOT EXISTS` 的建表并发现表已存在，因此 fail closed；这是模拟历史库不完整，不是 production v008 需要放宽约束。
- **规则：** 历史版本 fixture 必须删除所有高于模拟版本引入的表；production migration 必须保持严格建表/失败语义，不添加 `IF NOT EXISTS` 来掩盖上下文伪造或 schema drift。
- **最小复现：** `_open()` 创建 v8 DB；fixture 删除 `risk_transition_receipts`、cancel/ledger v4–v7 表，留下 `approval_receipts`，将版本设为 3，再 `_open()`，即触发 v8 `CREATE TABLE approval_receipts` 的 `MIGRATION_FAILED`。
- **窄修复：** `test_execution_store.py` 的模拟 v3 fixture 额外执行 `DROP TABLE approval_receipts`（其索引随表删除），升级后 recovery 断言新增 `rows.approval_receipts == ()`；未修改 production、v008 migration、schema 或其他测试行为。
- **既有 focused-test 证据：** VALIDATION4/既有记录中的 approval `13 passed`、store/v008 `8 passed`、Ruff exact6、mypy production4 与 cold import 证据均保持历史原样；本轮没有重新运行集成回归或任何 Python/pytest/Ruff/mypy/cold/SQLite 检查。
- **通过条件：** 该 v3 fixture 不再保留 v8-only `approval_receipts`，reopen 升级后 `recovery.approval_receipts == ()`，且 production v008 仍无 `IF NOT EXISTS`；后续集成验证应确认该单测通过。当前只交付静态 fixture 修复，不把既有或未运行证据扩写为本轮验证/Gate 通过。

## 16. VALIDATION5 integration-fix 验证证据

- **identity preflight：PASS。** `quant`、approval 与 store 均精确从当前 source worktree 导入；direct-call Windows Miniforge carrier 使用 BelowNormal、affinity `0xF00`、数值线程不超过 2。
- **完整 focused 回归：PASS。** `tests/unit/test_approval.py` 与完整 `tests/unit/test_execution_store.py` 合计 `230 passed, 5 skipped in 9.18s`；修复前唯一 v3 fixture 失败已关闭。
- **Ruff exact6：PASS。** approval、migration registry、v008、store 与两份完整测试文件返回 `All checks passed!`。
- **mypy production4：PASS。** 返回 `Success: no issues found in 4 source files`。
- **cold imports：PASS。** approval、migration registry、v008 与 store 均精确指向当前 worktree。
- **scope/temp：PASS。** 验证前后业务变更仍只有 `test_execution_store.py` 与本交付报告，另有同一 reviewer 的既有初验报告；`git diff --check` 无错误，仅既有 LF/CRLF 提示。fresh pytest basetemp 已精确删除。
- **边界：** 本轮没有修改或运行 PAPER、A2/manual E2E、网络、浏览器或真实 worker；结果支持 REWORK4 source fix 提交，不等于 UA-M4-005 或后续 Gate 已关闭。

DELIVERY_READY docs/framework/agent/M4_P8_A1_DurableApprovalReceiptStore交付报告.md
