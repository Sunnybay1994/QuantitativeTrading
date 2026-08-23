# M3-G8C CLI 合同首包任务单

## 目标与边界

按 [`docs/framework/M3实施与Agent交接.md`](../M3实施与Agent交接.md) 的 G8 CLI 合同和
[`M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md`](M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md)
第 4 节，首包只冻结 CLI 解析、停止点、失败聚合和规范 stdout。实际 readiness、snapshot、
train/evaluate/backtest、tracking、复现比较和 acceptance handlers 由后续分包注入；本包不伪造任何
artifact 或 receipt，不声称 formal G8 完成。

## 冻结合同

- 保留现有内部 `experiment-identity` 命令参数、`execute=` 注入和旧 summary 形态。
- 新增 `readiness`/`snapshot`/`train`/`evaluate`/`backtest`/`run-all`/
  `verify-reproducibility`/`acceptance-audit`；全部必须传 `--config`。
- G1/snapshot identity 只接受 64 位小写 hex；fold 只接受 `fold_NNN`；horizon 只接受
  `5` 或 `10`。`run-all` 的 G1 release 与 snapshot 精确 XOR。
- 参数错误在 dispatcher 前以 code 2 返回。业务失败按 `(scope,node_id,error_code)`
  稳定排序全量列出，进程退出码取最小的 `2..8`。
- stdout 恰好一份 canonical JSON。dispatcher 未提供时显式返回 handler unavailable，
  任意 exception、非有限数、token/secret/Bearer 和绝对路径均不进入 stdout。

## 反例与验收

覆盖缺失共同 config、`run-all` 零个/两个 source、fold/horizon 错误、参数错误时
dispatcher 被调用、乱序多类失败、嵌套 token/绝对路径与异常消息泄漏。Windows 和
WSL base 分别运行定向 Ruff、mypy 和 `test_m3_run_cli.py`。

返工冻结：public dispatcher 的非结构化 stdout 属于不可信输出，捕获后丢弃；dispatcher
抛出的任意异常固定映射为 `M3_COMMAND_FAILED/5`，不得信任异常对象自带 `.code`。
双斜杠 POSIX 路径、UNC、Windows drive 路径及普通 POSIX 绝对路径均不得进入 public summary。
