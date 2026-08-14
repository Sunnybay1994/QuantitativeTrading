# M3 G8C-C1 U8 R1：exception-only observer 单次诊断任务单

日期：2026-08-13  
状态：**主 Agent 串行诊断终态；`INSUFFICIENT_INTERNAL_EVIDENCE`；retained 输入已精确清理**

## 1. 前置事实

U6 honest retained probe 已证明 300-symbol/1-session 的 0.5x 场景进入 G7E 后，在 F2 public `execute_formal_a_share_session` 映射为 `M3_A_SHARE_EXECUTION_INVALID`。U6 的 Python trace 因默认 line-event 开销达到 30 分钟上限，不能证明 F2 内部原始异常；三根 U6 retained 输入已精确清理。

## 2. 唯一目标

再生成一次新的 honest retained chain；probe 仅在 `a_share_execution.py` frame 上安装 exception observer，并立即设置 `f_trace_lines=False`、`f_trace_opcodes=False`，只记录 exception type/function/line/message hash。不得修改产品、参数、返回、异常传播或 capability。

## 3. 执行边界

- producer 仍使用 public G1→target→backtest-plan，显式 retain；不是 U6 重跑证据。
- probe 只运行 0.5x；先用现有 focused F2 测试证明 observer 能捕获内部异常且无明显时延放大。
- producer 最多 60 分钟无阶段进展；probe 最多 30 分钟。
- 无论成功失败，按新 locator 的 path/kind/dev/inode/tree SHA 精确清理三根并写 receipt。
- 不修改 G7E/F2 production，不猜修业务语义，不运行外部 Agent。

## 4. 通过条件

取得 F2 public wrapper 抛出前最后一个非 `AShareExecutionError` exception event 的 exact function/line/type，并能映射到一个可陈述的不变量；否则仍为 `INSUFFICIENT_INTERNAL_EVIDENCE`。

## 5. 执行终态

- producer 唯一一次成功：G1 `465.211s`，总链 `2484.806s`，session `_f0r2_351066fe1471`。
- exception-only probe 已设置 `f_trace_lines=False`、`f_trace_opcodes=False`，但仍在 `1804.1s` 达到 30 分钟上限，未形成 evidence 文件。该结果说明主要耗时来自 honest fresh/replay 路径，不能归因于 line-event trace。
- 未取得 F2 public wrapper 前的原始异常，结论仍为 `INSUFFICIENT_INTERNAL_EVIDENCE`，不修改 G7E/F2。
- cleanup token `23c4f2f23b8e4019b717be9e636319c0` 已精确删除 G1 release、stage root、config，receipt `residual=[]`；事后 `_f0r*`、config、G1 release children 均为 0。
