# M3 G8 R1 正式 Backtest StageRunner 闭环独立初验报告

日期：2026-08-10  
角色：未参与实现的全新外部独立初验 Agent（`cursor-grok-4.5-high`）  
工作区：`m3-g4-formal` worktree  
结论：**PASS（仅解锁主验，不宣称 G8 / M3 / ext4 / 真实数据 Gate PASS）**

## 1. 范围与只读约束

已完整阅读 `AGENTS.md`、`.ai/README.md`、`docs/agent/M3_G8_R1任务单.md`、
`docs/agent/M3_G8_R1正式BacktestStageRunner闭环交付报告.md`，并只读核对白名单内
production / tests。本会话唯一持久写入为本报告。未联网、未 `git add`/`commit`、
未写正式 artifact、未触凭据/账户。临时对抗脚本与输出已删除。

受验源码 SHA256（与交付报告一致）：

| 文件 | SHA256 |
|---|---|
| `a_share_reporting.py` | `d9ef9b59ddcfc32a6fbe2bba89c30e5fcd405f5a284cd3189b4bf53f6335f0c8` |
| `backtest_stage.py` | `825fcd81df372b9165060414c8cb1d7919dc6ec9af6171c4ebaba904547b5307` |
| `orchestration.py` | `93ba5ff5ad537998ae1565f5089b4ca2262094684532608d6b16590a8f81623c` |
| `backtest/__init__.py` | `af741250ab639df909372797447ce16142c6cd690db9f8368b2e83babd14761b` |
| `research/m3/__init__.py` | `be2434ec62e085129ed12d2f81192c26a76b21a7c537588d68011fd9d7e05a30` |

`src/quant/data/m3_release.py` / `run_state.py` 无 diff；`orchestration.py` 仅
`make_work_run_plan` formal 截断到 `backtest_plan`；G8 文件无
`rename`/`os.replace`/`shutil.move` 非原子 fallback。`git diff --check` 白名单路径通过。

说明：worktree 另有既有 Gate 未提交改动；不纳入本包白名单扩张，亦不据此判 FAIL。

## 2. 合同映射（独立核对，非复述）

1. **formal WORK 首 wave**：`make_work_run_plan` non-development `stage_defs` 止于
   `BACKTEST_PLAN_STAGE_SPEC`，源码片段不含 `BACKTEST_STAGE_SPEC` /
   `TRACKING_STAGE_SPEC`。development chain 仍含 development-backtest/tracking。
2. **21 / 29 SSOT**：`backtest_artifact_input_paths` / `backtest_artifact_output_relative_paths`
   为公开 SSOT；builder expected names、final receipt 比对、handler `StageBuildReport`
   均调用它们；`verify_backtest_build_output` 与 `verify_backtest_artifact` 共用
   `_verify_formal_build_tree`，pre-receipt 不读 receipt、不返回 verified bundle。
3. **调用顺序与 fresh**：Windows actual 对抗实测首次
   `build → pre → pre → final`，且 `g7f-plan==4`、`g7e-plan==12`、两次 pre nonce 互异；
   实现者 golden 另覆盖 resume=`["pre","final"]`、`resume=False`=`["pre"]`、
   orphan=`["pre","build","pre","pre","final"]`。无 `_FormalBundle` 缓存迹象。
4. **脱敏与零残留**：build/closure/final hostile 与递归 exception graph 外层均为稳定
   `M3StageRunnerError` code，`cause/context` 空，不泄露 TOKEN/SQL/PID/绝对路径；
   失败路径无 receipt 残留。
5. **identity**：同字节不同 inode 的 receipt replacement、嵌套 roots、case-alias 重复
   physical root 均在 plan 前 `STAGE_INPUT_INVALID`；21 输入绝对路径唯一。
6. **§10**：`test_m3_orchestration_plans.py` 已删除八项 `inspect.getsource` 循环；
   production verifier 未为迎合内省而改。summary 仍保留其既有 inspect（范围外）。
7. **§11**：Windows `platform_supports_renameat2_noreplace()=True` 且 golden 实跑；
   WSL1 `/mnt/f` DrvFS 上 capability=`False`，golden 窄 skip；**不宣称 ext4**。

## 3. 实现者未使用的对抗反例

| 反例 | 结果 |
|---|---|
| 同字节 target receipt 替换（不同 inode） | `STAGE_INPUT_INVALID` |
| `collections.abc.Mapping` hostile `__iter__`（TOKEN/SQL/PID） | 稳定 `STAGE_INPUT_INVALID`，无泄露 |
| roots case-alias 指向同一 physical dir | `STAGE_INPUT_INVALID` |
| nested roots | `STAGE_INPUT_INVALID` |
| 递归 `__cause__` exception graph @ build | `STAGE_BUILD_FAILED`，无泄露 |
| 首次发布 fresh nonce + exact 4/12 内部计数 + handler `config is` | PASS |
| completed receipt 自报完整但删 leaf `metrics.json` | `STAGE_RECOVERY_CONFLICT` |
| orphan 后注入 extra empty directory | `STAGE_RECOVERY_CONFLICT`，无新 receipt |
| pre(final) 通过后、final verifier 前改写 `backtest_metrics.json` | `STAGE_RECOVERY_CONFLICT`，无泄露 |
| 两 writer 同 work：A 持锁时 B | B=`STAGE_LOCK_FAILED`，A=`OK` |
| caller Decimal default / 低精度+ROUND_DOWN+Inexact trap / 高精度 | 全程不变 |

弱攻击备忘：`dict` 子类仅覆盖 `__iter__` 不会击中 CPython `dict.items()`；真正
`Mapping` 才会触发。不构成生产缺陷。

## 4. 验证命令与压缩证据

### Windows Miniforge（`D:\Miniforge3\python.exe`）

- §7 组合（只启动一次）：**`92 passed, 666132 warnings in 1699.82s`**
- Ruff：All checks passed
- mypy：3 production files Success
- cold import：`WINDOWS_COLD_IMPORT_PASS`
- capability：`WINDOWS_RENAMEAT2_NOREPLACE True`
- 发布态对抗脚本：约 926s，四项全 PASS
- 两 writer / Decimal 探针：PASS

### WSL Miniforge `base`（worktree `/mnt/f/...`，**DrvFS**）

- §7 组合（只启动一次）：**`91 passed, 1 skipped, 196824 warnings in 492.14s`**
- Ruff / mypy：通过
- cold import：`WSL_COLD_IMPORT_PASS`
- capability：`WSL_RENAMEAT2_NOREPLACE False`（golden 窄 skip）
- 该绿测仅为 WSL interpreter + DrvFS 兼容证据，**不是 Linux ext4 Gate**

warnings 均为 Pandera/Polars `concat(how='horizontal')` 弃用提示；另有 `.pytest_cache`
权限告警，不影响结论。

## 5. 残留风险（不阻断初验 PASS）

1. 实现者未单独行为测试 formal `make_work_run_plan` 截断；本次以源码合同 + 对抗源码断言覆盖。
2. WSL1 无 exclusive commit actual 发布证据；主验若关平台 Gate，须先在 capability=true 的
   Linux ext4 复跑 golden。
3. worktree 存在既有非本包白名单脏文件；主验应继续按包边界审阅，避免误把历史 Gate 改动
   算入本包。

## 6. 结论

未发现阻断性契约破坏。独立对抗反例均 fail-closed。  
**独立初验 PASS — 仅解锁主 Agent 最终验收。**
