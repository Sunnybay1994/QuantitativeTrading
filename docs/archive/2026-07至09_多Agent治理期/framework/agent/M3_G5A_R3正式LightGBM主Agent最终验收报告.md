# M3 G5A R3：正式 LightGBM 主 Agent 最终验收报告

日期：2026-08-09  
结论：G5A 正式工程合同通过；不等于 M3 或 Linux/ext4 Gate 通过

## 验收结论

G5A 已关闭 R1–R3 的三类阻断：formal builder 在任何输出/训练前 fresh-verify 完整 G1→G4C 链并要求
exact capability/root；prediction 严格绑定有序唯一 `(as_of, symbol)` 与 metadata 逐行闭包；上游 hostile
verifier 的 `ValueError`/非 `ValueError` 均换译为固定错误且 cause/context 为空。

实现与独立复验还证明：正式和 development 类型、receipt stage 与入口分离；native LightGBM 4.6.0
train/save/load/predict 使用保存的 best iteration；模型、metadata、curve、receipt 或 copied-root 任一漂移均
fail closed；包根 import 在 fresh Python 进程中不加载 LightGBM。

## 主验与独立证据

```text
Windows formal→development pytest: 20 passed in 261.94s
Windows 新增 hostile 定向测试: 1 passed
Windows fresh-process lazy-import: 1 passed
Windows Ruff: PASS
Windows model.py + formal test mypy: PASS
WSL base /mnt/f 新增两项: 2 passed

独立复验 Windows: 20 passed in 260.89s; Ruff/mypy PASS
独立复验 WSL base /mnt/f: 20 passed in 150.12s; Ruff/mypy PASS
独立 hostile probe: builder/verifier × ValueError/RuntimeError 全部稳定脱敏
```

扩大 mypy 到既有 development fake-LightGBM 测试时出现 pandas stubs 与动态 fake module 的既有 7 项噪声；
冻结的生产模块与 formal 测试定向 mypy 已通过。Pandera/Polars warnings 为既有弃用警告。

## 完成边界

本结论只关闭 G5A 工程合同并解锁 G5B。完整 folds/horizons 正式训练、真实数据性能、G5B–G9、M3 总 Gate
及 Linux/ext4 发布终验仍未关闭。当前 WSL 工作树位于 `/mnt/f` DrvFS，不能表述为 ext4 证据。
