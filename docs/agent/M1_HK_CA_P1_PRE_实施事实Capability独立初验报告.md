# M1-HK-CA-P1-PRE：实施事实 Capability 独立初验报告

日期：2026-08-09  
角色：未参与实现的全新独立初验  
结论：**实施事实子包 FAIL，返回返工；HK bar capability 仍 blocked**  
边界：本结论不是正式 HK 数据、HK60、复权、M1 或 ext4 Gate 结论

## 1. 独立性与范围

- 只读核对了任务书、交付报告、P0/R2/R3 任务与主验链、实施代码、Schema 和实现测试。
- 生产代码与实现测试均未修改；仅写本报告。未联网、未读取凭据、未访问正式数据或 journal，未 add/commit。
- 初验增加了实现者未报告的合法另一 query/source/version/event-set token 置换、P0+implementation 合法
  whole-rehash、hostile P0 verifier、未知 hostile adapter、set pickle、模块 reload、普通 ACTIVE/日期冒充以及
  capability 低层篡改反例。
- 当前工作树位于 `/mnt/f` DrvFS；WSL 结果不代表 ext4 Gate。

## 2. 结论摘要

内容绑定 attestation 的主要防替换边界有效：合法另一 query/source/version/event set、P0 与 implementation
全闭包重建后均不能复用旧 token；factory-only、projection/set pickle、reload、hostile adapter/P0 verifier
也均 fail closed，公开异常 cause/context 为空且 traceback 未泄漏 marker。

但是实施事实的两个更前置不变量未满足：

1. 当前唯一正向 fixture 没有从 retained implementation records 解析实施状态、确认时间、修订或撤回，而是
   在检查一个只含 `scope_complete` 的常量 raw 后，直接遍历 P0 ACTIVE actions 合成 `IMPLEMENTED`。因此现有
   绿测不能证明“普通 ACTIVE/日期不得冒充 IMPLEMENTED”，反而存在机器可复现的被签发路径。
2. fresh `_preflight` 没有重验 capability 的 `source`/`adapter_version` 值约束。合法构造后把
   `adapter_version` 低层篡改为空字符串，source wrapper 仍会为新内容签发 attestation，selector 和 public set
   verifier 均接受。

故实施事实子包不能进入主验，必须返回实现 Agent 返工并由新的独立上下文复验。

HK bar capability 未实现不构成本报告的失败原因。任务书停止条件已经触发：现有 finalize/request/HKEX
supplement 不能 source-verifiably 提供逐 effective key 的 availability 闭包。保持
`HK_BAR_CAPABILITY_UNSUPPORTED`、不签发 `VerifiedHkBarBundle` 是正确边界，因此结论明确为：
**实施事实子包 FAIL，bar capability 仍 blocked**。

## 3. 标准—证据—结论

| 冻结标准 | 独立证据 | 结论 |
|---|---|---:|
| 普通 P0 `ACTIVE`、日期或调用方布尔值不能冒充来源确认的 `IMPLEMENTED` | 正向 fixture 的 retained raw 仅为 `{"scope_complete":true}`，不含 event/status/confirmed/withdrawal；adapter 随后直接遍历 `p0_result.actions` 合成实施行。一次性复现输出 `ACTIVE_DATE_ONLY_FIXTURE_SIGNED 2` | **FAIL** |
| capability/source/version 在每个 fresh 消费边界严格有效 | `_preflight` 只检查 required booleans；低层把合法 capability 的 `adapter_version` 改为空后，wrapper、selector、set verifier 仍通过，输出 `LOW_LEVEL_EMPTY_ADAPTER_VERSION_SIGNED '' 2` | **FAIL** |
| P0 result/projection 与 implementation raw/candidate/evidence 合法 whole-rehash 后旧 token 不可复用 | 构造另一合法 `as_of` 的 P0 source-verified projection/result，再构造对应 implementation query/bundle/evidence 并正常签发；移植旧 implementation token 后返回 `HK_CA_IMPLEMENTATION_VERIFY_FAILED` | PASS |
| 旧 token 不可移植到另一合法 query/source/version/event set | 四类独立合法闭包均先由 public verifier 通过，移植旧 token 后分别稳定返回 `HK_CA_IMPLEMENTATION_VERIFY_FAILED` | PASS |
| factory-only、pickle、reload fail closed | factory-only 由实现测试拒绝；独立补测 projection 与 implemented set pickle 均 `TypeError`，模块 reload 后旧 capability 返回稳定错误 | PASS |
| future confirmation/withdrawal 不改写较早 as-of | future confirmed row 现有测试拒绝；但没有 retained status history，也没有 future withdrawal/correction fixture，正向 adapter 完全不解析 withdrawal | **FAIL（证据缺失）** |
| hostile adapter 与 hostile P0 verifier 异常稳定脱敏 | 现有 nested hostile adapter 与独立未知 `KeyError` adapter、hostile P0 verifier 均映射为稳定 code；cause/context 为空，traceback 无 marker | PASS |
| exact event set/revision/source 闭包 | query event ids 排序唯一；evidence keys 与 query exact equality；source wrapper 和 set builder 将 `symbol/action_type/source/source_event_id/source_revision_id` 与 P0 actions 一一比对；缺失与跨 identity 测试通过 | PASS |
| bar availability 不可证明时停止 | 未新增 bar loader/schema；交付报告给出 finalize/request/HKEX supplement 缺口，与任务书停止条件一致 | BLOCKED（正确边界） |

