# M1 HK-HISTORY-R4 Plan 公共边界递归异常脱敏主 Agent 最终验收报告

日期：2026-08-11  
结论：PASS

## 验收结论

`build_hk_history_plan_v2`、`load_hk_history_plan`、`write_or_verify_plan` 已与 recover/evidence 公共边界统一为
宽捕获、failure flag、退出 active handler 后稳定抛错。原错误分类保持不变，hostile 递归异常图不再通过
`__cause__`、`__context__`、traceback 或 repr 泄漏。本结论只关闭 HISTORY-R4 工程返工，不解锁 licensed
`01065.HK@2026-05-05`、HK60、M1 或 ext4 Gate。

## 外部独立初验

全新外部复验结论 PASS：原样重放 R3 三个 FAIL 反例，并增加 OSError、TypeError 三级链、`__notes__`、隐式
context、MemoryError、BrokenPipe 等对抗，均稳定脱敏；recover/evidence、R2 语义与 canonical plan 未回归。

- Windows：`150 passed, 2 skipped`。
- WSL base/DrvFS：`152 passed`。
- 双平台 Ruff、mypy、cold import：PASS。

## 主 Agent 复核

- 高风险定向节点：`11 passed`。
- 覆盖三 plan 入口、recover/evidence hostile 图、ABSENT replay、bar 与 no-trade 互斥、01065 无 licensed evidence
  fail-closed、hardlink/同 bytes 换 inode 来源绑定。
- Ruff、mypy、cold import、scoped diff check：PASS。

## 剩余边界

当前仅证明 retained/offline history 工程合同；`01065` 权威无交易事实材料仍需用户提供，WSL 结果来自 DrvFS
而非 ext4，正式 HK60 finalize 与 M1 Gate 继续开放。

