# M1 HK-HISTORY-R2：无行情事实与零网络恢复任务单

日期：2026-07-31（Asia/Shanghai）

状态：**合同冻结；权威无交易事实来源待确定，生产实现不得先行猜测**

执行角色：主 Agent。用户当前要求省略外部实现与外部初验；内部 subagent 仅完成只读缺口审计，
生产实现、测试与最终裁定由主 Agent完成。

## 1. 目标

在永久保留 R1 失败证据的前提下，解决
`01065.HK@2026-05-05`“市场开市但单证券无行情”无法与供应商漏数区分的问题，并建立：

1. 可审计、精确到 `(symbol, trade_date)` 的权威无行情事实；
2. 新 plan / 新 journal 下对既有完整 raw 的严格零网络恢复；
3. 后续新请求仍保持一次一个、无自动 retry、raw-first、全批闭合前不写 clean；
4. available-history Gate 与回填计划消费同一无行情事实 SSOT。

R1 plan SHA
`ffbf8f345626b9db834a7b4c31fa8c31a6b60ffe5053ab4953a27bb2c4c50a03`
及其 journal 永久只读。本任务不得通过改写旧 expected keys、补造 OHLC 或确认重试第三批来“修复”旧记录。

## 2. 已冻结事实

- R1 共 8 批；当前 2 receipt / 3 intent / 3 attempt / 0 finalize。
- batch 1：4,800 / 4,800；batch 2：4,742 / 4,742。
- batch 3：4,690 / 4,691，唯一缺
  `01065.HK@2026-05-05`；80 个目标证券均出现且无重复。
- 2026-07-22 targeted raw-first 探针再次返回 0 行且列集合完整；相邻
  `2026-05-04/2026-05-06` 均有行情。
- 空响应只证明“供应商稳定无行”，不等于权威停牌或无交易事实。
- `02983.HK@2026-07-10` 是独立的真实行情来源缺口；不得借本任务用
  `02525.HK` 替代、伪装成 Tushare 行或静默排除。

## 3. 前置来源裁定

生产实现前必须冻结 `01065.HK@2026-05-05` 的权威无交易事实来源及许可边界。证据最少包含：

```text
schema_version
symbol
trade_date
market
reason
source
source_record_id
source_as_of
raw_selector
raw_file_sha256
raw_metadata_sha256
```

`reason` 使用版本化枚举，首个切片只接受能明确证明“该证券当日没有可形成日线的交易”的状态；不得把
targeted 0 行、零成交量 bar、缺字段、接口异常或未知状态转换为豁免。

来源尚未确定时，只允许完成接口、fixture 与 fail-closed 测试；不得创建真实 PASS evidence。

### 3.1 2026-07-31 官方来源探针

已确认 HKEX `Daily Quotations (Main Board)` 是合适的候选 SSOT。官方报告包含：

- `QUOTATIONS`；
- `SALES RECORDS FOR ALL STOCKS`；
- `DEALINGS IN SECURITIES SUSPENDED DUE TO INSUFFICIENT PUBLIC FLOAT`；
- 报告交易日和全市场摘要。

当前入口为
`https://www.hkex.com.hk/eng/stat/smstat/dayquot/qtn.asp?sc_site=market_website`，单日报告使用
`dYYMMDDe.htm`。2026-07-31 实测网页只列出 2026-06/07，历史
`d260505e.htm` 已返回 404；HKEX 官方同时把更早数据归入 Historical Data Services / Data Marketplace。
因此不能把网页当前不存在、HKEXnews 没有 01065 停牌公告，或 Tushare targeted 0 行拼接成“权威无交易”
证明。真实 R2 evidence 必须来自取得许可并留存 raw 的 2026-05-05 Daily Quotations 或同等级官方历史产品。

## 4. plan v2 与身份

新增 plan 版本，不原地扩展 R1 JSON：

- 固定完整逐证券 expected sessions；
- 另绑定 canonical no-trade evidence 集合及集合 SHA；
- 每个 request 的 wire 参数、排序 symbols、原始 expected sessions 和 effective expected bar keys
  均进入 plan；
- `effective expected = original expected - precisely proven no-trade keys`；
- request ID 继续只绑定实际 wire 参数，使 wire 参数未变的前三批可复用既有 raw；
- plan SHA 必须绑定 evidence identity、原始与 effective expected 集合；
- 新 plan 使用全新 journal root，旧 plan/journal 不得迁移、覆盖或补写 receipt。

同一 evidence 不得覆盖目标外证券、日期、市场或多个 session。重复、冲突和多来源不一致必须
`HK_HISTORY_REFERENCE_INVALID`。

## 5. 显式离线恢复

CLI 新增互斥模式：

