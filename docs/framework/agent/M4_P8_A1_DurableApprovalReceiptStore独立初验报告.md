# M4 P8 A1-R2 独立初验报告

审查身份：01a0322c-f932-7162-b6fb-9f630cf2471f
角色：唯一独立初验 reviewer
模式：STATIC_ONLY
结论：REVIEW_FAIL

## 1. 稳定性与范围

- worktree：F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-a1-durable-approval-store
- HEAD：ac57ce9e40dc6731e1106b2fa2398f4013fa19da
- branch：codex/m4-a1-durable-approval-store
- 初始审查前 Git 状态只包含任务合同中的 exact8：approval.py、migrations/__init__.py、
  v008_approval_receipts.py、store.py、test_approval.py、test_execution_store.py、
  任务单和交付报告；没有发现其他 writer/source drift、暂存项或额外路径。
- git diff --check 无输出；HEAD、branch 和路径集合在读取后再次核对仍稳定。
- 只读取用户指定的八个文件；没有使用实现 Agent、外部 Cursor、其他 Agent、worktree、
  top-level task 或 commit。
- 没有运行 Python、pytest/collection、Ruff、mypy、cold import、SQLite、网络、浏览器、
  worker 或真实 I/O；本报告不是代码执行或 Gate 批准。

## 2. 静态合同结论

HMAC_SHA256_CREDENTIAL_V1 的主体覆盖和验签路径静态一致：build 用显式的
_receipt_body canonical JSON 计算 HMAC，verify 用同一字段集合重建主体；tag 不在主体内，
receipt_id 对含 tag 的 canonical envelope 做哈希，tag 和 receipt_id 均用
hmac.compare_digest 校验。decode 通过 exact key、canonical bytes、固定 schema、固定
credential kind 和字段类型检查拒绝重复键、额外键、future/unknown wire、非 UTC 和结构漂移。

secret 没有进入 ApprovalReceipt 字段、payload、store 索引、StoredApprovalReceipt 或
RecoveryRows；store 模块也不接收 credential。build 对 secret 的 bytes/hex 直接出现在
主体中的情况额外拒绝，异常使用稳定错误码。这个结论限于直接持久化/文本泄露，不是对
hostile Python 进程的绝对保密声明。

public verify_approval_receipt_for_store -> unpack_verified_approval_receipt 的正常链路
静态具备 exact type、canonical receipt/payload 相等、proof 绑定 receipt_id+精确 payload
的检查。raw、直接构造、缺 proof、跨 receipt replay、payload/index drift、VerifiedApprovalReceipt
子类和 bytes 子类均被现有 exact-type 分支拒绝；错误 key、tag、identity、future、
unknown credential 也有对应代码/测试路径。v008 只追加 approval_receipts 表、唯一约束和
plan/session、recovery、operator/session 索引；MIGRATIONS 注册 v8，现有 v7->v8 测试保留
旧 command 行。代码和文档没有新增 A2 manual=true、dispatch、PAPER 路径，也没有声称关闭
UA-M4-005。

## 3. 阻塞发现 F1：raw/index 私有 helper 仍可绕过 hand-off

### 现象

ExecutionRepository._put_approval_receipt_candidate(candidate) 是可由普通调用者直接访问的
实例方法。它接受公开的 StoredApprovalReceipt dataclass，只做 receipt_id、业务键和 nonce
查询，然后直接 INSERT；在该入口没有调用 unpack_verified_approval_receipt，也没有
HMAC 验证、proof 验证或 candidate 的 canonical/index 对账。put_verified_approval_receipt
虽然先走了正确 hand-off，但并没有让这个 raw/index 写入口本身 fail closed。

### 根因

证明边界只放在一个 public method 上，实际持久化 helper 仍把可手工构造的
StoredApprovalReceipt 当成已验证候选。Python 的单下划线约定不是访问控制；这里甚至不需要
reflection、object.__new__ 或读取模块私有 key，调用者只需直接调用公开 repository 对象的
下划线方法。

### 应遵循规则

任务合同要求 store 只接受 verify_approval_receipt_for_store 产生的 credential-free
hand-off，并要求 raw+index bypass fail closed。持久化前必须存在不可伪造的内部证明，或
raw/index helper 必须不在 repository boundary 上可调用；不能把 decode、dataclass 字段或
方法命名约定当成验签证明。

