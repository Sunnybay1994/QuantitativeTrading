# M3 G1 R1B / R1C-A 主验返工交付报告

日期：2026-07-17
角色：外部实现 Agent（接续；上一会话卡死无交付报告）
状态：**待独立初验**（不宣布 R1B / R1C / G1 / Gate 通过）

## 0. 卡死诊断（本轮强制）

| 项 | 内容 |
|---|---|
| 现象 | `tests/unit/test_m3_g1_workflow.py::test_verified_state_self_proof_bidirectional_closure` 超过 18 分钟无结束，被主 Agent 终止；本轮用 `timeout -s KILL 120` 复现为 exit 137，测试收集后无任何断言输出。 |
| 根因 | **测试构造问题，非生产死锁 / journal flock 泄漏。** 自证测试通过 `_advance_to_reference` + `prepare` + `publish` 跑完整 300 成分股链路：INDEX 后 `history_requests=1205`；HISTORY 单段约 229s；随后 REFERENCE/PREPARE/PUBLISH 每次都再 `_inspect` 全量核验收据并重建 candidate，累计墙钟可超 15–18 分钟，表现为“卡死”。journal lock 为非阻塞 `LOCK_NB`，诊断中未见阻塞等待。 |
| 最小复现 | 在 WSL `base` 下对自证单测 `timeout 120 pytest ...::test_verified_state_self_proof_bidirectional_closure`；或分阶段计时：INDEX ~2.5s → HISTORY ~229s → REFERENCE 在剩余预算内仍无法完成第二次 inspect。 |
| 修复 | 自证测试改为只构建 **fresh + INDEX**（秒级）覆盖双向闭包反例；提前产物用 `object.__new__` 满足 exact-type 的 None 闭包检查；response 缺项/重复/乱序打在 index responses 同一 exact-id 路径上。合法 HISTORY/REFERENCE/PREPARE/PUBLISH 构造仍由既有 `test_five_stage_fake_publish_and_inspect_closure` 覆盖。 |
| 防挂测试 / 超时证据 | 新增 `test_verified_state_self_proof_does_not_hang`（90s 墙钟）；定向复跑自证两测：**2 passed / 5.52–5.90s**（`timeout 90/120` 下正常退出 0，不再 137）。 |

## 1. F1–F4 映射

### F1 `VerifiedG1WorkflowStateV1` 自证

- 生产：`g1_workflow.py` 中 `_validate_workflow_state_closure`，由 `__post_init__` 调用；阶段前缀 + 产物双向闭包 + plan totals counts + responses exact 顺序/完备；值对象失败为稳定 `ValueError`，无 IO/联网。
- 测试：`test_verified_state_self_proof_bidirectional_closure`（P0-A、提前 candidate/prepared/published、counts、response 缺项/重复/乱序、合法 fresh/INDEX）；`test_verified_state_self_proof_does_not_hang`。

### F2 `G1CliResultV1` 自证

- 生产：`run_g1.py` `__post_init__` — 裸 64 hex、identity 生命周期双向、FAILED/SUCCESS/INCOMPLETE 与 error_code/error_operation 闭包。
- 测试：`test_cli_result_rejects_illegal_hex_and_identity_lifecycle`、`test_cli_result_rejects_illegal_error_operation_closure`、`test_cli_result_accepts_legal_identity_samples`。

### F3 项目内 config 路径闭包

- 生产：`_validate_config_path(path, *, project_root)` — 项目内相对、禁 `..`、末端与祖先非 symlink、读取前后 fingerprint TOCTOU、失败 `CLI_CONFIG_INVALID`。
- 测试：outside / `..` 穿越 / 末端 symlink / 祖先 symlink / 读取中替换 / 项目内任意子路径合法。

### F4 argparse 后保留已识别 command

- 生产：`_peek_command` 跳过 `--config`/`--project-root` 等取值；无歧义单 command 在后续失败时保留。
- 测试：修正 `test_argparse_rejects_token_and_unknown`；新增 config 值形似 `status` 而真实 command 为 `history` 的归属用例。

## 2. 白名单改动

- `src/quant/research/m3/g1_workflow.py` — F1 闭包（承接上一会话）
- `src/quant/research/m3/run_g1.py` — F2/F3/F4（承接上一会话）
- `tests/unit/test_m3_g1_workflow.py` — 重写自证测试 + 防挂回归
- `tests/unit/test_m3_run_g1.py` — F2–F4 用例（承接上一会话）
- 本报告

未改 `__init__.py`、M4、configs、路线图；未联网、未读 token/data legacy、未启动 R1C-B、未 git init。

## 3. 自测命令与结果

```text
# 卡死单测（修复后）
timeout 120 conda run -n base python -m pytest \
  tests/unit/test_m3_g1_workflow.py::test_verified_state_self_proof_bidirectional_closure \
  tests/unit/test_m3_g1_workflow.py::test_verified_state_self_proof_does_not_hang -q
→ 2 passed in ~5.9s

# 定向（排除五段长测；任务书允许长测保留既有证据）
conda run -n base python -m pytest \
  tests/unit/test_m3_run_g1.py tests/unit/test_m3_g1_workflow.py -q -k "not five_stage_fake"
→ 53 passed, 1 deselected in 20.25s

conda run -n base python -m ruff check \
  src/quant/research/m3/g1_workflow.py src/quant/research/m3/run_g1.py \
  tests/unit/test_m3_g1_workflow.py tests/unit/test_m3_run_g1.py
→ All checks passed

conda run -n base python -m mypy \
  src/quant/research/m3/g1_workflow.py src/quant/research/m3/run_g1.py
→ Success: no issues found in 2 source files
```

未跑全量 pytest；五段 fake 长测本轮未重跑（单 HISTORY 已证实 ~229s，全链路易再超 15min）。

## 4. 给独立初验的提示

- 对抗项仍按任务单 §9；自证合法阶段若需 HISTORY+，请复用/串行 `test_five_stage_fake_publish...`，勿在自证单测内再嵌一套 300 成分全链路。
- 本交付状态仅为**待独立初验**。
