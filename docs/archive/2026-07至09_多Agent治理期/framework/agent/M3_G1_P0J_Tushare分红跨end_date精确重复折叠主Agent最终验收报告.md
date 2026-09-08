# M3 G1 P0J：Tushare 分红跨 end_date 精确重复折叠主 Agent 最终验收报告

状态：**P0J / P0J-R1 通过；G1 仍阻塞于下一独立质量缺陷**

日期：2026-07-29（Asia/Shanghai）

## 1. 验收结论

P0J 的目标行为已经闭包：

- Tushare `dividend` 正式字段除 `end_date` 外全部严格相同的实施行只形成一个经济事件；
- canonical `end_date` 取精确簇内最大值，`raw_row_count` 保留原始行总数；
- 600733.SH 的两条跨 `end_date` 送股行只计一次 `stock_ratio=2.5`；
- 600930.SH 依靠不同 `ann_date` 保留两个真实事件；
- `None` 与 `0`、任一正式 provenance 字段差异以及输入顺序均不被宽松等价；
- canonical 改写后若出现同 rank / decision、不同 exact provenance 的碰撞，稳定抛出
  `G1_CORPORATE_ACTION_VERSION_CONFLICT`，不静默合并；
- selection 身份已升级为
  `tushare_dividend_cninfo_rights_capital_iso_date_cross_end_exact_fold_v6`。

本结论只接受 P0J/P0J-R1，不宣称 G1、REFERENCE、PREPARE、PUBLISH、Linux publish Gate 或新
`VerifiedG1Release` 通过。

## 2. 交付链

| 阶段 | 提交 | 结论 |
|---|---|---|
| P0J 冻结 | `0683bdc` | 跨 `end_date` 精确重复折叠合同 |
| 外部实现 | `f467c1a` | v6 selection 与测试矩阵 |
| 独立初验 | `af76cee` | FAIL：canonical 后可能与另一 provenance 行静默合并 |
| P0J-R1 冻结 | `8e47d4f` | canonical 后 provenance 碰撞 fail-closed 合同 |
| 外部返工实现 | `247d6d7` | exact identity 贯穿两级折叠 |
| 外部独立复验 | `ec92dbe` | PASS；新增 `base_date` / `cash_div` 对抗反例 |

## 3. 主 Agent 代码与测试验收

主 Agent 逐项复核 `0683bdc^..247d6d7` 的生产代码和测试差异，确认：

- exact identity 复用 `_dividend_cross_end_exact_identity`，包含全部正式字段且只排除
  `end_date`；
- `_fold_identical_candidates` 只有 rank、decision 和 exact identity 全同才累计；
- exact identity 只存在于内部 wrapper，未进入 Schema 或公开摘要；
- 没有新增第二套 selector、阈值放宽或证券特判。

Windows 原生 Miniforge：

```text
pytest tests/unit/test_m3_execution_facts.py
       -k "dividend or corporate_action_selection or reconciliation or version_constants" -q
26 passed, 107 deselected
ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py
All checks passed
mypy src/quant/data/m3_execution_facts.py
Success
```

WSL Miniforge base 同一 pytest 聚焦命令：

```text
26 passed, 107 deselected
```

## 4. 正式零网络证据

对正式 637 份 dividend 收据执行 selection：

```text
637/637 responses success
ledger=6014 rows
selection_evidence=6038 rows
selection_version=...cross_end_exact_fold_v6
```

关键正式形状：

- 600733.SH：`ledger=1`、`stock_ratio=2.5`、canonical `end_date=2018-08-23`、
  `raw_row_count=2`；
- 600930.SH：`ledger=2`，分别保留 `ann_date=2026-01-08` 和 `2026-01-24`。

证据产物：

```text
artifacts/g1_component_diag_20260722/validate_formal_dividend_selection_p0j.json
```

P0J 后正式 `status` 于 Windows 原生执行约 54 分钟，结束为：

```text
outcome=FAILED
error_operation=INSPECT
error_code=G1_WORKFLOW_QUALITY_FAILED
```

产物：

```text
artifacts/g1_component_diag_20260722/formal_status_p0j_v1.out.log
artifacts/g1_component_diag_20260722/formal_status_p0j_v1.err.log
```

该结果证明正式流程已重新进入候选审计，但顶层 CLI 折叠了具体失败上下文。零网络捕获探针随后裁定
下一首败仍在 600733.SH，但已越过原 2018-09-19 重复送股，转为 2018-09-27 股改复牌日的独立
no-event factor 跳变；证据见
[`20260729_P0J后正式首败_600733股改对价复牌因子.md`](20260729_P0J后正式首败_600733股改对价复牌因子.md)。
这不能证明 candidate 或 HISTORY Gate 已通过。

## 5. 提交卫生与已知非阻断项

- 实现白名单源码、测试的 `git diff --check` 通过；
- `af76cee` 的历史 FAIL 报告和 `ec92dbe` 的 PASS 报告各保留 Markdown 双空格硬换行，
  宽范围 `git diff --check` 会报告这些文档行尾；报告中的检查范围明确只包含实现白名单文件，
  因而不存在测试自报失真；
- 工作区其他既有 modified docs 属交接前换行/状态噪声，本轮未暂存、归一化或覆盖。

## 6. 下一步

下一首败已裁定为 600733 股改股份对价缺失。后续：

1. 按诊断记录拆分并冻结 P0K-A raw-first 数据链与 P0K-B 事件/对账语义；
2. 分别进入新的外部实现 → 全新外部独立初验 → 主 Agent 终验闭环；
3. 只有正式 `status` 全部通过后，才按新源码身份重建 REFERENCE / PREPARE / PUBLISH。
