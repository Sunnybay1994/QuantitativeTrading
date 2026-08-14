# M1-HK-CA-P1-PRE R3：Exact Capability 与 Withdrawal 因果闭包返工交付报告

日期：2026-08-09  
状态：**R3 已交付，待全新独立上下文复验；不自行宣布开发合同或任何 Gate 通过**

## 1. 返工结果

本轮只关闭 R2 独立复验的两个阻断：

1. production `_preflight` 由 `isinstance` 收紧为 exact runtime type；普通 capability 子类在 builder、source
   wrapper、selector 和 public set verifier 四个 fresh 边界均 fail closed。source wrapper 在 preflight 失败时
   不调用 adapter。
2. synthetic retained parser 对 withdrawal 的所有 required text 做严格 `str`、trim 后非空且原值无首尾空白
   检查；confirmation 必须 aware UTC 且不晚于 bundle `source_observed_at`；source-record identity、业务键和
   canonical order 都必须唯一确定。
3. withdrawal 采用两阶段处理：先遍历并完整验证全部 future/known records 的结构、UTC、observation causality、
   exact P0 link、唯一性与排序，再按 query `as_of` 判断是否撤回当前 implemented scope。不会因第一条已知撤回
   或“future 不影响当前选择”而跳过后续 retained record 验证。
4. exact-type 并未变成 instance-unique：同进程 exact-content capability clone 保留相同 construction
   attestation，仍可被 projection/set fresh verifier 正常消费。projection/set 不可 pickle、reload fail closed、
   R1/R2 HMAC 与 whole-rehash 行为保持。

HK bar capability/history 仍未实现或修改。

## 2. FAIL 闭环

### 2.1 Capability 子类

- 现象：普通无额外方法的 subclass 可经四个 fresh 边界签出两条 implemented actions。
- 根因：`isinstance` 接受 subclass，construction attestation 只绑定内容、不负责 exact runtime class。
- 修复：`type(capability) is HkCorporateActionImplementationCapability`，其后才校验 source/version、construction
  HMAC 和全部 required booleans。
- 测试：同一 subclass 分别进入 builder、wrapper、selector、public verifier，四处均返回
  `HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED`；wrapper adapter call count 为零。对照 exact-content
  `copy()` capability 仍通过 selector 与 public verifier。

### 2.2 Withdrawal retained 旁路

- 现象：空白 source record、晚于 bundle observation 的 confirmation、完全重复 future withdrawal 均可签发。
- 根因：withdrawal 解析后不进入 evidence schema，R2 没有给该旁路历史建立完整的 strict/time/unique 验证。
- 修复：
  - `event_id/source/source_event_id/source_revision_id/withdrawal_confirmed_at/source_record_id` 全部 strict text；
  - confirmation aware UTC 且 `<= bundle.source_observed_at`；
  - `(source, source_record_id)` 和 `(source, source_event_id, source_revision_id)` 分别作为 retained record 与本
    fixture 支持的 withdrawal 业务唯一键；完全重复及不同 payload 重复均拒绝；
  - records 必须按 `(source, event, revision, confirmed_at, source_record_id)` canonical 排序；
  - 全部验证完成后才应用 query as-of。
- 测试：空、全空白、首尾空白、非字符串 source record；observation 之后 confirmation；完全重复；同业务键
  不同 source record/time；反向顺序均拒绝。合法两个不同 event 的 canonical future withdrawals 保持早期
  implemented set；known withdrawal 仍 fail closed。

本 fixture 对每个 P0 event/revision 只支持一个 canonical withdrawal record；没有声称支持真实来源的多次撤回/
更正格式。未来来源若支持多 revision，必须另行冻结 revision chain 和严格时间序。

## 3. 修改范围

- `src/quant/data/hk_corporate_action_implementation.py`：capability exact-type fresh preflight。
- `tests/unit/test_hk_corporate_action_implementation.py`：withdrawal strict/time/unique/two-pass parser 与 R3 对抗矩阵。
- 本报告。

没有修改 schema、domain export、connector、`hk_history_backfill.py`、HK60/U0C/G1、正式 data/artifacts/journal、
`data/legacy`、依赖或 enums。未联网、未读取凭据、未 add/commit；worktree 其他既有脏文件原样保留。

## 4. 验证结果

Windows 原生 Miniforge：

```text
test_hk_corporate_action_implementation.py
47 passed

test_schemas.py + test_hk_corporate_action_implementation.py + test_hk_history_backfill.py
124 passed, 1 skipped in 41.69s

Ruff（改动生产与测试文件）
All checks passed!

mypy（schemas.py、domain/__init__.py、hk_corporate_action_implementation.py）
Success: no issues found in 3 source files
```

WSL Miniforge `base`，同一 `/mnt/f` worktree：

```text
同一三文件 pytest
125 passed in 38.97s

同一文件 Ruff
All checks passed!

同一 3 个生产文件 mypy
Success: no issues found in 3 source files
```

Windows 一个 skip 为既有平台差异；Pandera/Polars deprecation warnings 未形成断言失败。`/mnt/f` 是 DrvFS，
不是 ext4；这些结果只证明双平台开发合同反馈。

## 5. 保持的边界

- R2 only-scope、status/future confirmation、source/version 八组四边界、raw/P0 whole-rehash、factory-only、
  projection/set pickle 与 hostile exception 脱敏回归继续通过。
- Construction/projection/set attestation 都是进程内 content-bound 防替换机制，不是外部数字签名或 WORM。
- HK bar capability 继续等待 PRE-B receipt v3 和 HKEX canonical observed-at；本轮不生成或推断
  `bar_available_at`。
- 真实 licensed implementation source、01065/HK60、gross total-return、复权、M1 与 ext4 Gate 均未验证。
- 下一步必须由未参与 R3 实现的全新独立上下文复验 §14 全部反例，再由主 Agent 裁定。
