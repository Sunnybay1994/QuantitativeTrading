# M3 G8 R3：WSL 不可达实体窗口测试证据返工交付报告

日期：2026-08-11  
角色：全新外部 tests-only 实现 Agent  
状态：**实现与自测收口完成，待未参与本轮的全新独立复验**  
环境：Windows Miniforge（capability=true）；WSL Miniforge `base`/DrvFS（capability=false）；未联网、未 add/commit

依据：[`M3_G8_R1任务单.md`](M3_G8_R1任务单.md) §13；前置 FAIL：[`M3_G8_R2_G7FQuality与ReleaseContext同步返工独立复验报告.md`](M3_G8_R2_G7FQuality与ReleaseContext同步返工独立复验报告.md)

本报告**不**声明独立初验、主验、G8/ext4/M3 Gate PASS。

## 1. 交付结论

tests-only 收紧后两窗证据诚实性：

| 窗 | capability false | capability true |
|---|---|---|
| handler→temp | 双平台实跑；`STAGE_OUTPUT_INVALID`；mut≥1；无残留/cause/context | 同左 |
| temp→final | **构建前**窄 skip：`exclusive commit unsupported; inode window unreachable`；**不**接受 `STAGE_PUBLISH_FAILED` | 实跑 mut≥1；仅 `STAGE_RECOVERY_CONFLICT`；无残留/cause/context |
| final→receipt | 同上窄 skip | 实跑 mut≥1；EntityGuarded≥1；base receipt publish=0；仅 `STAGE_RECOVERY_CONFLICT`；无残留/cause/context |

production 未改；`backtest_stage.py` blob SHA 仍为 `e7dcd9827098709c94d85b41a5c4214740b8441d`。

## 2. 白名单改动

| 路径 | 说明 |
|---|---|
| `tests/unit/test_m3_g8_r1_formal_backtest_stage.py` | 后两窗 capability 门控；mutation/EntityGuarded/base-publish 计数；去掉 `STAGE_PUBLISH_FAILED` 放宽 |
| `docs/framework/agent/M3_G8_R1任务单.md` | 仅状态行 → R3 已交付、待独立复验 |
| 本报告 | 唯一交付文档 |

未改：production / golden / G7F / StageRunner primitive / 其他测试。

## 3. 验证终态

| 平台 | 项 | 结果 |
|---|---|---|
| Windows | capability | `True` |
| Windows | 三窗 inode 节点 | **3 passed**，503.72s（`.tmp-g8-r3-win-inode.txt`） |
| Windows | G8 unit 其余（`-k not inode_replace`，长测不重复） | **9 passed, 3 deselected**，238.90s（`.tmp-g8-r3-win-unit-rest.txt`） |
| Windows | 等价 G8 unit 覆盖 | 3+9 = **12** |
| Windows | Ruff / cold / `git diff --check` | All passed / `cold-ok True True` / clean |
| WSL | capability | `False` |
| WSL | unit+golden | **10 passed, 3 skipped**，217.19s（`.tmp-g8-r3-wsl-combo.txt`） |
| WSL | skip 理由（`-rs` 定向） | 后两窗×2：`exclusive commit unsupported; inode window unreachable`；golden×1：`host lacks atomic directory no-replace publication`（§11） |
| WSL | Ruff / cold | All passed / `cold-ok True True`（DrvFS 下 `git diff --check` 因 worktree `.git` 路径不可用；以 Windows 为准） |

## 4. 风险与下一步

- WSL1/DrvFS skip ≠ Linux ext4 Gate；未来 capability true 宿主必须实跑三窗与 golden。  
- 下一步：未参与本轮实现的全新外部 Agent 只写  
  `docs/framework/agent/M3_G8_R3_WSL不可达实体窗口测试证据独立复验报告.md`；独立复验 PASS 后方可进主验。
