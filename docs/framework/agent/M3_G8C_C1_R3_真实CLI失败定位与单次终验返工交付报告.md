# M3 G8C-C1 R3：真实 CLI 失败定位与单次终验返工交付报告

日期：2026-08-12  
角色：外部实现 Agent（模型 `auto`；不声称具体底层模型；全新上下文）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
任务单：[M3_G8C_C1_R3_真实CLI失败定位与单次终验返工任务单.md](M3_G8C_C1_R3_真实CLI失败定位与单次终验返工任务单.md)  
前置：[M3_G8C_C1_R2_单次长链证据与静态门禁返工交付报告.md](M3_G8C_C1_R2_单次长链证据与静态门禁返工交付报告.md) **FAIL**  
UA-AGENT-001：已批准；未接触 token/账号/私密配置/受许可原始数据/正式 data 内容。  
结论：**R3 FAIL。** Phase A 一次透明诊断已取得 exact payload 与抛出边界；根因属于已主验 G8 `backtest_stage`/`orchestration` 的 stage build，不属于 `run_m3.py` C1 seam。未修改生产接线，未启动 Phase B，未重跑 R2/R3 长链。不得进入独立初验，不得宣布 C1/G8C/M3/ext4 Gate。

## 1. 白名单与实际改动

| 路径 | 处置 |
|---|---|
| `src/quant/research/run_m3.py` | **未改**。证据证明 C1 已按 R1 映射 exact `M3StageRunnerError`/`STAGE_BUILD_FAILED`→exit 5 |
| `tests/integration/test_m3_g8c_c1_backtest_cli.py` | Phase A 曾加入透明包装；诊断结束后移除包装，永久保留 `assert code == 0, payload` |
| `tests/unit/test_m3_g8c_c1_backtest_cli.py` | 未改（已有 STAGE_* 映射回归；本轮缺陷不在 C1 seam） |
| `tests/unit/test_m3_run_cli.py` | 未改 |
| `docs/framework/M3实施与Agent交接.md` | 只同步 C1 R3 FAIL 状态 |
| 本 R3 任务单 | 状态 → 外部实现 FAIL |
| 本交付报告 | 新增 |

未改 `formal_cli_resolve.py`、`backtest_stage.py`、orchestration、C0 support、R1/R2 历史报告、schema/config、正式 data。未联网、未 add/commit/push。未删除历史脏文件。未使用 `# type: ignore` / `Any` 掩盖 / fake verified / `SimpleNamespace` 签发 / `object.__new__`。

最终候选 SHA-256（包装已移除后）：

| 文件 | SHA-256 |
|---|---|
| `src/quant/research/run_m3.py` | `573fd24eb363181f2d98edd69b71bf94d6a885f902de26e68b25987fee059060`（与 R2 相同） |
| `tests/unit/test_m3_run_cli.py` | `f26023a01d8cea242788c6b701c0d5a53c4a2116fa279e730e972a130adceb32` |
| `tests/unit/test_m3_g8c_c1_backtest_cli.py` | `5af772327f774d9560096c014f5db2f261a9c1691a0808ae684891f358a0afca` |
| `tests/integration/test_m3_g8c_c1_backtest_cli.py` | `5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2` |

Phase A 启动时 integration SHA 为 `867c66cc5aa80521478155c724121c391886642e3f42cfc1473ef63da657908d`（含临时包装）；该 revision 只跑了下面这一次诊断链。

## 2. 短门禁

Windows：`D:\Miniforge3\python.exe`，cwd=本 worktree，`PYTHONPATH=src`。  
WSL：`/home/mabw/miniforge3/bin/conda run -n base`，cwd=`/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`。DrvFS/`wslfs` 只作兼容证据，不宣称 ext4 Gate。

