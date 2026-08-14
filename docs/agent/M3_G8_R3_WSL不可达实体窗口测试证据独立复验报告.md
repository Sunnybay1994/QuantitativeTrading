# M3 G8 R3：WSL 不可达实体窗口测试证据独立复验报告

日期：2026-08-11  
角色：全新外部独立复验 Agent（未参与 R3 实现）  
模型：`cursor-grok-4.5-high`（实际）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
结论：**PASS**（仅解锁主验；非 ext4 / 非 G8 Gate / 非主验）

依据：`AGENTS.md` / `.ai`；[`M3_G8_R1任务单.md`](M3_G8_R1任务单.md) §13；R2 FAIL：[`M3_G8_R2_G7FQuality与ReleaseContext同步返工独立复验报告.md`](M3_G8_R2_G7FQuality与ReleaseContext同步返工独立复验报告.md)；R3 交付：[`M3_G8_R3_WSL不可达实体窗口测试证据返工交付报告.md`](M3_G8_R3_WSL不可达实体窗口测试证据返工交付报告.md)。

生产代码、实现者测试、任务/既有报告全程只读；本会话唯一仓库写入为本报告。未联网、未 `git add`/`commit`。

## 1. 范围与只读核对

- HEAD：`eace7ebbd61a622a66f9b1cdb6402f42922aae73`
- `src/quant/research/m3/backtest_stage.py` blob SHA：`e7dcd9827098709c94d85b41a5c4214740b8441d`（与 R2/R3 交付一致；本轮未改 production）
- 白名单仅 `tests/unit/test_m3_g8_r1_formal_backtest_stage.py`（tests-only）；全文 **无** `STAGE_PUBLISH_FAILED`
- 后两窗在 `platform_supports_renameat2_noreplace()==False` 时于测试入口、`_case`/构建前：
  `pytest.skip("exclusive commit unsupported; inode window unreachable")`
- capability true：`mut_calls>=1`；后两窗仅 `STAGE_RECOVERY_CONFLICT`；final→receipt 另断言 EntityGuarded≥1 且 base `_publish_static_receipt`=0；`_assert_stage_fail_clean` 保证无 receipt/temp 残留且 cause/context 空
- capability：Windows `True`；WSL/DrvFS `False`（**非 ext4**）

## 2. §13 合同逐项映射

| §13 要求 | 独立证据 | 结论 |
|---|---|---|
| production SHA 仍为 R2 值 | `git hash-object` → `e7dcd982…8441d` | 满足 |
| handler→temp 双平台实跑 | Win 三窗 3 passed；WSL combo 中该窗未 skip（仅后两窗+golden skip）；WSL 爆炸构建探针 `build_hits=1` 且未 skip | 满足 |
| capability false：后两窗构建前窄 skip，准确理由，不接受 `STAGE_PUBLISH_FAILED` | 独立探针 force/false 与 WSL native：`build_hits=0`，理由精确匹配；unit 无该宽码 | 满足 |
| capability true：三窗实际 mutation；temp→final 仅 `STAGE_RECOVERY_CONFLICT`；final→receipt EntityGuarded 且 base publish=0 | 独立 Win 时间线探针（见 §4） | 满足 |
| 实跑失败无 receipt/temp/cause/context | 探针 `receipt_files=0`/`tmp_files=0`/`cause_none`/`context_none`；unit `_assert_stage_fail_clean` | 满足 |
| WSL 当前 revision unit+golden 明确终态 | **10 passed, 3 skipped**；skip 理由见 §3 | 满足 |
| 双平台 Ruff/cold/diff；生产不变 | §3 | 满足 |

## 3. 动态复跑终态

### Windows（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`，cap=True）