### 最小复现（静态描述，未执行）

在空 store 中，用 test_execution_store.py 已有的 self-consistent HMAC-invalid payload
构造 forged_raw，使其 tag 被改写且 receipt_id 仅按新 envelope 重算；decode 可得到 forged。
随后仅用 forged 的字段构造：

    candidate = StoredApprovalReceipt(
        receipt_id=forged.receipt_id, identity=forged.receipt_id,
        schema_version=forged.schema_version, classification=forged.classification,
        credential_kind=forged.credential_kind, credential_id=forged.credential_id,
        operator_id=forged.operator_id, session_date=forged.session_date,
        action=forged.action, plan_identity=forged.plan_identity,
        challenge_identity=forged.challenge_identity,
        store_recovery_identity=forged.store_recovery_identity,
        source_identities_digest=forged.source_identities_digest,
        issued_at=forged.issued_at, nonce=forged.nonce, payload=forged_raw
    )
    with store.transaction() as repo:
        repo._put_approval_receipt_candidate(candidate)

该路径没有 credential、VerifiedApprovalReceipt 或 proof；candidate 的字段仍可满足 v008
的长度/固定值/唯一键约束，因此静态上可落库 HMAC-invalid receipt。现有
test_v8_hmac_invalid_self_consistent_payload_has_no_public_store_bypass 只检查
put_verified_approval_receipt(forged)，没有覆盖这个直接 helper 入口。

### 通过条件

删除 repository boundary 上的 raw/index 写入口，或让它只能由 approval module 交付的
不可伪造内部令牌调用，并在该边界增加 self-consistent HMAC-invalid candidate 的拒绝测试。
普通 direct、object.__new__/__setattr__、subclass、fake decode、raw+bool、raw+index 和
wrong/missing/replayed proof 均必须在唯一持久化入口 fail closed。

## 4. 信任边界与能力复制对抗项

proof 是同一 Python 进程内的 capability，不是恶意 Python 的隔离边界。
_HANDOFF_PROOF_KEY 和 _new_verified_handoff 仍是可由模块属性访问的对象；能够主动读取
模块私有状态或调用私有工厂的 hostile caller 可以为结构上自洽的伪造 receipt 生成 proof。
因此不能声称 malicious-reflection guarantee。正常受信 Python 调用者的 public
verify->store 路径仍有 exact payload/receipt binding；F1 则比 reflection 更弱，直接下划线
helper 调用已足以绕过，不能用上述信任边界掩盖。

新增能力复制对抗项（实现者测试未覆盖，静态未执行）：

- CC-1：对合法 verified 执行 dataclasses.replace(verified, payload=forged_raw)。
  VerifiedApprovalReceipt 的 init=False 自定义 __init__ 无条件抛出
  APPROVAL_RECEIPT_NOT_VERIFIED，因此 replace 不能制造带新 payload 的 capability。
- CC-2：对合法 verified 做 copy.copy(verified)，再尝试通过 object.__setattr__ 改动
  receipt 或 payload。若复制保留 exact fields/proof，它至多是同一已验证 capability 的
  exact replay；任何改动都会破坏 canonical pair 或 proof。该复制允许性仍需后续运行时测试
  证实，不能在 STATIC_ONLY 下宣称通过。

## 5. 测试路径与证据边界

test_approval.py 直接导入并调用真实 codec/build/decode/verify/public hand-off；没有替换
核心实现。test_execution_store.py 直接调用真实 ExecutionStore.open、真实 transaction、
真实 repository 方法，并用 sqlite3 破坏/重开数据库来构造旧库和索引漂移场景；fixture 只
提供数据、临时根和边界 fault injection，不是核心实现替身。因此已有测试设计会到达真实
实现路径，但本轮没有执行它们。

当前仍缺少明确的非空 approval restart 证据：测试在同一打开的 store 上验证 round-trip，
而 v7 reopen 场景验证的是空 approval 表。应补充 close/reopen 后只取 raw bytes/index，
再由 caller 用 credential 重新 verify 的测试。该项是运行时证据缺口，不得被实现报告的
STATIC_DONE 或本次静态审查改写为测试通过。

## 6. 复核结论

