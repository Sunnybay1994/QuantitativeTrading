# M3 G8C-C0 F0 R5：fixture teardown 零残留观测独立复验报告

日期：2026-08-12  
角色：外部独立初验 Agent（模型 `auto`；不声称具体底层模型；未参与 R5 实现的全新上下文）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
解释器：exact `D:\Miniforge3\envs\m3chain312\python.exe`（`PYTHONPATH=src`；cwd=本 worktree）  
任务单：[M3_G8C_C0_F0_R5_fixtureTeardown零残留观测返工任务单.md](M3_G8C_C0_F0_R5_fixtureTeardown零残留观测返工任务单.md)  
交付报告：[M3_G8C_C0_F0_R5_fixtureTeardown零残留观测返工交付报告.md](M3_G8C_C0_F0_R5_fixtureTeardown零残留观测返工交付报告.md)  
前置 R4 复验：[M3_G8C_C0_F0_R4_ownedCleanup来源绑定独立复验报告.md](M3_G8C_C0_F0_R4_ownedCleanup来源绑定独立复验报告.md)  
UA-AGENT-001：已批准；未接触 token/账号/私密配置/受许可原始数据/正式 data 内容。

## 结论

**PASS** — 仅解锁主 Agent 主验。  
不宣称 C0/C1、G8C、M3 或 ext4 Gate PASS。  
实现者交付报告 §4 未回收的长链摘要、23:01 FileExistsError 重试、以及任何进程退出后扫描，**均不得**当作本轮 PASS。本会话在最终 revision 上只启动一次 Windows honest public-chain，并独立取得：

`...........s` → **11 passed, 1 skipped**, 198745 warnings in **6846.60s**（1:54:06，<7200）；**EXIT=0**；无 `F`/`E`；fixture teardown 断言作为 pytest 生命周期执行且通过。

## 1. 角色与只读边界

- 生产、`tests/support`、实现者测试、任务书与既有报告：**只读**。
- 唯一写入仓库：本报告。
- 独立探针与长链 marker 仅系统 TEMP；探针目录已在长链前精确删除；长链 marker 在写入本报告后精确删除。未清理或改动既有脏文件。
- 未联网、未 add/commit/push、未写正式 `data/` / 长期 artifact、未触其他 worktree。
- 未改 production verifier/issuer；未使用 fake verifier / private issuer / `SimpleNamespace` / `object.__new__` / replace verified capability。未构建第二条真实 G1。

## 2. 标准—证据—结论（逐项）

| 冻结项 | 独立证据 | 结论 |
|---|---|---|
| R5 只改 integration fixture 生命周期与任务/报告白名单；`session.py` 保持 R4 final SHA256；`src/` 不因 R5 改动 | `session.py` SHA256=`B4AD0BF4BC181657F870D7800BD58A5518312E72F7146C1B2A6AEF531ADE5646`（启动前与长链后两次）；mtime=2026-08-11 17:01:14（R4）；339 行。测试文件 mtime=21:19:07。`src/quant/research/m3/formal_cli_resolve.py` mtime=03:15:35，早于 R5。support 仍 4 模块 15+60+339+817=**1231** | **PASS** |
| module fixture 在 `with` 内保存 stage/config/G1 exact paths 并 `yield`；`with` 退出后、teardown 内裸断言三路径不存在、`_f0r*` 空、report 非空且精确三处 `removed:{path}` | 源码 `formal_chain_locator` L336–367：赋值在 `with` 内、`yield` 后断言在 `with` 外；无 `try/except` 降级。已删 `_wait_path_gone` / `zero_residuals`；测试文件无 `time.sleep` | **PASS** |
| 不得用 `_wait_path_gone`、独立 zero_residuals 测试、sleep/polling、事后扫描替代 | 测试文件扫描上述针均为 False。`session.py` 仅保留 R4 `_remove_verified_dir` 的 0.1s 同 inode `rmdir` 重试，非 R5 残留观测 | **PASS** |
| 实现者未用的 TEMP teardown 顺序/失败传播探针 | §4：yield 期三路径在且 report=`[]`；`with` 后三路径消失且 3×`removed:`；teardown 逆断言 → pytest **ERROR**、EXIT=1 | **PASS** |
| R4 六个 cleanup 对抗（ABA/不刷新/类型-link/检查异常/正常清理） | Windows `-k test_owned_cleanup_`：**6 passed**, 6 deselected；EXIT=0；3.43s / 5141ms | **PASS** |
| Windows Ruff / mypy / cold import | Ruff All checks passed（266ms）；mypy Success 1 file（2641ms）；cold `qlib`/`lightgbm`/`mlflow`/`lgb` **NONE**（3737ms） | **PASS** |
| WSL base capability=False；cleanup 快速节点；fstype 非 ext4 | `capability=False`；`sys.platform=linux`；`-k "test_owned_cleanup_ or test_wsl_capability_gate"` **7 passed**；`stat -f`=`wslfs`；`df -T`/`findmnt`=**drvfs** | **PASS**（兼容证据，**非** ext4 Gate） |
| 最终 Windows honest public-chain 只启动一次；独立取得摘要/EXIT；teardown 实际执行 | §5：PID 21192 一次；`11 passed, 1 skipped`；EXIT=0；无 ERROR。未用退出后扫描补 PASS | **PASS** |
| 白名单 / 本会话无生产改动 | 本会话只写本报告。工作树既有 `src/` 脏状态对话开始即存在，非 R5、非本复验写入 | **本会话遵守**；跨 Gate 脏树交主验知悉 |

