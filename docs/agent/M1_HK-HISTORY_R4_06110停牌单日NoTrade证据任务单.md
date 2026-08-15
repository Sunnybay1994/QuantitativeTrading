# M1 HK-HISTORY R4：06110.HK 2026-06-25 停牌单日 No-Trade 证据任务单

状态：**R4 主验返工合同已冻结；R3 独立复验在 §10 范围内 PASS，但主 Agent 同型检查确认 UA-M1-001/004 仍可换标 HKEX source。允许全新外部实现会话按 §11 最小返工。** 真实 evidence/plan/journal 物化仍由主 Agent 在 R4 实现、独立复验和主验通过后执行。

日期：2026-08-15（Asia/Shanghai）
平台：Windows 工程闭环；不声明 Linux/ext4。
外部会话：实现与独立初验使用两个全新 Cursor 会话，显式 `--model cursor-grok-4.6-high`。

---

## 1. 现象与根因

HK60 v2b 第 7 批 `request_id=acf04ebeaae412950660e3f23b4116c7f51e6200e56c87d688249f38c8e8b0da` 于 2026-08-15 16:48（CST）完成唯一网络请求后稳定返回 `HK_HISTORY_RAW_INVALID`，限频器正确停止且未重试。

只读逐键差集：

- request effective expected keys：4,694；
- retained raw unique keys：4,693；
- duplicate=0、unexpected=0；
- 唯一 missing：`06110.HK@2026-06-25`。

该缺失是市场事实，不是 API 分页或传输失败：

1. HKEXnews 官方 Exchange Notice：`06110` 滔搏国际股份于 2026-06-25 上午 9:00 起停牌：
   `https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0625/2026062500129.htm`
2. Tushare 本次 immutable raw 在同一 80-symbol/60-session request 中只缺该键；其他 4,693 键完整。
3. 独立公开来源同日记载停牌（例如经济通停牌列表）：
   `https://www.etnet.com.hk/www/tc/news/news-article.php?category=latest&newsid=2026062568&section=categorized`

用户已明确授权：此类低概率单日无交易事件在多个来源一致且不影响策略/实盘时，不再反复纠缠。该授权只支持**精确证券×日期**证据，不允许泛化停牌规则。

---

## 2. 目标与不变量

新增第三类 exact user-approved no-trade record：

```text
approval_id / source_record_id = UA-M1-005
symbol = 06110.HK
trade_date = 2026-06-25
reason = NO_DAILY_TRADING_V1
source = USER_APPROVED_MULTI_SOURCE_CONSENSUS
raw_selector = user-approved-consensus/ua-m1-005-06110-2026-06-25.record
raw schema = hk-no-trade-user-approved-trading-halt-v1
```

它必须与 UA-M1-001（01065 单日）和 UA-M1-004（02402 13 日范围）并存，旧 identity/验证行为不变。`HKNoTradeEvidenceSchema` 只允许增加这一条 exact 析取，列、dtype 和其他规则不变；不得增加通配证券/日期，不得把该记录标作 `HKEX_DAILY_QUOTATIONS`。

---

## 3. Canonical raw payload

实现必须在 verifier 中冻结以下 canonical JSON 语义；生产代码不负责联网或写正式 raw：

```json
{
  "approval_id": "UA-M1-005",
  "decision": "NO_DAILY_TRADING_V1",
  "impact_assessment": {
    "changes_cash": false,
    "changes_corporate_actions": false,
    "changes_positions": false,
    "changes_real_orders": false,
    "changes_strategy_signal": false
  },
  "observations": [
    {
      "observation": "TRADING_HALTED_FROM_09_00",
      "source_kind": "HKEX_NEWS",
      "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0625/2026062500129.htm"
    },
    {
      "observation": "RETAINED_ZERO_ROW",
      "source_kind": "TUSHARE_HK_DAILY"
    },
    {
      "observation": "LISTED_AS_SUSPENDED",
      "source_kind": "INDEPENDENT_PUBLIC_MARKET_NEWS",
      "url": "https://www.etnet.com.hk/www/tc/news/news-article.php?category=latest&newsid=2026062568&section=categorized"
    }
  ],
  "schema_version": "hk-no-trade-user-approved-trading-halt-v1",
  "symbol": "06110.HK",
  "trade_date": "2026-06-25"
}
```

JSON 字节仍用项目既有 canonical `ensure_ascii=False, sort_keys=True, separators=(",", ":")`，无尾随换行。metadata 继续复用 `hk-no-trade-raw-metadata-v1`，绑定 source、record id、source_as_of、raw_selector、raw SHA；source_as_of 由主 Agent物化时显式冻结，不由 mtime/now 推断。

---

## 4. R1 阻断与最小生产改动

R1 外部实现会话在写生产代码前用公共 loader 探针确认：即使 backfill verifier 接受 UA-M1-005，现行
`HKNoTradeEvidenceSchema.user_approved_consensus_is_exactly_scoped` 仍只允许 UA-M1-001/004，公共正向必然失败。
绕过 Schema、改 source 或泛化规则均不诚实。R1 因此停止且未留下半实现；报告保留为本轮设计纠错证据。

