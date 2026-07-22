# M3 G1-R1C 分阶段 CLI 独立初验报告（R1C-A）

日期：2026-07-16  
初验模型：`cursor-grok-4.5-high`（非 fast；**未使用** GPT/Terra）  
身份：外部独立初验 Agent（**未参与** R1C-A 实现）  
结论：**通过（可交主验）**；**披露 R1B 亦待主验**；**未关闭** G1 / B4 / M3 / R1C Gate；**未勾选**路线图

环境：`cwd=/home/mabw/win/Cursor/quant`；`/home/mabw/miniforge3/bin/conda run -n base …`。  
未改生产代码、未改仓库测试、未执行 `git init`、未跑全量 pytest、未真实联网。

---

## 1. 初验范围与证据边界

| 项 | 处理 |
|---|---|
| 任务合同 SSOT | `docs/agent/M3_G1_R1C分阶段CLI与真实全量运行外部闭环任务单.md`（§3–§7、§9、§10 代码初验） |
| 实现者自述 | `docs/agent/M3_G1_R1C分阶段CLI交付报告.md`（**不作证据**） |
| 只读核对 | `src/quant/research/m3/run_g1.py`、`tests/unit/test_m3_run_g1.py`、`README.md` CLI 段 |
| 写入白名单 | **仅本报告** |
| 禁止 | 改代码；全量 pytest；真实联网；宣称 Gate 关闭 |

对抗使用一次性 `/tmp` 脚本（不入库）。

---

## 2. 质量命令复跑摘要（初验自跑为准）

| 命令 | 摘要 |
|---|---|
| `python -m pytest -q tests/unit/test_m3_run_g1.py` | **25 passed**（约 2.1s） |
| `python -m ruff check src/quant/research/m3/run_g1.py tests/unit/test_m3_run_g1.py` | **All checks passed** |
| `python -m mypy src/quant/research/m3/run_g1.py` | **Success: no issues found in 1 source file** |
| 全量 pytest | **未跑**（任务禁止） |
| 真实 INDEX/HISTORY | **未跑**（R1C-A 范围外） |

---

## 3. 任务书逐条映射（§3–§7 / §9 / 初验关注点）

### 3.1 唯一 CLI 入口与参数禁令（§3）

| 要求 | 证据 | 判定 |
|---|---|---|
| 唯一入口 `python -m quant.research.m3.run_g1` | `run_g1.py` `__main__` → `main()`；README CLI 段一致 | 通过 |
| 公共参数仅 `--config` / `--project-root`；`run-all --stop-after` 默认 `PREPARE` | `_build_parser`；`run-all` choices=`INDEX…PUBLISH` | 通过 |
| 禁止 `--token` / `--raw-root` / `--journal-root` / `--release-root` / rate·version 覆盖 | `_FORBIDDEN_FLAGS` + `_reject_forbidden`；实现者 `test_argparse_rejects_token_and_unknown` | 通过 |
| 业务值来自 C0；token 不经 CLI | `_validate_config_path` → `load_m3_config`；无 token 形参 | 通过 |

### 3.2 停止点与 connector 实例化边界（§3–§4）

| 要求 | 证据 | 判定 |
|---|---|---|
| `status/prepare/publish` 不实例化 connector | `_run_command` 三分支无 `_new_*`；`test_status_prepare_publish_never_construct_connectors` | 通过 |
| `index/history` 仅 Tushare；`reference` 仅 BaoStock | `_run_command` + `test_index_instantiates_only_tushare` / `test_reference_instantiates_only_baostock` | 通过 |
| `run-all` 按阶段懒构造；前置失败不提前后段 connector | `test_run_all_stop_after_and_lazy_connectors` / `test_run_all_mid_failure_no_later_connector` | 通过 |
| 单段不自动补前置；仅 `run-all` 顺序推进 | `history` 直调 `run_g1_history_stage`（不先 index）；`test_history_without_index_no_connector` 证 INDEX_INCOMPLETE | 通过 |
| `run-all` 复用已完成阶段 | `completed` 集合跳过；`test_run_all_resume_skips_completed` | 通过 |
| `status` 合法未完成 → exit 0 / `INCOMPLETE` | `test_status_incomplete_exit_zero` | 通过 |

### 3.3 `G1CliResultV1` stdout 合同（§5）

| 要求 | 证据 | 判定 |
|---|---|---|
| 一行严格 JSON；键排序；紧凑 separators；`allow_nan=False`；UTF-8 | `_emit` + `test_stdout_strict_json_no_paths_or_nan` | 通过 |
| schema / 字段闭包与 dataclass | `G1CliResultV1` + `_result_mapping` | 通过 |
| argparse 未得合法 command → `command=None`；合法后保留 literal | `test_argparse_*`；config 失败保留 `command=status`（symlink 测） | 通过 |
| 非 FAILED 不得带 error；FAILED 必有 code；stage 前缀自证 | `__post_init__` | 通过 |
| 不得输出路径/token/样本；未知异常不泄原文 | `test_unknown_exception_maps_internal` | 通过 |
| identity：PREPARE 返回带 release_id、无 manifest；PUBLISH 才有 manifest | `_identity_from_state`；`test_prepare_twice_identity_stable` / `test_status_success_when_published` | 通过 |
| digest 裸 hex 自证 | `__post_init__` **未**校验 hex 形态（弱项，见 §5 残余） | 弱通过 |

### 3.4 退出码与 CLI-only codes（§6）

