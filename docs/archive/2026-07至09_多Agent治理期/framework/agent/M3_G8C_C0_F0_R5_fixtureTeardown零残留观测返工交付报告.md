# M3 G8C-C0 F0 R5：fixture teardown 零残留观测返工交付报告

日期：2026-08-11  
角色：外部实现 Agent（模型 `auto`；不声称具体底层模型；全新上下文）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
任务单：[M3_G8C_C0_F0_R5_fixtureTeardown零残留观测返工任务单.md](M3_G8C_C0_F0_R5_fixtureTeardown零残留观测返工任务单.md)  
前置：R4 独立复验 **FAIL**（零残留节点早于 module fixture teardown）；R4 身份绑定对抗本身 PASS  
UA-AGENT-001：已批准；未接触 token/账号/私密配置/受许可原始数据/正式 data 内容。  
结论：**最小生命周期返工已交付并完成实现自测；待全新独立初验。不宣称 C0/C1/G8C/M3/ext4 Gate PASS。官方长链 pytest 摘要因承载层断开未回收，不得用进程退出后扫描补成 PASS。**

## 1. 白名单与实际改动

| 路径 | 处置 |
|---|---|
| `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` | `formal_chain_locator` 在 `with` 内保存 stage/config/G1 exact 路径并 `yield`；`with` 退出后再断言三路径不存在、`_f0r*` 为空、`_LAST_OWNED_CLEANUP_REPORT` 非空且含三个 `removed:{path}`。删除 `test_formal_public_chain_owned_cleanup_zero_residuals` 与 `_wait_path_gone` |
| R4 任务单 | 仅状态/链接 → R5 交付 |
| R3 续跑任务单 | 仅状态/链接 → R5 交付 |
| 本 R5 任务单 | 仅状态 → 实现自测完成待全新独立初验 |
| 本交付报告 | 新增 |

未改 `tests/support/m3_formal_public_chain/session.py`、`src/`、其余 support/tests/config、既有报告、正式 `data/`/长期 artifact、其他工作树。未联网、未 add/commit/push。未使用 fake verifier / private issuer / `SimpleNamespace` / `object.__new__` / replace capability。  
support 仍 4 模块（`__init__`/`g1_inputs`/`session`/`stage_chain`）；R4 身份绑定实现未动。

## 2. 冻结合同如何落地

- 不改 fixture `scope="module"`，不拆第二测试模块，不重复构建真实 G1。
- `yield` 期间 session 仍活；五个 honest/hostile 节点继续复用同一 locator。
- `yield` 返回后 `with` 正常退出，`public_formal_chain_session.finally` 完成 `_owned_cleanup`，然后 fixture teardown 内裸 `assert`（不捕获、不降级 warning）。
- 删除轮询/`sleep`/独立残留测试；禁止进程退出后补扫作为官方 PASS。
- TEMP 探针证明：teardown `assert False` → pytest **ERROR** 且 EXIT=1。

## 3. 验证终态（诚实）

解释器：exact `D:\Miniforge3\envs\m3chain312\python.exe`，cwd=本 worktree，`PYTHONPATH=src`。  
WSL：`/home/mabw/miniforge3/bin/conda run -n base`，cwd=`/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`。

| 检查 | 终态 | 墙钟 | 首次失败 / skip |
|---|---|---|---|
| 无 G1 生命周期探针（TEMP generator + 真实 `_owned_cleanup`） | **LIFE_PASS**；yield 期路径在且 report=`[]`；`with` 后三路径消失且 3×`removed:` | 4420ms | 无 |
| TEMP pytest 顺序探针 | **3 passed**；事件 `setup,yield,user,skipper,independent` 之后才 `after_with`；EXIT=0 | 6769ms | 无 |
| TEMP teardown 失败探针 | **1 passed, 1 error**；`ERROR at teardown`；EXIT=**1** | 3372ms | 有意失败 |
| Windows `-k test_owned_cleanup_` | **6 passed**, 6 deselected；EXIT=0 | pytest 3.07s / 4666ms | 无。`.pytest_cache` WinError 5（非本任务写入） |
| Windows Ruff（仅改动测试文件） | All checks passed；EXIT=0 | 306ms | 无 |
| Windows mypy `--follow-imports=silent`，`PYTHONPATH/MYPYPATH=src` | Success: 1 source file；EXIT=0 | 3478ms | 无 |
| cold import（`formal_cli_resolve` + 四 support + 本测试模块） | 第三方 `qlib`/`lightgbm`/`mlflow`/`lgb` **未**冷导入；`quant.research.m3.fetch_qlib_tool` 仅项目模块名 | 3778ms | 首轮子串误报已纠正，非产品缺陷 |
| scoped `git diff --check` / 空白扫描 | EXIT=0；**WHITESPACE_OK**；源码无 `sleep`/`_wait_path_gone`/`zero_residuals` | — | 白名单测试对 index 为 untracked |
| WSL fstype | `stat -f`=`wslfs`；`df -T`=**drvfs**；**非 ext4** | 含在 WSL 墙钟 | 不宣称 ext4 Gate |
| WSL capability | `False`；`sys.platform=linux` | — | skip 语义，非 PASS |
| WSL `-k "owned_cleanup or wsl_capability"`（`PYTHONPATH=src`） | **7 passed**, 5 deselected；EXIT=0 | pytest 1.99s / WSL 约 24s | 首轮缺 `PYTHONPATH` collection ERROR，已复跑绿 |
| 官方 Windows honest public-chain | 见 §4 | ~7145s | 见 §4 |