在 `src/quant/data/hk_history_backfill.py`：

- 新增 UA-M1-005 exact record/key/selector/notice URL 常量；
- 扩展 `_user_approved_no_trade_is_exact`；
- 扩展 `_verify_user_approved_no_trade_raw`，逐字段/逐字节验证 §3 payload；
- 复用现有 `HKNoTradeEvidence` / `HKNoTradeEvidenceSet` / `_verify_evidence_projection` / v2 plan builder；
- 不改 public API、不新增 CLI、不改通用 source/reason 集合。

在 `src/quant/domain/schemas.py` 只把 exact UA-M1-005
`06110.HK ∧ 2026-06-25 ∧ source_record_id=UA-M1-005 ∧ 指定 raw_selector`
加入现有 user-approved consensus 析取；不得改 Schema 列、dtype、其他 source/reason 或任何非 HKNoTrade 规则。
`tests/unit/test_schemas.py` 只补 exact 正向和 symbol/date/record/selector 漂移拒绝，并回归 UA-M1-001/004。

该 exact 析取必须是双向封闭的：只要 `source_record_id == "UA-M1-005"`，或
`raw_selector == "user-approved-consensus/ua-m1-005-06110-2026-06-25.record"`，`source` 就必须精确等于
`USER_APPROVED_MULTI_SOURCE_CONSENSUS`，且证券、日期、record id、selector 必须共同构成 §2 的唯一 exact key。
不得允许 `HKEX_DAILY_QUOTATIONS` 或其他 source 携带 UA-M1-005 的 record/selector 身份进入公共 loader。

禁止修改 query、connector、clean store、配置、正式 data/artifacts。

---

## 5. 稳定失败语义

- exact 正向：`load_hk_no_trade_evidence` PASS；v2 plan 只扣除 `06110.HK@2026-06-25`。
- 错 symbol/date/selector/approval/schema/source kind/URL/observation/payload 顺序或任何额外字段：`HK_HISTORY_REFERENCE_INVALID`，`cause/context=None`。
- 把 2026-06-24、2026-06-26 或任意其他证券作为 UA-M1-005：拒绝。
- 旧 UA-M1-001/004 仍逐字通过，identity 不漂移。

---

## 6. 必测反例

在 `tests/unit/test_hk_history_backfill.py` 至少覆盖：

1. canonical UA-M1-005 raw+metadata → evidence loader PASS。
2. v2 plan effective dates 只减 06110@06-25，06-24/06-26 仍保留。
3. 本次 4,693 行 retained raw + UA-M1-005 evidence 可通过 request raw closure（fixture 模拟，不读正式 data）。
4. 错 symbol、前/后一天、错 selector、错 approval id。
5. 删除/增加/reorder observation；更换 HKEX 或独立来源 URL。
6. 把 Tushare zero row 改成其他语义。
7. impact 任一字段 true。
8. raw 或 metadata 单字节漂移。
9. UA-M1-001/004 正向回归与 identity 不变。
10. hostile 异常图稳定脱敏。

不得以 `object.__new__`、改私有 seal 或绕过 loader 构造正向 evidence。

---

## 7. 实现白名单

- `src/quant/data/hk_history_backfill.py`
- `src/quant/domain/schemas.py`（仅 `HKNoTradeEvidenceSchema` exact 析取）
- `tests/unit/test_hk_history_backfill.py`
- `tests/unit/test_schemas.py`（仅该 Schema 直接测试）
- 本任务单状态
- 唯一交付报告 `docs/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据交付报告.md`

独立初验只读生产与实现测试，唯一可写其复验报告。

不得修改 query 文件、README、路线图、用户待批示清单、正式 data/artifacts；主 Agent在合流后另行物化与同步 SSOT。

---

## 8. 实现验证

Windows：定向 `test_hk_history_backfill.py` 与 `test_schemas.py` 新增节点、UA-M1-001/004 邻接、Ruff、mypy、cold import。不得联网、不得真实回填、不得跑全量测试。

实现完成后更新状态为“实现与 Windows 定向自测完成；待全新外部独立初验”，不宣称真实 plan/HK60 Gate。

---

## 9. 主 Agent 后续唯一恢复路径

实现与外部独立初验 PASS、主 Agent合流后：

1. 从 §3 生成 immutable raw+metadata；记录 SHA。
2. 用 UA-M1-001 ∪ UA-M1-004 ∪ UA-M1-005 构建新的 v2 plan（不得改写 v2b）。
3. 新建按新 plan identity 派生的 journal；`--recover-existing-only` 零网络复用已有 raw。预期 7/8。
4. 距 2026-08-15 16:48:28 CST 至少 3,660 秒后才允许最后一批唯一网络请求。
5. 8/8 后按既有顺序 recover → 一次 finalize-v3 → fresh bundle。

任何 request id/参数漂移导致不能复用 raw、raw 除该键外仍不闭合、或 evidence 扩大到第二个键，立即停止。

---

## 10. R2 独立初验阻断与 R3 最小返工

### 10.1 现象