## 3. 快速节点 / 静态 / WSL（先于长链）

启动前复查：无活 `formal_cli_resolve`/`m3chain312` pytest；session config 不存在；`_f0r*`=0；`data/clean/m3_g1/releases` 空。旧 python PID 29532（`D:\Miniforge3\python.exe`，2026-08-09）与本目标无关，未触动。

| 检查 | 终态 | 墙钟 | 首次失败 / skip |
|---|---|---|---|
| 独立 TEMP teardown 顺序+失败传播探针 | **1 passed, 1 error**；`ERROR at teardown`；EXIT=**1**。yield JSON 三路径 True、report=`[]`；after-with 三路径 False、3×`removed:` | pytest 5.17s / 6733ms | 有意失败（逆残留断言） |
| Windows `-k test_owned_cleanup_` | **6 passed**, 6 deselected；EXIT=0 | 3.43s / 5141ms | 无。`.pytest_cache` WinError 5（非本任务写入） |
| Windows Ruff（改动测试文件） | All checks passed；EXIT=0 | 266ms | 无 |
| Windows mypy `--follow-imports=silent`，`PYTHONPATH/MYPYPATH=src` | Success: 1 source file；EXIT=0 | 2641ms | 无 |
| cold import（`formal_cli_resolve` + 四 support + 本测试模块） | `COLD_BANNED_HITS=NONE`；EXIT=0 | 3737ms | 无 |
| 测试文件空白 / 禁词扫描 | trailing=NONE；无 `_wait_path_gone`/`zero_residuals`/`time.sleep`/`SimpleNamespace`/`object.__new__` | — | tracked `git diff --check` EXIT=0（该文件对 index 为 untracked） |
| WSL fstype | `stat -f`=`wslfs`；`df -T`/`findmnt`=**drvfs**；**非 ext4** | 含在 WSL 19935ms | 不宣称 ext4 Gate |
| WSL capability | `platform_supports_renameat2_noreplace()=False`；`sys.platform=linux` | 同上 | skip 语义，非 PASS |
| WSL `-k "test_owned_cleanup_ or test_wsl_capability_gate"`（`PYTHONPATH=src`） | **7 passed**, 5 deselected；EXIT=0 | pytest 2.02s / WSL 约 20s | capability 节点在 Linux 写前 skip；非长链 |

## 4. 独立对抗（实现者未用）

实现者拆成三次 TEMP：generator LIFE、pytest 事件序、`assert False` teardown。  
本会话只用**一次** pytest 调用，且失败谓词与实现者不同：

1. module fixture 镜像 R5：`with` 内创建 TEMP 三路径（stage 目录 / config 文件 / g1 目录），绑定真实 `_entity_token`，yield 期间清空并观察 `_LAST_OWNED_CLEANUP_REPORT`；`finally` 调真实 `_owned_cleanup`。
2. 测试体写 `during_yield.json`：三路径存在、子文件存在、report=`[]`。
3. `with` 退出后写 `after_with.json`，再断言「任一路径仍存在」。cleanup 成功则该断言失败 → teardown ERROR。
4. TEMP `conftest.py` 的 `pytest_runtest_makereport` 只在 `when=="teardown"` 落盘 `excinfo`。
5. **禁止** `public_formal_chain_session`、真实 G1、fake verifier/issuer/`SimpleNamespace`/`object.__new__`/replace capability。

