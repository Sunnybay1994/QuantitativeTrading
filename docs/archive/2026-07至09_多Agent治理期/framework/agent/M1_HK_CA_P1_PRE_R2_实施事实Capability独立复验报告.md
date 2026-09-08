# M1-HK-CA-P1-PRE R2：实施事实 Capability 独立复验报告

日期：2026-08-09  
角色：未参与 R2 返工实现的全新独立复验  
结论：**实施事实子包 FAIL，返回返工；HK bar capability 仍 blocked**  
边界：本结论不是正式 HK 数据、01065/HK60、复权、M1 或 ext4 Gate 结论

## 1. 独立性、范围与最终判定

- 只读核对了 P1-PRE 任务书 §13、R1 FAIL、R2 返工交付、实施事实生产代码、Schema 与实现测试。
- 生产代码和实现测试均未修改；只写本报告。未联网、未读取凭据、未访问正式 data/journal，未 add/commit。
- 独立补做了 retained only-scope、字段 strict parse、withdrawal 时间闭包、capability exact type、四个 fresh
  消费边界、合法新闭包旧 token 置换、hostile adapter/P0 verifier、pickle/reload 和 exact event set 探针。
- R1 的两个原始阻断大部已闭环：only-scope + P0 ACTIVE 不能签发，source/version 低层篡改会在所有 fresh
  边界拒绝。但是 R2 新增的 exact-type 规则没有实现，且 synthetic approved adapter 的 withdrawal retained
  parser 仍接受不规范或时间上不可知的撤回记录。因此实施事实子包仍为 **FAIL**，不得进入主验。
- HK bar capability 仍按 PRE-B 等待 receipt v3/availability 闭包；本轮未伪造 `bar_available_at`。它是正确的
  **blocked** 边界，不是本报告 FAIL 原因。

## 2. 标准—证据—结论

| 冻结标准 | 独立证据 | 结论 |
|---|---|---:|
| raw 只有 `scope_complete`，P0 全 ACTIVE 且日期已过也不能签发 | 完整 source wrapper 调用稳定返回 `HK_CA_IMPLEMENTATION_EVIDENCE_INVALID` | PASS |
| retained status/confirmed/event/revision/source record strict parse | status/confirmed/source-record/event/revision 缺失，错误 event/revision，空白 implementation source-record 均拒绝；PENDING/ANNOUNCED/APPROVED/COMPLETED_BY_DATE 与 future confirmation 正式测试通过 | PASS（implementation record） |
| withdrawal retained history strict、可知且 exact | query as-of 后但 bundle observed-at 前的 withdrawal 正确保留早期 implemented set；as-of 已知 withdrawal 正确拒绝。但空白 withdrawal `source_record_id`、晚于 bundle `source_observed_at` 的 withdrawal、完全重复 future withdrawal 均被完整签发 | **FAIL** |
| `_preflight` 与所有 fresh consumer 重验 capability exact type | `_preflight` 使用 `isinstance`；普通 Python 子类经 builder、source wrapper、selector、public verifier 全通过并签出 2 条 | **FAIL** |
| source/version 空、空白、整数、另一值在四个边界均拒绝 | 正式 8 组矩阵与独立复现均返回 `HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED`；wrapper preflight 失败前不调用 adapter | PASS |
| 另一合法 raw/P0/adapter version whole-rehash 后旧 token 不可复用 | 三个新闭包均先合法签发；移植旧 projection token 后均返回 `HK_CA_IMPLEMENTATION_VERIFY_FAILED` | PASS |
| construction attestation 不能由普通非 capability 对象伪造 | 复制相同字段和 attestation bytes 的普通 mimic 因类型检查拒绝；字段有任何变化时 content-bound digest 拒绝 | PASS（但 exact subclass 缺口见问题一） |
| hostile adapter/P0 verifier 稳定脱敏 | adapter 的 ValueError/RuntimeError 均映射为 `...EVIDENCE_INVALID`；hostile P0 映射为 `...VERIFY_FAILED`；cause/context 为空且 traceback 无 marker | PASS |
| pickle/reload/factory-only/exact event set fail closed | projection/set pickle 为 TypeError；reload 后旧 projection/capability 拒绝；event set 缺失/重复/额外分别稳定拒绝 | PASS |
| bar availability 不可证明时停止 | R2 未实现 bar capability，保持 PRE-B blocked | BLOCKED（正确边界） |

## 3. 阻断问题一：capability 子类通过了要求 exact type 的四个 fresh 边界

