# M1-HK-CA-P1-PRE R3：实施事实 Capability 独立复验报告

日期：2026-08-09
角色：未参与 R3 返工实现的全新独立复验
结论：**实施事实子包 PASS，可进入主 Agent 最终验收；HK bar capability 仍 blocked**
边界：本结论不是正式 HK 数据、01065/HK60、复权、M1 或 ext4 Gate 结论

## 1. 独立性、范围与最终判定

- 只读核对了 P1-PRE 任务书 §14、R2 FAIL、R3 返工交付、实施事实生产代码、Schema、公开导出与三份定向实现测试。
- 未参与 R3 实现，未修改生产代码或实现测试；只新增本报告。未联网、未读取凭据、未访问正式
  data/journal，未 add/commit。
- 没有以实现者自报绿测作为结论。独立增加了两层 capability 继承、known withdrawal 在前而后续 future
  withdrawal 越界、adapter 直接抛 ValueError/RuntimeError、合法 capability pickle-copy、合法 raw/P0/adapter
  新闭包移植旧 token 等实现报告未使用的反例。
- R2 的两个阻断均已关闭：fresh capability 边界统一拒绝非 exact runtime type；withdrawal retained parser 在
  query as-of 选择前遍历并验证全部结构、UTC 因果、exact P0 link、唯一性和 canonical 顺序。
- 因此实施事实子包本轮判定 **PASS**，可进入主 Agent 最终验收。HK bar capability 继续等待 PRE-B receipt v3
  与 canonical availability evidence；这是正确的 **blocked** 边界，不构成本报告 FAIL。

## 2. 标准—证据—结论

| 冻结标准 | 独立证据 | 结论 |
|---|---|---:|
| capability 必须为 exact type | `_preflight` 在生产代码 680-696 行使用 `type(value) is HkCorporateActionImplementationCapability`；builder 358 行、wrapper 401 行、selector/public verifier 经 568 行均 fresh 调用该检查 | PASS |
| subclass/多层继承四边界拒绝，wrapper 不调用 adapter | 独立两层继承探针在 builder、wrapper、selector、public verifier 均返回 `HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED`；wrapper `calls=0` | PASS |
| 合法 exact-content copy 不被 instance-unique 身份破坏 | 普通 `copy()` 与 capability pickle round-trip 后均保持 exact type，selector 与 public verifier fresh 通过，各得到 2 条 action | PASS |
| withdrawal required text strict | parser 274-284 行对全部 required text 要求 exact `str`、非空且原值等于 `strip()`；独立空、全空白、首尾空白、非字符串 source record 全部返回 `...EVIDENCE_INVALID` | PASS |
| withdrawal observation causality | parser 287-295 行要求 aware UTC 且 confirmation 不晚于 bundle `source_observed_at`；独立 `2026-08-02 > 2026-08-01T12:00Z` 即使不影响早期 as-of 仍拒绝 | PASS |
| withdrawal exact/业务唯一性及 canonical 顺序 | parser 307-330 行分别维护 source-record key 与业务 key，并检查冻结排序键；完全重复、同业务键不同 record/time、反向顺序均拒绝 | PASS |
| 先验证全部 withdrawal，再应用 query as-of | parser 274-330 行完成全部遍历后才在 331 行应用 as-of；独立“known 合法记录在前、后续 future 越界 event”返回 `...SCOPE_INVALID`，证明未被 known 的 fail-closed 选择短路 | PASS |
| 合法 future/known withdrawal 语义 | 两个不同 event 的 canonical future withdrawals 保留较早 as-of 的 2 条 action；截至 as-of 已知 withdrawal 返回 `...EVIDENCE_INVALID`，未签发 implemented set | PASS |
| exact implementation event scope | 独立缺失、重复、额外 event 分别返回 `...SCOPE_INVALID`、`...EVIDENCE_INVALID`、`...SCOPE_INVALID` | PASS |
| only-scope 不得从 P0 ACTIVE 推导 IMPLEMENTED | 独立 `only_scope=True` 返回 `HK_CA_IMPLEMENTATION_EVIDENCE_INVALID` | PASS |
| 合法新闭包不得复用旧 token | 独立构造并 fresh 签发另一 raw-bundle identity、adapter version、P0 whole-rehash 闭包，再移植旧 projection attestation；三者均返回 `...VERIFY_FAILED` | PASS |
| hostile 异常稳定脱敏 | adapter 直接抛 ValueError/RuntimeError 均映射 `...EVIDENCE_INVALID`；hostile P0 verifier 映射 `...VERIFY_FAILED`；cause/context 为空且 traceback 无 marker，P0 失败时 adapter 未调用 | PASS |
| pickle/reload fail closed | projection/set pickle 均为 TypeError；模块 reload 后旧 capability 在 builder 返回 `...CAPABILITY_UNSUPPORTED`，旧 projection 在 selector 返回 `...EVIDENCE_INVALID` | PASS |
| bar availability 不可证明时停止 | R3 未实现或修改 bar capability/history，未生成或推断 `bar_available_at` | BLOCKED（正确边界） |