| 检查 | Phase A 前 | 移除包装后 |
|---|---|---|
| Windows focused unit | **80 passed, 1 skipped**；EXIT=0 | 同左 |
| Windows Ruff | All checks passed | All checks passed |
| Windows mypy `--follow-imports=silent`（4 files） | Success | Success |
| Windows cold import `run_m3` | `COLD_HEAVY=NONE`；`COLD_BANNED=NONE` | 生产未改，未重做 |
| WSL unit / Ruff / mypy / cold | **81 passed**；Ruff/mypy Success；`COLD_OK=True` | Ruff/mypy Success |
| WSL capability / fstype | `renameat2=False`；`sys.platform=linux`；`stat -f`=`wslfs`；`df -T`=**drvfs** | 未宣称 ext4 Gate |
| scoped `git diff --check` | EXIT=0 | EXIT=0 |
| 无其他 C1 writer/pytest | 启动前确认 | 诊断结束后 PID 37496/33036 已退出；`_f0r*`=NONE |

## 3. Phase A：一次透明诊断长链

于 2026-08-12T04:44:35+08:00 启动 **一次**，独立 wrapper 自然回收；未启动第二次，未读活动日志，未重跑 R2。

```text
PYTHONPATH=<worktree>/src
M3_G8C_C1_R3_DIAG_PATH=<diagnostic>/phase_a_observe.json
D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_m3_g8c_c1_backtest_cli.py
```

| 字段 | 实测 |
|---|---|
| 证据目录 | `C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-r3-diagnostic\` |
| evidence | `...\M3_G8C_C1_R3_diagnostic_evidence.txt` SHA-256 `5f5ffe29634624b7b7f82cdc56a2fca87588860b32700f1298f20a92f9342659` |
| observe | `...\phase_a_observe.json` SHA-256 `299bc2919f2f1b06b00ad4242de5992950d5413d11eee51062e0db68ab286dc4` |
| stdout / stderr | `..._stdout.txt` SHA-256 `b89afbb2d7b25be727106409e8ea5714b00f5e0739356376bf5f9736e0e139ba`（4554 B）；stderr SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`（空） |
| WRAPPER_PID / PYTEST_PID | 33036 / **37496** |
| START / END | 2026-08-12T04:44:35+08:00 / 2026-08-12T05:51:05+08:00 |
| 墙钟 | **3990 s**（pytest 摘要 3986.23s） |
| pytest 摘要 | `1 failed, 1 skipped, 196621 warnings in 3986.23s (1:06:26)` |
| wrapper `EXIT=` 字段 | **空**（`Start-Process`/`Wait-Process` 未回填 `ExitCode`）；摘要与 assertion 已证明失败。未据此重跑 |
| 子进程 / `_f0r*` | pytest/wrapper 已退出；`artifacts/research/m3/_f0r*` 为空；摘要无 teardown ERROR |

透明包装：保存原 callable，原参数原样传入，原返回/原异常原样抛出；只记录边界名、调用次数、exact type、str `.code`、int `.exit_code`、`__cause__ is None`、`__context__ is None`。未记录异常 `str/repr`、路径或配置内容。调用次数与未包装路径一致（resolve×1、stage×1）。

## 4. 六项根因闭环

### 4.1 现象

canonical failure payload（`assert code == 0, payload` 已展示）：

```json
{"command":"backtest","failures":[{"error_code":"STAGE_BUILD_FAILED","exit_code":5,"node_id":"backtest","scope":"command"}],"ok":false}
```

`main(...)` 返回 5。fixture 已建成 public chain（`file_counts={'g1': 18, 'stage_tree': 2448}`，`total_seconds≈2344`）。

exact 边界与调用次数（observe JSON）：

| 边界 | calls | exc_type | public `.code` | public `.exit_code` | cause_none | context_none |
|---|---|---|---|---|---|---|
| `resolve_formal_backtest_cli_inputs` | **1** | null | null | null | null | null |
| `run_formal_backtest_stage` | **1** | `quant.research.m3.orchestration.M3StageRunnerError` | `STAGE_BUILD_FAILED` | null（该类型无此字段） | **true** | **true** |

payload 不是 `M3_COMMAND_FAILED`；C1 按 R1 §4.2 原样透传了 exact StageRunner 码。

### 4.2 根因

被违反的是 **G8 formal backtest stage 的 build 不变量**，不是 C1 CLI 接线：

