# M3 G8C-C1 U2 R1：外置观察插件与单次长链诊断报告

日期：2026-08-12  
角色：外部 Cursor `auto` 独立只读取证（U2-B）；未参与 U2-A 准备  
模型：`auto`（不声称具体底层模型）  
结论：**FAIL / 证据不足（业务首失败边界未定位）；不得冻结产品修复；禁止重跑本轮长链**

证据目录（只读核验）：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u2-r1-g8-build-diagnostic\`

## 1. 现象（已证明事实）

唯一 pytest 长链已结束，终态明确：

| 字段 | 值 |
|---|---|
| `STATUS` | `FINISHED`（run evidence 尾部） |
| `EXIT` | `1` |
| `ELAPSED_SEC` | `6` |
| `WRAPPER_PID` | `22180`（核验时已 EXITED） |
| `PYTEST_PID` | `24072`（核验时已 EXITED） |
| `START` / `END` | `2026-08-12T13:17:47+08:00` / `2026-08-12T13:17:53+08:00` |
| `MODEL` | `auto` |
| `SUMMARY` | 空 |

`phase_u2_observe.json` 终态精确为：

```json
{"boundaries":{},"events":[],"first_failure":null,"model":"auto"}
```

`M3_G8C_C1_U2_R1_diagnostic_stdout.txt` / `..._stderr.txt` 长度均为 0。

Integration 测试 SHA 仍冻结为
`5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2`
（与 U1/U2 任务单、prepare/run evidence、本轮复算一致）。仓库 production/tests/support 本会话未改。

因此：**没有**可用于判定 G7F/G7E/G7D、fixture 或 publication「第一个业务失败边界」的 observe 事件；不能猜业务根因。

## 2. 文件哈希清单（本轮复算 SHA-256）

| 文件 | 长度 | SHA-256 |
|---|---:|---|
| `u2_observer_plugin.py` | 9617 | `7706fa0b0147e0e3036c1acdfad1e3a140c768430f5f60c34d448af297e5448c` |
| `run_u2_diagnostic.ps1` | 6249 | `0a68941aa1ea8519726857fd18b3e5157b9d7f8bf0556f3a87f836a97dfff5fe` |
| `u2a_short_static_checks.txt` | 1292 | `11fd28a606bcc32214e2d3eaa81a6694d6fd2954097f27f7efdd94189a4ac777` |
| `M3_G8C_C1_U2_R1_prepare_evidence.txt` | 1026 | `f86832972589f1879d15b231d6e4562b6262463ee591265d58dd36d3dc510341` |
| `M3_G8C_C1_U2_R1_run_evidence.txt` | 1355 | `9267fe4bc01d4ac0a2beaf56d99daa979c200cd7f9ff21c9120fc222b61b2232` |
| `phase_u2_observe.json` | 65 | `cb8f6dde506184228713ac8eb48b3b6aeb51249aa59fd413571689fc07c0609d` |
| `M3_G8C_C1_U2_R1_diagnostic_stdout.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `M3_G8C_C1_U2_R1_diagnostic_stderr.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/integration/test_m3_g8c_c1_backtest_cli.py`（工作树） | — | `5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2` |

prepare/run evidence 内记载的 plugin/wrapper/integration SHA 与上表一致。

## 3. 只读审计要点

### 3.1 Wrapper（`run_u2_diagnostic.ps1`）

- 单一 `System.Diagnostics.Process`；记录 PID、命令、cwd、`PYTHONPATH`、`MODEL=auto`、输入哈希；`finally` 写 `STATUS/END/ELAPSED_SEC/EXIT`。
- 命令与任务单冻结命令一致；`PYTHONPATH` 含证据目录与工作树 `src`；设置 `M3_G8C_C1_U2_R1_OBSERVE_PATH`。
- stdout/stderr 经 `BeginOutputReadLine` / `BeginErrorReadLine` 异步写入；使用 **`WaitForExit($budgetMs)` 超时重载**后直接 `Refresh`/`ExitCode`，**未**再调用无参 `WaitForExit()` 排空异步流，并在 `finally` 立即 `Dispose` StreamWriter。

### 3.2 Plugin（`u2_observer_plugin.py`）

- 14 个冻结边界名称与 U1 §4 / 短静态 `BOUNDARIES=14` 一致；短静态 `py_compile/ruff/import_smoke=PASS`。
- 安装点仅为 `pytest_runtest_call` hookwrapper；`_is_target_item` 用整文件路径
  `tests/integration/test_m3_g8c_c1_backtest_cli.py` 匹配（该文件含 **2** 个 `test_*`）。
- Observe 文件：`O_CREAT|O_EXCL` 独占创建；构造时即 `_write_snapshot()`（空 `boundaries/events`、`first_failure=null`、`model=auto`）。
- Windows 上先跑的 `test_wsl_capability_gate_skips_before_chain_writes` 在 **call** 阶段 `pytest.skip`；会先 `_install()` 再 skip。
- 其后 `test_windows_actual_cli_happy_path_...` 再次 `_install()` 时，同一 `phase_u2_observe.json` 已存在 → **`FileExistsError`（源码可证）**，真链 call 无法完成透明包装。

### 3.3 为何「无法进入第一个业务边界」（工程层，已证明）

**已证明：**