```text
--recover-existing-only
```

该模式：

1. 加载并复验 seed；
2. 按 plan 顺序检查 receipt；
3. 对 `COMPLETE raw + no receipt` 使用 v2 effective expected keys 重新验证并写入新 journal receipt；
4. 遇到首个 `ABSENT` raw，返回 `INCOMPLETE`；
5. connector 构造与网络调用次数必须严格为 0；
6. 不写 intent、attempt、failure、clean 或 finalize。

普通模式保持“一次最多一个新 API request”。不得在离线恢复完成后于同一进程自动进入网络阶段。

前三批恢复的目标结果：

```text
receipt_count=3
intent_count=0
attempt_count=0
api_calls=0
clean_writes=0
batch_3=4690/4690 PASS
```

旧 journal 和 raw bundle 必须在恢复前后字节不变。

## 6. available-history Gate

`query_available_bar_window` 与 `query_universe --require-available-history` 必须消费同一已验证 evidence
投影：

- 只有权威 evidence 精确覆盖的 key 可从 required bar keys 排除；
- 输出审计摘要至少包含豁免数量和 reason 计数；
- 无证据缺行、额外 bar、生命周期外 bar、重复键、evidence 摘要漂移继续 fail closed；
- 不得把 Gate 改成“取最近 N 个现有观察”，因为这会掩盖中间任意漏数。

## 7. 文件白名单

生产代码：

- `src/quant/domain/schemas.py`
- `src/quant/data/hk_history_backfill.py`
- `src/quant/data/backfill_hk_history.py`
- `src/quant/data/query.py`
- `src/quant/data/query_universe.py`

测试：

- `tests/unit/test_hk_history_backfill.py`
- `tests/unit/test_backfill_hk_history.py`
- `tests/unit/test_query.py`
- `tests/unit/test_query_universe.py`
- `tests/unit/test_schemas.py`

文档按公共 CLI 和 Gate 变化同步 `README.md`、路线图及验收报告。不得修改 M3 G1、交易执行或
`archive/legacy_pre_greenfield/`。

## 8. 失败语义

- evidence 结构、来源、identity、raw 或目标覆盖非法：
  `HK_HISTORY_REFERENCE_INVALID`；
- plan v1/v2、evidence SHA、expected keys 或 journal root 冲突：
  `HK_HISTORY_PLAN_CONFLICT`；
- 离线模式遇到首个不存在的 raw：稳定返回 `HK_HISTORY_INCOMPLETE`，不是 API 失败；
- raw 额外/重复/缺失键、列漂移、目标外证券或达到 5,000 行：
  `HK_HISTORY_RAW_INVALID`；
- 全部 receipt 前 finalize：
  `HK_HISTORY_INCOMPLETE`。

错误输出不得包含 token、供应商原文或绝对路径。

## 9. 强制反例

1. targeted 0 行但无权威 evidence：第三批仍为 `HK_HISTORY_RAW_INVALID`。
2. evidence 的 symbol/date/source/raw SHA 任一漂移：`HK_HISTORY_REFERENCE_INVALID`。
3. evidence 覆盖两日但 raw 只缺一日：不得扩大豁免。
4. 新 plan 指向旧 journal，或尝试覆盖旧 plan：`HK_HISTORY_PLAN_CONFLICT`。
5. 离线恢复遇 batch 4 `ABSENT`：返回 incomplete，connector 构造和 API 调用均为 0。
6. batch raw 有额外键、重复键、目标外证券或 5,000 行：继续 fail closed。
7. 把其他供应商的 `02983` 行改写为 `source=tushare`：provenance / receipt 校验必须拒绝。
8. available-history 缺中间 session、但仍有最近 60 个现有观察：必须失败。
9. v2 receipt 存在但 evidence 后被替换并同步改 plan 文件：receipt 重验必须失败。

## 10. 实施与真实执行顺序

1. 冻结并留存权威无交易来源的一次最小 raw-first 探针；
2. 实现 Schema、plan v2、离线恢复和 Gate 共同投影；
3. Windows 定向反馈；WSL Miniforge base 同组 pytest、Ruff、mypy；
4. 新建 v2 plan / journal，零网络恢复 batch 1–3；
5. 主验确认旧 journal/raw 字节不变；
6. batch 4–8 仅需 5 次 `hk_daily` 请求，每次一个、间隔至少 3,600 秒；
7. 全批通过后仍不得 finalize，直到 `02983.HK@2026-07-10` 的合规行情来源合同独立关闭；
8. 最终双 Route Gate 通过后，才可关闭 HK60 子项。

31 个 ETF Instrument 的许可来源与港股复权链属于 M1 的另外两个 Gate；HK60 通过不自动关闭它们。
