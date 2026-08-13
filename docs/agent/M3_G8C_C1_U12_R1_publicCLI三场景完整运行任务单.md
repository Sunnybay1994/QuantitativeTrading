# M3 G8C-C1 U12 R1：Public CLI 三场景完整运行任务单

日期：2026-08-13  
状态：**STOP（Windows 单次运行超过 120 分钟无终态；已精确清理；待重新设计耗时边界）**

## 1. 目标

在有效 300 证券 honest chain 上执行真正的 `python -m quant.research.run_m3 backtest`，闭合：

`CLI → formal resolver → G8 StageRunner → G7F 三个成本场景 → 21-input/29-output receipt → final verifier`。

## 2. 边界

- 复用 U11 的有效 A 股 fixture 与 public producer，不伪造 capability。
- CLI 参数只含 config、snapshot-id、fold、horizon；不得注入 stage root、work key、artifact roots 或结果对象。
- 首次执行 `resume=true`；成功后同一输入再执行一次，必须走 completed resume，不重复发布。
- 记录 stdout 单行 JSON、exit code、最终 root/receipt 身份与 29 outputs；禁止记录路径之外的敏感输入。
- 无论成功失败，按 producer locator 精确清理三项 session-owned roots；StageRunner 产物位于该 owned stage root 内。

## 3. 停止条件

- producer 任一 public stage 失败；
- CLI 超过 120 分钟仍无终态；
- 需要 private result/capability 注入或缩小 300 证券域；
- root/receipt/locator 身份漂移。

命中停止条件时保留脱敏摘要后精确清理，不迁就实现。
