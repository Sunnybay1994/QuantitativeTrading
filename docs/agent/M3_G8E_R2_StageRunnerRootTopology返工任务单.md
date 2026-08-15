# M3 G8E R2 StageRunner Root Topology 返工任务单

状态：实现与普通开发检查完成；待项目结构统筹合流；successor 长运行未授权。

## 1. 现象与根因

retained two-fold 在首个 `fold_001/h5` reproducibility 单元稳定返回
`M3_REPRODUCIBILITY_INVALID`，且没有创建 repro lock、artifact 或 receipt。

确定根因是 `reproducibility._run_stage` 把 `PROJECT=project_root` 与均位于其下的
`G1_RELEASE`、`G8`、`EXTERNAL_QLIB` 同时交给 `StageRunner`。共享
`StageRunner._validate_roots` 禁止 root 物理嵌套，因此构造阶段先以
`STAGE_INPUT_INVALID` fail closed，公共边界再脱敏为
`M3_REPRODUCIBILITY_INVALID`；fresh worker 尚未启动。

## 2. 冻结修复

- resolver 与 worker 继续使用 `G1_RELEASE/G8/EXTERNAL_QLIB` 三个专业 root；不得改变其接口或验真。
- REPRO 的 `StageRunner`、external inputs、outputs 和 stage receipt 只使用
  `{"PROJECT": project_root}`。
- config、`pyproject.toml`、runtime source、feature/label/alignment manifest 与
  receipt 均形成 PROJECT-relative exact digest。
- `verify_formal_reproducibility_artifact` 只接受 inputs/outputs 全为 `PROJECT` alias 的正式 REPRO receipt。
- `acceptance.resolve_acceptance_subject` 验证 REPRO 时必须传 PROJECT-only registry。
- comparison key、容差、worker protocol、路径和公共错误码均不改变。
- 不放宽共享 nested-root 拒绝，不修改 receipt schema。

## 3. 唯一写白名单

1. `src/quant/research/m3/reproducibility.py`
2. `src/quant/research/m3/acceptance.py`
3. `tests/unit/test_m3_reproducibility.py`
4. `tests/integration/test_m3_acceptance.py`
5. 本任务单
6. `docs/agent/M3_G8E_R2_StageRunnerRootTopology返工交付报告.md`

禁止修改 `orchestration.py`、`run_state.py`、`formal_cli_resolve.py`、
`acceptance_work.py`、配置、`__init__.py`、roadmap、共享 SSOT、旧 retained root
及两份 retained session config。

## 4. 必须覆盖的反例

以真实目录拓扑构造项目根 `P`：

- `G8=P/artifacts/research/m3/stage`
- `G1_RELEASE=P/data/clean/m3_g1/releases/id`
- `EXTERNAL_QLIB=P/data/external/qlib/v0.9.7`

直接把上述三个 root 与 `PROJECT=P` 一并传给 `StageRunner` 必须继续稳定拒绝
`STAGE_INPUT_INVALID`。通过正式 REPRO API 时，StageRunner 必须只收到
PROJECT root；首次发布生成两个 attempt 和 receipt，第二次 `reused=True` 且不得
再次调用 worker；receipt 的全部 inputs/outputs 必须使用 PROJECT alias。

Acceptance 定向测试必须证明其 REPRO verifier 参数 registry 只含 PROJECT。

## 5. 开发检查

在 Windows Miniforge 开发反馈环中单实例、BelowNormal、CPU affinity `0xF00`、
数值线程不超过 2，顺序执行：

1. focused pytest：上述两份测试文件；
2. Ruff：两生产文件与两测试文件；
3. mypy：两生产文件；
4. 两模块 cold import；
5. `git diff --check`、六路径 scope 与临时/进程残留检查。

不得运行 actual worker、retained resume、successor、readiness/acceptance 全链、
真实 artifact 发布或全量回归。

## 6. 停止与退出条件

若需要放宽 nested-root 规则、修改共享 publication/receipt schema、改变 identity
公式、扩大白名单或读取/写入 retained 现场，立即停止并重新裁定。

退出时只能声明“root topology 修复与普通开发检查完成”；不得声明 actual fresh
worker、successor、readiness、M3 Gate 或 Linux Gate 已通过。六路径形成单一安全提交，
由项目结构统筹合流；本任务不得自行合流或删除 worktree。
