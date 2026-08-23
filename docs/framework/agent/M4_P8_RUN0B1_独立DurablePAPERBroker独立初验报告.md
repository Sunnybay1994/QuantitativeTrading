# M4-P8-RUN-0B1：独立 Durable PAPER Broker 独立初验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**FAIL**

## 1. 验收范围与边界

本次依据 `M4_P8_RUN0B1_独立DurablePAPERBroker任务单.md`，只读核对实现、实现测试、RUN-0A R3 主验边界及
现有 `PaperGatewayFactory`、`BrokerSnapshotPort`、gateway contracts。除本报告外未修改生产代码或实现测试；
未创建正式 PAPER root，未注册或启动 soak，未联网。

双平台实现者测试全部绿色，但新增对抗稳定复现三项高风险合同破坏，故 RUN-0B1 尚不具备进入主验的条件。

## 2. 阻塞问题

### F1：caller 可自行签发任意 formal policy 与 gateway identity

- **现象**：`build_paper_broker_policy_descriptor(..., classification="formal")` 接受任意 `example-*` 版本并直接
  返回 formal descriptor；`DurablePaperGatewayFactory` 不要求 exact `PaperBrokerStore`，只读取鸭子对象的
  `policy_identity`、`gateway_identity` 和 `verify_fresh()`。独立探针用 fake store 成功让 `identity()` 和
  `open().gateway_identity` 返回 caller 指定的 `"a" * 64`，并生成 `VerifiedPaperGateway`。
- **根因**：development descriptor builder 同时承担 formal capability 签发；factory 构造器只做结构性调用，
  没有绑定 fresh、exact、包内签发的 store/account/policy proof。
- **违反规则**：任务单 §6.1 要求 factory identity fresh 验证 store/account/policy descriptor，且 caller 不能用
  任意 64hex 自报；§7 明确 formal policy 必须由 RUN-0B2 版本化 loader 产生，unknown/example/development policy
  不能标为 formal。
- **最小复现**：构造 `classification="formal"` 的 `example-*` policy，再传入仅实现三个同名属性/方法的
  `FakeStore`；当前 factory 成功返回 caller 指定 gateway identity。输出：
  `ADVERSARIAL_FORMAL_AND_GATEWAY_SELF_MINT_REPRODUCED`。
- **应新增测试**：任意 formal classification、exact/subclass/fake store、复制或 dataclass clone、任意 64hex
  gateway identity 均必须在 capability 构造前 fail closed；development 路径只能得到明确不同且不可用于 formal
  runtime 的类型或身份。
- **通过条件**：RUN-0B1 公共 builder 只产生 development policy；formal policy 留给 RUN-0B2 唯一 fresh loader
  路径。factory 必须绑定 exact verified store proof，caller-provided duck object 不得签发 verified gateway。

### F2：账户 whole-state rehash 可绕过 fresh verify，broker evidence 不重放闭合

- **现象**：在空 broker store 中把 `account_state` 从 100000 CNY 改为 canonical 99999 CNY，再使用实现自身
  `_state_digest(conn)` 重算并更新 checkpoint；`store.verify_fresh()` 与后续 `read_state()` 均通过，且接受了没有
  任何 broker operation/event 支撑的资金变化。
- **根因**：checkpoint 是 DB 内可重算的无外部锚 hash；`_verify_database()` 只比较当前 mutable rows 的重算摘要，
  没有从 initial account + canonical terminal callbacks 重放出唯一账户状态，也没有不可由 DB 修改者同步重写的
  retained anchor。因此合法 canonical 替换并重算摘要即可通过。
- **违反规则**：任务单 §3.5、§5.2、§6.3 与必测反例 9 要求 account/event/journal/checkpoint 任一改动及
  whole-rehash fail closed，并要求账户、事件和 broker evidence 闭合。
- **最小复现**：只更新 `account_state.payload` 与 `checkpoint.state_digest`，不新增 operation、event 或 journal；
  当前输出 `ADVERSARIAL_WHOLE_STATE_REHASH_ACCEPTED`。
- **应新增测试**：initial snapshot 无事件资金变化、合法 canonical account replacement、operation/event/account
  全体协调改写与 whole-rehash 都必须失败；fresh evidence 必须逐事件重放并与 retained account bytes exact 相等。
