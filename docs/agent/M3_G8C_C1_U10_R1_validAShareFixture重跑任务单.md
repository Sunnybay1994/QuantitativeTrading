# M3 G8C-C1 U10 R1：有效 A 股 Fixture Honest Chain 重跑任务单

日期：2026-08-13  
状态：**完成；producer 成功，0.5x probe 在无异常证据时达到 30 分钟诊断预算并停止；retained 输入已精确清理**

## 1. 目标

在 U9 已证明 public-chain 后 150 个 `000xxx.SH` 为无效测试输入并完成最小修正后，重新生成一次完整 honest public chain，确认执行层能消费 300 个合法 A 股代码，并取得下一真实边界或成功结果。

## 2. 输入与边界

- 深市 150 个：`000001.SZ`–`000150.SZ`；沪市 150 个：`600001.SH`–`600150.SH`。
- G1、snapshot、provider、fold、feature、label、alignment、model、prediction、target、backtest plan 均走现有 public builder/verifier。
- 不放宽生产 `resolve_a_share_order_quantity_rule`；不伪造 capability；不修改 G7E/F2 控制流。
- producer 完成后只运行一次 0.5x probe；无论成功失败，按 locator 精确清理 G1 release、stage root 和 session config。
- 运行是集成开发反馈，不表述为主 Agent 的独立初验。

## 3. 停止条件

- producer 任一阶段稳定失败；
- locator 或 retained root 身份/摘要漂移；
- probe 超过既定 30 分钟窗口；
- 需要放宽生产证券规则或绕过 public capability 才能继续。

命中任一条件时记录真实边界并清理，不用猜测值迁就任务。