| 要求 | 证据 | 判定 |
|---|---|---|
| 0/2/3/4/5/6/7 矩阵 | `_exit_for_workflow` + `test_exit_code_matrix` | 通过 |
| CLI-only：`CLI_ARGUMENT_INVALID` / `CLI_CONFIG_INVALID` / `CLI_INTERNAL_ERROR` / `OUTPUT_REDACTION_FAILED` | `_CLI_CODES`；失败仍写 FAILED JSON；stderr `op:code` 或 `CLI:code`；无 traceback | 通过 |
| `main()` 返回 int；测试可调 `_run` | `main` / `_run(write_output=…)` | 通过 |

### 3.5 敏感扫描（§6.2）

| 要求 | 证据 | 判定 |
|---|---|---|
| 对最终 JSON bytes 扫描；命中 → 不输出原 bytes，改 `OUTPUT_REDACTION_FAILED` / exit 2 | `_sensitive_hit` / `_emit_redaction_failed`；`test_redaction_failure_on_sensitive_payload` | 通过 |
| 模式含 token/password/Bearer/盘符/`/mnt/`/`/home/`/`tushare.local.toml`；无任意长 hex 规则 | `_SENSITIVE` regex | 通过 |
| status/prepare/publish 不为扫描加载 token | 三命令不构造 connector、不读 token 文件 | 通过 |

### 3.6 Tushare 分类器（§7）

| 要求 | 证据 | 判定 |
|---|---|---|
| `TimeoutError` / 网络 errno → NETWORK；非网络 OSError → PERMANENT | `test_classify_timeout_and_network_errno` | 通过 |
| rate limit / 频次 → RATE_LIMIT；502/503/504 / temporarily unavailable → TRANSIENT_SERVER；其余 PERMANENT | `test_classify_rate_limit_and_transient` | 通过 |
| 链循环 / 恶意 `__str__` 安全退化；不保存文本 | `_safe_exc_text` + seen-set；`test_classify_malicious_chain_and_sensitive_message` | 通过 |
| 私有，仅供 workflow 注入 | `_classify_tushare_error` 传入 index/history | 通过 |

### 3.7 `run-all --stop-after` 与 publish unsupported（§4 / §9）

| 要求 | 证据 | 判定 |
|---|---|---|
| 各 stop-after 严格停止；默认停 PREPARE 不 publish | `test_run_all_default_stop_prepare`；INDEX stop 测 | 通过 |
| `publish` unsupported：CLI 不直调底层 publisher；经 `publish_g1_workflow`；exit 7 | 模块无 publisher import；`test_publish_unsupported_exit_7`（workflow 调用 1 次，门禁在 R1B） | 通过 |

### 3.8 实现者测试矩阵（§9）对照

实现者 25 测覆盖：七命令 connector 边界、stop-after/中段失败/resume、stdout 合同、exit 矩阵、禁参、分类器、脱敏、publish unsupported、双 prepare、import 隔离、socket 阻断 status。  
**未见**：stdout mid-write partial（本初验补）。

---

## 4. 新增对抗反例（实现者未用）

### 4.1 stdout partial-write（主反例）

- **脚本**：`/tmp/r1c_adversarial_stdout_partial_write.py`（一次性；不入库）
- **手法**：自定义 stdout 在写出约半行 JSON 后抛 `OSError`，模拟管道中断 / partial-write
- **观察**：
  - 正常路径：单行 299B JSON，`status` → exit 0 / `INCOMPLETE`
  - 对抗：`main` **向上传播** `OSError`（未捕获）；stdout 残留约 149B 截断 JSON；**未**伪造成功完整合同行；stderr 空
- **判定**：相对任务「成功路径一行严格 JSON / 不得谎报 SUCCESS」——**未硬失败**（无 exit 0 假完整合同）。记为**残余风险**：生产 `main` 对 stdout IO 错误未归一为 `CLI_INTERNAL_ERROR`+稳定 FAILED JSON。建议主验/后续可选加固，**不作为本初验退回因**。

实现者已有：未知参数、config symlink、恶意 `__str__` 链、`run-all` resume；故选 **stdout partial-write** 作为未覆盖对抗。

---

## 5. 残余与披露（非退回）

1. **R1B 待主验**：本包基于待主验 R1B 公共 API；R1B 主验若改签名/失败语义，R1C 需跟进。
2. **stdout IO 中断**：见 §4.1；当前失败模式为异常外溢 + 截断残留，非假 SUCCESS。
3. **`G1CliResultV1` digest/identity 出现条件**未在 `__post_init__` 做裸 hex / 阶段联动强校验（依赖构造路径正确）。
4. **未关 Gate**：R1C-A 代码初验通过 ≠ G1 Gate；真实全量 / 正式 PUBLISH 不在本包。

---

## 6. 结论

| 项 | 内容 |
|---|---|
| 结论 | **通过（可交主验）** |
| 报告路径 | `docs/agent/M3_G1_R1C分阶段CLI独立初验报告.md` |
| 定向 / ruff / mypy | 25 passed / All checks passed / Success |
| 新增反例 | stdout 半行写出后 `OSError` 外溢，无假 SUCCESS 完整合同 |
| Gate | **未关闭**；披露 **R1B 亦待主验** |
| 返工 | 无需六项返工格式 |

实现者无需按标准返工格式返工；可交主 Agent 终验（代码阶段 R1C-A）。真实全量运行须待主验通过后再启。
