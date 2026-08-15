# M1 HK-HISTORY R3：02402 停复牌区间 No-Trade 证据任务单

日期：2026-08-15
状态：外部独立初验与主 Agent Windows 工程验收 PASS；允许物化 UA-M1-004 证据并恢复 HK60 v2
实现模型：`cursor-grok-4.6-high`

## 1. 现象与权威事实

HK60 v2 请求 `cb795f…ffaf` 已于 2026-08-15 14:46:28 将 4,772 行 Tushare raw 原样、不可变落盘，
但 receipt fail-closed 为 `HK_HISTORY_RAW_INVALID`。只读诊断确认：列、空值、主键、证券集合、OHLC mapper
和 `Bar1dSchema` 均合法；唯一差异是 `02402.HK` 缺少 2026-04-14 至 2026-04-30 的 13 个共同开市日。

权威来源闭环：

- HKEX suspension notice：
  `https://www.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040100185.htm`，明确 02402 H 股
  自 2026-04-01 09:00 起暂停买卖；
- HKEX resumption notice：
  `https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0504/2026050400135.htm`，明确 02402 H 股
  于 2026-05-04 09:00 恢复买卖；
- Tushare retained raw 在上述 13 日均无行，并从 2026-05-04 恢复行情。

用户已指示：这种小概率事件经多个来源确认一致后无需继续纠结，不影响策略和实盘。该指示构成本次
`UA-M1-004` 精确业务裁决，但不得泛化到其他证券、日期或来源。

## 2. 目标与不变量

在既有 `USER_APPROVED_MULTI_SOURCE_CONSENSUS` 下增加第二个 exact record，使 v2 plan 能从
`02402.HK` 原始 expected dates 中只减去以下 13 日：

`2026-04-14,15,16,17,20,21,22,23,24,27,28,29,30`。

必须保持：

1. 既有 `UA-M1-001 / 01065.HK@2026-05-05` raw、metadata、evidence identity 和 plan 行为逐字不变；
2. 新记录 exact：`source_record_id=UA-M1-004`，selector 为
   `user-approved-consensus/ua-m1-004-02402-2026-04-01-to-2026-05-04.record`；
3. 新 raw payload exact schema `hk-no-trade-user-approved-suspension-range-v1`，包含 symbol、suspension UTC、
   resumption UTC、上述 13 日、两条 exact HKEX URL/观察值及 Tushare retained-zero-row 观察；
4. 每个 `HKNoTradeEvidence` 仍是一日一 key；13 项可共享同一个 retained raw/metadata，但各自
   `evidence_sha256` 必须按现有 identity 公式独立计算；
5. 2026-05-04 不得作为 no-trade，区间外任何日期、其他 symbol、其他 record id/selector/source、URL 漂移、
   raw/metadata/hash 漂移均拒绝；
6. 只改变 expected-key 证据闭包，不改 raw、mapper、OHLC、策略、现金、公司行动或订单语义。

## 3. 生产修改

只允许修改：

- `src/quant/data/hk_history_backfill.py`
- `src/quant/domain/schemas.py`

实现要求：

- 把当前 user-approved 单 key 硬编码演进为两个 exact record 分支，不允许开放任意 caller record；
- `_verify_user_approved_no_trade_raw` 按 exact `source_record_id` 分支重建 canonical payload；未知分支拒绝；
- `HKNoTradeEvidence.__post_init__` 与 `HKNoTradeEvidenceSchema` 的 dataframe check 对两个 record 使用相同 exact
  范围，不得一处放宽、一处收窄；
- 不改变 public API、schema version、evidence identity、set identity、plan v2 或 receipt 格式；
- 所有 public 失败继续稳定脱敏、cause/context 为空。

本实现不创建实际 raw/evidence/plan，不联网。主 Agent 在代码通过后再用 canonical bytes 物化业务证据和新计划。

## 4. 测试与反例

只允许修改 `tests/unit/test_hk_history_backfill.py`，至少覆盖：

- 既有 01065 fixture 与其 frozen identity/plan 行为不变；
- 新 02402 exact 13 项共享 raw/metadata，loader 与 plan v2 构造通过，只减去这 13 日；
- 04-13、05-04、其他 symbol、record id、selector、source、URL、观察文本、no-trade dates 增删换序、raw 和
  metadata hash 漂移分别拒绝；
- 13 项少一/多一/重复 evidence 拒绝或导致 plan 不能满足 exact expected projection；
- hostile JSON/type/path 异常继续脱敏；
- 现有 v2/v3 minimal chain、recover/no-clobber 回归不受影响。

Windows：focused `test_hk_history_backfill.py`、Ruff 两生产文件+测试、mypy 两生产文件。无需 Linux。

## 5. 报告、禁止项与交付

唯一实现报告：
`docs/agent/M1_HK-HISTORY_R3_02402停复牌区间NoTrade证据交付报告.md`。

禁止修改 mapper、connector、raw store、CLI、配置、其他测试/文档；禁止读取 ignored token、联网、写 data/artifacts
业务产物、add/commit/push。实现完成后必须由未参与实现的全新外部会话独立复验；PASS 后主 Agent 才物化
actual evidence、新 plan 和新 journal，并先零网络 recover 已有 raw。