- C0 resolver 一次成功，说明 project/config/identity/upstream receipt 闭包通过了已主验 resolver。
- Stage 一次真实执行后，`StageRunner` 在 `handler(context)`（`build_backtest_artifact`）处捕获任意异常，并 `raise M3StageRunnerError("STAGE_BUILD_FAILED") from None`（`orchestration.py` 约 566–569 / 660–663 行）。这与 observe 的 exact type、`.code`、`__cause__ is None`、`__context__ is None` 一致。
- C1 seam 没有少调、没有改参数语义、没有把成功改成失败；它只是把已主验 stage 的稳定失败码写成 canonical JSON。
- 内层 build 异常被 StageRunner 故意剥掉，公共字段无法再还原具体哪一条 backtest 输出/覆盖率/成交约束被违反；继续定位必须进入 `backtest_stage.py` / `build_backtest_artifact` / public-chain fixture，超出本轮白名单。

fixture 构建期 LightGBM 有 “0 used features / no meaningful features” 警告，只是给主 Agent 的旁证线索，**不是**本轮可证明的根因细节。

### 4.3 应遵循规则

- R1 §3：`load_m3_config` → `resolve_formal_backtest_cli_inputs` → `run_formal_backtest_stage`，每次 exact 一次。
- R1 §4.2：exact `M3StageRunnerError` 且 code∈冻结集合 → 原样 code / exit 5。
- R3 §5 / §9.3：若缺陷属于 `formal_cli_resolve.py`、`backtest_stage.py` 或更上游，立即停止并写 FAIL；不得扩大 catch、改成成功、弱化 identity/receipt、跳过 verifier 或预建 backtest root。
- G8 StageRunner 合同：build 失败稳定为 `STAGE_BUILD_FAILED`，不向 CLI 泄漏 cause/context/path。

### 4.4 最小复现

- 诚实长链：本轮唯一 Phase A 命令 + observe/stdout 证据（约 66 分钟）。**禁止再跑。**
- 秒级 C1 映射回归：已有 `tests/unit/test_m3_g8c_c1_backtest_cli.py::test_stage_runner_codes_map_to_exit_five` 覆盖 `STAGE_BUILD_FAILED`→exit 5。再写一条同类 unit 不能证明 G8 build 不变量。

### 4.5 新增测试

本轮不新增 C1 unit（根因不在 seam）。永久保留 `assert code == 0, payload`，避免再次出现 R2“有 JSON 但 -q 看不到 error_code”。Phase A 包装已从最终 revision 删除。

### 4.6 通过条件

未满足。短门禁绿不能推断 C1 honest integration PASS。Phase B **未启动**。需主 Agent 另冻 G8 backtest build / public-chain fixture 上游任务；C1 仅在上游可诚实成功后再冻 R4 做无包装单次终验。

## 5. 停止条件自检

| 项 | 本轮 |
|---|---|
| Phase A 改变调用参数/次数/返回/异常 | **未发生**；resolve×1 成功，stage×1 原样抛出 |
| 第二次诊断/R2/Phase B 长链 | **未做** |
| 根因属白名单外已主验模块 | **是** → 停止，不改上游 |
| 弱化 fresh/receipt/identity/脱敏 | **未做** |
| 短门禁 | 全绿 |
| Phase B | **未启动**（§9.3） |
| 联网 / add / commit / push / 删历史脏文件 | **未做** |
| 宣布 Gate / 独立初验 | **未做** |

## 6. 给主 Agent / 未来 R4

- 不要启动 R3 独立初验。
- 不要把 `STAGE_BUILD_FAILED` 当成 C1 映射缺陷去改 `run_m3.py`。
- 下一轮应先冻结 **G8 formal backtest build**（及/或 public-chain mini fixture 是否足以让 `build_backtest_artifact` 成功）的上游任务；C1 R4 只在上游可绿后再做一次无包装 honest integration。
- Phase A 证据保留在系统临时目录，勿当 PASS。
- wrapper `EXIT=` 空缺是 PowerShell `Start-Process` 回收瑕疵；权威终态是 pytest 摘要与 assertion payload。
