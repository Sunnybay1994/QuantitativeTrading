# M3 G7F R2：corporate reload 测试隔离独立复验报告

日期：2026-08-10  
状态：**PASS；仅解锁主 Agent 最终验收**

## 1. 独立结论

R2 tests-only 返工符合任务单 §16。父 pytest 进程不再对
`quant.backtest.corporate_actions` 执行 `importlib.reload`；cold import 与 reload 合同完整迁入 fresh
`python -I` 子进程，R1 中旧/new enum、state、transition identity 分裂导致的同进程顺序污染已闭包。

独立复验在 Windows Miniforge 与 WSL Miniforge `base` 上均得到：实现者未使用的 fixed-order 7 节点通过、
R1 原 8 文件原顺序单进程精确 `153 passed`、G7F unit + golden 精确 `10 passed`。定向 Ruff、mypy、fresh
cold import 与白名单 `git diff --check` 继续绿色。因此本轮结论为 PASS，可提交主 Agent 最终验收。

该结论不等于 G7F 主验、G8、Linux/ext4 或 M3 Gate PASS。WSL 工作树位于 `/mnt/f` DrvFS，仅构成双平台
兼容证据。

本轮只新增本报告。生产代码、实现测试、任务书、已有报告与 artifact 均保持只读；未联网，未访问真实数据、
账户或券商，未执行 add、commit、push 或发布。

## 2. R1 问题与 R2 闭包映射

### 2.1 现象与根因

R1 的 corporate-actions cold 节点在 pytest 已收集 G7E 后，于父进程原地 reload production module。旧 consumer
持有 reload 前 identity，而旧函数的 globals 指向 reload 后 identity，导致 actual G7E formal replay 被 exact
边界正确拒绝。R1 原 153 项因此为 `148 passed / 5 failed`。

### 2.2 R2 最小修复

`tests/unit/test_m3_corporate_actions.py` 的唯一 R2 代码差异为：移除父进程 `importlib.reload`，改由父进程拼装
脚本并调用 `[sys.executable, "-I", "-c", script]`。子进程显式插入当前工作树 `src`，并验证：

- 导入及 reload 前后 `qlib`、`lightgbm`、`mlflow` 均未加载；
- `corporate_actions.__all__` 与冻结 public surface 精确相等，私有 issuer 不可达；
- reload 前签发的旧 state 与 transition 均稳定拒绝，错误仅为
  `M3_A_SHARE_ENTITLEMENT_INVALID`，`cause/context=None`；
- reload 后新签发的 exact state/transition 可完成 pre-open advance，公开 full-day factor mark 可用。

父测试只检查隔离子进程的 return code 并在失败时带出 stderr；它不再改变父进程中已收集 production module 的
class、enum 或 opaque capability identity。production exact type、issuer、phase 与 fresh 语义没有被放宽。

## 3. 只读范围与冻结哈希

R2 交付报告及 R1 冻结值所列 G7F production/tests 当前 SHA-256 精确不变：

- `src/quant/backtest/a_share_reporting.py`：
  `698937e25ae69505497565fe65722e4e694ae2b7b00e50ecf0370332085b3a81`；
- `src/quant/backtest/a_share_simulator.py`：
  `2e123bc293137b468307bd64bd8ede2f4bbbced0ba48b487596461f235605406`；
- `tests/unit/test_m3_g7f_formal_backtest_artifact.py`：
  `b3a28fec24d63f02e259fd1a11e9779b04976976c0ef9986718a0e9b81866a3e`；
- `tests/integration/test_m3_g7f_formal_backtest_artifact_golden.py`：
  `3b13fe167e8586e014ec530c578e2e853d9d513e1ea36caacaf1b639e2f150ce`。

补充记录当前 `corporate_actions.py` 为
`415d8e428e6d2019b92120e10a4b76c65ccebee42a5a4262d9e982a937bee05e`，R2 测试为
`f104e8fe7e831b1ce479f7431db685e49f9b3221d6145a2a10c59ff75c9fe3c6`。

工作树包含大量本任务开始前已存在的 M3 未提交改动。本轮未清理、覆盖或归并这些用户/其他 Agent 工作；只按
白名单审查 R2 测试差异并写本报告。

## 4. 独立对抗性 fixed-order

