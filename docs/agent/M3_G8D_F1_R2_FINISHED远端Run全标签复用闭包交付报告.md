# M3 G8D-F1 R2：FINISHED 远端 Run 全标签复用闭包交付报告

日期：2026-08-10

角色：外部实现 Agent（R2 最小返工；不得自行宣布 Gate / 初验通过）

模型：`cursor-grok-4.5-high`

工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`

结论：**R2 实现与自测完成，待全新外部独立复验**。只声明工程合同返工自测绿；不宣称真实 tracking / G8 / M3 / ext4 / 真实 MLflow Gate 状态。

## 1. 现象—根因—规则—最小复现—新增测试—通过条件

| 项 | 内容 |
|---|---|
| 现象 | 远端 1 个 `FINISHED` run，5 个 protected identity tags/hash 与当前 request 一致，但 `formal_gate_eligible` 从 `"true"` 漂移为 `"false"` 时，`register_remote_tracking_run` 仍复用该 run。 |
| 根因 | `_register_remote_locked` 调用 `_validate_remote_run` 时只传入 protected tags 子集，create 首写的 request tags（`formal_gate_eligible` / `release_kind`）未参与复用校验。 |
| 应遵循规则 | 任务单 §5 tags exact；§6「1 个仅 FINISHED 且全部 tag/hash 一致可复用」；§13：request tags 与 protected tags 全部逐键逐值一致才可复用；额外普通远端标签允许，不做整个 tag set exact。 |
| 最小复现 | `build_formal_tracking_request` → fake client 预置 `FINISHED` run（protected 全对 + `formal_gate_eligible="false"`）→ `register_remote_tracking_run`；修复前复用，修复后 `ValueError: remote tracking run content conflict` 且 `create_calls==0`。 |
| 新增测试 | `test_finished_remote_reuse_requires_request_tags_exact`：`formal_gate_eligible` / `release_kind` 分别漂移、分别缺失、全部一致+额外普通 tag 复用同 run id、protected 冲突拒绝且不 create、hostile `.get` Mapping 仍抛稳定异常且不 create。 |
| 通过条件 | 上述回归绿；既有 G8D unit/golden、tracking journal、G8 R1 邻接 Windows+WSL base 按 §11 通过；Ruff/mypy/cold/diff 通过；只读文件 SHA 不变。 |

## 2. 最小改动

白名单仅改：

1. `src/quant/research/m3/tracking.py`：复用校验改为 `_validate_remote_run(run, {**dict(request.tags), **expected_tags})`。仍是子集逐键比较；额外普通远端标签不受影响。status / 多匹配 / protected / development API / create 首写语义不变。
2. `tests/unit/test_m3_g8d_f1_formal_tracking_stage.py`：新增上述正式 unit。
3. 任务单状态 →「R2 实现与自测完成，待全新外部独立复验」。
4. 本报告。

只读且 SHA 不变：`tracking_stage.py`、golden、`__init__.py`。R1 交付/初验报告未改。未联网、未真实 MLflow、未安装依赖、未 `git add`/`commit`、未写正式 artifact。

## 3. 验证证据（本会话实际执行）

### Windows Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`）

| 命令 | 结果 |
|---|---|
| Ruff 白名单 | All checks passed |
| mypy `tracking.py` | Success |
| cold import + capability | `WINDOWS_COLD_IMPORT_PASS True`；`WINDOWS_RENAMEAT2_NOREPLACE True` |
| 新 unit 单测 | `1 passed in 186.34s` |
| G8D unit | `9 passed, 75435 warnings in 194.66s`（`.tmp-g8d-f1-r2-unit-win.txt`） |
| G8D golden | `2 passed, 75435 warnings in 194.79s`（capability=true，actual 未 skip；`.tmp-g8d-f1-r2-golden-win.txt`） |
| journal + G8 R1 unit/golden | `14 passed, 476984 warnings in 1074.97s`（`.tmp-g8d-f1-r2-adj-win.txt`） |

### WSL Miniforge base / DrvFS（`/mnt/f/.../m3-g4-formal`）

| 命令 | 结果 |
|---|---|
| cold + capability | `WSL_COLD_IMPORT_PASS True`；`WSL_RENAMEAT2_NOREPLACE False`（非 ext4；仅窄 skip） |
| Ruff / mypy | 通过 |
| 组合一次：G8D unit+golden + journal + G8 R1 unit | `23 passed, 1 skipped, 158546 warnings in 343.65s`（`.tmp-g8d-f1-r2-combo-wsl.txt`） |
| 唯一 skip | `test_actual_publish_resume_noresume_orphan_and_remote_counts`（能力位 false） |

warning 均为 Pandera/Polars `concat(how='horizontal')` 弃用提示，无业务失败。

### Diff / SHA

- `git diff --check`（改动白名单）通过
- HEAD：`eace7ebbd61a622a66f9b1cdb6402f42922aae73`
- SHA256：

| 文件 | SHA256 | 备注 |
|---|---|---|
| `tracking.py` | `b7b63fafd90baeb2d689e499ea86ff9e212c374bef4d76994336131b44e5ad91` | R2 已改 |
| unit | `849d9151fdc56371ca58af5767ea209fdf29716f7cef3b48b88435ef605f5846` | R2 已改 |
| `tracking_stage.py` | `cf4ae7a8fea7b9c0ffefb8e0ec0732d9394448d95f95804512a3be7236160063` | 与 R1 一致 |
| `__init__.py` | `866b5a1f7abe4d90d37f6106cf6756a16ed0d38b173118f5e6e8a54bb5c86e11` | 与 R1 一致 |
| golden | `f83e82d747a69c187c5b3521fc657b9ff19323c9b9b69e964ba25b4e610af903` | 与 R1 一致 |

## 4. 下一步

交给**未参与 R2 实现**的全新外部 Cursor 独立复验；重点用不同 request tag 值与缺失组合再次攻击 FINISHED 复用闭包。主 Agent 不得直接修补后跳过复验。通过后方可进入主验。