R2 独立初验确认：caller 可构造
`source=HKEX_DAILY_QUOTATIONS`、`source_record_id=UA-M1-005`、UA-M1-005 canonical selector/key 的记录；
即使 raw 内容为无关 JSON（例如 `{"not":"halt"}`），dataclass、Schema 和公共 loader 仍会接受。

### 10.2 根因

生产 verifier 只有在 `source == USER_APPROVED_MULTI_SOURCE_CONSENSUS` 时才调用
`_verify_user_approved_no_trade_raw`；Schema 则以“非 USER_APPROVED 或任一 exact approved record”为析取，
没有建立 UA-M1-005 record/selector 身份到 USER_APPROVED source 的反向约束。

### 10.3 应遵循规则

UA-M1-005 是用户批准的多来源共识证据，不是 HKEX daily quotations 证据。其 `source_record_id` 与
`raw_selector` 都是来源身份的一部分；任一出现时必须强制 exact USER_APPROVED source 与整组 canonical key，
不得通过更换 source 跳过 canonical raw 复核。不要借此收紧或重定义普通 HKEX quotations 通道。

### 10.4 最小复现与新增测试

- canonical UA-M1-005 + USER_APPROVED + canonical raw：继续通过；
- canonical UA-M1-005 record/selector + `HKEX_DAILY_QUOTATIONS` + canonical raw：拒绝；
- 同一伪 source + garbage raw：拒绝；
- 只漂移 record 或 selector、source 仍 USER_APPROVED：拒绝；
- UA-M1-001/004 与普通 HKEX quotations 正向行为、identity 均不漂移；
- public 失败稳定为 `HK_HISTORY_REFERENCE_INVALID`，`cause/context=None`。

### 10.5 通过条件

只做上述反向来源绑定和相应定向回归；不得新增 source、列、dtype、public API 或正式数据写入。Windows focused、
UA-M1-001/004/普通 HKEX 邻接、Ruff、mypy、cold import 通过后，由另一全新外部 Cursor 会话独立复验。

---

## 11. R3 独立复验 PASS 后的主 Agent 同型阻断与 R4 最小返工

R3 报告：[`M1_HK-HISTORY_R4_06110停牌单日NoTrade证据R3独立复验报告.md`](M1_HK-HISTORY_R4_06110停牌单日NoTrade证据R3独立复验报告.md)。

### 11.1 现象

R3 已正确关闭 UA-M1-005 的反向来源绑定，并通过独立复验。主 Agent 随后以同一 public loader 对旧记录做同型检查：
把合法 UA-M1-001 的 symbol/date/record/selector 保留，仅将 `source` 与 canonical metadata source 改为
`HKEX_DAILY_QUOTATIONS`，raw 换成 `{"not":"halt"}`，再按公开字段重算 evidence 与 set identity，
`load_hk_no_trade_evidence` 实际返回成功：

```text
UA001_SPOOF_ACCEPTED HKEX_DAILY_QUOTATIONS UA-M1-001
```

R3 独立报告也把“UA-M1-001/004 仍可挂 HKEX”列为残余。该问题阻断真实 v2c 物化。

### 11.2 根因

R3 反向约束只枚举 UA-M1-005 record/selector。旧 UA-M1-001/004 以及 `user-approved-consensus/` selector
命名空间仍可搭载非 USER_APPROVED source；projection 对非 USER_APPROVED source 不调用 canonical user-approved
raw verifier，而 Schema 的 existing exact 析取也只有 USER_APPROVED → exact 的单向约束。

### 11.3 应遵循规则

来源身份是整体合同：任何 `source_record_id` 以 `UA-M1-` 开头，或 `raw_selector` 位于
`user-approved-consensus/` 命名空间，都只能属于 exact `USER_APPROVED_MULTI_SOURCE_CONSENSUS`；随后仍必须命中
现有 UA-M1-001/004/005 exact allowlist。反向约束不得只按最新记录逐条补丁。普通 HKEX selector/record 不受影响，
不得借此实现或猜测 HKEX HTML parser。

### 11.4 最小实现与正式回归

- 把 R3 的 UA-M1-005-only dataclass/Schema 反向约束提升为上述 user-approved identity namespace 约束；
- public loader 与 Schema 分别拒绝 UA-M1-001、UA-M1-004、UA-M1-005 identity 挂 HKEX source；
- 每条至少覆盖 canonical raw 与可解析 garbage raw；record-only、selector-only 均拒绝；
- canonical USER_APPROVED 001/004/005 均保持通过，identity 字节不变；
- 普通 HKEX source 使用非 UA record 与非 user-approved selector 的正向控制组保持通过；
- 失败稳定为 `HK_HISTORY_REFERENCE_INVALID`，`cause/context=None`。

### 11.5 通过条件

不改列、dtype、public API、source/reason 集合、canonical payload、evidence identity 公式或正式数据。Windows focused、
完整 136 项邻接、Ruff、mypy、cold import 通过后，由未参与 R4 实现的另一全新 Cursor 会话对 001/004/005 三条
换源攻击独立复验；PASS 后才重新进入主验和真实物化。
