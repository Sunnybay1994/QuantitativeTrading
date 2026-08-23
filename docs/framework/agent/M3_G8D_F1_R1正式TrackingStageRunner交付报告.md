# M3 G8D-F1 R1 正式 Tracking StageRunner 交付报告

日期：2026-08-10

角色：外部实现收尾 Agent（承接前一实现会话 60 分钟承载超时后的落盘实现）

状态：实现与自测完成，待未参与实现的全新外部 Agent 独立初验；仅声明“G8D-F1 formal tracking StageRunner 工程合同 PASS”，不宣称真实 tracking、G8、M3、ext4 或真实 MLflow Gate PASS。

## 1. 会话交接

- 前一实现会话已将白名单生产代码、新 unit/golden 落盘，但因 60 分钟承载超时失去输出并停止；任务状态仍为“待实现”，交付报告不存在。
- 前会话明确终态证据（可引用、未猜测）：
  - `.tmp-g8d-unit-win.txt`：`18 passed ... in 386.88s`（unit+golden 组合）
  - `.tmp-g8d-wsl.txt`：`17 passed, 1 skipped ... in 303.61s`
- 本会话只核对与收尾：保留已落盘正确实现；仅做合同内最小修复（Ruff 未用 import、mypy scenario Literal / `runner_error` 重定义）；未重写设计、未扩大白名单、未联网、未装依赖、未 `git add/commit`、未写正式 artifact。

## 2. 交付结果

- `tracking.py`：新增 `FormalTrackingFreshVerificationContext`、`formal_tracking_input_paths`（exact 34）、`formal_tracking_upload_paths`（exact 11）、`build_formal_tracking_request`（22 params / 2 tags / finite metrics）、`register_remote_tracking_run`（纯远端登记 + 外置 `lock_root`，不写 request/marker 文件）。`register_tracking_request` 保持 development 兼容。
- `tracking_stage.py`：`make_formal_tracking_run_plan` / `run_formal_tracking_stage` / `FormalTrackingStageResult`；formal `run_*` 强制显式 fake-friendly client；handler 顺序冻结为 request → remote → marker；local closure 不查 remote、不重跑上游 verifier。
- `__init__.py`：tracking API 导出；stage 符号惰性 `__getattr__`。
- 新测试覆盖 34/11/22/2、identity/hostility、remote 0/1/2 与 marker 前崩溃恢复同 run id、resume/no-resume/orphan 计数、stable errors、cold import。

## 3. 关键合同核对

| 项 | 证据 |
|---|---|
| 34 inputs / 2 outputs / 11 upload / 22 params / 2 tags | unit `test_formal_plan_and_request_close_34_11_22_2_tags_metrics` + golden always-run |
| fresh 各 once（每次 public run 入口） | golden 首跑/resume/no-resume/orphan 均断言 `["evaluation","backtest"]` |
| remote 纯登记 + 外置锁 | lock path 含 `stage_root/.tracking-locks/...`；final tree 无 `.tracking-locks` |
| 恢复同 run id | unit crash/recovery；golden orphan `create_calls` 不增且 marker run id 相同 |
| 调用顺序 | 首次 remote+closure×3；resume closure×2 且 remote 0；`resume=False` closure×1→`STAGE_ALREADY_COMPLETE`；orphan closure→remote→closure×3 |
| stable errors / cold import | hostile client → `STAGE_BUILD_FAILED` 零泄漏；Windows/WSL cold import PASS |

## 4. 验证证据（本会话实际执行）

### Windows Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`）

- G8D unit（修复后）：`8 passed, 75435 warnings in 216.01s`（`.tmp-g8d-f1-r1-unit-win-after-fix.txt`）
- G8D golden：`2 passed, 75435 warnings in 216.34s`（capability=true，actual 未 skip；`.tmp-g8d-f1-r1-golden-win.txt`）
- tracking journal 邻接：`8 passed in 4.13s`
- G8 R1 unit 邻接：`5 passed, 7676 warnings in 97.61s`
- G8 R1 golden 邻接：`1 passed, 469308 warnings in 1008.17s`
- Ruff：白名单全部通过
- mypy：`tracking.py` / `tracking_stage.py` Success
- cold import：`WINDOWS_COLD_IMPORT_PASS`
- capability：`WINDOWS_RENAMEAT2_NOREPLACE True`

### WSL Miniforge base（长测一次）

- 组合：unit + G8D golden + tracking journal + G8 R1 unit → `22 passed, 1 skipped, 158546 warnings in 371.76s`（`.tmp-g8d-f1-r1-combo-wsl.txt`）
- 唯一 skip：`test_actual_publish_resume_noresume_orphan_and_remote_counts`（`platform_supports_renameat2_noreplace()==False`）；fake remote/contract 仍 PASS
- Ruff / mypy：通过
- cold import：`WSL_COLD_IMPORT_PASS`
- capability：`WSL_RENAMEAT2_NOREPLACE False`

warning 均为 Pandera/Polars `concat(how='horizontal')` 弃用提示，无业务失败。

### Diff / SHA

- `git diff --check` 白名单通过
- scoped status 仅白名单生产/测试与本任务文档；未执行联网、安装、`git add`、commit
- SHA256：
  - `tracking.py`: `a84292af055c1c9ea57e64824422822abd9e4687bd5a6ad1770f03645e04e9b3`
  - `tracking_stage.py`: `cf4ae7a8fea7b9c0ffefb8e0ec0732d9394448d95f95804512a3be7236160063`
  - `__init__.py`: `866b5a1f7abe4d90d37f6106cf6756a16ed0d38b173118f5e6e8a54bb5c86e11`
  - unit：`790f85c1b926192142a7ab5c72f077a7170067f780634095c351306046f71303`
  - golden：`f83e82d747a69c187c5b3521fc657b9ff19323c9b9b69e964ba25b4e610af903`

## 5. 剩余边界与下一步

- 当前 WSL1/DrvFS 无 `RENAME_NOREPLACE` actual 发布证据；Linux ext4 Gate 仍待后续。
- 未跑真实 MLflow / 网络 / 正式 G1 artifact。
- 下一步：未参与本轮实现的全新外部 Agent 写入 `docs/framework/agent/M3_G8D_F1_R1正式TrackingStageRunner独立初验报告.md`，并增加任务书 §10 未公开反例；通过后再进入主 Agent 终验。