| 项 | 结果 | 产物 |
|---|---|---|
| 三窗 inode | **3 passed**，499.30s | `.tmp-g8-r3-indep-win-inode.txt` |
| G8 unit 其余（`-k not inode_replace`） | **9 passed, 3 deselected**，252.29s | `.tmp-g8-r3-indep-win-unit-rest.txt` |
| 等价 G8 unit | 3+9=**12** | — |
| Ruff / cold / `git diff --check` | All passed / `cold-ok True True` / clean | `.tmp-g8-r3-indep-ruff-win.txt` / `.tmp-g8-r3-indep-cold-win.txt` |

### WSL Miniforge `base` / DrvFS（cap=False）

| 项 | 结果 | 产物 |
|---|---|---|
| unit+golden | **10 passed, 3 skipped**，226.99s | `.tmp-g8-r3-indep-wsl-combo.txt` |
| skip 理由 | 后两窗×2：`exclusive commit unsupported; inode window unreachable`；golden×1：`host lacks atomic directory no-replace publication`（§11） | 同文件 `-rs` |
| Ruff / cold | All passed / `cold-ok True True` | `.tmp-g8-r3-indep-ruff-cold-wsl.txt` |

## 4. 实现者未用对抗探针

探针仅落系统临时目录（`%TEMP%\g8r3-indep-adv-*.py`），未改仓库。

### A. capability=false + 爆炸构建（证明 skip 在构建前）

Windows 强制 `platform_supports_renameat2_noreplace→False`，并将 `build_backtest_artifact` monkeypatch 为 `RuntimeError("INDEP_PROBE_BUILD_MUST_NOT_RUN")`：

| 窗 | skipped | build_hits | boom | 理由 | ok |
|---|---|---|---|---|---|
| after_temp_before_final | True | 0 | False | `exclusive commit unsupported; inode window unreachable` | True |
| after_final_before_receipt | True | 0 | False | 同上 | True |

产物：`.tmp-g8-r3-indep-adv-win.txt`（PROBE A）。

WSL native（cap 已为 False）同构：后两窗 `build_hits=0`+同理由；handler→temp **未 skip** 且 `build_hits=1`（触达爆炸构建，证明该窗仍实跑）。handler 窗因构建爆炸未进入 mutation，unit 内 `mut_calls` 断言连带失败——属探针构造后果，非产品缺陷。产物：`.tmp-g8-r3-indep-adv-wsl.txt`。

### B. Windows 三窗 mutation 计数/顺序（实现者 unit 未打印时间线）

| 窗 | code | timeline | mut | eg | base_publish | 残留/cause/context | ok |
|---|---|---|---|---|---|---|---|
| after_handler_before_temp | `STAGE_OUTPUT_INVALID` | `pre@1,mut@1` | 1 | 0 | 0 | 全空 | True |
| after_temp_before_final | `STAGE_RECOVERY_CONFLICT` | `pre@1,pre@2,mut@2` | 1 | 0 | 0 | 全空 | True |
| after_final_before_receipt | `STAGE_RECOVERY_CONFLICT` | `pre@1,pre@2,mut@2,entity_guard` | 1 | 1 | 0 | 全空 | True |

无 `STAGE_PUBLISH_FAILED`。产物：`.tmp-g8-r3-indep-adv-win.txt`（PROBE B）。`SUMMARY probe_a_ok=True probe_b_ok=True`。

## 5. 对照 R2 FAIL

R2 阻断：WSL 后两窗实为 exclusive commit 不可达，却用 `{STAGE_RECOVERY_CONFLICT, STAGE_PUBLISH_FAILED}` 假绿。  
R3 已改为 capability 门控 + 构建前窄 skip；capability true 只认实体码与 mutation/EntityGuarded 计数。本轮独立复验确认假绿路径已关闭。

## 6. 残余边界与下一步

- 本 PASS **仅解锁主验**；不宣称 Linux ext4、G8/M3 Gate、正式发布通过。
- WSL1/DrvFS skip ≠ ext4 Gate；未来 capability true 的 Linux 宿主必须实跑三窗与 golden。
- 下一步：主 Agent 终验；主验 PASS 后才恢复 G8C。
