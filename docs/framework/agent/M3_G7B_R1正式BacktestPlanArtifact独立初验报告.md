# M3 G7B R1：正式 BacktestPlanArtifact 独立初验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**PASS（进入主 Agent 最终验收）**

## 1. 范围与边界

依据 `M3_G7B_R1正式BacktestPlanArtifact任务单.md`，只读审查 formal G7B 的合同、实现者交付报告、G7A R2
主验、目标实现与实现者测试。生产代码及实现者测试未修改；独立反例使用临时测试文件执行，验证后已删除。本报告
是唯一持久新增文件。未联网、未 add/commit，未写正式 artifacts、G1 journal 或候选映射。

本结论只证明 formal BacktestPlanArtifact 工程合同通过独立初验，不是主 Agent 最终验收，不是完整真实 work、
真实券商费用、M3 或 Linux/ext4 Gate。

## 2. 合同证据映射

- **formal 身份与 fresh 闭包**：formal/development verified 类型分离；builder/verifier 均在 public 边界内精确一次
  调用 `verify_target_artifact`，传入 G1→G7A 完整 context，并显式逐字段比较 root、两个 DataFrame、manifest
  及两项 hash。独立验证 well-typed 但 hash 非 exact 的返回和 hostile `ValueError` 均被脱敏为稳定错误，且
  cause/context 为空。
- **调度和物理序**：target 只验证 `(as_of,symbol)` 物理顺序，不排序修复；SH open 子序列从 fresh G1 日历的
  物理序读取，要求非空、唯一、严格递增；signal 域 exact 等于 fold test dates，执行日严格取 SH session
  index+1，尾部缺下一 session 失败。独立使用非全反转 permutation、SH 日历整表反转及截断 terminal signal
  后日历，均在空 output root 内失败关闭。
- **成本与科学配置**：从 config fresh 重建 exact `0.5/1/2`；2022-04-28/29、2023-08-27/28 边界连续；
  commission rate/min 与 slippage 按三档精确缩放，stamp tax/transfer fee逐 period 不缩放；rounding 三项、
  annualization=252、scaled components均有显式约束。成本 schedule/version/order quantity rule进入输出 manifest，
  并经 receipt 输出 digest闭包绑定。
- **receipt**：固定 `backtest-plan/WORK/work_key`、19 inputs、4 outputs；通用 receipt 验真后按 root selector重建
  exact path集合。独立少一项失败；hardlink alias在通用 receipt publisher 的单链接约束处先行失败；另一 work
  修改 manifest、重算四项 output digest并合法重签 receipt，仍被 fresh manifest重算拒绝。
- **不可变发布**：builder 在 `ArtifactPublication` lease 内完成 fresh target、日历读取、数学和四文件写入；
  exclusive create、flush/fsync、readback、exact commit和owned-only rollback均复用唯一公共实现。独立在 verifier
  fresh窗口 rename整个 root并复制 same bytes回原路径，root实体连续性拒绝；预置竞争者同名文件时 fresh verifier
  零调用，竞争字节既未覆盖也未删除。
- **输出验真与异常**：verifier pre/post root/文件实体连续、exact tree、双 stable read、fresh重算 manifest/content/
  costs和receipt闭包；公开仅暴露 `M3_BACKTEST_PLAN_ARTIFACT_INVALID` 或 rollback稳定码。冷导入未加载 Qlib、
  LightGBM、MLflow。

## 3. 独立新增反例

相对实现者四个测试，额外实际执行：

1. 非全反转 target permutation；
2. well-typed 但 `manifest_sha256` 非 exact 的 hostile fresh返回；hostile `ValueError`含路径/token/SQL文本；
3. SH 日历物理整表反转；terminal signal后截断导致无 next session；
4. 三 multiplier逐字段数值关系、两个费用边界、税费/过户费不缩放；
5. receipt少 calendar 项；hardlink alias；
6. 另一 work修改 manifest并重签全部 outputs/receipt；
7. fresh期间 whole-root rename+same-bytes复制替换；
8. caller root已有竞争同名文件的 no-clobber及fresh零调用。

上述反例全部按冻结合同失败关闭；未发现产品缺陷。

## 4. 实际验证结果

Windows 原生 `D:\Miniforge3\python.exe`，显式 worktree `PYTHONPATH`：

- 独立反例 + 实现者 formal G7B：`7 passed`，177.07s；
- Ruff（G7B三生产文件、导出及实现者测试）：`All checks passed!`；
- mypy（3 source files，独立 cache）：`Success: no issues found in 3 source files`；
- cold import：`G7B_INDEPENDENT_WINDOWS_COLD_IMPORT_PASS`。

WSL Miniforge `base`，显式 `/mnt/f/.../m3-g4-formal/src`：

- 独立反例 + 实现者 formal G7B：`7 passed`，84.28s；
- Ruff：`All checks passed!`；
- mypy（3 source files，`/tmp`独立 cache）：`Success: no issues found in 3 source files`；
- cold import：`G7B_INDEPENDENT_WSL_COLD_IMPORT_PASS`；
- `stat -f -c %T .`：`wslfs`。

pytest仅有既有 Pandera/Polars deprecation warnings。一次临时测试因点号文件名 collection失败后改用正常临时
模块名；一次 hardlink反例按预期在通用 receipt publisher提前拒绝，但测试最初未先 unlink而影响后续重签，清理
hardlink后重跑通过；首次并行 mypy共享 cache触发 mypy 2.2.0 internal error，改用两平台独立 cache后均通过；
首次WSL cold-import仅为PowerShell/bash引号承载失败，直接 WSL 参数重跑通过。这些均未触发产品改动，也未计为
产品测试通过前的证据。

## 5. 剩余风险

- 当前 WSL 路径实测为 `wslfs`/DrvFS，不是 ext4；WSL绿测仅证明定向兼容，不能宣称 Linux/ext4 Gate。
- 未执行真实全 fold、真实成本事实复核、正式 artifact/receipt发布或性能 Gate；开放末段仍是研究成本假设。
- 本 PASS 仅允许进入主 Agent 最终验收；G7D/G9及正式 M3 Gate仍按任务依赖继续。