## 4. 返工问题一：正向 fixture 允许 ACTIVE/日期冒充 IMPLEMENTED

### 现象

`tests/unit/test_hk_corporate_action_implementation.py` 的 `_ImplementationAdapter.verify_retained` 只验证 raw 为
固定 `{"scope_complete":true}` 与 metadata 为固定 issue；该 raw 不包含任何实施记录。随后 adapter 遍历
`self.p0_result.actions`，自行填写 `implementation_status="IMPLEMENTED"`、effective/confirmed 时间和 selector，
再交给 factory 和 source wrapper 签发。

一次性最小复现检查 raw 不含 `IMPLEMENTED`/`implementation_confirmed_at`，检查 P0 revision evidence 全部为
`ACTIVE`，然后调用 selector 与 public set verifier；实际仍签出两条实施事实：

```text
ACTIVE_DATE_ONLY_FIXTURE_SIGNED 2 {"scope_complete":true}
```

### 根因

source-neutral wrapper 的信任边界是 source adapter；但测试 adapter 没有履行“从 retained implementation
records fresh 解析并证明状态”的职责。当前测试把 P0 selected action 当成了 implementation evidence 的数据源，
导致测试绿色只证明 HMAC 包装自洽，不证明实施事实真实来自 retained source bytes。

### 被破坏的不变量

- `ACTIVE` 只表示 P0 PIT 修订链的选中版本，不表示已实施。
- 只有来源 retained records 明确给出的 status、confirmation、revision/correction/withdrawal 闭包才能投影
  `IMPLEMENTED`；日期或 P0 action 不能补造这些事实。
- capability boolean 是 preflight 条件，不是实施记录本身。

### 必须新增的测试

1. 正向 retained fixture 必须逐 event 含显式 implementation status、effective date、official confirmed time、
   stable source record/revision identity，以及 correction/withdrawal history；adapter 必须实际解析这些 bytes。
2. raw 只有 scope complete、P0 action 为 ACTIVE 且 ex/pay/list date 已过时，adapter/wrapper 必须拒绝，不得生成
   `IMPLEMENTED`。
3. retained status 为 `PENDING/ANNOUNCED/APPROVED`、缺失 status 或缺失 confirmation 时拒绝。
4. future confirmation 不能进入较早 as-of；future withdrawal 不得改写较早 as-of，但在 withdrawal 已对当前
   as-of 可知时必须按冻结语义拒绝/撤回，不能继续输出 IMPLEMENTED。
5. correction/withdrawal 缺失、重复、跨 event/revision/source 和 exact scope 缺/多均 fail closed。

### 通过条件

- 正向 adapter 不再从 P0 actions 或当前日期合成实施字段，所有输出字段均可追溯到 retained record selector。
- 上述反例进入正式单元测试，并在 Windows 与 WSL base 定向套件中通过。
- 新的独立复验能证明“删掉 retained implementation record 或把它改成非 IMPLEMENTED 后无法签发”。

## 5. 返工问题二：fresh preflight 接受被篡改的空 adapter version

