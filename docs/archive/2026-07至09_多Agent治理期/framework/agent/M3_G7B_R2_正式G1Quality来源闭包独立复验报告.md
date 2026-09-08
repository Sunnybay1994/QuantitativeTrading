# M3 G7B R2：正式 G1 Quality 来源闭包独立复验报告

日期：2026-08-10  
角色：未参与实现的全新外部独立初验 Agent（只读生产/实现测试/任务单/既有报告；本文件为唯一写入）  
任务单：[`M3_G7B_R1正式BacktestPlanArtifact任务单.md`](M3_G7B_R1正式BacktestPlanArtifact任务单.md) §10  
交付报告：[`M3_G7B_R2_正式G1Quality来源闭包返工交付报告.md`](M3_G7B_R2_正式G1Quality来源闭包返工交付报告.md)

## 结论

**PASS（仅解锁主验）**。未发现 §10 合同级缺陷；不得宣 Gate / 主验通过 / G7F 同类返工解锁。

## 逐项核对

| 合同项 | 证据 | 结果 |
|---|---|---|
| formal 19-input = manifest → quality → eligible → … → target 四项 → trade calendar | `_formal_receipt_inputs` 固定 19 元组；闭环断言 `inputs[0..2]` 为 manifest/quality/eligible，`inputs[1]==quality_path` 且 `name==quality.json`，无 `receipt.json`；`len==19` + normcase 去重 + `samefile` 拒 alias | PASS |
| quality path/sha/fresh 绑定 | `_formal_g1_quality_path` 强制 `root/quality.json`（未 import G7A 私有 helper）；`_formal_fresh_upstream_bytes` 绑定 `release.quality_sha256`；`_validate_formal_outer` 在 build/verify 入口调用 | PASS |
| `VerifiedG1Release` 无伪 receipt 语义 | 字段 exact：`artifact_paths/manifest/manifest_sha256/quality/quality_sha256/release`；无 `receipt_sha256`；fixture G1 根无正向 `receipt.json`；前三项禁 receipt 名 | PASS |
| G7A R3 递归闭包 | formal plan 仅 public `verify_target_artifact`；formal G7A 定向测试绿；plan 自有 quality 闭包与 G7A R3 同构（manifest→quality→eligible） | PASS |
| development 不变 | `_validate_upstream_bytes` / `_receipt_inputs` / `build_*` / `verify_*` development 相对 HEAD 函数体 UNCHANGED，仍绑 `root/receipt.json` + `receipt_sha256`；development plan + config 邻接绿 | PASS |
| 白名单/禁改 | 本包主张范围：`a_share_plan.py`、formal plan 测试、任务单状态、交付报告；初验未改生产/实现测试；未 add/commit/联网 | PASS* |

\*工作树另有大量既有脏文件（含未提交 G7A formal 等），不在本包 R2 主张范围；初验未将其计为本包变更。

## 实现者未用对抗（双平台）

独立脚本位于系统临时目录（不改生产/测试；Windows：`%TEMP%\g7b-r2-indep-adv\adv.py`；WSL：`/tmp/g7b-r2-indep-adv/adv.py`）：

| ID | 攻击面（相对实现者 suite 增量） | Win | WSL |
|---|---|---|---|
| A1 | quality↔`target_weights.parquet` same-bytes hardlink alias（实现者仅 quality↔manifest） | PASS reject alias | PASS |
| A1b | quality↔`trade_calendar.parquet` same-bytes hardlink alias | PASS reject alias | PASS |
| A2 | 旧伪 G1 `receipt.json` 整包合法重签后 verify（先正确 verify 对照） | PASS `M3_BACKTEST_PLAN_ARTIFACT_INVALID` | PASS |
| A3 | `quality_path` 指向根外 same-bytes 副本（非 exact `root/quality.json`） | PASS invalid | PASS |
| A3b | 整根 G1 root 替换（quality same-bytes 保留）+ 旧 `manifest_sha256` 绑定 | PASS invalid | PASS |
| A4 | 对 `_formal_fresh_upstream_bytes` 注入含绝对路径/TOKEN 的 hostile（实现者打的是 `verify_target_artifact`/缺 quality） | PASS 仅稳定码、无 cause/context/路径泄漏 | PASS |

## 定向验证证据

Windows（`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`）：

- formal G7B：`5 passed`，107.81s
- formal G7B + formal G7A + development plan + config：`111 passed`，472.98s
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 1 source file`
- cold import：`G7B_R2_INDEP_COLD_IMPORT_PASS`（未加载 LightGBM/Qlib/MLflow）
- `git diff --check`（白名单源/测）：通过
- 对抗：6/6 PASS

WSL Miniforge `base`（`/mnt/f/.../m3-g4-formal`）：

- 同上四测文件组合：`111 passed`，205.61s
- Ruff / mypy 通过；cold import `G7B_R2_INDEP_WSL_COLD_IMPORT_PASS`
- `stat -f -c %T .` → `wslfs`（DrvFS 兼容，非 ext4/Linux Gate）
- WSL `git diff --check` 因 worktree `.git` 路径解析失败（与交付报告一致）；Windows 同范围已通过
- 对抗：6/6 PASS

未 add/commit/联网；未改生产或实现者测试。

## 残留（不构成初验 FAIL）

- 父 SSOT 骨架表若仍写 “G1 release manifest/receipt/…” 属主 Agent 文档同步。
- 未跑真实全折 `VerifiedG1Release` 主验链。
- WSL `/mnt/f` 仅 DrvFS 兼容证据。

## FAIL 清单

无。
