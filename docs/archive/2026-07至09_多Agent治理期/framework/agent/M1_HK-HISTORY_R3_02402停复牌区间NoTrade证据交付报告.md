# M1 HK-HISTORY R3：02402 停复牌区间 No-Trade 证据交付报告

日期：2026-08-15
实现模型：`cursor-grok-4.6-high`
状态：实现与自测完成；待独立初验

## 结果

- 状态：已交付，待未参与实现的全新外部会话独立初验。
- 未联网、未读取 ignored token、未创建 `data/` / `artifacts` 业务产物、未 add/commit/push。
- 本会话只写入白名单生产/测试文件与本报告；任务单仅更新状态行。

## 修改文件及目的

| 文件 | 目的 |
| --- | --- |
| `src/quant/data/hk_history_backfill.py` | 将 user-approved 单 key 硬编码演进为 UA-M1-001 / UA-M1-004 两个 exact record 分支；未知 `source_record_id` 拒绝；UA-M1-004 raw 按 `hk-no-trade-user-approved-suspension-range-v1` 重建 canonical payload。 |
| `src/quant/domain/schemas.py` | `HKNoTradeEvidenceSchema` dataframe check 与 `__post_init__` 使用同一 exact 范围：01065 单日 + 02402 的 13 个开市日。 |
| `tests/unit/test_hk_history_backfill.py` | 01065 回归、02402 13 项共享 raw/plan 投影、范围/payload/hash 漂移、少一/多一/重复、hostile 脱敏。 |
| 本报告 | 压缩记录修改、验证与剩余风险。 |

明确未修改：mapper、connector、raw store、CLI、配置、其他测试/文档；未物化正式 evidence/plan/journal。

## 冻结的 UA-M1-004 合同

- `source_record_id=UA-M1-004`
- `raw_selector=user-approved-consensus/ua-m1-004-02402-2026-04-01-to-2026-05-04.record`
- 13 个 no-trade 日（一日一 key，共享同一 retained raw/metadata，`evidence_sha256` 独立计算）：
  `2026-04-14,15,16,17,20,21,22,23,24,27,28,29,30`
- `2026-05-04` 不是 no-trade。
- canonical raw 字段：`schema_version`、`approval_id`、`symbol`、`suspension_at=2026-04-01T01:00:00+00:00`、`resumption_at=2026-05-04T01:00:00+00:00`、`no_trade_dates`、三条 observations（两条 exact HKEX URL + `RETAINED_ZERO_ROW`）。
- UA-M1-001 payload / selector / record / identity 公式未改。

## 验证

| 命令 | 结果 | 摘要 |
| --- | --- | --- |
| `D:\Miniforge3\python.exe -m pytest tests/unit/test_hk_history_backfill.py tests/unit/test_schemas.py -q` | 通过 | 196 passed, 2 skipped |
| `ruff check` 两生产文件 + `test_hk_history_backfill.py` | 通过 | All checks passed |
| `mypy` 两生产文件 | 通过 | no issues found in 2 source files |

未运行 Linux/WSL Gate（任务书不要求）。未物化真实 evidence，因此正式 HK60 v2 recover/finalize 仍未关闭。

## 并发工作树说明

实现期间 `src/quant/domain/schemas.py` 同时出现非本任务的 `DailyBasic1dSchema`；`src/quant/domain/__init__.py` 与 `tests/unit/test_schemas.py` 亦有对应脏改。本会话未回滚、未继续改这些非白名单文件。独立初验应把 `DailyBasic1dSchema` 视为其他会话产物，不计入本任务合同。

## 风险与交接

- 主 Agent 仍须用本实现的 canonical bytes 物化 02402 retained raw/metadata、13 项 evidence、新 v2 plan，并先零网络 recover 已有 raw。
- 本实现只改变 expected-key 证据闭包；不改 raw/mapper/OHLC/策略/现金/公司行动/订单语义。
- 下一步：未参与实现的外部独立初验；PASS 后主 Agent 再物化业务产物。
