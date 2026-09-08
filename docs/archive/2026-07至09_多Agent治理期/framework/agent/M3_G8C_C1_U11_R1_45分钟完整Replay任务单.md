# M3 G8C-C1 U11 R1：45 分钟完整 Replay 任务单

日期：2026-08-13  
状态：**完成；300 证券 honest 0.5x replay 成功；retained 输入已精确清理**

## 1. 目标

复用 U10 已验证的 300 个有效 A 股 fixture，重新生成一次 honest public chain，并给唯一 0.5x replay 最多 45 分钟，以取得成功终态或第一个真实异常。

## 2. 不变量

- 不缩小 300 证券域，不减少 public fresh verifier，不伪造 capability。
- actual G7E/G7C/F1/F2、0.5 multiplier、正式 cost periods 与 initial cash 不变。
- observer 仍只记录 `a_share_execution.py` 的脱敏 RAISE 元数据，不修改控制流。
- producer 只运行一次；probe 只运行一次；无论结果如何按 locator 精确清理三根。

## 3. 停止条件

- producer 稳定失败；
- probe 超过 2700 秒；
- root/locator identity 或 tree SHA 漂移；
- 需要改产品或缩小业务域才能完成。

若 probe 再次仅超时，不做第三次同型全链重跑，转为专门性能阶段测量。
