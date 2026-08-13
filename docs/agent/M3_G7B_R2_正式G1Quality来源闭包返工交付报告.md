# M3 G7B R2：正式 G1 Quality 来源闭包返工交付报告

日期：2026-08-10  
状态：外部实现与双平台定向自测完成；待未参与实现的全新外部 Agent 独立初验与主 Agent 最终验收  
任务单：[`M3_G7B_R1正式BacktestPlanArtifact任务单.md`](M3_G7B_R1正式BacktestPlanArtifact任务单.md) §10

## 1. 现象与最小修复

- 现象：formal `_formal_receipt_inputs` 将 G1 第二项固定为 `release.release.root / "receipt.json"`；真实
  `VerifiedG1Release` 无 `receipt_sha256`，exact tree 也不含该文件，合法正式 G1 无法进入计划发布。
- API 核验（无冲突，继续实现）：
  - `VerifiedG1Release` fields exact：
    `release/manifest/manifest_sha256/quality/quality_sha256/artifact_paths`
  - `G1Release.quality_path` 与 `quality_sha256` 可用；不得补造 G1 `receipt.json`
  - 权威规则与 G7A R3 一致：`docs/M3实施与Agent交接.md` §4.8
- 最小修复（仅 formal，白名单内）：
  1. 新增 `_formal_g1_quality_path`：强制 `quality_path == root / "quality.json"`（未 import G7A 私有 helper）；
  2. `_formal_receipt_inputs` 第二项改为 exact `quality_path`，仍精确 19 项，顺序
     manifest → quality → eligible → … → target 四项 → trade calendar；
  3. 新增 `_formal_fresh_upstream_bytes`，绑定 `release.quality_sha256`，并由
     `_validate_formal_outer` 在 build/verify 入口调用；
  4. 拒绝 G1 三项中出现 `receipt.json`、quality 路径非法、bytes 漂移与 samefile alias。
- development `_receipt_inputs` / `_validate_upstream_bytes`、公开 API、G1、G7A、调度/Decimal/成本、
  publication 与错误码均未改动。

## 2. 测试与 fixture

- 闭环断言：19 输入第二项为 `quality.json`，sha256 等于 `quality_sha256`，且正式 G1 根上无
  `receipt.json`；继续断言 next-session 调度。
- 新增 `test_r2_formal_plan_g1_quality_closure_rejects_drift_alias_and_pseudo_receipt`：
  旁路伪 receipt 不进入闭包、缺失 quality、quality 内容漂移、manifest↔quality hardlink samefile alias、
  用 `receipt.json` 冒充 quality_path、旧伪 receipt 整包合法重签 verify 拒绝；hostile 边界
  cause/context 脱敏。
- formal fixture 继续复用 G7A R3 的无伪 G1 receipt exact 布局，不在 G1 root 创建正向所需 fake receipt。

## 3. 验证证据

Windows 原生 Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`）：

- formal G7B：`5 passed`，93.32 秒。
- formal G7B + formal G7A + development plan + config：`111 passed`，395.43 秒。
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 1 source file`
- cold import：`G7B_R2_COLD_IMPORT_PASS`（未加载 LightGBM/Qlib/MLflow）
- `git diff --check`（白名单文件）：通过

WSL Miniforge `base`（`/mnt/f/.../m3-g4-formal`）：

- 同上四测文件组合：`111 passed`，229.68 秒。
- Ruff / mypy / cold import：`G7B_R2_WSL_COLD_IMPORT_PASS`
- `stat -f -c %T .` → `wslfs`：本结果为 WSL/DrvFS 兼容证据，不是 ext4/Linux Gate。
- 注：WSL 侧 `git diff --check` 因 worktree `.git` 路径解析失败（exit 128）；Windows 同范围已通过。

scoped 写入限于：
`src/quant/backtest/a_share_plan.py`、`tests/unit/test_m3_formal_backtest_plan_artifact.py`、
本任务单状态与本交付报告；未 add/commit，未改 G7A/G1/development/其他脏文件，未联网。

## 4. 风险与未关闭边界

- 父 SSOT 骨架表若仍写 “G1 release manifest/receipt/…” 属主 Agent 文档同步，不在本白名单。
- formal fixture 仍复用 development 的 manifest/quality bytes 身份以衔接既有链，但物理根与 receipt 闭包已按
  正式 G1 exact tree 隔离；真实 `VerifiedG1Release` 全折主验未跑。
- 未宣称独立初验、主验、Gate、G7F 同类返工解锁。独立初验须由全新外部 Agent 追加攻击并只写
  `docs/agent/M3_G7B_R2_正式G1Quality来源闭包独立复验报告.md`。
