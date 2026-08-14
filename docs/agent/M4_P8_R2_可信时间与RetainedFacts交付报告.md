# M4 P8 R2：可信时间与 Retained Facts 交付报告

日期：2026-08-09  
状态：返工实现与自测完成；`WAITING_FOR_SOAK_EVIDENCE`；等待全新独立复验

## 返工结果

R2 关闭了 R1 独立复验提出的三条正式证据旁路：

- 正式 `PAPER_REAL_TIME` 的 build `started_at`、session/fault `completed_at` 和 Gate `as_of` 均由模块内私有
  UTC wall-clock 核对，只接受调用时过去五分钟内且不晚于当前时钟的值；正式公共接口没有 clock 注入点。
- manifest 新增 `root_identity`，以平台规则规范化实际绝对 root 后只保存不可逆 SHA-256，并把它绑定进
  `run_id`；append、verify 和 decision 都重新核对实际传入 root。完整目录复制到其他绝对 root 后稳定拒绝。
- session 改为 `sessions/<date>/{receipt.json,facts.json}`；fault 改为
  `faults/<drill>/{receipt.json,before_facts.json,after_facts.json}`。receipt 增加 facts digest；所有 sidecar
  保持 exclusive/no-clobber，相同 bytes 重试幂等、异 bytes 冲突，磁盘 verifier 要求精确目录与文件集合。

## Retained facts 闭包

P8 内新增窄、versioned、strict canonical JSON codec，没有 pickle、动态 import、任意 Mapping 或通用反序列化：

- recovery 保留 command/event/order aggregate/cancel 的原始公共 wire bytes，order/cancel delivery 全状态，
  cancel-event link，ledger entry/context/checkpoint canonical bytes，disposition 与 issue facts；
- reconciliation 保留稳定 identity、UTC `as_of`、disposition、Gate 与 difference facts；
- P7 report 保留 `encode_execution_report` 的完整 canonical bytes；磁盘验收重建 exact `ExecutionReport`，由其
  公共 dataclass 合同重新验证字段、排序、totals、Gate 与 report identity；
- fault before/after facts 各自重建 exact `RecoveryResult`，再重算经济影响集合、outcome、stable code 与 receipt。

因此磁盘 verifier 不信任 receipt 自报的 recovery/reconciliation/report id、command/event/ledger 摘要或 fault
结果。上游 decode/identity/link 异常都在 P8 边界换译为稳定错误码，并切断 cause/context。

## 对抗性测试

新增或强化以下反例，均 fail closed：

- 单进程用回溯 29 日时间创建正式 run；
- 完整 canonical run 复制到另一个绝对 root；
- receipt-only、facts-only、receipt 与 facts 同步 whole-rehash；
- session/fault sidecar 分别删除、增加、交换；
- event-command link、ledger wire、P7 report totals/identity 同步重哈希漂移；
- 完整订单、成交、账本 session 与 fault before/after 从磁盘 retained facts 重建；
- development 跨 29 日仍只返回 `WAITING_FOR_SOAK_EVIDENCE`。

## 验证证据

Windows 原生 Miniforge：

- P8 定向 pytest：`25 passed`；
- P5-P8 合流 pytest：`495 passed, 5 skipped`；
- 定向 Ruff：`All checks passed!`；
- 定向 mypy：`Success: no issues found in 2 source files`。

WSL Miniforge base、`/mnt/f`：

- P5-P8 同范围合流 pytest：`500 passed`；
- 定向 Ruff 与 mypy 均通过；
- `findmnt` 确认工作树为 `drvfs`。该结果证明 WSL base + DrvFS 开发兼容，不是 ext4/Linux 正式 Gate。

## 设计边界与未完成事项

- 本轮没有启动、注册或伪造正式 28 日 soak，没有写入正式 artifacts/journal，也没有网络或 broker 调用。
- 开发 fixture 与 fake clock 只验证合同，不能构造正式 PASS；M4 状态仍是 `WAITING_FOR_SOAK_EVIDENCE`。
- `root_identity` 是不可逆路径绑定，不是密钥或签名。R2 关闭的是在 trusted manifest/root 不变时篡改或复制
  receipt/facts 的旁路；若威胁模型要求抵抗攻击者重造全部合法业务 wire、manifest 和新 root 的全新 run，需另行
  冻结外部签名/可信时间戳服务，不属于本地零网络 P8 R2 合同。
- 只有未参与 R2 实现的全新独立复验通过后，才可冻结并注册正式 PAPER runner；真实四周证据和 ext4 Gate
  继续保持开放。