- **通过条件**：验证器从不可变 initial snapshot 和严格有序 callback 重放账户及订单终态，并绑定能够发现
  whole-rehash 的独立 retained anchor；上述合法闭包替换不再通过。

### F3：账户计算发生在写事务外，两个 writer 可提交陈旧快照并丢失更新

- **现象**：`DurablePaperGateway._submit()` 先调用 ephemeral policy，再通过 `store.read_state()` 在只读事务中
  计算新账户，最后才进入 `persist_operation()` 的 `BEGIN IMMEDIATE`。独立探针让两个不同证券 submit 同时读取
  同一初始账户，再按顺序完成两个合法 SQLite 写事务。最终 broker evidence 含 2 个 order，却仅有 1 个持仓，
  且 fresh verify 仍通过。
- **根因**：写锁不覆盖 predecessor state 的读取和 account/callback state transition；`persist_operation()`
  信任 caller 传入的完整 account，没有 predecessor checkpoint/CAS，也不在锁内重放 callbacks。
- **违反规则**：任务单 §5.2 要求 state + journal + checkpoint 原子事务，§6.1 要求 operation fence、callbacks、
  broker state 与 transaction 先持久化，§6.2 要求 crash/retry 不二次或漏记账。
- **最小复现**：两个 submit 在 barrier 后分别持有同一旧快照；第一个 commit 完成后第二个用旧快照串行 commit。
  当前输出 `ADVERSARIAL_CONCURRENT_LOST_UPDATE_ACCEPTED 2 1`。
- **应新增测试**：两个独立 store handle/process 对不同 command 并发 submit；允许一个返回 BUSY，但 exact retry
  必须基于 fresh predecessor 重算。最终事件、订单、持仓和现金必须同时包含两次且仅一次影响。
- **通过条件**：在同一 `BEGIN IMMEDIATE` 内 fresh 读取 predecessor、验证 operation fence、计算/重放
  callbacks 和账户并提交；或使用绑定 checkpoint/source identity 的严格 CAS，漂移时只返回 retry/busy 而不提交
  陈旧状态。

## 3. 通过的合同与对抗

- 现有测试覆盖并通过 root/OMS 路径分离、完整 root 复制拒绝、DB replacement、descriptor/checkpoint tamper、
  exact retry、UNKNOWN restart 不重发、duplicate callback 只记账一次、partial fill、cancel late fill/final cancel、
  writer busy、pre-commit rollback、post-commit lost return 与 fresh broker evidence。
- 新增多 session 对抗通过：session1 显式 EOD 后，session2 首次 operation 使 evidence 回到 `INTRADAY`，
  session2 terminal finalize 后恢复 `END_OF_DAY`；输出 `ADVERSARIAL_MULTI_SESSION_FINALITY_PASS`。
- WSL fresh process 导入 `quant.execution.gateways.paper_durable` 通过，无循环导入。
- 白名单状态符合交付报告；`gateways/__init__.py` 未改，`git diff --check` 通过。

这些通过项不抵消 F1-F3；尤其现有测试未覆盖 caller capability 自签、可重算 whole-state replacement 和事务外
陈旧状态交错。

## 4. 验证命令与结果

Windows 原生 Miniforge（`PYTHONPATH=src`）：

- `pytest tests/unit/test_paper_broker_store.py tests/unit/test_paper_durable_gateway.py -q`：`16 passed`；
- `ruff check` 两个生产文件和两个测试文件：PASS；
- `mypy` 两个生产文件：PASS；
- 三组临时目录独立探针：F1、F2、F3 均复现；multi-session finality PASS。

WSL Miniforge base，当前 `/mnt/f`：

- 同组 pytest：`16 passed`；
- 同范围 Ruff：PASS；
- 两个生产文件 mypy：PASS；
- fresh process import：PASS。

当前 WSL 仍是 WSL1/DrvFS。本报告仅裁定 RUN-0B1 工程合同；不构成真实 WSL2/ext4 durability Gate，不表示
formal runner、Task Scheduler 或 28 天 soak 已启动，也不改变 `WAITING_FOR_SOAK_EVIDENCE`。

## 5. 返工结论

实现者需按 F1-F3 形成同一轮最小返工，并为每项加入上述独立反例的正式回归测试。返工完成后必须由未参与
返工实现的新上下文重新独立初验；在复验 PASS 与主 Agent 终验前，RUN-0B1 不解锁 formal RUN-0C/D 装配。
