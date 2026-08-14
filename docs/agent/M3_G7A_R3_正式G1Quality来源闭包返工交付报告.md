# M3 G7A R3：正式 G1 Quality 来源闭包返工交付报告

日期：2026-08-10  
状态：外部实现与双平台定向自测完成；待未参与实现的全新外部 Agent 独立初验与主 Agent 最终验收  
任务单：[`M3_G7A_R1正式TargetArtifact任务单.md`](M3_G7A_R1正式TargetArtifact任务单.md) §10

## 1. 现象与最小修复

- 现象：formal `_formal_receipt_inputs` 将 G1 第二项固定为 `release.release.root / "receipt.json"`；真实
  `verify_g1_release` exact tree 不含该文件，合法正式输入被稳定拒绝。
- 最小修复（仅 formal）：
  1. 新增 `_formal_g1_quality_path`：强制 `quality_path == root / "quality.json"`；
  2. `_formal_receipt_inputs` 第二项改为 exact `quality_path`，仍精确 14 项，顺序为
     manifest → quality → eligible → feature/prediction/folds/experiment；
  3. 新增 `_formal_fresh_upstream_bytes`，绑定 `release.quality_sha256`，并由
     `_validate_formal_inputs` 在 build/verify 入口调用；
  4. 拒绝 G1 三项中出现 `receipt.json`、quality 路径非法、bytes 漂移与 samefile alias。
- development `_fresh_upstream_bytes` / `_receipt_inputs`、公开 API、G1 registry、`m3_release.py`、
  Decimal/Top-k、publication 与错误码均未改动。

## 2. 测试与 fixture

- formal fixture 改为独立 `formal-g1-release/<release_id>` exact 布局：根目录仅有
  `manifest.json`、`quality.json`、`eligible_keys.parquet`；禁止写伪 G1 `receipt.json`。
- 闭环断言：14 输入第二项为 `quality.json`，sha256 等于 `quality_sha256`，且根上无 `receipt.json`。
- 新增 `test_r3_formal_target_g1_quality_closure_rejects_drift_alias_and_pseudo_receipt`：
  旁路伪 receipt 不进入闭包、缺失 quality、quality 内容漂移、manifest↔quality hardlink samefile alias、
  用 `receipt.json` 冒充 quality_path、旧伪 receipt 重签 verify 拒绝。

## 3. 验证证据

Windows 原生 Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）：

- formal G7A 全套：`7 passed`，123.09 秒。
- development 邻接：closed_loop / receipt-13 / r2 allocation / light import：`5 passed`。
- Ruff：`targets.py` + formal 测试 `All checks passed`。
- mypy：`targets.py` `Success: no issues found`。
- cold import：`G7A_LIGHT_IMPORT_PASS`（未加载 LightGBM/Qlib/MLflow）。

WSL Miniforge `base`（`/mnt/f/.../m3-g4-formal`）：

- formal 7 + development 4 定向节点：`11 passed`，87.50 秒。
- Ruff / mypy / cold import 均通过。
- `stat -f -c %T .` → `wslfs`：本结果为 WSL/DrvFS 兼容证据，不是 ext4/Linux Gate。

scoped diff：本轮实现写入限于
`src/quant/research/m3/targets.py`、`tests/unit/test_m3_formal_target_artifact.py`、本任务单状态与本交付报告；
未 add/commit，未改 G1/development 合同或其他既有脏文件。

## 4. 风险与未关闭边界

- 父 SSOT 骨架表仍写 “G1 release manifest/receipt/eligible”；本包按任务单 §10 以 formal quality 为准。
  表文同步属主 Agent，不在本白名单。
- formal fixture 仍复用 development 的 manifest/quality bytes 身份以衔接既有 G4–G5B 测试链，但物理根与
  receipt 闭包已按正式 G1 exact tree 隔离；真实 `VerifiedG1Release` 全折主验未跑。
- 未宣称独立初验、主验、Gate、G7B/G7F/G8 恢复通过。独立初验须由全新外部 Agent 追加攻击并只写
  `docs/agent/M3_G7A_R3_正式G1Quality来源闭包独立复验报告.md`。
