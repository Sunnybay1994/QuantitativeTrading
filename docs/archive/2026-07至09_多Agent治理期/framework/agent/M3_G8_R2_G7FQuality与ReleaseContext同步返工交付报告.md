# M3 G8 R2：G7F Quality 与 Release Context 同步返工交付报告

日期：2026-08-11  
角色：外部实现 Agent（全新会话）  
状态：**实现者交付与自测收口完成，待未参与实现的全新独立初验**  
环境：Windows 原生 Miniforge；WSL Miniforge `base`（DrvFS `/mnt/f`）；默认不联网、未 add/commit

任务依据：[`M3_G8_R1任务单.md`](M3_G8_R1任务单.md) §12  
前置：[`M3_G7F_R4_preFinalReleaseContext实体绑定主Agent最终验收报告.md`](M3_G7F_R4_preFinalReleaseContext实体绑定主Agent最终验收报告.md)

## 1. 交付结论

按 §12 同步 current G7F R4 formal context 与 21-input Quality 闭包：调用链只接 exact
`BacktestArtifactFreshVerificationContext`（含绑定 `VerifiedG1Release`），21-input 唯一来自
`backtest_artifact_input_paths`（target4+plan5+experiment2+G1 manifest/quality/八表10），禁止 G1 receipt /
`receipt_sha256` / old four-path / fake receipt。每次 StageRunner closure 仍 actual 调用
`verify_backtest_build_output`（触发 R4 release/entity 重验，不缓存）。

核定：仅委托 G7F 仍不足以覆盖 **final closure 后 → receipt 发布前** 的同路径 quality/market entity 漂移
（receipt digest 对同字节换 inode 不可见）。故 production 最小增加 G8 侧
`_EntityGuardedFormalBacktestStageRunner`（子类，不改 StageRunner primitive 源码）：发布 receipt 前再跑一次
`backtest_artifact_input_paths` 实体绑定重验；失败 `STAGE_RECOVERY_CONFLICT`，无 receipt 残留。

本报告**不**声明独立初验、主验、G8/ext4/M3 Gate PASS。

## 2. 关键改动

| 路径 | 说明 |
|---|---|
| `src/quant/research/m3/backtest_stage.py` | `_EntityGuardedFormalBacktestStageRunner`；SHA256=`e7dcd9827098709c94d85b41a5c4214740b8441d` |
| `tests/unit/test_m3_g8_r1_formal_backtest_stage.py` | §12.2.4 反例：old/four-path/subclass/duck；21 组成；copied-root；三窗 inode/entity；新 context 边界 |
| `docs/framework/agent/M3_G8_R1任务单.md` | 仅状态行 |
| 本交付报告 | 唯一新增交付文档 |

未改：G7F/G1/G7A/B/E/P0、StageRunner primitive、tracking、CLI、`test_m3_g8_r1_formal_backtest_stage_golden.py` 正文（本轮未触）。

## 3. 验证证据（只读既有终态；本收口未重跑长测）

### Windows（有终态）

| 项 | 结果 | 来源 |
|---|---|---|
| R2 targeted `-k r2_` | `7 passed`，654.40s | 终端 947432 / 已删 `.tmp-g8-r2-targeted-unit-win.txt` |
| G8 unit 全文件 | `12 passed`，745.73s | 947433；**时点在子类定稿后、inode 断言放宽前** |
| subclass 后关键 R2 | `5 passed`，624.72s | 947434 |
| actual golden | `1 passed`，980.72s | 947435 |
| G7F/P0/G7E/F0-C-D 等邻接 | `178 passed`，1623.05s | 947436 |
| Ruff / mypy | All checks passed / Success（3 files） | 定稿后重跑产物曾写入 `.tmp-g8-r2-ruff-win.txt` / `.tmp-g8-r2-mypy-win.txt`（已删） |
| cold import | 会话内 `cold-ok` | **无独立 .tmp 存档** |

### WSL base / DrvFS

| 项 | 结果 | 来源 |
|---|---|---|
| Ruff / mypy / cold+capability | All checks passed / Success / `cold-ok False` | 947438 |
| G8 unit+golden（断言放宽前） | `2 failed, 10 passed, 1 skipped` | 947437：两例 inode 窗期望 `STAGE_RECOVERY_CONFLICT`，实得 `STAGE_PUBLISH_FAILED`；golden 按 §11 capability false 窄 skip |
| 断言放宽后 WSL 复跑 | **未计证据** | 947439 收口前仍在跑、日志空；已终止，未等待终态 |

说明：单元测试随后将后两窗允许码扩为 `{STAGE_RECOVERY_CONFLICT, STAGE_PUBLISH_FAILED}`（仍要求无 receipt/temp 残留）。**该放宽之后的 Windows 全量 G8 unit 与 WSL combo 均无完整绿终态存档。**

### 白名单 / diff

本轮实现触达：`backtest_stage.py`、`test_m3_g8_r1_formal_backtest_stage.py`、任务状态、本报告。  
worktree 另有既有 G7F/编排等 `M` 文件，**非本 R2 会话改动**。未联网、未 git add/commit。收口已删除全部 `.tmp-g8-r2-*`。

## 4. 剩余风险与下一步

- WSL/DrvFS 上同路径改写的错误码可能与 Windows 不一致；capability false 的 golden skip ≠ ext4 Gate。
- 断言放宽后的双平台完整复验留给独立初验。
- 下一步：未参与本轮实现的全新外部 Agent 只写
  `docs/framework/agent/M3_G8_R2_G7FQuality与ReleaseContext同步返工独立复验报告.md`。
