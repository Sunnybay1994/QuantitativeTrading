# M3 G8C-C1 R2：单次长链证据与静态门禁返工交付报告

日期：2026-08-12  
角色：外部实现 Agent（模型 `auto`；不声称具体底层模型；全新上下文）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
任务单：[M3_G8C_C1_R2_单次长链证据与静态门禁返工任务单.md](M3_G8C_C1_R2_单次长链证据与静态门禁返工任务单.md)  
前置：[M3_G8C_C1_R1_外部实现中止与返工记录.md](M3_G8C_C1_R1_外部实现中止与返工记录.md) **FAIL**  
UA-AGENT-001：已批准；未接触 token/账号/私密配置/受许可原始数据/正式 data 内容。  
结论：**R2 FAIL。** 三个定向 mypy 诊断与全部短门禁已闭合；最终 revision 的 Windows honest integration 只启动一次并留下可审计终态，但 EXIT=1。未重跑。不得进入独立初验，不得宣布 C1/G8C/M3/ext4 Gate。

## 1. 白名单与实际改动

| 路径 | 处置 |
|---|---|
| `tests/unit/test_m3_run_cli.py` | 仅补 §3 类型证明：`LoadedM3Config` / `M3RuntimeIdentityV1` 的 exact `isinstance`，以及 `frozen` 的 `tuple` 证明 |
| `src/quant/research/run_m3.py` | 未改（focused 未证明新的 R1 生产缺陷；长链失败后按停止条件不再扩改） |
| C1 unit/integration 测试 | 未改 |
| `docs/M3实施与Agent交接.md` | 只同步 C1 R2 FAIL 状态 |
| 本 R2 任务单 | 状态 → 外部实现 FAIL |
| 本交付报告 | 新增 |

未改 R1 任务/中止记录/C0 support/上游生产与测试。未联网、未 add/commit/push。未删除历史脏文件。未使用 `# type: ignore` / `Any` / fake verified / `SimpleNamespace` 构造 / `object.__new__`。

## 2. 短门禁（长链前全部 PASS）

Windows 解释器：`D:\Miniforge3\python.exe`，cwd=本 worktree，`PYTHONPATH=src`。  
WSL：`/home/mabw/miniforge3/bin/conda run -n base`，cwd=`/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`，`PYTHONPATH=src`。

| 检查 | 终态 |
|---|---|
| Windows focused unit | **80 passed, 1 skipped**；EXIT=0 |
| Windows Ruff | All checks passed |
| Windows mypy `--follow-imports=silent`（4 files） | **Success: no issues found in 4 source files** |
| Windows cold import `run_m3` | `COLD_HEAVY=NONE`；`COLD_BANNED=NONE`（未加载 `qlib`/`lightgbm`/`mlflow`/`lgb`/`formal_cli_resolve`/`backtest_stage`） |
| scoped `git diff --check` / trailing | EXIT=0；`TRAILING=NONE` |
| 白名单 | 本轮生产/测试写集仅 `tests/unit/test_m3_run_cli.py` 类型证明；其余 C1 候选为 R1 保留 |
| 无其他 writer / 无活 C1 pytest | 启动前确认 |
| WSL unit / Ruff / mypy / cold | **81 passed**；Ruff PASS；mypy Success 4 files；`COLD_OK=True` |
| WSL capability / fstype | `renameat2=False`；`sys.platform=linux`；`stat -f`=`wslfs`；`df -T`=**drvfs**。只作兼容证据，不宣称 Linux/ext4 Gate |

候选 SHA-256（长链启动前，之后未再改这些文件）：

| 文件 | SHA-256 |
|---|---|
| `src/quant/research/run_m3.py` | `573fd24eb363181f2d98edd69b71bf94d6a885f902de26e68b25987fee059060` |
| `tests/unit/test_m3_run_cli.py` | `f26023a01d8cea242788c6b701c0d5a53c4a2116fa279e730e972a130adceb32` |
| `tests/unit/test_m3_g8c_c1_backtest_cli.py` | `5af772327f774d9560096c014f5db2f261a9c1691a0808ae684891f358a0afca` |
| `tests/integration/test_m3_g8c_c1_backtest_cli.py` | `9549b74b111851271b53dbc4da5a33bcd622d2c6deaa653d8a8e17d9d6dbab5c` |

