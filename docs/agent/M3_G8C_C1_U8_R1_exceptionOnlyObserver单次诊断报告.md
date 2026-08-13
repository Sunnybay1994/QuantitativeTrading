# M3 G8C-C1 U8 R1：exception-only observer 单次诊断报告

日期：2026-08-13  
结论：**INSUFFICIENT_INTERNAL_EVIDENCE；未修改产品；retained 输入已清理**

U8 使用新的 honest public chain，不复用或冒充 U6 producer。G1 耗时 `465.211s`，G1→backtest-plan 总耗时 `2484.806s`。probe 只运行 0.5x，并在 `a_share_execution.py` frame 上禁用 line/opcode trace，只观察 exception event。

probe 仍在 `1804.1s` 达到冻结的 30 分钟上限，未写出 exception evidence。结合 U6 的无 trace private probe 约 `1534.5s` 才到 F2 public 异常，可知 honest fresh/replay 本身已占据主要预算；当前不能通过 Python trace 在限定窗口内获得 F2 脱敏前异常。

cleanup token `23c4f2f23b8e4019b717be9e636319c0` 已按 path/kind/dev/inode/tree SHA 删除 exact G1 release、`_f0r2_351066fe1471` stage 和派生 config。cleanup receipt 位于 `C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u8-r1\cleanup-receipt.json`，`residual=[]`；事后三类路径均为零残留。

后续若继续，必须先在 F2 production 外层冻结一个默认关闭、测试显式启用的窄诊断 hook，或允许更长单次 probe 预算；继续复制 retained producer + Python trace 不再具有工程收益。