HMAC canonicalization、直接 secret 非持久化、正常 proof 绑定、v008 静态注册、旧/新库
合同方向、冲突/索引漂移/未来版本/错误 key 的 fail-closed 设计和 A1/no-op 范围边界
基本符合冻结文本；但 F1 违反“唯一 hand-off persistence boundary”这一核心不变量，
且尚无非空 approval restart/re-verify 的运行证据。

最终结论：REVIEW_FAIL

## 7. REVIEW_REWORK1（同一独立审查身份）

审查身份：`01a0322c-f932-7162-b6fb-9f630cf2471f`。本节为 F1 closure 的追加复核，保留上文全部历史；本轮仍为 `STATIC_ONLY`，未运行 Python、pytest、Ruff、mypy、cold import、SQLite、网络、浏览器、真实 I/O、CPU 或 worker，未提交。

### 7.1 基线与漂移

- 目标 worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-a1-durable-approval-store`。
- 静态 Git 复核仍为 HEAD `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`、branch `codex/m4-a1-durable-approval-store`。
- `git status` 仅显示 exact8 的预期源码/测试/任务书/交付报告变更及本既有独立初验报告；没有额外 writer/source 路径漂移。未修改 implementation、tests、taskbook 或 delivery report。
- 当前任务书和交付报告明确为 `STOPPED_PENDING_ROOT_RESUME`，并明确 focused pytest 未运行；这不是独立初验、主验或 Gate 通过证据。

### 7.2 F1 closure：raw/index candidate writer bypass

#### 现象

前轮 F1 的 `ExecutionRepository._put_approval_receipt_candidate(StoredApprovalReceipt)` 已从当前 `store.py` 消失。静态搜索显示 `StoredApprovalReceipt(...)` 只出现在只读行解析 `_row_to_stored_approval` 和唯一 persistence boundary `put_verified_approval_receipt` 的内部 candidate 构造处；`INSERT INTO approval_receipts` 也只在该 public hand-off method 内出现。公共 `StoredApprovalReceipt` 仍是 recovery/read DTO，但没有接受它写入的 repository/module helper。

#### 根因

REWORK1 将 candidate 构造、receipt/index 一致性依赖、唯一性检查和 SQL insert 内联到 `put_verified_approval_receipt`，并把 `unpack_verified_approval_receipt(verified)` 放在所有持久化动作之前；因此 caller 提供的 raw/index DTO 不再拥有独立写入口。

#### 应遵循规则

必须只有 credential-free、已由 approval module 验证并绑定 exact canonical payload 的 `VerifiedApprovalReceipt` hand-off 可以进入持久化；raw bytes、decoded receipt、bool、普通/伪造 `StoredApprovalReceipt`、index candidate 和 module/private helper 均不得成为另一个写边界。

#### 最小静态复现（最强 self-consistent HMAC-invalid candidate）

`test_v8_raw_index_candidate_has_no_repository_persistence_bypass` 先从合法 canonical payload 改 tag，并重算 `receipt_id`，得到结构自洽但 HMAC 无效的 `forged_raw`；再 `decode_approval_receipt(forged_raw)`，将其全部 index 与 `forged_raw` 装入 caller 可构造的 `StoredApprovalReceipt` candidate。随后对真实 `ExecutionStore.open`、真实 transaction、真实 `ExecutionRepository.put_verified_approval_receipt(candidate)` 做静态路径追踪：

1. `put_verified_approval_receipt` 首先调用 `unpack_verified_approval_receipt`。
2. `unpack_verified_approval_receipt` 要求 `type(value) is VerifiedApprovalReceipt`；candidate 是 `StoredApprovalReceipt`，因此在 candidate 构造和 SQL 之前得到 `APPROVAL_RECEIPT_NOT_VERIFIED`。
3. 新测试还静态断言 repository 与 `ExecutionRepository` 均没有 `_put_approval_receipt_candidate`，且 query 结果为空。

同一 boundary 对 raw forged payload 也先拒绝；对 object-new 伪造 hand-off 则仍走 canonical pair、proof 和 exact-type/field guards。以上是 source/test control-flow 证据，不是运行证据。

#### 通过条件

就 F1 的静态合同而言，当前源码满足“无 repository/module raw/index persistence bypass、candidate 只能在 verified hand-off method 内产生并插入”。但由于 focused tests 未执行，不能把该静态满足写成 REVIEW_PASS 或 runtime closure。

### 7.3 非空 close/reopen recovery 与 caller re-verification

新增 `test_v8_nonempty_approval_close_reopen_requires_caller_reverification` 先通过真实 verified hand-off 写入非空 approval，关闭后重新 `ExecutionStore.open`，从真实 repository 读取 `StoredApprovalReceipt`。源码路径显示 recovery 通过 `_row_to_stored_approval` 返回 canonical `payload` 与严格校验过的最小 indexed fields，不返回 `receipt` 或 `_proof`；`read_recovery_rows().approval_receipts` 使用同一 raw/index DTO。

恢复的 DTO 被直接传给唯一写 boundary 时应得到 `APPROVAL_RECEIPT_NOT_VERIFIED`；测试源码随后显式以 `recovered.payload` 加 caller credential/source identities 调用 `verify_approval_receipt_for_store`，再用新的 verified hand-off 做 exact replay no-op。这证明新增测试不是 fixture-only 设计，且静态上表达了“恢复后必须由 caller 重新 credential-verify，不能把数据库行当 trusted receipt”。但 close/reopen、数据库查询、HMAC 和 no-op 均未执行，故没有运行时证据。

### 7.4 新测试真实路径检查与剩余信任边界

新 candidate/reopen 测试调用真实 `ExecutionStore.open`、`transaction`、repository writer/read/recovery 方法；fixture 仅提供临时根和输入数据，candidate/forgery helper 只构造 adversarial input，没有替换 persistence implementation。该结论仅限静态阅读。

仍须诚实保留同进程 trusted-Python 边界：`VerifiedApprovalReceipt` 的 `_HANDOFF_PROOF_KEY` 与 `_new_verified_handoff` 是 module-private 设计，但同一 Python 进程内拥有 reflection/object-level 能力的代码仍可能读取或调用它们；因此不能宣称 malicious-reflection guarantee。当前 rework 关闭的是 public repository/module raw/index writer bypass，不是恶意同进程 Python 的绝对能力隔离。

### 7.5 执行证据缺口

#### 现象

任务书 §12 与交付报告 §8 记录最终 guard 发现禁止的 Python 进程，状态为 `STOPPED_PENDING_ROOT_RESUME`；focused approval/store pytest 及所有运行时检查均明确未运行。

#### 根因

本轮的冻结边界是 `STATIC_ONLY`，且 root resume/禁止进程清除前不得启动任何执行性验证。

#### 应遵循规则

缺少执行证据不能被静态源码覆盖、实现者自报或新增测试源码改写为通过；独立初验的最终通过必须等待授权恢复后的可重现实证据。

#### 最小静态复现

当前交付报告同时列出“F1 helper 已删除/close-reopen source coverage 已补充”和“focused pytest 未运行、不能声称测试通过”；两者并不矛盾，前者只能支持静态 closure，后者阻断 review pass。

#### 通过条件

root 清除禁止进程并重新确认稳定边界后，按授权范围运行并记录 focused approval/store 验证（包括 F1 candidate、HMAC-invalid、non-empty close/reopen reverify）；在此之前不得把本节标为通过。

## 8. REVIEW_REWORK1 结论

F1 静态 closure：`STATICALLY_CLOSED`。由于明确缺少执行证据，且用户规则要求 missing execution evidence 不得视为 pass，本轮最终结论：`REVIEW_FAIL`。

## 9. REVIEW_REWORK2（同一独立审查身份；窄 codec 复核）

审查身份：`01a0322c-f932-7162-b6fb-9f630cf2471f`。本节追加且不改写上文历史；范围仅为 `receipt_id` wire-root required-key 修复，模式仍为 `STATIC_ONLY`。本轮未运行 Python、pytest、Ruff、mypy、cold import、SQLite、CPU、网络、真实 I/O 或 commit。

### 9.1 基线、证据来源与状态

- worktree、HEAD、branch 仍为 `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-a1-durable-approval-store`、`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`、`codex/m4-a1-durable-approval-store`；Git 状态只有 exact8 既有业务变更及本审查报告，无额外 source/writer 路径漂移。
- 任务书 §13 与交付报告 §9 记录中央身份验证为 `PASS`，以及修复前 focused `test_approval` `10 passed / 2 failed`；失败集中在合法 canonical round-trip 与 no-op decode 入口的 `APPROVAL_RECEIPT_INVALID`。
- 交付报告 §10 明确记录 post-fix `test_approval` 未运行。本节不把该未运行状态写成测试通过，也不要求不可用的 post-fix runtime 证据来作本次静态 codec 结论；下述 `REVIEW_PASS` 仅表示静态窄范围审查通过，不是执行/Gate/主验批准。

### 9.2 `receipt_id` required-key 修复

#### 现象

修复前 `decode_approval_receipt` 把 `_WIRE_KEYS - {"receipt_id", "schema_version"}` 传给 `require_wire_root`，而 `_WIRE_KEYS` 本身已排除 schema key，导致合法 wire 的 required `receipt_id` 被误判缺失。

#### 根因

required-key 集采用了多余且错误的字段剔除表达式，实际遗漏了 `_WIRE_KEYS` 中的 `receipt_id`。

#### 应遵循规则

`require_wire_root` 必须接收完整的非 schema `_WIRE_KEYS`，其中必须包含 `receipt_id`；schema 由后续 exact-object/schema 检查处理。缺失、重复和任何额外 receipt key 必须 fail closed。

#### 最小静态复现与路径

当前 `approval.py` 的 `_WIRE_KEYS` 明确列出 `receipt_id`（约第 43–59 行），`decode_approval_receipt` 在约第 224–229 行以 `keys=set(_WIRE_KEYS)` 调用 `require_wire_root`，随后以 `set(_WIRE_KEYS) | {"schema_version"}` 调用 `require_exact_object`。因此：

1. 合法 `encode_approval_receipt(_receipt())` wire 含 `receipt_id`，不再被 root required-key 检查错误拒绝。
2. 新测试 `test_receipt_id_is_required_and_duplicate_receipt_id_fails_closed` 删除 `receipt_id` 后直接调用真实 `decode_approval_receipt`，覆盖缺失键。
3. 同一测试向原始 JSON 追加第二个 `receipt_id`，直接调用真实 decoder，覆盖 duplicate/extra receipt key；既有 `_rewrite(raw, extra="forbidden")` 覆盖一般 extra key，既有 duplicate-tag 测试覆盖重复键 fail-closed。

测试辅助函数只负责构造 adversarial bytes；断言入口是 production `decode_approval_receipt`，没有替换 codec、mock decoder 或仅检查 fixture 内容。

### 9.3 未回退的 codec 不变量

- canonical re-encode 仍在构造 `ApprovalReceipt` 后执行 `encode_approval_receipt(value) != payload` 拒绝路径；因此字段排序/JSON canonical bytes 仍必须与 wire 完全一致。
- future schema 仍由 `require_wire_root(..., schema=_SCHEMA)` 的 `WIRE_VERSION_UNSUPPORTED` 映射为 `APPROVAL_RECEIPT_UNSUPPORTED_VERSION`；既有 future-version 测试仍直达真实 decoder。
- HMAC/tag 验证仍只在 caller `verify_approval_receipt` 中基于 `_receipt_body(value)` 计算并用 `hmac.compare_digest`；修复未把 decode 当成验签，也未改变 wrong-key/tag fail-closed 语义。
- receipt identity 绑定仍由 `_validate_receipt` 对 `_receipt_envelope(value)` 重算 SHA-256，并由 `verify_approval_receipt` 再次对含 tag envelope 重算/constant-time 比较；`receipt_id` 只改 required-key 入口，没有改算法或绑定范围。
- exact8 中 store、v008 migration 及 execution-store approval paths 未因本窄修复扩围；它们仍把 codec 返回/错误作为实际 implementation path 的边界，未出现另一个 codec fixture-only substitute。

### 9.4 静态通过条件与剩余证据边界

#### 通过条件

完整 `_WIRE_KEYS`（含 `receipt_id`）进入 root required-key 检查；缺失/重复/额外 receipt key fail closed；合法 canonical receipt 可继续进入 existing exact-object、canonical re-encode、future-version、HMAC/tag 与 receipt-identity checks；新测试源码直接覆盖真实 codec。以上条件均在当前 exact8 源码与测试静态满足。

#### 剩余信任边界

post-fix `test_approval` 仍是 `UNRUN`，所以本报告不声称 10/2 之后的运行结果、语法/类型/平台行为或 Gate 通过；身份 `PASS` 与 pre-fix `10 passed / 2 failed` 仅按交付记录归档。此限制不阻断本次用户明确限定的静态窄 codec conclusion。

## 10. REVIEW_REWORK2 结论

`REVIEW_PASS`（STATIC_ONLY narrow codec review；不等于 focused pytest、Gate、独立运行验收或主验通过）。

## 11. REVIEW_REWORK3（同一独立审查身份；VALIDATION2 import-only cleanup）

审查身份：`01a0322c-f932-7162-b6fb-9f630cf2471f`。本节追加且不改写全部既有 findings/history；范围仅核对 REWORK3 是否删除 `store.py` 中 VALIDATION2 已确认的四个 F401 unused imports。本轮为 `STATIC_ONLY / zero Python`，未运行 Python、pytest、Ruff、mypy、cold import、SQLite、CPU、网络、浏览器、真实 I/O 或 commit。

### 11.1 基线与交付证据

- 目标 worktree、HEAD、branch 仍为 `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-a1-durable-approval-store`、`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`、`codex/m4-a1-durable-approval-store`；Git 状态仍只有 exact8 的既有业务文件及本审查报告，没有额外路径漂移。
- 交付报告 §11 的既有 VALIDATION2 证据诚实记录 `tests/unit/test_approval.py` `13 passed in 1.93s` 与冻结 approval/v008 store 节点 `8 passed in 3.00s`；这些是此前执行证据，不是本轮新执行。
- 同一报告 §11 记录 Ruff exact6 在首个失败处 STOP，四个 F401 为 `APPROVAL_RECEIPT_CLASSIFICATION`、`APPROVAL_RECEIPT_SCHEMA_VERSION`、`FORMAL_APPROVAL_ACTION`、`HMAC_SHA256_CREDENTIAL_V1`；§12 明确本轮 post-fix checks 未运行。本报告不把 13+8 或未运行的 post-fix 检查扩写成新的测试/Ruff/Gate 通过。

### 11.2 四个 F401 的窄修复核对

#### 现象

VALIDATION2 指出的四个 approval constants 曾位于 `src/quant/execution/store.py` import block，但当前 store 只实际需要 `ApprovalReceiptError`、`VerifiedApprovalReceipt`、`decode_approval_receipt` 与 `unpack_verified_approval_receipt`。

#### 根因

四个常量是 stale imports；它们不参与 store 的 receipt decode、verified hand-off、candidate 构造、唯一性检查、SQL insert、recovery 或任一 F1 proof boundary。

#### 应遵循规则

只删除工具明确报告的四个未使用名称；不得替换 API、重排/改写行为、触碰测试、schema、migration、codec、proof-forgery contract 或 F1 唯一 persistence boundary。

#### 最小静态复现与当前结果

当前 `store.py` import block（约第 22–27 行）只保留四个实际使用符号；静态搜索确认四个 F401 名称不再出现在 `store.py`。同一文件仍保留：

- `put_verified_approval_receipt` 先调用 `unpack_verified_approval_receipt`，并在同一 boundary 内完成 candidate/冲突检查/INSERT；
- `_row_to_stored_approval` 对 recovery payload 做 decode/index 对账；
- `ExecutionRepository`/module 中没有 `_put_approval_receipt_candidate`，F1 的 raw/index writer bypass 未复现。

这支持“REWORK3 仅为四行 unused-import cleanup”的静态结论；由于没有本轮前后可执行 diff 或 Ruff 重跑，不能把它写成新的工具执行证据。

### 11.3 无行为、测试、schema、migration 或合同漂移

当前 exact8 的 `approval.py`、`migrations/__init__.py`、`v008_approval_receipts.py`、两个测试文件和既有 store approval body 均保留既有 codec/store 合同；本轮 delivery 明确实际修复路径只有 `store.py`。静态阅读未发现 REWORK3 对 canonical codec、HMAC/proof、receipt identity、migration/schema、测试断言或 F1 raw/index boundary 的修改。

既有 13+8 测试源码调用真实 implementation paths，但它们的历史执行结果不能证明本轮 import cleanup 后仍已执行；本轮没有新增测试，也没有宣称任何新测试执行。

### 11.4 结论与证据边界

静态通过条件是：四个 VALIDATION2 F401 名称从 `store.py` import block 删除；其余 approval imports 与真实引用保持；不发生 production behavior、test、schema、migration、proof-forgery 或 F1 contract 变化。当前源码与交付记录满足该窄条件。

因此本轮结论为：`REVIEW_PASS`（仅 static import-cleanup review）。13+8 是既有 VALIDATION2 execution evidence；REWORK3 post-fix checks 是 `UNRUN`，本结论不等于 Ruff 通过、Gate 通过、A1 关闭或任何新测试执行。

## 12. VALIDATION4（同一原始独立审查身份；开发验收证据链复核）

审查身份：`01a0322c-f932-7162-b6fb-9f630cf2471f`。本节追加且保留全部 prior findings/history；本轮严格 `STATIC_ONLY / zero Python`，未运行 Python、pytest、Ruff、mypy、cold、SQLite、网络、浏览器、CPU 或其他执行性检查，未修改 exact8、implementation、tests、taskbook、delivery report 或提交。

### 12.1 证据来源与身份边界

- 当前 worktree、HEAD、branch 仍为 `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-a1-durable-approval-store`、`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`、`codex/m4-a1-durable-approval-store`；Git dirty 集仍为 exact8 既有业务路径及本独立审查报告，无额外路径漂移。
- delivery §13 的 VALIDATION3 明确是 carrier 在身份断言前因 PowerShell/Python 参数展开失败的 `STOP`；它没有到达 approval、migration、store 或测试 implementation path，因此不进入绿/红实现证据，也不抵消后续 VALIDATION4。
- delivery §11 的 VALIDATION2 是既有 focused execution evidence：真实 `test_approval.py` `13 passed`，以及冻结 approval/v008 store 节点 `8 passed`。该证据发生在 REWORK3 的纯 import cleanup 前，不能写成由本轮重新执行。
- delivery §14 的 VALIDATION4 记录 identity preflight、Ruff exact6、mypy production4、cold imports、scope/diff 均 `PASS`，并明确 focused validation 未重复；本审查只核对该记录与 exact8/历史边界，不把记录冒充本轮执行。

### 12.2 A1 开发验收证据链判断

#### 现象

VALIDATION2 已覆盖行为层 focused approval/store/v008 反例；REWORK3 的唯一生产变更是删除四个已确认未使用的 `store.py` import。VALIDATION4 再记录该清理后的 Ruff、mypy、cold-import 与 scope/diff 检查通过，而没有重复 focused 行为测试。

#### 应遵循规则

carrier STOP 必须与实现证据隔离；行为测试、静态工具、导入检查和范围检查必须分别标明来源与时间，不得把未运行项目写成通过，也不得把 development acceptance evidence chain 扩写成 A2、Gate 或生产验收。

#### 最小静态复现

将证据按时间与职责闭合：

1. VALIDATION3 只在 carrier 解析阶段失败，没有实现结论。
2. VALIDATION2 的 `13+8` focused 结果直接对应 exact8 中真实 codec/store/migration 测试路径，提供行为证据。
3. REWORK3 已由前一节静态核对为四个 F401 import 删除，无测试、schema、migration、proof-forgery 或 F1 boundary 改动。
4. VALIDATION4 的 Ruff exact6、mypy production4、cold 与 scope/diff 记录覆盖该窄修复后的静态、导入和范围风险；其不重复 focused 测试的事实被明确保留。

因此，这些记录在“现有行为 focused evidence + 纯 import cleanup 后的独立工具/导入/范围证据”意义上形成闭合的 A1 development acceptance evidence chain。它不是本 reviewer 新执行出的测试链，也不是 Gate 结论。

### 12.3 诚实性与范围结论

delivery §13 没有把 carrier STOP 写成实现失败或通过；§14 没有伪造新的 focused pytest 结果，而是明确引用 VALIDATION2 并说明未重复；报告也明确保留 `13+8` 的历史来源、VALIDATION4 的记录来源和本审查的零执行边界。该证据叙述是诚实的。

本节结论仅限 A1 development acceptance evidence chain：不扩展到 A2 `manual=true`、approved no-op E2E、PAPER、Linux Gate、formal daily、soak/runtime 或 UA-M4-005 closure。

## 13. VALIDATION4 结论

`REVIEW_PASS`（A1 development acceptance evidence chain 静态复核通过；无本轮执行、无新测试声明、无 Gate 或 A2/UA-M4-005 通过声明）。
