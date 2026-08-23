# M3 G8C-C1 U2 R1：外置观察插件与单次长链取证任务单

日期：2026-08-12  
状态：**U2-B 已收口：FAIL/证据不足；工程仪器根因已证明（无法进入首个业务边界）；禁止重跑 U2 长链；不得冻结产品修复；待 U3 秒级先验后单次真链**  
上游：[M3_G8C_C1_U1_R1_G8Build分层透明诊断报告.md](M3_G8C_C1_U1_R1_G8Build分层透明诊断报告.md) **FAIL / 证据不足**  
U2-B 报告：[M3_G8C_C1_U2_R1_外置观察插件与单次长链诊断报告.md](M3_G8C_C1_U2_R1_外置观察插件与单次长链诊断报告.md) **FAIL**

## 1. 唯一目标

在不依赖 Cursor 会话持续存活的前提下，只运行一次 Windows honest public-chain integration，取得
`build_backtest_artifact` 内第一个失败边界的可审计证据。U2 只诊断，不修生产、不宣布 Gate。

## 2. 三阶段职责分离

### 2.1 U2-A：外部 Cursor `auto` 准备

全新 Cursor 会话只做短任务：

- 只读核对 U1 任务、报告和当前 production callable；
- 在新的系统临时目录写 `u2_observer_plugin.py` 与 `run_u2_diagnostic.ps1`；
- plugin 通过 pytest hook 在目标测试调用前临时包装冻结边界，参数/返回/异常/顺序完全透明；
- 包装范围与 U1 §4 精确相同；事件格式与秘密排除规则沿用 U1 §3；
- wrapper 使用单一 `System.Diagnostics.Process`，明确记录 PID、开始/结束、墙钟、整数 ExitCode、命令、cwd、
  `PYTHONPATH`、`MODEL=auto` 与输入哈希；
- 仅运行 Ruff/py_compile/一个不执行链的 plugin import smoke；**不得启动 pytest 长链**；
- 仓库 production、tests、support 全部只读；结束时报告 `READY` 或 `FAIL`。

### 2.2 主 Agent：唯一长链托管

U2-A READY 后，主 Agent核对 plugin/wrapper 内容和哈希，确认无其他 writer/pytest，再只启动一次 wrapper。
命令必须使用：

```powershell
D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q -p no:cacheprovider \
  -p u2_observer_plugin tests/integration/test_m3_g8c_c1_backtest_cli.py
```

临时目录加入 `PYTHONPATH` 仅用于加载 plugin；工作树 `src` 同时显式加入。最大预算 10800 秒。运行中只低频
检查同一 PID，不读活动日志、不重复启动。wrapper 必须独立于 Cursor 会话自然存活并在 `finally` 写终态。

### 2.3 U2-B：外部 Cursor `auto` 只读取证

长链结束后启动另一全新 Cursor 会话，只读 production/tests 和完成后的临时证据，写唯一持久报告：

`docs/framework/agent/M3_G8C_C1_U2_R1_外置观察插件与单次长链诊断报告.md`

报告给出首个失败边界、前后调用次数、exception exact type/public code、分类、最小返工白名单与秒级回归。
U2-B 不改 plugin、证据、production 或 tests，不补跑长链。

## 3. 冻结边界与观察格式

必须观察：

- `backtest_stage.build_backtest_artifact`；
- `a_share_reporting._formal_bundle`、`_validate_formal_inputs`、`verify_backtest_plan_artifact`、
  `load_verified_a_share_market_facts`、`_formal_config_values`；
- `simulate_formal_a_share_scenario`（记录 canonical multiplier）、`_formal_scenario_metrics`、
  `_formal_parquet_bytes`、`_formal_scenario_manifest`、`_validate_formal_readback`；
- `ArtifactPublication.write_bytes`、`read_bytes`、`commit`。

每条事件只含 boundary、seq、call_n、started/ok/failed、multiplier、exact return/exception type、public code、
exact int exit_code、cause/context 是否 None。禁止异常文本/repr、路径、帧、配置、原始字节、账号或秘密。

## 4. 证据目录与 no-clobber

新目录固定：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u2-r1-g8-build-diagnostic\`

启动 U2-A 前必须不存在。所有文件 exclusive create；若已存在立即 FAIL，不覆盖、不删除。至少包含：plugin、
wrapper、prepare evidence、run evidence、observe JSON、stdout、stderr。每个文件最终 SHA-256 写入 U2-B 报告。

## 5. 文件白名单

仓库永久写入仅允许：

1. 本任务单状态；
2. 唯一 U2-B 诊断报告。

系统临时目录只允许 §4 文件。production、仓库 tests/support、config/schema、正式 artifact/data、U1/R1–R3
历史报告全部只读。禁止联网、add/commit/push。

## 6. 停止条件

任一情况立即停止且不启动/不重跑长链：plugin 不能透明安装；边界名称漂移；短静态检查失败；目录已存在；
存在其他 writer/同链 pytest；wrapper 无法保证整数 EXIT 与 finally；需要修改仓库测试/production/support；证据含
秘密；第一次长链已启动后任何人要求重跑。

## 7. 通过条件与后续

U2 诊断完成要求：唯一长链有明确整数 EXIT、完整 observe 和哈希；U2-B 报告确定首个失败边界或用完整事件
证明仍无法区分；仓库文件无临时观察残留。完成后由主 Agent 冻结最小实现返工，并重新进入“全新 Cursor
实现 → 另一全新 Cursor 独立初验 → 主验”。