### 现象

任务书 §13.2 第 4 项明确要求 `_preflight` 及所有 fresh consumer 重验 capability **exact type**。实际
`src/quant/data/hk_corporate_action_implementation.py:682` 使用：

```python
isinstance(capability, HkCorporateActionImplementationCapability)
```

独立定义普通子类：

```python
class SubCapability(HkCorporateActionImplementationCapability):
    pass
```

用继承构造器生成 all-true、合法 source/version 的对象后，依次调用 parsed-only builder（通过 fixture
adapter）、`verify_hk_corporate_action_implementation_source`、selector 与 public set verifier，实际输出：

```text
NON_EXACT_CAPABILITY_SUBCLASS ACCEPTED SubCapability 2
```

普通非子类 mimic 即使复制相同字段与 attestation bytes 也会拒绝；合法 capability 的 source/version 发生任何
改变也会拒绝。因此问题不是 HMAC 未绑定字段，而是冻结的 exact-type 条件未实现。

### 根因

R2 把“必须是指定 class 的 exact 实例”实现成了“是该 class 或任意 subclass”。construction attestation
只绑定 source/version/required booleans，不绑定 exact runtime class；子类继承 `__post_init__` 后可获得合法
attestation。

### 应遵循规则与被破坏的不变量

- 任务书 §13.2：fresh consumer 必须重验 capability exact type，不能只做 `isinstance`。
- source wrapper 只允许冻结的窄 capability 值对象进入 adapter 与签发链，不能给未冻结 subclass 留行为覆盖面。
- construction attestation 证明内容未变，不替代 exact-type 验证。

### 最小复现、必须新增测试与通过条件

最小复现即上述无额外方法的普通 subclass。新增正式测试应在以下四处逐项断言
`HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED`：

1. parsed-only factory/builder；
2. source wrapper，且 adapter call count 不增加；
3. selector；
4. public set verifier。

通过条件：`_preflight` 对任意非 exact capability type fail closed；合法 exact capability 仍通过；既有
source/version 八组低层篡改矩阵保持通过。

## 4. 阻断问题二：withdrawal retained parser 未关闭 source-record、时间和重复闭包

### 现象

fixture adapter 在 `tests/unit/test_hk_corporate_action_implementation.py:268-292` 解析 withdrawal。当前只检查
`source_record_id` 是非空字符串，并只比较 `withdrawal_confirmed_at > query.as_of`；没有要求 trimmed
nonempty，没有要求 withdrawal confirmation 不晚于 retained bundle `source_observed_at`，也没有检查重复
withdrawal record/event identity。

独立探针均通过 source wrapper、selector 与 public verifier：

```text
WITHDRAWAL_AFTER_SOURCE_OBSERVED ACCEPTED 2
WITHDRAWAL_BLANK_SOURCE_RECORD ACCEPTED 2
WITHDRAWAL_DUPLICATE_RECORD ACCEPTED 2
```

其中第一例为 `withdrawal_confirmed_at=2027-01-01T00:00:00Z`、bundle
`source_observed_at=2026-08-01T12:00:00Z`；第二例 `source_record_id=" "`；第三例将同一 future withdrawal
原样放入两次。它们仍可让 `withdrawal_history_complete=True` 的 adapter 签发 exact implemented set。

对照结果正确：

```text
WITHDRAWAL_FUTURE_ASOF_KNOWN_BY_OBSERVED ACCEPTED 2
WITHDRAWAL_KNOWN_ASOF REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
```

即 query as-of 后、但 retained observation 前已知的 future withdrawal 不改写较早 as-of；截至 as-of 已知的
withdrawal 则 fail closed。失败只在 retained withdrawal 自身 strict/time/exact closure。

### 根因

R2 strict parser 对 implementation record 复用了后续 evidence validator 的 `_nonempty`、observed/confirmed
约束和 exact event set，但 withdrawal 是解析后即丢弃的旁路历史；它没有对应 canonical row validator，也没有
维护 withdrawal record/event 的 seen set。因此不规范或 observation 时点尚不可知的 withdrawal 仍被当成
“完整撤回历史”。

### 应遵循规则与被破坏的不变量

- §13.2 要求 retained bytes strict parse，并明确包含必要 withdrawal scope 与 source record identity。
- source retained bundle 不能在其 `source_observed_at` 之前证明一个更晚才确认的 withdrawal。
- 声明 `withdrawal_history_complete=True` 时，空白身份或完全重复的 record 不能静默归一为有效完整历史。
- future withdrawal 只可指 `query.as_of < confirmed_at <= source_observed_at` 的已观察后续事实；已知 withdrawal
  必须撤回当前 implemented 输出。