## 3. 独立对抗证据摘要

```text
MULTILEVEL_BUILDER REJECTED HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED
MULTILEVEL_WRAPPER REJECTED HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED CALLS=0
MULTILEVEL_SELECTOR REJECTED HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED
MULTILEVEL_PUBLIC_VERIFIER REJECTED HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED
EXACT_COPY ACCEPTED 2
EXACT_PICKLE_COPY ACCEPTED 2

WITHDRAWAL_SOURCE_RECORD_EMPTY REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
WITHDRAWAL_SOURCE_RECORD_BLANK REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
WITHDRAWAL_SOURCE_RECORD_PADDED REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
WITHDRAWAL_SOURCE_RECORD_NONSTR REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
WITHDRAWAL_AFTER_OBSERVED REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
WITHDRAWAL_EXACT_DUPLICATE REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
WITHDRAWAL_BUSINESS_DUPLICATE_DIFFERENT_PAYLOAD REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
WITHDRAWAL_NONCANONICAL REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
WITHDRAWAL_DISTINCT_CANONICAL_FUTURE ACCEPTED 2
WITHDRAWAL_KNOWN REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
KNOWN_THEN_FUTURE_OUT_OF_SCOPE_TRAVERSED REJECTED HK_CA_IMPLEMENTATION_SCOPE_INVALID

EXACT_EVENT_MISSING REJECTED HK_CA_IMPLEMENTATION_SCOPE_INVALID
EXACT_EVENT_DUPLICATE REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
EXACT_EVENT_EXTRA REJECTED HK_CA_IMPLEMENTATION_SCOPE_INVALID
ONLY_SCOPE_ACTIVE REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID

LEGAL_RAW_BUNDLE_WHOLE_REHASH_OLD_TOKEN REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
LEGAL_ADAPTER_VERSION_OLD_TOKEN REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
LEGAL_P0_WHOLE_REHASH_OLD_TOKEN REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
HOSTILE_ADAPTER_ValueError REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID CLEAN
HOSTILE_ADAPTER_RuntimeError REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID CLEAN
HOSTILE_P0 REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED CLEAN
PROJECTION_PICKLE REJECTED TypeError
SET_PICKLE REJECTED TypeError
RELOAD_OLD_CAPABILITY REJECTED HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED
RELOAD_OLD_PROJECTION REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
```

其中 distinct future withdrawal 使用两个不同 P0 event/revision/source-record，按
`(source, source_event_id, source_revision_id, withdrawal_confirmed_at, source_record_id)` 排序；query as-of 为
2026-05-10，withdrawal confirmations 为 2026-05-11/12，bundle observation 为 2026-08-01T12:00Z。它们在
bundle 观察时点可知、在 query as-of 尚未生效，所以合法保留早期 action，结构与因果语义没有混淆。

## 4. 代码与测试审查

