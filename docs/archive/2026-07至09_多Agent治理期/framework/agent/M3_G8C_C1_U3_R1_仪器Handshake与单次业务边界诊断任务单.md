# M3 G8C-C1 U3 R1：仪器 Handshake 与单次业务边界诊断任务单

日期：2026-08-12  
状态：**U3-B 已收口：仪器 Handshake PASS；唯一 Diagnostic FAIL（module fixture setup / owned config 残留 `FileExistsError`）；G7F 14 边界零调用；产品根因未进入；禁止重跑 U3 Diagnostic；待 U4 精确 owned cleanup 后新仪器+唯一新 Diagnostic**  
上游：[M3_G8C_C1_U2_R1_外置观察插件与单次长链诊断报告.md](M3_G8C_C1_U2_R1_外置观察插件与单次长链诊断报告.md) **FAIL / 仪器缺陷已证明**  
交付：[M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断报告.md](M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断报告.md)

## 1. 唯一目标

先用秒级、可重复的微型 pytest handshake 证明**同一份**外置 plugin 和 wrapper 能正确选择唯一 node、记录边界、
捕获 setup/call 错误并完整排空 stdout/stderr；只有 handshake 全部通过，主 Agent 才托管一次新的 Windows honest
public-chain integration，定位 `build_backtest_artifact` 内第一个业务失败边界。

U3 只诊断，不修改生产/仓库测试、不冻结产品修复、不宣布 C1/G8/G7F/Gate。

## 2. 三阶段职责

### 2.1 U3-A：全新 Cursor `auto` 仪器准备与 handshake

只允许在新临时目录创建 plugin、参数化 wrapper、微型 probe/test 和准备/handshake 证据；允许执行秒级
handshake，**禁止执行仓库 integration 或任何真实链**。仓库只允许更新本任务状态。

### 2.2 主 Agent：唯一真实链

仅在 U3-A 明确 READY、handshake 满足 §6、integration SHA 未变且无并行 writer/pytest 时，主 Agent 使用
同一 wrapper 的 `Diagnostic` 模式启动一次真实链。运行中不读活动日志、不重复启动。

### 2.3 U3-B：全新 Cursor `auto` 只读取证

真实链终态后只读 production/tests 和临时证据，更新任务状态并写唯一报告：

`docs/framework/agent/M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断报告.md`

不得补跑、改码或把仪器推断写成产品根因。

## 3. 新目录与 no-clobber

固定新目录：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u3-r1-g8-build-diagnostic\`

U3-A 启动前必须不存在；所有文件 exclusive create，禁止覆盖/删除 U1/U2 证据。至少包含：

- `u3_observer_plugin.py`；
- `run_u3_diagnostic.ps1`（同一脚本支持 `Handshake` / `Diagnostic`）；
- `u3_handshake_target.py`、`test_u3_handshake.py`；
- prepare、handshake、diagnostic 各自 evidence/stdout/stderr/observe；
- 短静态结果与 SHA-256。

## 4. Plugin 修正合同

1. 真实目标 nodeid 必须精确等于：
   `tests/integration/test_m3_g8c_c1_backtest_cli.py::test_windows_actual_cli_happy_path_zero_write_boundary_and_canonical_json`；
   禁止按整文件、substring 或 glob 匹配。
2. 使用 `pytest_runtest_protocol` hookwrapper 或等价协议级生命周期，在目标 setup 前安装、teardown 后 `finally`
   恢复；同一目标只能安装一次。
3. Observe 生命周期必须记录 collection 完成、目标 protocol started、setup/call/teardown report outcome，以及安装
   success/failure的 exact exception type；即使 fixture/setup 失败也必须有可审计事件。
4. 只有进入目标 protocol 才 exclusive create diagnostic observe；同文件的 WSL skip 用例不得创建/修改它。
5. 边界包装必须精确覆盖 U2 的 14 项，保持参数、返回、异常、调用次数、顺序不变；bare `raise`；原对象在
   `finally` 恢复。
6. Handshake 模式使用同一 observer/lifecycle/wrapper 核心，只把边界注册表换成 temp probe 的唯一 `ping`
   callable，并用 exact handshake nodeid；不得另写一套“假通过”仪器。
7. 事件严格脱敏：不记录异常文本/repr、路径、配置、帧、原始字节或秘密。

## 5. Wrapper 修正合同

1. 参数仅 `Handshake` / `Diagnostic`；两种模式共享同一进程启动、重定向、超时、终态和哈希实现。
2. 使用单一 `System.Diagnostics.Process`；`WaitForExit(timeout)` 返回 true 后必须再调用无参 `WaitForExit()`
   排空异步 stdout/stderr；超时 kill 后同样无参等待；最后才关闭 writer。
3. 明确记录 wrapper/pytest PID、命令、cwd、精确 PYTHONPATH、MODEL=auto、开始/结束、墙钟、整数 EXIT、输入
   SHA；`finally` 必须写终态。
4. 为避免事件 handler 与 writer 竞态，关闭前解除 handler或证明无参等待已完成全部回调；短测试要能稳定捕获
   已知 stdout 与 stderr marker。
5. Diagnostic 命令固定：

```powershell
D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q -p no:cacheprovider \
  -p u3_observer_plugin tests/integration/test_m3_g8c_c1_backtest_cli.py