### 最小复现、必须新增测试与通过条件

将现有 `_retained_withdrawal` 分别改为上述三个 payload 即可复现。新增测试至少覆盖：

1. withdrawal `source_record_id` 为空、空白、前后带空白、非法类型；
2. `withdrawal_confirmed_at > bundle.source_observed_at`；
3. 完全重复 withdrawal record，以及任务冻结的 event/source/revision/source-record 唯一性；
4. 保持“较晚 as-of 才知道的 withdrawal 不改写较早 as-of、截至 as-of 已知则拒绝”的既有正反例。

通过条件：三类反例均在 factory/source wrapper 签发前稳定 fail closed，公开异常 cause/context 为空且无 payload
泄漏；合法 future/known withdrawal 语义保持不变。

## 5. 其余独立对抗证据

```text
ONLY_SCOPE_ACTIVE REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
SOURCE_VERSION_FOUR_BOUNDARIES REJECTED
LEGAL_RAW_WHOLE_REHASH_OLD_TOKEN REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
LEGAL_ADAPTER_VERSION_OLD_TOKEN REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
LEGAL_P0_WHOLE_REHASH_OLD_TOKEN REJECTED HK_CA_IMPLEMENTATION_VERIFY_FAILED
EXACT_SET_MISSING REJECTED HK_CA_IMPLEMENTATION_SCOPE_INVALID
EXACT_SET_DUPLICATE REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
EXACT_SET_EXTRA REJECTED HK_CA_IMPLEMENTATION_SCOPE_INVALID
HOSTILE_ADAPTER_ValueError HK_CA_IMPLEMENTATION_EVIDENCE_INVALID CLEAN True
HOSTILE_ADAPTER_RuntimeError HK_CA_IMPLEMENTATION_EVIDENCE_INVALID CLEAN True
HOSTILE_P0 HK_CA_IMPLEMENTATION_VERIFY_FAILED CLEAN True
PROJECTION_PICKLE REJECTED TypeError
SET_PICKLE REJECTED TypeError
RELOAD_OLD_PROJECTION REJECTED HK_CA_IMPLEMENTATION_EVIDENCE_INVALID
RELOAD_OLD_CAPABILITY REJECTED HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED
```

同进程 exact-content capability clone 或 capability value-object pickle 会保持相同 source/version/booleans 与
attestation；独立探针未发现它们能绕过另一 raw/query/P0/result 的 semantic verifier，且 reload 后失效。按
§4.2/§13 的 content-bound 而非 instance-bound 合同，这一观察不单独判失败。projection 与 verified set 仍
不可 pickle，旧 projection token 仍不能移植到任何合法新闭包。

## 6. Windows / WSL base 定向验证

| 环境 | 检查 | 实际结果 |
|---|---|---|
| Windows Miniforge | 原定向三文件 pytest，禁用项目内 cache | `116 passed, 1 skipped` |
| Windows Miniforge | 原改动生产/测试文件 Ruff `--no-cache` | `All checks passed!` |
| Windows Miniforge | 3 个生产文件 mypy `--no-incremental` | `Success: no issues found in 3 source files` |
| WSL Miniforge base `/mnt/f` | 同一三文件 pytest | `117 passed` |
| WSL Miniforge base `/mnt/f` | 同一文件 Ruff | `All checks passed!` |
| WSL Miniforge base `/mnt/f` | 同一 3 个生产文件 mypy | `Success: no issues found in 3 source files` |

Windows 的一个 skip 为既有平台差异；Pandera/Polars deprecation warnings 未形成断言失败。当前工作树在
`/mnt/f` DrvFS，不是 ext4；这些绿测只证明双平台定向反馈，而且未覆盖本报告两个新增反例。

## 7. 最终结论

- **实施事实子包：FAIL，返回实现 Agent 返工。**
- 返工必须按“现象—根因—规则—最小复现—新增测试—通过条件”关闭 exact capability type 与 withdrawal
  retained closure，再由未参与实现的另一全新上下文复验。
- **HK bar capability：仍 blocked，且不因此 FAIL。**
- 即使后续复验通过，也只表示来源无关实施事实开发合同成立；不表示存在真实 licensed implementation
  adapter，不关闭 01065/HK60、gross total-return、复权、M1 或 ext4 Gate。