| 观测 | 实测 |
|---|---|
| yield 期 | `stage/config/g1/child` 均为 true；`cleanup_report=[]` |
| `with` 后 | 三路径 false；report 精确三行 `removed:{stage,config,g1}` |
| hook | `when=teardown`；`excinfo_type=AssertionError` |
| pytest | `.E`；**1 passed, 1 error**；`ERROR at teardown of test_yield_period_...`；EXIT=**1** |
| 残留 | owned 三路径已由真实 cleanup 删除；探针目录长链前已 `Remove-Item`；`PROBE_LEFT=False` |

这同时证明：零残留观测窗口必须在 `finally`/`_owned_cleanup` 之后；且 teardown 裸断言失败会使 pytest 非零，不能被 warning/日志吞掉。

## 5. 唯一一次 Windows honest public-chain

抗重连：启动前在 `%TEMP%\m3_g8c_c0_f0_r5_indep_r5v1_longchain\` 建立本轮唯一 `pid/output/error/exit/started/cmd` marker。本会话无恢复重连；未发现第二份 marker，也未第二次启动 pytest。活着时只查 PID/exit marker，**未读** `output.txt`/`error.txt`。

```text
$env:PYTHONPATH='src'
D:\Miniforge3\envs\m3chain312\python.exe -m pytest tests/integration/test_m3_g8c_c0_formal_cli_resolve.py -q --tb=line
```

| 字段 | 实测 |
|---|---|
| marker | `%TEMP%\m3_g8c_c0_f0_r5_indep_r5v1_longchain\` |
| 启动 | 2026-08-11T23:32:44+08:00 |
| pytest PID | **21192**（wrapper 51868） |
| 进程结束 | 2026-08-12T01:26:54+08:00 |
| pytest 墙钟 | **6846.60s**（1:54:06，<7200） |
| wrapper elapsed | 6855061ms |
| 进度行 | `...........s`（11 点 + 1 skip；无 F/E） |
| 摘要 | **11 passed, 1 skipped**, 198745 warnings |
| EXIT | **0**（`exit.txt`=`0`；stderr 空） |
| 首次 skip | 进度行末位 `s` = Windows 上 `test_wsl_capability_gate_skips_before_chain_writes`（非 PASS） |
| teardown | 无 `ERROR at teardown`。五节点请求了 module fixture；pytest 在打印摘要前执行 fixture teardown。独立探针已证明同构 teardown 失败会变成 ERROR/非零。因此本摘要是 teardown 断言**已执行且通过**的进程内证据 |
| 事后扫描 | **未做**，也不得补成 PASS |

实现者 §4 未回收摘要与 23:01 重试 **不是**本轮证据。

## 6. 现象—根因—规则 对照

R4 失败：独立 `zero_residuals` 跑在 module fixture teardown 之前，读到活 session（路径仍在、report=`[]`）。  
R5 修复：删除该节点与 `_wait_path_gone`；把零残留裸断言移到 `with` 退出之后、仍在 fixture teardown 内。  
本轮：源码合同成立；独立探针证明观测窗口与失败传播；官方长链 11/1/0 且无 teardown ERROR。R4 身份绑定六节点仍绿。

## 7. 禁止项与范围

| 项 | 本轮 |
|---|---|
| 本会话改 production / support / 实现者测试 | 无 |
| 联网 / add / commit / push | 无 |
| 正式 data / 长期 artifact / 其他 worktree | 无 |
| 重复或并发长链 | **无**（仅 23:32:44 PID 21192 一次） |
| 把实现者未回收长链或退出后扫描当 PASS | **无** |
| fake verifier / 第二条真实 G1 | **无** |
| 工作树既有 `src/` 脏文件 | 对话开始已存在；非 R5 白名单、非本会话写入 |

## 8. 非声明

- 本报告 **PASS 只解锁主 Agent 主验**，不关闭 C0/C1，不宣布 G8C / M3 / Linux·ext4 Gate PASS。
- WSL 本轮仅为 DrvFS/wslfs 上的 capability=False 与 cleanup 快速节点。
- `.pytest_cache` WinError 5 / Errno 13 为既有权限警告，非本任务写入。
