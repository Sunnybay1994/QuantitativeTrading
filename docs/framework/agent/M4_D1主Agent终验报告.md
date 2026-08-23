# M4-D1 主 Agent 终验报告

日期：2026-07-16  
结论：**不通过，退回“外部实现 → 全新外部独立初验”闭环**  
范围：M4-D1 repository Protocol、production adapter 与 in-memory contract fake

## 1. 证据

- 冻结合同：[`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) §4、M4-D1。
- 外部交付与初验：[`M4_D1数据访问端口交付报告.md`](M4_D1数据访问端口交付报告.md)、
  [`M4_D1数据访问端口独立初验报告.md`](M4_D1数据访问端口独立初验报告.md)。
- 主 Agent 定向复跑：`tests/unit/test_execution_ports.py` **11 passed**。
- 未跑全量 pytest；下列纯内存反例已证明 repository 信任边界不成立。

## 2. 主验反例

### P0-A：InMemory mapping key 与 snapshot 内容未绑定

- **现象**：把证券 A 的 verified snapshot 存在 `(session_date, {证券B})` key 下，请求证券 B 时原样返回 A。
- **根因**：构造器直接 `dict(snapshots)`；exact lookup 命中后只做 PIT，不核对 key、snapshot 交易日、证券集合
  和 snapshot identity。
- **结果**：`INMEMORY_KEY_CONTENT_MISMATCH_ACCEPTED 600000.SH`。
- **影响**：合同 fake 会给上层测试制造虚假正确结果，使 B4/P3 等消费者在错误证券集上仍显示通过。

### P1-B：quality gate 接受非 bool

- **现象**：`CleanMarketFactsBundle.quality_passed=1` 被当作通过并生成 verified snapshot。
- **根因**：bundle 无 strict constructor，repository 使用 truthiness 而非 exact bool。
- **结果**：`NON_BOOL_QUALITY_ACCEPTED 0a4559f0`。

### P1-C：畸形 bundle 外溢非合同异常

- **现象**：合法 bundle 类型但 `states=("bad",)` 时，repository 抛 `AttributeError`。
- **根因**：访问 `state.market/state.symbol` 前没有验证 tuple element；bundle 类型正确被误当作内容已验真。
- **结果**：`MALFORMED_BUNDLE_EXCEPTION AttributeError False`。

### P1-D：reader 异常未经稳定映射和脱敏

- **现象**：注入 reader 抛 `OSError("/home/user/private/market.parquet")`，load 原样外溢 OSError 和绝对路径。
- **根因**：reader 调用不在 adapter 的错误边界内；部分后续映射还使用 `raise ... from exc` 和 `str(exc)`。
- **结果**：`READER_ERROR_LEAK OSError True False`。
- **影响**：违反 repository typed fail-closed 和 M4 异常/路径脱敏不变量。

## 3. 结论

D1 当前为**主验不通过、待外部返工**。它仍是基于待返工 D0 的预实现；D0/D1 均复验通过前，不对
P0/P1/P3 作最终验收结论。返工合同见 [`M4_D1主验返工任务单.md`](M4_D1主验返工任务单.md)。
