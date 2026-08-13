# M3 G8 R3：WSL 不可达实体窗口测试证据主 Agent 最终验收报告

日期：2026-08-11
结论：**PASS（工程主验）**；允许恢复 G8C resolver，**不**代表 Linux ext4、G8 或 M3 Gate 通过。

## 验收范围

依据 `M3_G8_R1任务单.md` §13，复核 R2 失败闭环、R3 tests-only 实现、外部交付报告与未参与实现的外部独立复验报告。R3 未修改 production；`backtest_stage.py` Git blob 仍为
`e7dcd9827098709c94d85b41a5c4214740b8441d`，裸文件 SHA-256 为
`A13F07DF8790554931864DBA106F7A7AFCA526E27218CF27758DEE8DE76AF693`。两种口径在此明确区分。

## 关键合同结论

- handler 后、temp closure 前窗口继续实际执行；不得以平台能力跳过。
- temp 后、final closure 前及 final 后、receipt 前窗口在 no-replace capability=false 的 WSL1 上，于构建前以明确理由窄 skip，不再接受 `STAGE_PUBLISH_FAILED` 充当实体守卫证据。
- capability=true 的 Windows 三窗口均实际执行 mutation；后两窗只接受 `STAGE_RECOVERY_CONFLICT`，final→receipt 还验证 EntityGuarded 已触达且 base receipt publish 未发生。
- 所有实际执行的失败保持无 receipt/temp 残留、cause/context 为空；skip 不计作 ext4 Gate 证据。

## 主 Agent 复验

- Windows：`test_m3_g8_r1_formal_backtest_stage.py -k inode_replace`：**3 passed**，498.49s。
- WSL base / `/mnt/f` DrvFS：G8 unit+golden：**10 passed, 3 skipped**，226.74s；两项后窗口 skip 理由精确为 `exclusive commit unsupported; inode window unreachable`，golden 一项为宿主缺少 atomic directory no-replace。
- Windows 定向 Ruff、cold import、定向 diff-check：PASS。
- WSL 定向 Ruff：PASS；独立初验另已确认 WSL cold import与独立爆炸构建探针通过。
- 外部独立初验结论：PASS；production、实现测试和既有文档只读，仅写指定报告。

## 保留风险

- 当前 WSL 为 WSL1/DrvFS，no-replace capability=false；两个后窗口与 actual golden 尚未在 Linux ext4 capability=true 宿主实际运行。
- 本结论只关闭 R3 测试证据诚实性返工；tracking、CLI、正式数据与 M3 总 Gate 仍开放。