## 3. 唯一 Windows honest integration

最终 revision 于 2026-08-12T03:25:54+08:00 启动 **一次**，由独立 wrapper 自然回收；未启动第二次 pytest。

```text
PYTHONPATH=<worktree>/src
D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q -p no:cacheprovider tests/integration/test_m3_g8c_c1_backtest_cli.py
```

`m3chain312` 在清空 `PYTHONPATH` 时会导入 `D:\Miniforge3\envs\m3chain312\Lib\site-packages\quant`；wrapper 因此显式把 worktree `src` 放进 `PYTHONPATH`，否则会测到错误树。

| 字段 | 实测 |
|---|---|
| 证据文件 | `C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-r2-honest-integration\M3_G8C_C1_R2_honest_integration_evidence.txt` |
| 证据 SHA-256 | `ee8fa3d3ef555cd4027ee64b2e6ffa217fb1e05adab67abd31bd11d2c477f447` |
| stdout / stderr | 同目录 `..._stdout.txt`（3639 B）/ `..._stderr.txt`（0 B）；未把大日志复制进仓库 |
| WRAPPER_PID / PYTEST_PID | 27204 / **11088** |
| START / END | 2026-08-12T03:25:54+08:00 / 2026-08-12T04:32:48+08:00 |
| 墙钟 | **4014 s**（<10800） |
| pytest 摘要 | `1 failed, 1 skipped, 196621 warnings in 4010.34s (1:06:50)` |
| EXIT | **1** |
| 子进程 / `_f0r*` | pytest/wrapper 已退出；`artifacts/research/m3/_f0r*` 为空；摘要无 teardown ERROR |

失败节点：`test_windows_actual_cli_happy_path_zero_write_boundary_and_canonical_json`  
断言：`tests/integration/test_m3_g8c_c1_backtest_cli.py:109` → `assert code == 0` → **`assert 5 == 0`**。  
其前断言已证明 stdout 恰一行且可 `json.loads`；`-q` traceback **未打印**该 JSON 的 `error_code`。fixture repr 含 `total_seconds=2351... file_counts={'g1': 18, 'stage_tree': 2448}`，总墙钟 4010 s，说明失败发生在 public chain 建成之后的 actual CLI/`run_formal_backtest_stage` 路径，而不是快速 config/resolve 短路。skip 为 Windows 上的 WSL capability 节点。  
按 §4/§7：EXIT 非零即 R2 FAIL，**禁止重跑**以补看 payload。

## 4. 现象—根因—规则（长链）

- 现象：唯一 honest integration 自然结束，EXIT=1；`main(...)` 返回 5。
- 根因：本会话在不重跑的前提下，不能把 5 精确归到某一个冻结码（`FORMAL_CLI_ARTIFACT_MISSING` / `FORMAL_CLI_CLOSURE_DRIFT` / `STAGE_*` / `M3_COMMAND_FAILED`）。测试先断言 `code == 0`，`-q` 不展示 payload。
- 应遵循规则：R2 §4/§7.4；缺少 error_code 不得靠第二次长链补证。
- 最小复现：§3 唯一命令 + 证据文件。
- 新增测试：本轮不改 integration（改完也不能再跑官方长链）。
- 通过条件：须由主 Agent 另冻 R3；建议失败时先断言/暴露 canonical `failures[0].error_code`，再决定是否最小修生产。

## 5. 禁止项自检

| 项 | 本轮 |
|---|---|
| 第二次官方长链 | **未做** |
| 读活动日志替代等待 | **未做**；只在 FINISHED 后读终态摘要 |
| 删除历史脏文件 | **未做** |
| 联网 / add / commit / push | **未做** |
| 宣布 Gate / 独立初验 PASS | **未做** |

## 6. 给主 Agent / 未来 R3

- 不要启动 R2 独立初验。
- 下一轮必须新冻 R3；实现与初验仍用不同全新 Cursor `--model auto` 会话。
- 证据文件保留在系统临时目录，勿当 PASS。
- 短门禁与 mypy 类型证明可复用，但不能推断 C1 生产合同已通过。