- exact-type 修复位于单一 `_preflight`，四个 fresh 边界复用同一检查，没有新增平行身份机制；content-bound
  capability clone/pickle 仍合法，符合 §14 明确非 instance-unique 的合同。
- source wrapper 在读取 capability 后立即 preflight，发生 unsupported 时早于 `adapter.verify_retained`，所以
  subclass 或多层继承不会触发 adapter 外部行为。
- synthetic adapter 先完整解析 withdrawals，再解析 implementation records；withdrawal validation 不依赖当前
  selection 是否会被撤回。记录 key 与业务 key 分开，既拒绝完全重复，也拒绝同 event/revision 的不同 payload。
- 正式 R3 测试覆盖单层 subclass、source-record 四类非法值、晚于 observation、exact/业务重复、canonical
  顺序、合法不同 event future withdrawal、known withdrawal 与 exact clone。独立复验补上多层继承和
  known-first 后续越界记录，未发现阻断缺口。
- 没有发现需要返回实现 Agent 的新问题。

## 5. Windows / WSL base 定向验证

| 环境 | 检查 | 实际结果 |
|---|---|---|
| Windows Miniforge | `test_schemas.py`、`test_hk_corporate_action_implementation.py`、`test_hk_history_backfill.py`，禁用项目 cache | `124 passed, 1 skipped` |
| Windows Miniforge | 3 个生产文件 + 3 个定向测试文件 Ruff `--no-cache` | `All checks passed!` |
| Windows Miniforge | `schemas.py`、`domain/__init__.py`、implementation 模块 mypy `--no-incremental` | `Success: no issues found in 3 source files` |
| WSL Miniforge base `/mnt/f` | 同一三文件 pytest | `125 passed` |
| WSL Miniforge base `/mnt/f` | 同一 6 文件 Ruff | `All checks passed!` |
| WSL Miniforge base `/mnt/f` | 同一 3 个生产文件 mypy | `Success: no issues found in 3 source files` |

Windows 的一个 skip 是既有 symlink 平台差异；Pandera/Polars deprecation warnings 未形成断言失败。测试禁用
项目内 pytest cache、关闭 bytecode，并把 pytest/mypy 临时目录放在系统临时目录，未向生产或测试路径写入产物。

`findmnt` 实际返回：

```text
/mnt/f drvfs rw,noatime,uid=1000,gid=1000,case=off
```

因此 WSL 结果只证明同一 DrvFS 工作树上的双平台定向开发反馈，**不是 ext4 Gate**。

## 6. 范围与 diff 检查

- `git diff --check` 对 tracked diff 退出 0。implementation 与对应测试在当前叠加工作树中仍为既有 untracked
  文件，另以 no-index check 核对，两份代码文件没有 whitespace error；仅出现 Git 的 LF/CRLF 转换提示。
- R3 交付报告第 3 行存在既有 Markdown hard-break 两个尾随空格；它不在生产代码/测试内，本复验未修改实现者
  报告，不将其判为合同阻断。
- 写报告前记录的只读 SHA256：implementation
  `BCF601FF27893A907A4BFC21E808E1BABD059E585FEF737B6C6C17572CC4F431`；对应测试
  `138837D642943AEF34454E4F670703700BC7EC074F919A719FD9B9C5C03CD299`。报告写入后将再次核对。
- 工作树含任务开始前已有的 P0/HK history/HK60/U0C 等修改和未跟踪文件；本复验不接管、不清理、不评价
  这些范围，也未运行无关全量测试。

## 7. 最终结论

- **实施事实子包：PASS，可进入主 Agent 最终验收。**
- R2 exact capability type 与 withdrawal retained 因果/唯一性/顺序闭包已由代码审查、正式回归和新增对抗
  反例共同证明；未发现阻断问题。
- **HK bar capability：仍 blocked，且不因此 FAIL。**
- 即使主验接受，本结论也只关闭来源无关实施事实开发合同；不表示存在真实 licensed implementation adapter，
  不关闭 receipt v3、01065/HK60、gross total-return、复权、M1 或 ext4 Gate。
