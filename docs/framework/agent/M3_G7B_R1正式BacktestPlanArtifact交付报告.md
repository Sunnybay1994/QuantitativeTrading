# M3 G7B R1：正式 BacktestPlanArtifact 交付报告

日期：2026-08-09  
角色：实现 Agent  
状态：实现与自测完成；待独立复验和主 Agent 最终验收  
依据：[任务单](M3_G7B_R1正式BacktestPlanArtifact任务单.md)

## 1. 完成内容

- 新增 formal `VerifiedBacktestPlanArtifact` 与不可序列化
  `BacktestPlanFreshVerificationContext`，并做 exact type 安全导出；development verified 类型不变。
- 新增 `build_backtest_plan_artifact` / `verify_backtest_plan_artifact`：每个入口各精确一次调用 public
  `verify_target_artifact`，显式逐字段比对 fresh capability。
- formal 路径只验证、不修复 target 与 SH 日历物理顺序；signal 必须是 verified SH open session，执行日严格取
  verified session 的 index+1，尾部缺 session 失败关闭。
- schedule 保持 `(execution_date, as_of, symbol)` 物理序，diagnostics 保持 `as_of` 物理序；每日权重以
  `Decimal(str(weight))` 求和后投影。
- 从 fresh config 重建 `0.5/1/2` 三档成本，验证三项 rounding、252 annualization、连续自然日成本期间及
  2022-04-28/29、2023-08-27/28 边界；印花税与过户费不缩放。
- receipt 固定 `backtest-plan/WORK/work_key`，精确绑定 G7A 14 项、target 四项与 G1 日历，共 19 项输入和
  四项输出，拒绝重复、alias、错 root 与闭包漂移。
- builder 复用唯一 `ArtifactPublication`；fresh 验真位于 root lease 内，四文件内存生成、exclusive 写、
  flush/fsync/readback 后提交。verifier 使用 root/文件实体连续性、双重稳定读及 receipt 后再次稳定读，拒绝
  link/reparse、whole-root 或文件替换及原地内容漂移。
- formal 公共边界只暴露 `M3_BACKTEST_PLAN_ARTIFACT_INVALID` 或
  `M3_BACKTEST_PLAN_ROLLBACK_FAILED`，清除 cause/context；development API、stage 与既有实现未改。

## 2. 修改文件

- `src/quant/backtest/a_share_plan.py`
- `src/quant/backtest/__init__.py`
- `src/quant/research/m3/contracts.py`
- `src/quant/research/m3/__init__.py`
- `tests/unit/test_m3_formal_backtest_plan_artifact.py`
- 本任务单与本交付报告

worktree 中其余既有修改、未跟踪报告和测试文件均未触碰；没有联网、add/commit，也没有写正式 artifacts、
journal 或候选映射。

## 3. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，显式 worktree `PYTHONPATH`：

- G7B formal：`4 passed`（最终复跑 76.42s）。
- G7B + G7A + development plan + config：`109 passed`（392.64s）。
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 3 source files`
- cold import：`G7B_COLD_IMPORT_PASS`，未加载 Qlib/LightGBM/MLflow。

WSL Miniforge `base`，显式 worktree `PYTHONPATH`：

- G7B formal：`4 passed`（最终复跑 44.02s）。
- G7B + G7A + development plan + config：`109 passed`（231.87s）。
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 3 source files`
- cold import：`G7B_WSL_COLD_IMPORT_PASS`。

`git diff --check` 对 G7B 白名单文件通过。pytest 仅有既有 Pandera/Polars deprecation warnings；无测试失败。
首次 Windows pytest 因未隔离 `PYTHONPATH` 导入到错误源码而 collection 失败，改为显式 worktree
`PYTHONPATH` 后通过。首次组合 WSL cold-import 命令仅因 PowerShell/bash 引号承载失败；单独以直接 WSL
参数重跑后通过，代码测试与静态检查未受影响。

## 4. 剩余边界

- 这是 formal 工程合同自测证据，不是独立复验或主 Agent 验收。
- 当前 WSL 项目路径位于 DrvFS/wslfs；WSL 绿色只证明定向兼容，不等于 ext4/Linux Gate。
- 未运行真实全 fold、真实券商费用事实复核或 G9 成本 Gate；开放末段仍是研究成本假设。
- 未生成正式 backtest receipt/发布物；测试只使用确定性本地 fixture。