### 现象

`HkCorporateActionImplementationCapability.__post_init__` 在初次构造时检查 source/version 非空，但
`_preflight` 只检查对象类型和 required booleans。先合法构造 capability，再执行：

```python
object.__setattr__(capability, "adapter_version", "")
```

随后调用 source wrapper，仍可签发新 projection；selector 与 public set verifier 均成功。实际输出：

```text
LOW_LEVEL_EMPTY_ADAPTER_VERSION_SIGNED '' 2
```

这不是旧 token whole-rehash；source wrapper 对已经失效的 capability 主动签发了一个新 token。

### 根因

实现把构造期 dataclass 校验误当成 fresh 消费校验。冻结 dataclass 可被低层修改，项目 P0/R2/R3 已明确要求
所有公开消费边界重验值对象，而不是只依赖 `__post_init__`。

### 被破坏的不变量

- source wrapper 只能为 fresh-valid、非空且类型严格的 source/version capability 签发 attestation。
- attestation payload 绑定一个值不等于该值满足合同；签名前必须先完整验证语义字段。

### 必须新增的测试

1. 分别低层篡改 `source`、`adapter_version` 为空、空白、非字符串，并在 factory、source wrapper、selector、
   public set verifier 边界验证稳定拒绝。
2. 低层篡改任一 required boolean 为 `False` 或非 `bool` 的既有检查继续保持。
3. 公开异常必须保持稳定 code、空 cause/context 和无 marker traceback。

### 通过条件

- `_preflight` fresh 重验 capability 的完整构造不变量，至少包括严格类型、trim 后非空 source/version 和全部
  required booleans；不得只依赖 `__post_init__`。
- 上述低层篡改不能到达 adapter 调用或 HMAC 签发，且正式回归在 Windows/WSL base 均通过。

## 6. 独立新增对抗结果

```text
LEGAL_VERSION_TOKEN_SWAP REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
LEGAL_P0_AND_IMPLEMENTATION_WHOLE_REHASH_OLD_TOKEN REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
LEGAL_SOURCE_TOKEN_SWAP REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
LEGAL_EVENT_SET_TOKEN_SWAP REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
HOSTILE_P0_VERIFIER REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
HOSTILE_ADAPTER_UNKNOWN REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
PROJECTION_PICKLE REJECTED TypeError
SET_PICKLE REJECTED TypeError
MODULE_RELOAD_OLD_CAPABILITY REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
ACTIVE_DATE_ONLY_FIXTURE_SIGNED 2 {"scope_complete":true}
LOW_LEVEL_EMPTY_ADAPTER_VERSION_SIGNED '' 2
```

所有 hostile 探针同时断言公开异常 `__cause__ is None`、`__context__ is None`，traceback 不含私有 marker。

## 7. Windows / WSL base 定向验证

| 环境 | 检查 | 实际结果 |
|---|---|---|
| Windows Miniforge | `pytest tests/unit/test_schemas.py tests/unit/test_hk_corporate_action_implementation.py tests/unit/test_hk_history_backfill.py` | `94 passed, 1 skipped` |
| Windows Miniforge | 改动文件 Ruff | `All checks passed!` |
| Windows Miniforge | 3 个生产文件 mypy | `Success: no issues found in 3 source files` |
| WSL Miniforge base `/mnt/f` | 同一三文件 pytest | `95 passed` |
| WSL Miniforge base `/mnt/f` | 同一改动文件 Ruff | `All checks passed!` |
| WSL Miniforge base `/mnt/f` | 同一 3 个生产文件 mypy | `Success: no issues found in 3 source files` |

Windows 的 1 个 skip 为平台相关既有差异；Pandera/Polars deprecation warnings 未形成断言失败。绿测不能覆盖
本报告两个新增语义反例。`/mnt/f` 是 DrvFS，不是 ext4。

## 8. 最终判定

- **实施事实子包：FAIL，返回实现 Agent 返工。**
- **HK bar capability：仍 blocked。** 其未实现符合冻结停止条件，不是实施事实子包失败原因。
- 返工后必须由未参与返工实现的全新独立上下文复验两个失败闭环、其余 token/异常/lifecycle 回归及双平台
  定向 Gate；初验通过后才能进入主 Agent 最终验收。
