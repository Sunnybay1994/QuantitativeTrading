# M3 G8 R1 正式 Backtest StageRunner 闭环交付报告

日期：2026-08-10

角色：外部实现 Agent

状态：实现与自测完成，待未参与实现的全新外部 Agent 独立初验；不宣称 G8、M3、ext4 或真实数据 Gate PASS。

## 1. 交付结果

- G7F 新增公开 21-input、29-output SSOT helper，以及 receipt 发布前的完整 fresh/tree verifier；最终 receipt verifier 与 pre-receipt verifier 复用同一业务闭包。
- 新增 `FormalBacktestStageResult`、`make_formal_backtest_run_plan`、`run_formal_backtest_stage`。formal wave 精确一个 WORK/backtest 节点，输入为 21 个 identity-resolved `ExternalInput`，输出为 29 个 leaf。
- formal `make_work_run_plan` 止于 `backtest_plan`；development chain 继续保留 development backtest/tracking。
- runner 使用既有 `StageRunner.run_static` 安全 primitive：handler 实际 G7F、每次 closure 实际 pre verifier、receipt 后实际 final verifier；不接 caller hash/result/transition/naked frame。
- 公开包采用惰性安全导出，冷导入不加载 Qlib、LightGBM 或 MLflow。

## 2. 关键合同与反例

- 首次发布顺序：`build -> pre(temp) -> pre(final) -> final`。
- completed resume：handler 0 次、pre(existing final) 1 次、final 1 次。
- `resume=False` completed：handler 0 次、pre(existing final) 1 次，稳定返回 `STAGE_ALREADY_COMPLETE`。
- 完整 orphan：`pre(existing) -> build -> pre(temp) -> pre(final) -> final`。
- 每个实际 G7F phase 均保持 plan verifier exact once、F0 loader exact once、G7E actual 三次；测试逐路径计数，没有缓存 `_FormalBundle`。
- hostile build、pre-closure、final 的稳定错误分别为 `STAGE_BUILD_FAILED`、`STAGE_OUTPUT_INVALID`、`STAGE_RECOVERY_CONFLICT`；外层在 exception handler 退出后重抛，message/cause/context 不泄露 TOKEN、SQL、PID 或绝对路径。
- 覆盖 21/29 集合、roots Mapping 顺序、嵌套 roots、work identity drift、不可序列化 result、temp/receipt 无残留。

## 3. §10 邻接测试返工

现象：既有 `test_m3_orchestration_plans.py` 使用 `inspect.getsource()`，要求八个已由 boundary decorator 委托的 verifier 函数体包含 `receipt.stage` 字面量；单节点稳定失败。

根因：测试绑定实现文本形状，从未调用 verifier，不是公开 receipt 行为合同。

规则：orchestration plan 测试只验证 exact stage/dependency/receipt path；各模块既有 receipt closure/tamper 测试负责 verifier 行为。

最小复现：原节点 Windows 独立 `1 failed`，首项为 development feature，移除后下一项 alignment 同型失败。

修正：完整删除八项源码内省循环和因此未用 imports，不复制重 fixture，不改任何 verifier production。

通过条件与结果：原节点 `1 passed in 2.65s`。

## 4. §11 WSL1 平台边界

首次 WSL actual golden 安全失败为 `STAGE_PUBLISH_FAILED`。一次定向探针确认：final 全父链存在；temp/final parent 同设备 `st_dev=2`；`renameat2(RENAME_NOREPLACE)` 返回 `-1/EINVAL(22)`。worktree-local DrvFS 同样为 `st_dev=17`、`-1/EINVAL(22)`，所以更换 `--basetemp` 无效。诊断代码和临时目录均已清理。

按任务 §11，不修改 StageRunner 或 no-clobber primitive。golden 只使用公开 `platform_supports_renameat2_noreplace()`：能力为 false 时精确 skip；为 true 时必须完整执行。Windows 能力为 true 且 actual golden 全执行通过；当前 WSL1 能力为 false，保持安全 fail-closed。Linux ext4 actual publication 仍待后续 Gate 验证。

## 5. 验证证据

### Windows Miniforge

- §7 组合：`92 passed, 666131 warnings in 1522.78s`。
- §11 标记加入后的 actual G8 golden：`1 passed, 469308 warnings in 1057.30s`，确认 capability=true 时没有 skip。
- G8 unit 最终定向：`5 passed, 7676 warnings in 85.45s`。
- Ruff：全部通过。
- mypy：3 个生产文件无问题。
- cold import：`WINDOWS_COLD_IMPORT_PASS`。
- capability：`WINDOWS_RENAMEAT2_NOREPLACE True`。

### WSL Miniforge base / WSL1

- golden 单节点能力边界：`1 skipped in 2.01s`。
- §7 最终组合：`91 passed, 1 skipped, 196823 warnings in 427.86s`。
- Ruff：全部通过。
- mypy：3 个生产文件无问题。
- cold import：`WSL_COLD_IMPORT_PASS`。

warning 均为 Pandera/Polars `concat(how='horizontal')` 弃用提示，无业务失败。

### Diff 与源码摘要

- scoped `git diff --check` 通过；未执行联网、`git add` 或 commit；未写正式 artifact。
- `a_share_reporting.py`: `d9ef9b59ddcfc32a6fbe2bba89c30e5fcd405f5a284cd3189b4bf53f6335f0c8`
- `backtest_stage.py`: `825fcd81df372b9165060414c8cb1d7919dc6ec9af6171c4ebaba904547b5307`
- `orchestration.py`: `93ba5ff5ad537998ae1565f5089b4ca2262094684532608d6b16590a8f81623c`
- `backtest/__init__.py`: `af741250ab639df909372797447ce16142c6cd690db9f8368b2e83babd14761b`
- `research/m3/__init__.py`: `be2434ec62e085129ed12d2f81192c26a76b21a7c537588d68011fd9d7e05a30`

## 6. 剩余风险与下一步

- 当前 WSL1 无法提供 `RENAME_NOREPLACE` actual 发布证据；必须在支持该 primitive 的 Linux ext4 环境重新运行 golden，不能用 fallback 覆盖或普通 rename 冒充 no-clobber。
- 本报告仅为实现者自测。下一步必须由未参与本轮实现的全新外部 Agent 按任务书增加未公开反例并独立初验；通过后再进入主 Agent 最终验收。