```

预算 10800 秒；Handshake 预算不超过 120 秒。

## 6. U3-A READY 的强制 handshake

微型测试文件至少含两个用例：先执行一个 skip，再执行 exact target；target 必须：

- 调用 probe `ping` 一次并得到原返回值；
- 发出唯一已知 stdout marker 与 stderr marker；
- 退出 0。

READY 必须同时证明：

- skip 用例未创建 observe、未安装边界；
- target observe 精确有 protocol/setup/call/teardown 与 `ping started/ok`，无二次安装/O_EXCL；
- stdout/stderr 文件分别包含预期 marker且非空；
- evidence 有 `STATUS=FINISHED`、明确整数 `EXIT=0`；
- plugin/wrapper py_compile/PowerShell AST/Ruff/import smoke/14 production boundary existence全绿；
- 仓库 integration SHA 仍为
  `5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2`；
- 没有启动真实链。

任一不满足即 U3-A FAIL，主 Agent不得运行 Diagnostic。

## 7. 真实链观察边界

精确沿用 U2 的 14 项：G8 `build_backtest_artifact`；G7F `_formal_bundle`、formal inputs/plan/facts/config、
三场景 simulation、metrics/parquet/scenario manifest、readback；P0 write/read/commit。每条事件仅记录 boundary、
seq、call_n、status、canonical multiplier、exact return/exception type、public code/int exit_code、cause/context None。

## 8. 文件白名单与禁止项

仓库永久写入仅允许本任务状态与唯一 U3-B 报告。production、tests/support、config/schema、正式 artifact/data、
U1/U2 任务/报告全部只读。临时文件仅 §3 新目录。禁止联网、add/commit/push、秘密、真实数据内容、重跑
U1/U2 或重复 U3 Diagnostic。

## 9. 停止条件

目录已存在；handshake 任一断言失败；边界名漂移；wrapper 流未排空；integration SHA 漂移；存在其他 writer/
同链 pytest；需要改仓库代码；证据可能泄密；第一次 U3 Diagnostic 已启动后任何人请求重跑。命中即停止并写
FAIL，不迁就、不猜产品根因。

## 10. U3-B 结论与后续

报告必须写“现象—根因（证明程度）—规则—最小复现—新增测试建议—通过条件”，列全部证据 SHA，明确首个
失败边界、之前/之后调用次数和分类。只有定位到可复现产品/fixture边界，主 Agent才冻结最小实现返工；随后仍
走“全新 Cursor 实现 → 另一全新 Cursor 独立初验 → 主验”。
