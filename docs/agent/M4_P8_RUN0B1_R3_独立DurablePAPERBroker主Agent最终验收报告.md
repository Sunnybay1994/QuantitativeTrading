# M4-P8-RUN-0B1 R3：独立 Durable PAPER Broker 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（仅 development broker 工程合同）**

## 1. 验收范围

本次主验依据 RUN-0B1 任务单 §13–§14、R1/R2 独立失败报告、R2/R3 交付与全新独立复验，验收独立
SQLite PAPER broker 的账户/策略/store 身份、root/DB 物理锚、operation journal、initial replay、append sequence
anchor、并发 predecessor CAS、UNKNOWN/restart、broker evidence、multi-session EOD finality 与解释器 teardown。

本结论不签发 formal policy，不建立正式 runtime，不注册或启动 soak。

## 2. 主验结论

- RUN-0B1 public policy builder 只产生 exact development value；formal policy 留给 RUN-0B2 版本化 loader，
  caller、duck/fake/subclass store 或任意 64hex 不能生成 gateway capability；
- broker store 与 OMS store 物理分离，descriptor绑定 root/DB/account/policy/store identity和instance nonce；Windows
  no-share-delete handle、POSIX no-follow fd 对 root/DB 做 fresh identity proof；
- immutable initial account 与按 sequence 排序的 canonical callbacks 是账户/订单 SSOT；fresh verifier重放并与
  retained account/order/event exact 对比，关闭 mutable account+checkpoint whole-rehash；
- broker root 下20位 sequence append anchors绑定 predecessor、operation、journal/state与store identity；exact retry
  不增第二anchor，DB commit后anchor前崩溃只允许对唯一已提交transition补同一anchor；
- predecessor state digest在 `BEGIN IMMEDIATE` 内CAS。两个writer读取同一旧前驱时最多一个首次提交，另一个
  retry/busy；基于fresh predecessor重试后两个经济影响各且仅一次；
- UNKNOWN跨restart保留且不重发；partial fill、duplicate callback、cancel late fill、final cancel与multi-session
  EOD finality闭合，broker evidence不读取OMS；
- `__del__` 是destructor-only best-effort且不会向stderr/unraisable泄露；显式 `close()` 仍遍历全部handle并把
  failure稳定映射为 `PAPER_BROKER_CLOSE_FAILED`，cause/context均None。

因此 RUN-0B1 development durable broker 工程合同完成，可进入 RUN-0B2 的 formal policy、durable risk 与生产
loader 前置设计；不得把development store/gateway直接装入formal runtime。

## 3. 验证证据

实现与独立复验：

- Windows：`25 passed`，Ruff、mypy、fresh import PASS；
- WSL base：`25 passed`，Ruff、mypy、fresh import PASS；
- 独立新增 module globals/`ctypes`/import/`sys`/`os` teardown、底层close `BaseException`、unraisablehook、
  legal whole-closure replacement、anchor swap、双store CAS与同事务 source/finality 对抗均通过。

主 Agent Windows复核：

- 两个定向测试文件：`25 passed`；
- Ruff：两个生产文件和两个测试文件 PASS；
- mypy `--no-incremental`：两个生产文件 PASS。

## 4. 尚未关闭

- RUN-0B2 formal policy/config loader、durable RiskDecision recovery、production target/market/planning loaders与
  LedgerContext/Service装配；
- RUN-0C verified schedule、RUN-0D runner、正式runtime manifest和注册流程；
- actual WSL2/ext4 durability Gate；当前 `/mnt/f` 证据为 WSL1 文件系统开发兼容验证；
- 不少于28个自然日的正式 PAPER soak与故障演练。

项目 M4 状态继续为 `WAITING_FOR_SOAK_EVIDENCE`。
