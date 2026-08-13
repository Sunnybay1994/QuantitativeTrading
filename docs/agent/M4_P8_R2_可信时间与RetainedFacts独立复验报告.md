# M4 P8 R2：可信时间与 Retained Facts 独立复验报告

日期：2026-08-09  
角色：未参与 R2 实现的全新独立初验 Agent  
结论：**FAIL**

## 结论摘要

R2 已正确关闭回溯 wall-clock、未来 `as_of`、不同物理 root 复制、损坏 wire、sidecar 集合漂移和 hostile
decoder 异常链泄漏；现有 P8 与 P5-P8 回归、Ruff、mypy 也均通过。但是 retained facts 仍只有一组可由调用者
整体重算的自哈希，没有一个在首次 append 时独立留存且后续 verifier 必须核对的不可重算锚。

独立反例把原 session 的完整 retained closure 替换成另一份**语义合法且内部完全一致**的
`RecoveryResult + ReconciliationResult + ExecutionReport`，再同步重算 receipt 全链字段。磁盘
`verify_soak_evidence` 接受了替换后的证据：

```text
WHOLE_VALID_CLOSURE_SUBSTITUTION_ACCEPTED True
ORIGINAL_RECOVERY d08244f3745e48b26d0f30321750eeb182f724028b84e9ec1bffc34a3ae97f9a
SUBSTITUTED_RECOVERY f3b1e5b994ea5cd5945366774c7e49cf95d435e7cc4a170f36fdf1e5cdce2d29
```

这直接违反 R2 冻结通过条件“receipt + facts 一起 whole-rehash 必须 fail closed”，故本轮不得进入主验，
也不得注册正式 28 日 runner。

## P1 阻断：语义合法的 retained closure 可整体替换并通过 verifier

### 现象与最小复现

1. 在原 development run 的同一 session 先 append 一份空状态的合法 P5/P7 closure。
2. 在另一根目录生成一份包含 command、event、ledger checkpoint、risk/report 的合法 filled closure。
3. 用第二份 session 的 canonical `facts.json` 整体替换第一份 facts。
4. 保持第一份 manifest、root、session 日期与 invocation 时间不变；把 receipt 的
   `recovery_id`、`reconciliation_id`、`execution_report_id`、command/event 摘要、ledger state、Gate/issue、
   `facts_sha256` 替换为第二份 closure 的值。
5. 按第一份 manifest 的 runtime identities 重新计算 `invocation_identity` 和 `receipt_id`。
6. 调用公开 `verify_soak_evidence(root=原root, manifest=原manifest)`。

实际结果是 verified session 精确等于伪造后的 receipt。替换前后 recovery identity 不同，且第二份 retained
command/event/ledger/report 全部与首次 append 的事实不同。

### 根因

`_decode_recovery_facts` 构造 `RecoveryResult`、`_decode_reconciliation_facts` 构造
`ReconciliationResult` 时，P5 dataclass 的 `__post_init__` 确实会重新计算 public identity；因此“只改
`recovery_id` 再同步改下游”的较弱攻击会被拒绝。当前缺口不是漏算单个 identity，而是：

- verifier 只证明当前 `facts.json` 内的 P5/P7 closure 彼此语义一致；
- receipt 的 facts digest、业务 identity、invocation identity 和 receipt identity 全是无密钥自哈希；
- manifest/root identity 没有绑定首次 append 的 session/fault retained closure；
- 换入另一份完整合法 closure 后，所有 identity 都可按公开 canonical 规则得到一套新的自洽值。

现有 `test_facts_only_and_receipt_plus_facts_whole_rehash_fail_closed` 只把 `recovery_id` 改成与原 wire 不一致的
任意值；`test_retained_semantic_wire_drift_fails_after_whole_rehash` 只制造 event link、ledger entry id 或 report
totals 的语义损坏。它们都没有覆盖“另一份语义合法 closure + 全链 identity 重算”。

### 应遵循规则、必须新增测试与通过条件

首次 append 必须在 receipt/facts 可重算集合之外留下一个 verifier fresh 核对的 root-scoped append-only
anchor，至少绑定 `run_id + session/fault key + facts digest + receipt digest`；Gate decision 也必须 fresh 核对该
anchor。若本地无密钥模型不能满足冻结的 whole-rehash 威胁模型，应由主 Agent 先重新冻结可信 journal、OS
protected anchor、HMAC/签名或可信时间戳边界，不能继续把一组自哈希表述为来源证明。