1. Observe 终态格式只能由 `_U2LayerObserver._write_snapshot` 产生 → 至少发生过一次 `_install()`。
2. `events`/`boundaries` 为空且 `first_failure=null` → 14 个包装边界 **从未被调用**。
3. `ELAPSED_SEC=6` + `EXIT=1` 与「未进入 honest public-chain 长业务路径」相容；与「已进入 `build_backtest_artifact` 内部再失败」不相容（后者应留下边界事件或显著更长墙钟；本轮无事件）。
4. Plugin 源码证明：整文件匹配 + 独占 observe + Windows 首用例 skip 安装 → 次用例安装失败 → **诊断仪器在真链 call 前失效**。这就是当前证据无法进入首个业务边界的直接工程原因。
5. Wrapper 源码证明：`WaitForExit(timeout)` 后不排空异步 stdout/stderr 即关闭 writer，构成 **stdout/stderr 丢失机制**（与 0 字节输出、空 `SUMMARY` 一致）。是否「pytest 完全无字节」无法在丢失机制存在时反证；机制本身已由源码证明。

**未证明（禁止当作结论）：**

- G7F/G7E/G7D 业务缺陷、fixture/窗口不满足、publication/readback 缺陷；
- 任一业务边界的 exception type/public code；
- C1 R3 `STAGE_BUILD_FAILED` 的内部阶段定位（仍停留在 R3 外层结论）。

**补充（推断，非业务根因）：** 若未来排除 O_EXCL 后仍无事件，需再核验
`backtest_stage` 对 `a_share_reporting.build_backtest_artifact` 的 import 绑定与补丁挂载点是否一致；**本轮不必也不应据此猜业务失败点**。

## 4. 现象—根因（证明程度）—规则—最小复现（不得执行）—新增测试建议—通过条件

| 项 | 内容 |
|---|---|
| **现象** | 唯一长链 `EXIT=1`、`ELAPSED_SEC=6`；observe 空事件；stdout/stderr 空；PID 均已退出；integration SHA 仍冻结。 |
| **根因（工程，已证明）** | （A）观察插件在 Windows skip 用例上独占创建 observe，导致真链用例 `_install` 失败，包装从未覆盖业务 call；（B）wrapper 异步流未排空即关闭，stdout/stderr 可丢。 |
| **根因（产品/G7F，未证明）** | 无。 |
| **应遵循规则** | 同一 U2 长链禁止重跑；不得用空日志/空 observe 猜测业务根因；未定位首失败边界前不得冻结生产返工；诊断仪器必须先证明能看到 call 期边界事件。 |
| **最小复现（不得在本会话执行）** | 在临时目录加载同一 plugin：先跑会 skip 的同文件首用例再跑第二用例，或直接对已存在 observe 路径二次 `_install()`，应得到 `FileExistsError`；wrapper 侧用 `WaitForExit(ms)` 短进程对照有/无随后无参 `WaitForExit()` 的捕获差异。 |
| **新增测试建议** | U3 秒级先验：专用微型 pytest + plugin handshake（见 §5）；断言仅匹配真链 nodeid 或 observe 生命周期可多次安装/单会话一次安装；wrapper 契约测试要求非空已知 stdout 被完整落盘。 |
| **通过条件** | 业务诊断通过：完整整数 EXIT + 非空或可解释的 observe 事件链，能指出首个失败边界 **或** 用完整事件证明无法区分；且 stdout/stderr 排空机制已验证。本轮 **未满足**。产品修复冻结通过：须以上业务证据，本轮 **不可冻结**。 |

## 5. 下一轮最小 U3 诊断设计（只设计，本会话不实现、不执行）

目标：在 **再次且仅一次** 真链前，用秒级先验证明「仪器可用」，避免再烧 10800s。

1. **新临时证据目录**（no-clobber）；新 plugin/wrapper 修订仅写 Temp，仓库仍只读（除未来任务单/报告白名单）。
2. **微型 handshake（强制先跑，秒级）**  
   - 专用最小测试模块（Temp 或严格隔离路径）：一个会 `skip` 的用例 + 一个调用「假边界/真实可补丁哑函数」的用例；**或** 明确只匹配真链 `nodeid`。  
   - 必须挂钩并记录：`pytest_collection_modifyitems` / collection 错误、`pytest_runtest_setup` 失败、`pytest_runtest_call` 安装成功/失败（含 exact exception type）。  
   - 断言：handshake 后 observe 含预期 `started/ok`（或故意失败事件），且 **不得** 因 O_EXCL 挡住第二用例。  
   - Wrapper：`WaitForExit(ms)` 为 true 后 **必须** 无参 `WaitForExit()`（或等价排空），再关闭 writer；先验命令应产生已知 stdout/stderr 并断言文件非空、哈希稳定。
3. **真链仍只许一次**：仅当 handshake PASS、边界名无漂移、无并行 writer、integration SHA 仍为冻结值时，主 Agent 托管启动唯一 public-chain；U3-B 另会话只读取证。
4. **仍禁止**：重跑已失败的 U2 长链；在无业务事件时改 production；宣布 Gate。

## 6. 结论

| 判定 | 结果 |
|---|---|
| U2 诊断目标（定位 `build_backtest_artifact` 内首个业务失败边界） | **FAIL** |
| 能否冻结产品/最小实现返工 | **否** |
| 工程仪器缺陷是否已证明 | **是**（plugin observe 生命周期/hook 匹配；wrapper 异步流排空） |
| 长链是否可重跑 | **否**（本轮已启动并终态明确） |
| 下一步 | 主 Agent 冻结 **U3**（秒级 handshake → 单次真链）；重新「外部实现准备 → 主托管真链 → 外部只读取证」 |

本报告为 U2-B 唯一持久交付；不修改 plugin/wrapper/证据/production/tests。
