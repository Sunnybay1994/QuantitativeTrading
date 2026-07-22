# M3 HISTORY-BATCH100 R2 外层超时中间快照与误判纠正报告

> **纠正（后续权威证据）：** 本文最初把外层 exit `124` 误判为 WSL 子进程已终止。后续静默态全量审计
> 证明原进程继续运行并完整提交了冻结的 100 个 identity。下文 `657/2528/1` 是活动写者运行期间的中间
> 快照，不是失败终态，不得再作为恢复依据。

## 结论

- 外层等待失败，退出码为 `124`；项目 CLI 未经该承载层返回结构化结果，因此该退出码不能解释为 Tushare 或 M3 workflow 错误。
- 原 WSL 子进程没有随外层等待断开而终止，并在后台继续持有写锁和推进冻结批次。
- 首次零网络审计看到的确定性前缀 `84` 个已提交和第 `85` 个 intent-only，是活动写者的瞬时状态。
- 静默态最终证据证明原批次完整提交 `100` 个 identity，使总 verified 从 `573` 增至 `673`、partial 归零。

## 审计结果

- history 总数：`3186`
- 完整且通过生产验证：`657`
- 缺失：`2528`
- partial：`1`
- 已验证 endpoint 总数：
  - `adj_factor=132`
  - `daily=130`
  - `dividend=130`
  - `stk_limit=136`
  - `suspend_d=129`
- 唯一 partial：
  - request id：`37d6f4c9315c926a937f58e7c4a9e0377702ffb3896f1887495a90da8b915609`
  - endpoint：`daily`
  - journal 文件集合：仅 `intent.json`
  - raw 状态：`ABSENT`

`657 + 2528 + 1 = 3186`，分类闭合；未发现孤儿 raw 或第二个 partial。

## 原中间快照（仅保留审计历史）

以下计数发生在原写者仍存活时，不代表终态：

- verified `657`
- missing `2528`
- partial `1`
- intent-only request id `37d6f4c9315c926a937f58e7c4a9e0377702ffb3896f1887495a90da8b915609`

## 根因与应遵循规则

- 现象：外层等待超时后，WSL 子进程继续执行；只读审计在运行中观察到 intent-only。
- 根因：主 Agent 未先确认 WSL 子进程和 journal 写锁已经静默，就把中间快照当作终态并下发恢复命令。
- 应遵循规则：承载层 timeout 不等于子进程终止。任何重试/恢复前必须检查操作系统进程或权威写锁；活动写者存在时只等待，不得从瞬时 partial 推导恢复任务。
- 新增规则已写回 `.ai/coding_rules.md` §9。
