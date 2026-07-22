# M3 HISTORY-BATCH100 R2 真实执行最终验证与流程纠正报告

## 最终账本结论

- 原 BATCH100 在外层等待 exit `124` 后仍于 WSL 中继续运行，并完整提交冻结的 100 个 identity。
- 随后误下发的 `--max-new-requests 1` 在写锁释放后提交了确定性 plan 的下一个 identity。
- 静默态生产验证结果：history `3186`、verified `674`、missing `2512`、partial `0`。
- verified endpoint 分布：`adj_factor=133`、`daily=136`、`dividend=131`、`stk_limit=141`、`suspend_d=133`。
- 工作流保持 `[INDEX]/INCOMPLETE`；没有 candidate、prepare 或 publish。
- WSL 进程检查未发现残留 `quant.research.m3.run_g1` 写者。

## 边界定位

- 原冻结 BATCH100 的最后 identity（index `672`）：
  `38de2304a90c56e47acdd62421f87e8bb028ef03c23eb737828b2a8518ab998a`
  （`suspend_d/000712.SZ`），receipt 有效。
- 额外提交 identity（index `673`）：
  `38e32d40b0c6f26d1e27845caa7e7570388eda97e782694192fd921347960e8b`
  （`daily/002466.SZ`），receipt 有效。
- 下一缺失 identity 从 index `674` 开始；没有跳号或重复写入。

## 被破坏的不变量与纠正

- 被破坏的不变量：任何新写者启动前，必须证明上一个写者已经静默。
- 主 Agent 错误：把命令承载层 timeout 当作 WSL 子进程终止，并用活动写者期间的 partial 快照下发恢复。
- 数据影响：多提交一个仍在确定性 plan 内、已授权且通过生产验证的 API identity；没有数据损坏或发布影响。
- 纠正：`.ai/coding_rules.md` §9 已新增跨本机/WSL/远端任务的子进程存活与写锁静默规则。以后外层 timeout 后先检查进程/锁；若写者仍在运行，只等待，不做恢复审计决策。

## 下一批冻结

- 为控制长尾响应风险，下一批上限降为 `50`。
- ordered request-id SHA-256：`93b5ff3c584fd654600c8830a3054b7d3ea50d2c7a97e0f94b0f8730c9cbbbd6`
- endpoint 分布：`adj_factor=12`、`daily=13`、`dividend=11`、`stk_limit=11`、`suspend_d=3`。
- 首个：`38ea117fd6eadc3e906a178ef26bea13e48372805c906cac2cbeb099265d3cd8`（`suspend_d/601799.SH`）。
- 末个：`3d883b2cd30b623c8f767a5a9d5c08f74ddac013500a3d7efc9b132a82f4a1dc`（`adj_factor/000975.SZ`）。

