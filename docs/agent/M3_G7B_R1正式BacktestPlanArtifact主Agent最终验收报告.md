# M3 G7B R1 正式 BacktestPlanArtifact 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS；允许解锁 G7D-F0 实现**  
边界：formal 工程合同通过；不是完整真实 work、真实成本事实、Linux/ext4 或 M3 Gate

## 1. 验收范围

主验核对任务书、实现交付、全新独立初验及白名单差异，重点确认：

- builder/verifier 各自 exact 一次调用 public G7A fresh verifier，并逐字段比较 formal target；
- SH open session 物理顺序只验证不修复，signal 映射严格下一 session，尾部缺 next session fail closed；
- formal target/scheduled/diagnostics 物理顺序与完整 batch/window exact；
- scientific config 的三档 multiplier、三种 rounding、annualization 与 cost schedule coverage；
- 只缩放 commission rate/min 与 slippage，stamp tax/transfer fee不缩放；
- 19-input/4-output receipt exact path set、hardlink alias、错root/少多项均拒绝；
- `ArtifactPublication` 覆盖 fresh 长窗口、首写前 root identity、no-clobber、回滚和稳定脱敏异常；
- formal/development exact type隔离，冷导入不加载 Qlib/LightGBM/MLflow。

独立初验额外覆盖了实现者未使用的 target 非平凡 permutation、日历乱序、tail、hostile/nonexact fresh、
另一 work whole-resign、whole-root replacement 与 hardlink alias，均 fail closed。未发现产品阻断。

## 2. 主 Agent 实际验证

Windows `D:\Miniforge3\python.exe`，worktree-local `PYTHONPATH=src`：

- `pytest tests/unit/test_m3_formal_backtest_plan_artifact.py -q`：`4 passed`；
- 定向 Ruff：PASS；
- 定向 mypy 3 source files：PASS。

首次 Windows pytest/Ruff 后同一组合命令中的 mypy 2.3.0 报一次无业务诊断的 `INTERNAL ERROR`；未重跑长
pytest，单独以相同3文件和 `--no-incremental --show-traceback` 复核后 `Success: no issues found`。该瞬时工具
错误不计产品失败，并在此如实保留。

WSL Miniforge base，`/mnt/f/.../m3-g4-formal`、`PYTHONPATH=src`：

- 同一 formal test 文件：`4 passed`；
- 定向 Ruff：PASS；
- 定向 mypy 3 source files：PASS。

实现交付的扩大回归为 Windows/WSL 各 `109 passed`；独立初验的实现者+新增关键节点为 Windows/WSL 各
`7 passed`。主验未机械重复全部长套件，而是结合两轮独立证据、源码映射与正式文件复跑收口。

## 3. 状态与剩余边界

G7B R1 标记主验 PASS，G7D-F0 前置满足。当前 WSL 实测仍是 wslfs/DrvFS，不是 ext4；本任务不关闭真实
成本有效期复核、完整真实 fold/work性能、G7-G9、Linux/ext4 或 M3 Gate。工作树既有脏文件、未跟踪报告和
权限型 pytest cache均保留，未 add/commit、未联网、未触碰正式 G1 artifacts/journal。