## 4. 唯一官方 Windows 长链

最终 revision 上于 21:22:51 启动 **一次**（父 pwsh 42960 → pytest **PID 47056**）：

```text
$env:PYTHONPATH='src'
D:\Miniforge3\envs\m3chain312\python.exe -m pytest tests/integration/test_m3_g8c_c0_formal_cli_resolve.py -q --tb=line
```

| 字段 | 实测 |
|---|---|
| 启动 | 2026-08-11T21:22:56+08:00（pytest 47056） |
| 进程结束 | WaitForExit 返回 2026-08-11T23:22:01+08:00 |
| 墙钟 | **约 7145s**（<7200） |
| pytest 摘要 / EXIT | **未回收**（承载层在等待中断开；stdout 未落入 terminals） |
| 事后扫描（23:22:19，**不得**当 PASS） | `_f0r*`=0；session config 不存在；G1 releases 为空 |

承载层约 23:01 对同一命令重试，撞上仍活的 47056 session：

- `LONGCHAIN_START=2026-08-11T23:01:01+08:00` → 5.21s → EXIT=1  
- `......EEEEEs`；**6 passed, 1 skipped, 5 errors**  
- **首次失败**：module fixture setup `FileExistsError`（`configs/research/_m3_f0r2_chain_session.toml`）  
- 该次 **不是**官方终态，也未再启动第三次长链；活 session 的 config/stage/G1 未手工删除。

因此：**不能**把 11 passed / 1 skipped / EXIT=0 写成已观测事实。独立初验必须自己捕获 fixture teardown 断言与 pytest 摘要。

## 5. Skip 边界

- Windows WSL capability 测试：skip（actual 由 fixture 覆盖）。
- WSL 上请求 `formal_chain_locator` 的五个链上节点：capability=false，写前 skip；teardown 断言不执行（`__enter__` 在 skip 处失败）。
- WSL cleanup 快速节点 + capability 节点：7 passed。

## 6. 禁止项自检

| 项 | 本轮 |
|---|---|
| 改 `session.py` / production / verifier / issuer | 未做 |
| fake verifier / private issuer / SimpleNamespace / replace verified | 未做 |
| 联网 / add / commit / push | 未做 |
| 正式 data 内容读取 / 长期 artifact / 其他 worktree | 未做 |
| 故意第二次官方长链 | **未做**；23:01 为断开重试且 fail-closed |
| 用退出后扫描补 PASS | **未做** |

## 7. 给独立复验

- 必须全新会话、`--model auto`；生产/support/实现测试只读；只写 `docs/framework/agent/M3_G8C_C0_F0_R5_fixtureTeardown零残留观测独立复验报告.md`。
- 补一个实现者未使用的 teardown 顺序探针。
- 先确认无活 `m3chain312`/`formal_cli_resolve` pytest，且 `_f0r*`/session config/G1 releases 为空。
- 快速节点 + Ruff/mypy/cold/WSL 之后，**只启动一次** Windows honest public-chain；核对 teardown 断言实际执行，且失败会使 pytest 非零。
- 不得把本报告 §4 事后扫描或 23:01 FileExistsError 重试当成 PASS。
- 通过后仍只解锁主验，不宣布 C0/C1/G8C/M3/ext4。
