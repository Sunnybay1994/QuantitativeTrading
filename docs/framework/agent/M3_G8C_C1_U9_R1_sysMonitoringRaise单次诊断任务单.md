# M3 G8C-C1 U9 R1：sys.monitoring RAISE 单次诊断任务单

日期：2026-08-13  
状态：**诊断完成；根因定位为 public-chain fixture 的无效沪市代码；retained 输入已精确清理**

## 1. 目标

用 Python 3.12 `sys.monitoring.events.RAISE` 低开销观察 honest 0.5x replay 在 `a_share_execution.py` 中抛出的异常事件，取得 F2 public 脱敏前最后一个非 `AShareExecutionError` 的 code name、bytecode offset、异常类型和消息哈希。

## 2. 边界

- 新 honest producer 一次；不是 U6/U8 结果重标。
- observer 只注册 `RAISE`，callback 只对 `a_share_execution.py` 追加最多 64 条脱敏元数据；不改 frame、参数、返回、异常或控制流。
- `finally` 必须关闭 events、注销 callback、释放 tool id。
- producer 60 分钟无阶段进展停止；probe 30 分钟停止。
- 无论成功失败，按新 locator 精确清理三根 retained 输入。
- 不修改 G7E/F2 production；没有原始异常不猜修。

## 3. 前置微探针

Windows `m3chain312` 已用纯内存 `ValueError` 验证 `sys.monitoring` RAISE callback 与 tool-id cleanup，输出 `M3_U9_MONITORING_PASS`；临时微探针文件已删除。
