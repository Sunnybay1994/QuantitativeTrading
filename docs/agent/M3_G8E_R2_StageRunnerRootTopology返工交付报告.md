# M3 G8E R2 StageRunner Root Topology 返工交付报告

状态：实现与普通开发检查完成；待项目结构统筹合流。旧 retained 失败现场继续冻结，successor 长运行未授权。

## 1. 交付结论

retained two-fold 的 `M3_REPRODUCIBILITY_INVALID` 已定位并按冻结合同做最小修复：

- resolver 和 fresh worker 仍使用 `G1_RELEASE/G8/EXTERNAL_QLIB` 三个专业 root；
- REPRO 的 `StageRunner`、external inputs、outputs 与 stage receipt 改为唯一
  `PROJECT=project_root` root；
- REPRO 公共 verifier 拒绝任何 input/output alias 不是 `PROJECT` 的 receipt；
- acceptance 在验 REPRO 时传入 PROJECT-only registry；
- 共享 nested-root 拒绝、receipt schema、comparison identity、容差与 worker protocol 均未修改。

这关闭的是 StageRunner 构造前的确定性 root-topology 阻断，不代表 actual fresh worker、successor、readiness、M3 Gate 或 Linux Gate 已通过。

## 2. 精确改动范围

1. `src/quant/research/m3/reproducibility.py`
   - 新增 PROJECT-only root registry；
   - REPRO publication/receipt 全部使用该 registry；
   - verifier 强制 receipt aliases 全为 PROJECT。
2. `src/quant/research/m3/acceptance.py`
   - acceptance 的 REPRO verifier 参数改为 PROJECT-only registry。
3. `tests/unit/test_m3_reproducibility.py`
   - 构造 `PROJECT` 下的真实 `G1_RELEASE/G8/EXTERNAL_QLIB` 嵌套拓扑；
   - 证明旧四-root 组合继续被 `STAGE_INPUT_INVALID` 拒绝；
   - 证明正式 REPRO 首发、resume、worker 调用次数与 PROJECT-only receipt closure。
4. `tests/integration/test_m3_acceptance.py`
   - 证明 acceptance 的 REPRO registry 精确且不可变地只含 PROJECT。
5. `docs/agent/M3_G8E_R2_StageRunnerRootTopology返工任务单.md`
6. 本交付报告。

未修改 `orchestration.py`、`run_state.py`、`formal_cli_resolve.py`、`acceptance_work.py`、配置、导出、roadmap、共享 SSOT 或旧 retained 字节。

## 3. 普通开发检查

全部检查在 Windows Miniforge 开发反馈环中串行执行，承载进程为 BelowNormal、CPU affinity `0xF00`，数值线程上限为 2：

- focused pytest：`32 passed, 1 skipped in 444.25s`；skip 为宿主不允许测试创建某类文件链接的既有平台分支；
- Ruff：四个生产/测试目标 `All checks passed!`；
- mypy：两个生产模块 `Success: no issues found in 2 source files`；
- cold import：`M3_G8E_R2_COLD_IMPORT_OK`，并断言模块从本 worktree 加载；
- focused pytest 的专用系统临时目录已精确清理；
- 最终 staged scope、cached diff-check 与资源残留在提交前再次核对。

测试中的 `_launch_worker` 使用确定性 fake writer；未执行 actual worker、retained resume、successor、readiness 或 acceptance 全链。

## 4. 剩余边界

- 旧 retained 现场已经是 reproducibility stage fail-closed 的失败终态，仍不得自动恢复、修改或清理。
- 本修复只解除 StageRunner root nesting 阻断。actual worker stdout/依赖行为和后续 readiness/acceptance 仍需另行授权的 successor 运行验证。
- 本提交只可由项目结构统筹合流；本任务不自行合流或移除 worktree。
