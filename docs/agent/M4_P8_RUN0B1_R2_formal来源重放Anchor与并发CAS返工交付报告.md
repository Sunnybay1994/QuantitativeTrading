# M4-P8-RUN-0B1 R2：formal 来源、重放 Anchor 与并发 CAS 返工交付报告

日期：2026-08-09

角色：R1 原实现 Agent 返工

状态：R2 实现与自测完成，待全新上下文独立复验和主 Agent 终验

## 1. 三项 P1 闭环

### 1.1 B1 不再签发 formal policy

- public `build_paper_broker_policy_descriptor` 删除 `classification` caller 参数，只产生 exact
  `classification="development"` value；直接构造或替换成 `formal` 的 descriptor 不能初始化 store。
- `DurablePaperGateway`、`DurablePaperGatewayFactory`、`DurablePaperBrokerSnapshotPort` 均先要求
  `type(store) is PaperBrokerStore`，拒绝 subclass、duck/fake 和 caller 64hex；factory/snapshot 再执行 store fresh
  proof，并从真实 descriptor 重算 gateway identity。
- RUN-0B1 仍未提供 formal signer；future formal policy capability 保留给 RUN-0B2 版本化配置 loader。

### 1.2 immutable initial replay 与 broker-root sequence anchor

- immutable 初始账户固定保存在 `initial-account.json`。
- fresh DB verifier 从 initial snapshot 起，按 journal sequence 解码 command/cancel 和严格 callback ordinal，去重同一
  operation 的 duplicate callback，再用唯一 replay 函数重建账户；重建结果必须与 retained `account_state` exact
  相等。
- 新增 retained `order_state` canonical wire；fresh verifier从 canonical events重建 observations并与 retained
  orders exact 对比。snapshot evidence 的 account/orders/events/source/finality 在同一个 SQLite read transaction
  中取得。
- 每个 transition 在 `sequence-anchors/` 生成 20 位十进制 sequence 文件；canonical anchor 绑定 predecessor
  anchor digest、journal entry/state digest、subject、kind 和 store identity。文件 exclusive create，POSIX 额外
  dir-fsync，Windows/POSIX 均持有 no-delete/no-follow identity anchor。
- checkpoint 独立保存 `anchored_sequence`。DB commit 后 anchor create 前失败时，fresh open 只补
  `anchored_sequence + 1 .. sequence` 的唯一 committed trailing anchors；已确认 anchor 缺失、错误 bytes、跳号、
  多余 sequence 或 predecessor 不闭合均拒绝。exact retry不新增 anchor。
- journal entry 进一步绑定 transition 当时的 whole-state digest；协调修改 account/checkpoint/journal 仍被 initial
  replay 拒绝，协调 DB rehash 与已确认 external sequence anchor 不一致也 fail closed。

### 1.3 predecessor CAS 关闭并发丢失更新

- gateway 在一个一致读 snapshot 取得 `AccountSnapshot + predecessor_state_digest`，计算 transition 后把 predecessor
  一并提交。
- `persist_operation` 在 `BEGIN IMMEDIATE` 内重新 fresh 验证 DB，并在任何写入前 exact 比较 checkpoint
  state digest；不一致返回 `PAPER_BROKER_PREDECESSOR_STALE`，零写入。SQLite writer 竞争继续独立返回
  `PAPER_BROKER_BUSY`。
- 两个独立 store handle 使用 barrier 强制读取同一 predecessor：首次最多一个成功；另一个 busy/stale，恢复后
  retry基于新 predecessor重算。最终两个 command、四个 events、两个 orders、两个 positions 和两次现金影响均
  且仅出现一次，fresh replay/anchor闭合。

## 2. 新增对抗性验证

- public builder formal 参数不存在；直接 formal descriptor 初始化失败；
- factory/gateway/snapshot 拒绝 subclass、duck store 和伪造 policy identity；
- valid account + checkpoint + journal 协调 whole-rehash 被 replay 拒绝；
- anchor commit-gap 自动补锚且不重放 transport，已确认 anchor 删除、改 bytes、sequence jump 均拒绝；
- 两 writer 旧 predecessor barrier + retry 经济状态四方一致；
- R1 exact retry、UNKNOWN restart、duplicate、partial/cancel late fill、EOD、busy/crash、path/file identity 全部回归。

## 3. 实际验证

Windows 原生 Miniforge：

- 定向 pytest：`22 passed`；
- 两个生产文件与两个测试文件 Ruff：PASS；
- 两个生产文件 mypy：PASS。

WSL Miniforge base，当前 `/mnt/f`：

- 定向 pytest：`22 passed`；
- 同范围 Ruff：PASS；
- 两个生产文件 mypy：PASS；
- fresh process import：PASS。

当前仍是 WSL1/DrvFS，只是工程兼容验证，不是 WSL2/ext4 Gate。

## 4. 边界与未关闭项

- 未修改正式 root/journal、未注册任务、未启动 soak、未联网、未 add/commit；
- broker-root anchor 是同 root 独立 retained record，不冒充外部签名或不可攻破的外部 trust anchor；
- actual power-loss/ext4 durability、RUN-0B2 formal policy/risk/loader、RUN-0C/D runtime 装配和至少 28 天 soak
  仍未关闭；
- M4 状态继续 `WAITING_FOR_SOAK_EVIDENCE`，本报告只提交 R2 工程证据，不能自行宣布 Gate PASS。
