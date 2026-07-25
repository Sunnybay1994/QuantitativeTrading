# 2026-07-23 外部 Cursor 协调 Agent：阶段性最终交付总报告

> 交回用户 → Codex 最终验收。**本报告不声称 Codex 最终验收通过。**

- 工作区：`F:\AI_Coding\QuantitativeTrading` ≡ WSL `/home/mabw/AI_Coding_win/QuantitativeTrading`
- Git HEAD：`ed77978`（脏工作树已全程保护）
- 协调角色：外部 Cursor 协调 Agent（接替 Codex 执行；实现/初验职责分离）

## 1. 完成的任务与 Gate 状态

| 项 | 状态 |
|---|---|
| R5 最小 fixture 独立初验 + 协调主验 | **子包阶段通过**（不宣布 B1B/G1 Gate） |
| G1 零网络首败定位（event_id 闭包） | **完成** → 实现缺陷返工闭环 **阶段通过** |
| 分红空腿 null 解析 | **阶段通过** |
| 窗外缺 ex_date 跳过 | **阶段通过** |
| 正式 full candidate / HISTORY stage | **仍失败**（见正式数据缺陷裁定） |
| REFERENCE / PREPARE / PUBLISH | **未进入** |
| VerifiedG1Release / G2A… | **未开始**（无 release；PUBLISH 另有 WSL2/ext4 环境阻塞） |
| M4 A 股 Paper 全闭环 | **未开始**（依赖 M3 G1） |

## 2. 当前真实阻塞

1. **正式数据**：`002131.SZ` 实施行窗内 `ex_date=null`（`record_date=20171213`，`div_listdate=20171218`）。按已验收合同 fail closed。裁定见 [`M3_G1_正式数据缺陷裁定_002131缺ex_date窗内.md`](M3_G1_正式数据缺陷裁定_002131缺ex_date窗内.md)。解除需新 raw/receipt 或先改 SSOT。
2. **环境**：Ubuntu **WSL1/wslfs**，`RENAME_NOREPLACE=False`，固件虚拟化关闭。正式 PUBLISH 需用户启用 VT-x 并提供经探针的 WSL2 ext4 root。

## 3. 角色映射（本轮外部会话）

| 子包 | 实现 | 独立初验 | 协调主验 |
|---|---|---|---|
| R5 fixture | 既有交付 | 全新 `cursor-grok-4.5-high` | 本协调会话（resume 2 passed / 39.75s） |
| event_id 闭包 | 全新 high | 另一全新 high | 本协调（7→后随返工增至更多 passed） |
| 空腿 null | 全新 high | 另一全新 high | 本协调（10 passed） |
| 窗外缺 ex_date | 全新 high | 另一全新 high | 本协调（13 passed） |

CLI 教训：Windows `cursor-agent` ArgumentList 中文易截断；应用短 ASCII boot 指向 UTF-8 prompt 文件。

## 4. 主要修改文件（相对接任时生产/测试增量）

生产/测试（返工累计）：

- `src/quant/data/m3_execution_facts.py`（event_id 闭包；空腿；窗外 null ex_date）
- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_m3_g1_workflow.py`（R5，接任前已有；本轮只读初验）

文档（任务/交付/初验/主验/裁定/进度，节选）：

- R5：任务单、交付、独立复验、协调阶段验收
- 闭包 / 空腿 / 窗外 ex_date：各任务单、交付、初验、阶段验收
- `M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md`
- `M3_G1_正式数据缺陷裁定_002131缺ex_date窗内.md`
- `20260722_Codex至Cursor后续整体交接_协调Agent进度与交付报告.md`
- 本总报告

诊断产物（仅 `artifacts/g1_component_diag_20260722/`，零网络）：`summary.json`、enrich/inspect 脚本与 JSON、diag 日志。

## 5. 实际验证命令与结果（摘要）

| 命令范围 | 结果 |
|---|---|
| R5 resume 两测（WSL base） | `2 passed` in ~40s |
| R5 对抗探针 | `SUMMARY PASS failed=0` |
| execution_facts 定向 `-k "corporate_action or ledger or dividend"` | 最终主验 **`13 passed`**；ruff/mypy/`git diff --check` 绿 |
| 零网络分层诊断（修复后） | 越过原 event_id/空腿/窗外问题；现卡在 `002131.SZ` 窗内缺 ex_date |
| 五个 510300 API | **零新增请求** |
| 正式 raw/journal/receipt | **未修改** |

## 6. 真实数据 / API 请求统计

- 正式 Tushare：**0** 次新请求（全程零网络复用 receipt）
- 510300 五 identity：**未重请求**

## 7. 未解决风险与环境阻塞

- full candidate 被 `002131.SZ` 正式数据缺陷 fail closed
- WSL1 无法满足不可变 PUBLISH 合同
- 曾出现 `five_stage` 在 WSL1 上 ~9h 未完成（已杀）；不以该测关闭 R5
- 公司行动正式数据可能还有更多残缺行；当前诊断在首个窗内缺 ex_date 处停止（正确）

## 8. 建议 Codex 最终验收时执行的命令

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading

# R5
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output python -m pytest \
  tests/unit/test_m3_g1_workflow.py -q \
  -k "history_bounded_incomplete_then_resume_success or history_unbounded_incomplete_still_fail_closed" \
  --durations=5

# 公司行动返工累计
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output python -m pytest \
  tests/unit/test_m3_execution_facts.py -q -k "corporate_action or ledger or dividend" --durations=10
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output python -m ruff check \
  src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output mypy src/quant/data/m3_execution_facts.py

# 只读确认数据裁定样本仍 fail closed（零网络）
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output python -u \
  artifacts/g1_component_diag_20260722/enrich_event_invalid.py
# 预期：FAIL symbol=002131.SZ code=G1_CORPORATE_ACTION_EVENT_INVALID

# 禁止：REFERENCE/PREPARE/PUBLISH；禁止重复五个 510300 API
```

## 9. git status / 定向 diff 摘要（验收时请重跑）

接任时已有大量未提交文档与 M3 实现；本轮在既有脏树上追加公司行动三处返工与多份 agent 文档。**请 Codex 用 `git status --short` 与针对**

- `src/quant/data/m3_execution_facts.py`
- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_m3_g1_workflow.py`

**的 `git diff -w --stat` 核对，勿 reset/checkout。**

## 10. 建议用户/Codex 下一步

1. 裁定是否为 `002131.SZ` 拉取/等待供应商更正 raw（新 snapshot + receipt），或修订 SSOT 允许窗内缺 ex_date 的审计省略。
2. 主机启用虚拟化并准备 WSL2 ext4 后，再谈正式 PUBLISH。
3. full candidate 通过前不得进 REFERENCE/PREPARE/PUBLISH，不得启动真实 G2A。
