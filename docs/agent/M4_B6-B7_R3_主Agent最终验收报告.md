# M4 B6/B7 R3：主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（开发工程合同）**

## 验收范围

本轮只验收 M4 B6 统一事件回测的完整 replay 闭包，以及 B7 在指标计算前对 B6 结果的
fresh 验证与异常链脱敏。不验收 P8 真实 soak、正式数据性能、Linux/ext4 或 M4 总 Gate。

权威输入：

- `M4_B6-B7_R2_完整Replay闭包返工任务单.md`；
- `M4_B6-B7_R3_异常链脱敏返工交付报告.md`；
- `M4_B6-B7_R3_异常链脱敏独立复验报告.md`。

## 主验结论

1. `SimulationReplayInputs` 保留并绑定 plans、market snapshots、initial account 与 simulation config。
   `verify_simulation_result_identity` 先重验公开结构，再使用同一 `simulate_order_plans` 重放，最后逐字段
   比较完整结果。删除/替换 decision、command、event、transition、checkpoint 或 replay input 后全量
   重哈希，仍不能通过公开 verifier。
2. B7 `build_trading_metrics` 在任何 scenario metrics 构造前调用 B6 公开 verifier。伪造输入在指标
   构造 0 次时被拒绝，不存在“先算指标、后报身份错误”的旁路。
3. R3 将 hostile verifier/scenario builder 的未预期异常只在 active `except` 内记录失败状态，
   离开 handler 后才抛 `TRADING_METRICS_INPUT_INVALID`。公开异常 `cause/context` 均为 `None`，
   traceback 不保留上游 sentinel。
4. 合法 partial-fill 路径、指标 identity 与原有 B1-B8 行为没有因脱敏修复发生算法漂移。

## 验证证据

主 Agent 在 Windows 原生 Miniforge 上使用全新 pytest basetemp 重跑：

```text
test_event_simulator.py + test_trading_metrics.py: 32 passed
Ruff: All checks passed
mypy: Success, 2 source files
```

未参与 R3 实现的独立复验者额外执行了实现者未使用的 hostile verifier、hostile builder、
decision 全删除+全量重哈希反例，并得到：

```text
Windows B6/B7: 32 passed
Windows B1-B8: 173 passed
WSL base /mnt/f B6/B7: 32 passed
Ruff/mypy: PASS on both interpreters
```

WSL 路径是 DrvFS，上述结果只证明 WSL base 开发兼容，不等于 ext4/Linux Gate。测试中的
Pandera/Polars deprecation warnings 为已知非失败输出。

## 状态与剩余风险

- B6/B7 R3 开发工程合同正式收口，可作为后续 M4 路径的已验收前置。
- M4 仍为 `WAITING_FOR_SOAK_EVIDENCE`；P8 真实 28 日、正式 runner、真实业务证据与 Linux/ext4 Gate
  均未由本报告关闭。
- P8 R4 正在独立复验前等待审查槽位；其公共导出解环不改变本报告对 B6/B7 业务
  语义的结论，但 M4 合流仍以 P8 R4 最终结果为准。

本轮未访问网络、真实账户或正式 journal，未执行 `git add/commit`。