实现者使用的是 cold → G7E fresh-plan → hostile Decimal → G7E golden 四节点。本轮另行构造未使用顺序，保持
同一 pytest 进程：

1. corporate-actions cold/reload 节点；
2. G7E ex-date 首买不追溯 entitlement；
3. G7E account identity 与 row-order stability；
4. G7E 五 session golden；
5. G7F actual build/verify、三次 G7E 与 21-input/29-output；
6. G7F whole-bundle metrics/receipt drift 拒绝；
7. G7F 三场景 golden。

实际结果：

- Windows：`7 passed`，`598.51s`；
- WSL base：`7 passed`，`493.08s`。

这证明 cold/reload 节点之后不仅 G7E 正向可用，而且 entitlement 时间语义、row-order、golden、G7F actual
builder/verifier、整包重哈希拒绝与三场景 golden 均不受父进程 identity 污染。

## 5. 强制回归与 G7F 合同

### 5.1 R1 原 153 项

按 R1 报告冻结的原文件顺序，在每个平台各一个 pytest 进程运行：

1. `test_m3_backtest_plan_artifact.py`；
2. `test_m3_nested_artifact_publication.py`；
3. `test_m3_formal_a_share_market_facts.py`；
4. `test_m3_corporate_actions.py`；
5. `test_m3_formal_a_share_open_execution.py`；
6. `test_m3_formal_a_share_session_execution.py`；
7. `test_m3_g7e_formal_a_share_simulator.py`；
8. `test_m3_g7e_formal_a_share_simulator_golden.py`。

实际结果：

- Windows：`153 passed`，`666.92s`；
- WSL base：`153 passed`，`459.19s`。

未排除 cold 节点、未调整顺序、未把 153 项拆为多个 pytest 进程。审查过程中曾误选名称相近的
`test_m3_formal_backtest_plan_artifact.py`，得到双平台 `147 passed`；发现摘要不等于冻结的 153 后立即判定该次
命令无效，并以上述正确原文件重跑。无效的 147 项结果未用于 PASS 结论。

### 5.2 G7F unit + golden

- Windows：`10 passed`，`469.37s`；
- WSL base：`10 passed`，`379.36s`。

当前 revision 上，R1 已通过的 hostile Decimal、三次 actual G7E、21-input/29-output、whole-bundle drift、
tree/receipt、terminal exit、turnover/rejection 口径与三场景 golden 关键测试均仍在并通过。R2 未修改这些
production/tests；无需把 R1 全部手工攻击机械重做一遍。

测试警告仅为既有 Pandera/Polars deprecation 与工作树 `.pytest_cache` 无写权限；均未改变测试结果或生产语义。

## 6. 静态、cold 与 diff

Windows 与 WSL base 均实际通过：

- Ruff：`a_share_reporting.py`、backtest `__init__.py`、两个 G7F 测试及 R2 corporate-actions 测试，
  `All checks passed!`；
- mypy：`a_share_reporting.py`，`Success: no issues found in 1 source file`；
- fresh `python -I` cold import：同时导入 `a_share_reporting` 与 `corporate_actions`，确认
  `qlib/lightgbm/mlflow` 未加载，`COLD_IMPORT_PASS`；
- 白名单 `git diff --check`：通过，仅有既有 LF/CRLF 提示。

首次并行静态命令中的 mypy 出现工具内部错误，未作为代码失败或通过证据；随后以平台串行、独立临时缓存重跑
并通过。首次 WSL cold-import 因 PowerShell/WSL 引号被承载层拆解而无效，随后用直接 WSL argv 重跑并得到
`COLD_IMPORT_PASS`。无效探针均未计入最终证据。

## 7. 边界与下一步

- 本报告 PASS 只解锁主 Agent 对 G7F R2/G7F 的最终契约验收；独立初验者不宣布主验通过。
- 未运行 Linux ext4；WSL `/mnt/f` DrvFS 结果不能关闭 ext4 Gate。
- 未执行 G8、全量项目 pytest、真实数据、真实网络或账户验证。
- 未重新构造 full G1 retained release；继续遵循 G7F 任务单 §15 的模块化 fixture 证据边界。
- 下一步由主 Agent 复核本报告、R2 diff、冻结哈希、153 项与 G7F 10 项终态，再决定是否关闭 G7F 主验并推进 G8。