新增回归必须复用两份由公开 P5/P7 builder 生成的合法但不同 closure，按上述步骤完整替换并重算所有下游
identity；`verify_soak_evidence` 必须稳定返回 `SOAK_EVIDENCE_INVALID`，异常 cause/context 为空。

## 次要结构风险：Gate decision 使用陈旧 verified 对象，不 fresh 读取磁盘

独立 TOCTOU 探针在 `verify_soak_evidence` 返回后把 `facts.json` 改成 `{}`。fresh verify 正确拒绝，但把先前
verified 对象直接传给 `decide_soak_gate` 仍得到：

```text
DECISION_AFTER_DISK_TAMPER WAITING_FOR_SOAK_EVIDENCE
FRESH_VERIFY_REJECT True
```

development 类型仍被强制 WAITING，因此该探针没有构造 development PASS；但同一调用形态意味着一份未来
已经满足 28 日的 formal verified 对象可在落盘证据随后漂移时继续参与 PASS 判定。返工应让 decision 对显式
root fresh 复验 manifest、sidecar 与 anchor，或把 verified capability 冻结成不可脱离 store snapshot 的窄接口。

## 已通过的对抗项

- formal wall-clock：五分钟整边界接受；旧 `5 分钟 + 1 微秒`、未来 `1 微秒` 均拒绝；时钟推进 29 日后旧
  append 与旧 decision `as_of` 分别稳定返回 `SOAK_SESSION_INVALID`、`SOAK_GATE_INPUT_INVALID`；未来
  decision `as_of` 拒绝。所有公开异常 cause/context 为空。
- root：完整目录复制到不同绝对 root 的现有测试拒绝；Windows `normcase` 大小写别名按合同接受；相对 root
  稳定拒绝。Windows 大小写别名不代表 WSL/Linux 同一物理 run。
- retained codec：command/event link、ledger wire、report totals/identity 的损坏 whole-rehash 均 fail closed；
  session/fault sidecar 的删除、新增、交换以及 unknown entry 均拒绝。
- hostile decoder：注入 `TOKEN C:/secret BROKER_MARKER` 的异常后公开结果仅为
  `SOAK_EVIDENCE_INVALID`，marker 不可见，cause/context 均为 `None`。
- development：现有 29 日完整 session 证据仍为 `WAITING_FOR_SOAK_EVIDENCE`；exact development verified
  类型分支无 PASS 路径。此项不抵消合法 closure 整体替换缺口。

## 验证命令与结果

Windows 原生 Miniforge：

```text
pytest test_execution_soak.py
25 passed in 6.54s

pytest test_reconcile.py test_execution_report.py test_execution_cli.py
       test_execution_service.py test_execution_store.py test_execution_wire.py
       test_execution_soak.py test_pretrade_risk.py
389 passed, 5 skipped in 18.10s

ruff check soak.py execution/__init__.py test_execution_soak.py
All checks passed!

mypy soak.py execution/__init__.py
Success: no issues found in 2 source files
```

WSL Miniforge base、`/mnt/f`：

```text
P8: 25 passed in 3.96s
P5-P8 合流: 393 passed, 1 skipped in 13.98s
Ruff: All checks passed!
mypy: Success: no issues found in 2 source files
findmnt: /mnt/f -> F:\, drvfs, case=off
```

WSL 结果只证明 base 解释器加 DrvFS 的开发兼容性，不是 ext4/Linux 正式 Gate。本轮没有启动 formal soak、
没有网络/broker 调用，也没有触碰正式 artifacts 或 journal；除本报告外保持生产代码与实现测试只读。

## 最终判定

**FAIL**。R2 的可信时间、物理 root 与 strict codec 改进有效，但语义合法的 retained closure 仍可整体替换并
通过磁盘 verifier，且 Gate decision 存在 verified 后磁盘漂移的陈旧读取窗口。状态必须回到“R3 返工实现 ->
全新独立复验”；正式 M4 四周 Gate 继续为 `WAITING_FOR_SOAK_EVIDENCE`。
