# M3 G1-R1C 分阶段 CLI 交付报告（R1C-A）

日期：2026-07-16  
包号：**R1C-A**（CLI + fake continuation；不含真实联网全量）  
实现模型：`cursor-grok-4.5-high`（非 fast；未用 GPT/Terra）  
状态：**待独立初验**

> 任务书路径写为 `docs/M3_G1_R1C…交付报告.md`；按 docs 治理放在 `docs/agent/`，本文件即该交付报告。

## 重要披露（前置依赖）

- **R1B** 当前状态：外部实现 + 独立初验/复验通过，**尚未主 Agent 终验**。
- 本包是基于**待主验** R1B 公共 API 的预实现；**不得**写成正式 verified Gate，也**未关闭** G1 / B4 / M3 Gate。
- 本交付**不宣称** Gate 通过；实现者自测不能代替独立初验或主 Agent 终验。

## 1. 冻结输入 / 输出摘要

### 输入（只读依赖）

- R1B 公共 API：`inspect_g1_workflow` / `run_g1_*_stage` / `prepare_g1_workflow` / `publish_g1_workflow` / `M3G1WorkflowError`（未改生产算法）
- C0：`load_m3_config`；connector 薄适配器：`TushareConnector` / `BaostockConnector`

### 输出（本包新增）

- 薄 CLI：`python -m quant.research.m3.run_g1`
- 规范 stdout：`G1CliResultV1` 一行严格 JSON
- 私有 `_classify_tushare_error`；敏感输出扫描 → `OUTPUT_REDACTION_FAILED`
- fake 测试证明停止点、恢复、exit code / summary 合同

## 2. 修改文件列表

| 路径 | 说明 |
|---|---|
| `src/quant/research/m3/run_g1.py` | 新建：薄 CLI |
| `tests/unit/test_m3_run_g1.py` | 新建：零网络 fake / 合同测试 |
| `README.md` | 仅新增唯一 CLI 使用说明与 WSL/base 命令 |
| `docs/agent/M3_G1_R1C分阶段CLI交付报告.md` | 本交付报告 |

未改：`g1_workflow.py` 业务算法、connector、data 合同、token/config、路线图。

## 3. 自测命令与摘要

环境：`/home/mabw/miniforge3/bin/conda run -n base …`（WSL Miniforge `base`；未用 Windows Python）。  
`.git` 目录为空（仅 `.` / `..`）→ 记为环境问题，本包未执行 `git init`。

| 命令 | 结果摘要 |
|---|---|
| `python -m pytest -q tests/unit/test_m3_run_g1.py` | **25 passed**（约 3s） |
| `python -m ruff check src/quant/research/m3/run_g1.py tests/unit/test_m3_run_g1.py` | **All checks passed** |
| `python -m mypy src/quant/research/m3/run_g1.py` | **Success**（修 connector 变量类型后） |
| 全量 `pytest` | **未跑**（任务默认定向覆盖） |
| 真实 INDEX/HISTORY | **未跑**（R1C-A 范围外） |

## 4. Fake 与真实网络

- **使用 fake**：测试 monkeypatch workflow 入口与 `_new_*_connector`；默认零网络（含 `socket` 阻断用例）。
- **未做真实网络**：无 Tushare/BaoStock 联网、无 2016–2026 回补、无正式 PUBLISH。
- **CLI 行为**：`status/prepare/publish` 不构造 connector；`index/history` 仅 Tushare；`reference` 仅 BaoStock；`run-all` 按阶段懒构造，前置失败不提前登录。

## 5. 已知限制

1. 依赖 R1B 待主验接口；若主验改动公共签名/失败语义，本包需返工。
2. WSL1 上 `publish` 仍可能稳定 `G1_WORKFLOW_PUBLISH_UNSUPPORTED`（R1B 既有门禁）。
3. 本包不含 R1C-B 真实全量 / R1C-C 正式 PUBLISH。

## 6. Gate 声明

- 交付状态：**待独立初验**。
- **未宣称** Gate / M3 / G1 / B4 / R1C 通过。
- **未勾选** `项目实施路线图.md`。
- **可否交初验**：是（代码阶段 R1C-A 自测完成，等待全新会话独立初验）。
