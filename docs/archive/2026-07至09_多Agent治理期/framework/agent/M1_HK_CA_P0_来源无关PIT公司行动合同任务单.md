# M1-HK-CA-P0：来源无关 PIT 公司行动合同任务单

日期：2026-08-09（Asia/Shanghai）  
状态：**R3 实现、独立复验与主 Agent 验收 PASS；仅限来源无关 development 合同，真实 HK 公司行动来源与 M1 Gate 仍开放**（见 [`M1_HK_CA_P0_R3_主Agent最终验收报告.md`](M1_HK_CA_P0_R3_主Agent最终验收报告.md)）  
风险等级：高（PIT、来源身份、公司行动经济语义）；本包只允许 fixture 与 retained bytes，禁止真实外部交互

## 1. 目标与价值

建立一个只面向港股、来源无关、可离线重验的公司行动 P0 合同，使下游能基于指定 `as_of` 得到“当时已知的版本”，并保留同一经济事件的完整修订/撤回证据。

用户可观察结果：

1. 一个未来真实来源适配器可把显式传入的 retained raw bundle 验证并投影为不可伪装的 verified candidate；
2. 通用 selector 只选择 `published_at <= as_of` 的候选，未来更正不得覆盖历史查询；
3. 同事件的原始版、修订版、撤回版拥有完整、连续、可重验的身份链；
4. 输出 canonical `CorporateActionSchema` 与逐候选 selection evidence，并对内容摘要和闭包做 fresh verification；
5. Windows 与 WSL base 使用同一 fixture 合同得到确定结果。

本包价值是先关闭“来源证据 → PIT 选版”这一公共工程缺口。它不等待 HK60 `01065` licensed bytes、U0C 自然时间窗或 G1 ext4 Gate，但也不替代上述任何 Gate。

## 2. 明确非目标

- 不实现或修改 Tushare、HKEX、AKShare、BaoStock、CNINFO 等真实 connector/source adapter。
- 不发网络请求，不读取 token，不扫描 `data/` 或 `data/legacy/`，不读取/修改正式 raw、clean、HK60 plan/journal、U0C artifacts 或 G1 release。
- 不构造累计复权因子，不生成 `ResearchPrice1dSchema` 总回报价格，不计算税费、汇率、碎股、供股认购或账户分录。
- 不扩展 `CorporateActionLedgerSchema`，不修改 A 股 M3 candidate/release、CNINFO raw-first、回测 entitlement state machine。
- 不宣称真实 HK 公司行动来源、全市场覆盖、复权链路、M1 Gate 或 Linux/ext4 Gate 通过。
- 不把 fixture adapter 移入 `src/quant/data/connectors/`，不预留插件框架或来源注册表。

## 3. 现状、SSOT 与不可复用边界

### 3.1 权威上下文

- 项目规则：`AGENTS.md`、`.ai/README.md`、`.ai/coding_rules.md`、`.ai/task_template.md`、`.ai/review_checklist.md` 及高风险/多 Agent 工作流。
- 剩余项审计：`docs/framework/agent/M1_HK60_剩余阻断与可并行工程包审计报告.md`。
- 字段与跨字段约束 SSOT：`src/quant/domain/schemas.py`。
- 市场、币种和公司行动类型 SSOT：`src/quant/domain/enums.py`。本包复用 `Market.HK`、`Currency.CNY/HKD`、`CorporateActionType.DIVIDEND/BONUS/SPLIT/RIGHTS`，不新增字符串副本，不修改 enums。
- 公共领域导出：`src/quant/domain/__init__.py`。
- 原始连接器边界：`src/quant/data/base.py`。现有 `fetch_corporate_actions` 只声明 raw 接口；Tushare/AKShare/BaoStock 均显式未实现。

### 3.2 可以复用的结构模式

仅可参考 A 股 M3 的以下通用不变量，不可复制其市场字段或业务规则：

- verified raw response 在进入 mapper/selector 前闭包 request、receipt、raw bytes 和稳定摘要；
- economic-event identity 与 candidate/revision identity 分离；
- 所有候选都保留 selection evidence，不能只留下最终行；
- selected canonical 行与 selected evidence 一一闭包；
- result 对象携带内容摘要，消费者入口 fresh 重验而不相信调用方自报；
- 重放、冲突、缺腿、截断、重复和身份漂移 fail closed。

### 3.3 明确不得复用的 A 股限定语义

下列现有合同不得被 import、包装或改名后用于 HK：

- `CorporateActionLedgerSchema`、`CorporateActionSelectionEvidenceSchema`、`CorporateActionReconciliationSchema`：证券限定六位 `.SH/.SZ`，action type、日期字段和来源为 M3 G1 A 股已实施事实；
- `select_g1_corporate_actions` 的 Tushare `div_proc="实施"`、`end_date/imp_ann_date/ann_date` 排名和 `cash_div_tax/stk_div` 数值口径；
- CNINFO `SUBID`、A 股代码、`Fxxx` 字段、配股/股改/股本变动公式与 Enckey 请求语义；
- `quant.backtest.corporate_actions` 的 A 股 record-close 捕获、SH session、整数送股、人民币分位 HALF_UP 与 entitlement 状态机；
- A 股 factor reconciliation、停牌复牌、股改对价和 `tushare+cninfo` source 集合。

P0 的 HK same-event 不能通过 `(symbol, ex_date, cash, ratio)` 猜测。它必须来自适配器冻结且可审计的 `source_event_id`；真实来源没有稳定事件/修订关联能力时，后续 source task 必须停止并重新冻结来源专属规则。

## 4. 公共领域合同

### 4.1 `CorporateActionSchema` 的最小演进

审计确认现有 schema 只有 `symbol/ex_date/action_type/cash_per_share/share_ratio/announce_time/source`，不足以表达 revision identity、币种、各类数量单位和结果闭包。实现必须在原 SSOT 上最小演进，不另建第二份 canonical clean 表。

冻结字段如下；具体 Pandera 写法可按现有风格实现，但字段、类型和分支语义不得改变：

| 字段 | 合同 |
|---|---|
| `event_id` | 64 位小写 SHA-256；选中经济事件唯一 |
| `symbol` | 仅 `^[0-9]{5}\.HK$` |
| `action_type` | `CorporateActionType` 四值之一 |
| `record_date` | `Date`，不能为空 |
| `ex_date` | `Date`，不能为空，`record_date <= ex_date` |
| `pay_date` | 可空 `Date`；DIVIDEND 必须有且 `>= ex_date`，其他类型必须空 |
| `stock_list_date` | 可空 `Date`；BONUS/SPLIT/RIGHTS 必须有且 `>= ex_date`，DIVIDEND 必须空 |
| `declared_currency` | 可空；DIVIDEND/RIGHTS 必须是 `Currency.CNY` 或 `Currency.HKD`，BONUS/SPLIT 必须空。它是发行人声明币种，不得自动改成 HKD |
| `cash_per_share_gross` | 可空有限正数；DIVIDEND 唯一启用。单位为“声明币种元 / 一股行动前普通股”，未扣税 |
| `stock_ratio` | 可空有限正数；BONUS 唯一启用。单位为“每一股行动前普通股新增股数”，不是 post/pre multiplier |
| `share_multiplier` | 可空有限正数且不得等于 1；SPLIT 唯一启用。单位为“行动后股数 / 行动前股数”；小于 1 表示 consolidation |
| `rights_ratio` | 可空有限正数；RIGHTS 唯一启用。单位为“每一股行动前普通股可认购股数” |
| `rights_subscription_price` | 可空有限正数；RIGHTS 唯一启用。单位为 `declared_currency` 元 / 一股新股 |
| `rights_subscription_start` / `rights_subscription_end` | RIGHTS 必填 Date 且 `ex_date <= start <= end <= stock_list_date`；其他类型必须空 |
| `announce_time` | timezone-aware UTC `Datetime`；等于 selected revision 的官方 `published_at`，不得用 fetch time 代替 |
| `source` | 非空稳定 source id |
| `source_event_id` | 非空、来源内稳定，同事件所有修订相同 |
| `source_revision_id` | 非空、来源内唯一，绑定 selected revision |
| `source_snapshot_sha256` | 64 位小写摘要，绑定 verified retained bundle |

各 action type 除本分支允许的经济字段外，其余经济字段必须严格为 null；禁止用 `0` 同时表达“不适用”和“真实零值”。零效果事件不进入 canonical action，但必须保留在 revision evidence 中并有明确状态。

`CorporateActionSchema` 的业务键为 `event_id` 唯一；不得以 `(symbol, ex_date)` 去重，因为同日可存在多个不同经济事件。

### 4.2 revision evidence schema

在 `schemas.py` 新增 `HkCorporateActionRevisionEvidenceSchema` 并由 `quant.domain` 公开导出。每个 retained revision/tombstone 一行，至少包含：

```text
economic_event_key_sha256
candidate_id
symbol
action_type
source
source_event_id
source_revision_id
revision_sequence
predecessor_candidate_id
revision_status                 # ACTIVE | WITHDRAWN
published_at                   # timezone-aware UTC
source_observed_at             # timezone-aware UTC，仅血缘，不参与 no-lookahead
record_date / ex_date / pay_date / stock_list_date
declared_currency
cash_per_share_gross / stock_ratio / share_multiplier
rights_ratio / rights_subscription_price
rights_subscription_start / rights_subscription_end
raw_bundle_sha256
raw_file_sha256
raw_metadata_sha256
raw_selector
selected
selection_reason               # SELECTED_AS_OF | SUPERSEDED_AS_OF | FUTURE_AS_OF | WITHDRAWN_AS_OF
query_as_of                    # timezone-aware UTC
```

约束：

- `candidate_id` 全表唯一；`source + source_revision_id` 全表唯一。
- 同一 `source + source_event_id` 只能对应一个 symbol/action type/economic event key。
- `economic_event_key_sha256` 绑定版本化标签、source、source_event_id、symbol、action type；不得绑定会被修订的日期或金额。
- `candidate_id` 绑定 event key、revision id/sequence/predecessor/status/published_at、全部经济字段及 raw evidence identity。
- evidence 的经济字段使用与 canonical schema 相同的分支约束；`WITHDRAWN` 行的经济字段可保留被撤回版本的精确内容，但 status 必须进入 candidate identity。
- `source_observed_at >= published_at`；observed/fetch time 不能替代官方 published time，也不能提高候选排名。
- `selected=True` 每个 event 最多一行；若 as_of 最新 revision 为 WITHDRAWN，则该 tombstone evidence 标为 selected/`WITHDRAWN_AS_OF`，canonical actions 中不得有该 event。
- `FUTURE_AS_OF` 必须 `published_at > query_as_of` 且不 selected；`SUPERSEDED_AS_OF` 必须已知但不是 as_of 最新；唯一 active selected 使用 `SELECTED_AS_OF`。

若 Pandera/Polars 当前不能单独证明 timezone-aware UTC，`hk_corporate_actions.py` 的 Python 边界必须在构造 DataFrame 前严格检查 aware datetime、`utcoffset() == 0`，并把 naive、非 UTC 或字符串猜时区稳定拒绝。

## 5. 来源无关 API 与严格 capability

实现文件 `src/quant/data/hk_corporate_actions.py` 冻结以下公开职责；允许按 Python 类型细节微调名称的内部成员，不允许改变调用方向和失败边界。

### 5.1 值对象

- `HkCorporateActionQuery`：冻结、严格类型；包含排序唯一的 5 位 `.HK` symbols、`event_date_start/end`、aware UTC `as_of`、排序唯一 `required_action_types`、排序唯一 `accepted_currencies`。空集合、重复、乱序、非法日期或非 UTC 均拒绝。
- `HkCorporateActionCapability`：冻结；包含 `source`、`adapter_version`、支持 action/currency 集合，以及以下必须为真的严格能力：
  - `retained_bytes_verifiable`
  - `official_published_at_available`
  - `stable_event_identity_available`
  - `stable_revision_identity_available`
  - `revision_predecessor_available`
  - `withdrawal_history_complete`
  - `correction_supplement_closure_complete`
  - `scope_completeness_verifiable`
- `HkCorporateActionRawFile`：冻结；显式 role、不可空 bytes、metadata bytes、各自声明 SHA-256。构造时 fresh 重算；role 至少支持 `MAIN/SUPPLEMENT/CORRECTION`，未知 role 拒绝。
- `HkCorporateActionRawBundle`：冻结、非空、顺序 canonical；绑定 query/source/source issue identity、文件 tuple、`source_observed_at`、`coverage_as_of` 与 bundle SHA。不得接受目录、glob、自动发现或懒加载路径。
- `VerifiedHkCorporateActionProjection`：冻结；只承载 capability、query、bundle identity、完整 candidates/evidence projection 及 projection digest。selector 必须重验其全部闭包，不能因为类型名而信任内容。
- `HkCorporateActionSelectionResult`：冻结；承载 canonical actions、revision evidence、两份 content digest、query identity；提供独立 `verify_hk_corporate_action_selection_result` fresh 重验入口。

### 5.2 source adapter Protocol

新增窄 `HkCorporateActionSourceAdapter(Protocol)`：

```python
source: str
capability: HkCorporateActionCapability

def verify_retained(
    self,
    *,
    query: HkCorporateActionQuery,
    bundle: HkCorporateActionRawBundle,
) -> VerifiedHkCorporateActionProjection: ...
```

Protocol 只解释调用方显式传入且已 fresh hash 的 retained bytes；不包含 fetch/download、token、URL、默认目录或网络 fallback。P0 测试在测试文件内实现 `FixtureHkCorporateActionSourceAdapter`，生产目录不得新增 fixture adapter。

严格 capability 规则：

1. query 的 action/currency 必须完全是 capability 子集；任一 required capability 为 false，必须在解析/选择前返回 `HK_CA_CAPABILITY_UNSUPPORTED`。
2. adapter 必须投影查询 scope 内**全部** revision 和 withdrawal，不允许只返回最终状态；`coverage_as_of < query.as_of` 失败。
3. source 能产生 query 未接受币种/类型、但不能证明其已被完整报告时，不得静默过滤；应 capability fail closed。
4. 未知字段、未知 record type、截断、分页/issue 不完整、漏 supplement/correction、重复 source revision、bytes/metadata digest 漂移都返回 evidence invalid；空结果只有在 adapter 能证明 scope 完整时才合法。
5. verified projection 由 adapter verifier 输出；调用方不能传普通 DataFrame、自己填写 `verified=True` 或直接自报 selection reason。

## 6. same-event 修订闭包与 PIT 选版

公开选择入口：

```python
def select_hk_corporate_actions(
    *, projection: VerifiedHkCorporateActionProjection
) -> HkCorporateActionSelectionResult: ...
```

selector 先 fresh 重验 capability/query/bundle/projection digest，再按以下确定规则执行：

1. 按 `(source, source_event_id)` 分组；event key 必须与组内 symbol/action type 一致。
2. 每组 `revision_sequence` 必须从 1 开始、严格连续、无重复；sequence=1 的 predecessor 必须 null，后续 predecessor 必须精确等于前一 candidate id。不能跨 event 指向。
3. `source_revision_id` 不得跨 event 重用；同 identity 同 bytes 重放必须得到同一 projection/result bytes，同 identity 不同内容必须冲突。
4. 以 `published_at <= query.as_of` 定义“当时可知”。`source_observed_at`、当前抓取时间、ex/record/pay/list date 均不参与可知时点。
5. 组内按 `(published_at, revision_sequence)` 严格递增；同 published_at 的不同经济内容或乱序 sequence 返回 version conflict，不增加隐藏 tie-breaker。
6. 没有 as_of 可知版本：该 event 不输出 canonical 行，所有行标 `FUTURE_AS_OF`。
7. 最新可知版本为 ACTIVE：唯一标 `SELECTED_AS_OF` 并投影一条 canonical action；更旧可知版本标 `SUPERSEDED_AS_OF`，未来版本标 `FUTURE_AS_OF`。
8. 最新可知版本为 WITHDRAWN：该 tombstone 唯一 selected/`WITHDRAWN_AS_OF`，canonical 不输出该 event；更旧版本不能复活。
9. 选中的 `event_id` 绑定版本化标签、economic event key 和 selected candidate id；同 as_of 重放必须稳定。不得使用随机数、绝对路径、PID、mtime 或当前时间。
10. 输出按稳定键排序，内容摘要使用项目已有 canonical table hashing；result verifier 必须重算 schema、排序、event/revision chain、actions↔selected evidence 和 digest 闭包。

no-lookahead 明确反例：原版 `2026-05-04 09:00Z`，经济字段 A；更正版 `2026-05-05 02:00Z`，经济字段 B。`as_of=2026-05-05 01:59:59Z` 必须选 A，`02:00Z` 起才选 B。即使 retained bundle 在 8 月取得，也不能让 B 回写 5 月 5 日 02:00Z 以前。

## 7. 失败语义

新增 `HkCorporateActionError(ValueError)`；对外消息只允许下列稳定代码，不包含路径、raw 内容、URL、请求参数、账号或凭据：

| 错误码 | 含义 |
|---|---|
| `HK_CA_INPUT_INVALID` | query、值对象类型、范围、排序、UTC 或 action 分支非法 |
| `HK_CA_CAPABILITY_UNSUPPORTED` | source 无法证明 required action/currency/revision/withdrawal/scope 能力 |
| `HK_CA_EVIDENCE_INVALID` | retained bytes/metadata/bundle/projection 摘要、字段、scope 或 source identity 不闭包 |
| `HK_CA_REVISION_CONFLICT` | same-event 分组、sequence/predecessor、published_at、重复 revision 或内容冲突 |
| `HK_CA_ACTION_UNSUPPORTED` | 已验证 raw 出现合同外 action/currency/经济字段，不能安全投影 |
| `HK_CA_RESULT_INVALID` | 输出 schema、排序、actions↔evidence 或 content digest fresh 重验失败 |

类型错误、Polars/Pandera/JSON/Unicode/摘要异常必须净化为上述代码；不得把底层异常文本串入稳定消息。不存在网络重试错误码，因为 P0 不允许网络。

## 8. 与复权、研究价格和账户核算的硬分离

- P0 的 canonical action 是 PIT 研究事实，不是累计 `AdjustmentFactorSchema`，不得写 `adj_factor`。
- P0 不调用 `apply_adjustment_factors`，不输出 `ResearchPrice1dSchema`，不实现 dividend reinvestment 或 total-return。
- P0 不输出或转换为 `CorporateActionLedgerSchema`，不调用 A 股 entitlement/account replay；gross cash 不等于实际到账现金。
- `declared_currency` 原样保留，不做 CNY/HKD FX 转换；缺 FX 不是填 1.0 的理由。
- RIGHTS 只表达官方权益参数，不假设投资者认购，不产生现金扣款或新股。
- 后续 P1 若构造 HK total-return，必须另冻 canonical implemented-action coverage、价格基准、币种/FX、税费、权益归属和公式；P0 通过不能提前关闭该 Gate。

## 9. 可写白名单

实现 Agent 只允许写：

```text
src/quant/domain/schemas.py
src/quant/domain/__init__.py
src/quant/data/hk_corporate_actions.py                 # 新文件
tests/unit/test_schemas.py
tests/unit/test_hk_corporate_actions.py                # 新文件
docs/framework/agent/M1_HK_CA_P0_来源无关PIT公司行动合同实现交付报告.md
```

独立初验 Agent 保持上述生产代码/测试只读，只允许新增：

```text
docs/framework/agent/M1_HK_CA_P0_来源无关PIT公司行动合同独立初验报告.md
```

主 Agent 最终验收报告路径：

```text
docs/agent/M1_HK_CA_P0_来源无关PIT公司行动合同主Agent最终验收报告.md
```

`src/quant/domain/enums.py` 明确只读：当前四类 action 与 CNY/HKD 足够 P0；若真实 fixture 暴露 USD 或新 action，本包停止并由主 Agent 重新冻结，不由实现者扩 enum。

## 10. 禁止路径与操作

```text
src/quant/data/connectors/**
src/quant/data/base.py
src/quant/data/m3_*.py
src/quant/backtest/**
src/quant/execution/**
src/quant/data/hk_history_backfill.py
src/quant/data/backfill_hk_history.py
项目 data/** 与 data/legacy/**
正式 HK60 plan/journal/candidate/clean
U0C scripts/tasks/logs/receipts/artifacts
G1 release/candidate/journal/artifacts
```

禁止联网、安装/升级依赖、读取 token、调用真实 SDK、扫描真实数据目录、触发计划任务、修改 Git 历史或清理其他 Agent 的脏文件。

## 11. 最小 fixture 与必测反例

fixture 必须极小、确定、纯内存或 `tmp_path`，至少两个 HK symbol、两个 event，并覆盖：

1. DIVIDEND：HKD gross cash，原版与次日更正；更正修改 cash/pay date。
2. BONUS 或 SPLIT：明确验证 `stock_ratio` 与 `share_multiplier` 单位不可互换；建议用 consolidation multiplier `0.5`。
3. WITHDRAWN：原 ACTIVE 后撤回，撤回前输出、撤回时及以后 canonical 消失，evidence 保留。
4. RIGHTS：合法 ratio/price/subscription dates；缺 price、币种、start/end 或日期乱序失败。
5. 同 identity 同 bytes 重放结果 digest 相同；同 source_revision_id 不同 bytes、raw/metadata digest 翻转失败。
6. sequence 从 2 开始、有 gap、重复、predecessor 指错/跨 event、同 event 改 symbol/action type 全部失败。
7. naive datetime、非 UTC datetime、用 observed time 冒充 published time、future revision 注入均失败或不被选择。
8. 未知 action、USD、`.SH/.SZ`、六位 `.HK`、Unicode 数字、NaN/Inf/负数/错误零值、0 代替 null 均拒绝。
9. capability 缺任一 required boolean、query 请求未支持类型/币种、coverage_as_of 早于 as_of、空结果但 scope completeness 不可证，均在 selection 前失败。
10. 普通 DataFrame、自造 selection reason、actions/evidence 任一字段或 digest 漂移，result verifier 失败。
11. 两个经济事件同 symbol/ex_date 仍各自保留；证明不得按 `(symbol, ex_date)` 合并。
12. import `quant.data.hk_corporate_actions` 不加载 Qlib、requests、tushare、akshare、baostock 或 CNINFO connector。

独立初验必须新增实现者未使用的反例，优先：同 `published_at` 不同经济内容、未来 WITHDRAWN 不能抹除历史 ACTIVE，以及 selected tombstone 被伪造成 canonical action。

## 12. 实施顺序与停止条件

1. 先写 schema 合法/非法分支测试，确认 `CorporateActionSchema` 演进不依赖 A 股 ledger。
2. 实现值对象、fresh hash 和 capability preflight，再实现 fixture adapter 测试。
3. 实现 revision closure/PIT selector/result verifier；所有失败先有反例。
4. 运行 Windows 定向测试和静态检查；再在 WSL base 对同一 worktree 运行对应集合。
5. 检查仅白名单 diff、公共导出和 import 边界；写压缩交付报告。

出现以下任一情况立即停止扩大实现并回报主 Agent：

- 现有 Pandera/Polars 无法可靠表达/验证所冻结 UTC 或分支字段，且需要改依赖；
- 需要修改 enums、BaseConnector、真实 connector、M3/A 股合同或公共 storage；
- fixture 需要假设真实 HKEX/Tushare 字段、record code、许可或经济口径；
- 发现 CNY/HKD 与四类 action 无法表达最小合同；
- 白名单文件存在并发写者或必须触碰正式状态。

## 13. 验证命令与平台边界

Windows 原生 Miniforge：

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py -q -p no:cacheprovider
D:\Miniforge3\python.exe -m ruff check src/quant/domain/schemas.py src/quant/domain/__init__.py src/quant/data/hk_corporate_actions.py tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py
D:\Miniforge3\python.exe -m mypy src/quant/domain/schemas.py src/quant/domain/__init__.py src/quant/data/hk_corporate_actions.py
```

WSL Miniforge base，在该独立 worktree 的 `/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m1-hkex-02983` 执行同一 pytest/Ruff/mypy 文件集合。该结果是 WSL/DrvFS 跨平台开发合同证据，不是 ext4 发布 Gate。

最后执行：

```powershell
git diff --check -- src/quant/domain/schemas.py src/quant/domain/__init__.py src/quant/data/hk_corporate_actions.py tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py docs/framework/agent/M1_HK_CA_P0_来源无关PIT公司行动合同实现交付报告.md
git status --short
```

不得机械运行真实网络、全量数据回补或发布 Gate。若 schema 公共演进使定向测试无法排除回归，主 Agent 在最终合流后裁定是否追加全量测试；实现者不得据局部绿测自行勾选路线图。

## 14. 成功标准与交付

- [ ] `CorporateActionSchema` 成为唯一 canonical 公司行动表，精确表达四类 action、币种和单位分支，无平行 clean 格式。
- [ ] retained raw/metadata/bundle/projection 均 fresh digest 闭包，调用方不能用普通 frame 冒充 verified projection。
- [ ] same-event revision 链连续、唯一、可重验；冲突和缺失 fail closed。
- [ ] `as_of` 只使用官方 UTC `published_at`，未来更正/撤回不前视。
- [ ] canonical actions 与逐候选 evidence、selected/tombstone 和内容摘要严格闭包。
- [ ] capability 不足、未知 action/currency/字段、截断/重复/摘要漂移稳定失败且错误脱敏。
- [ ] 没有网络、connector、复权、total-return、账户核算或正式数据写入。
- [ ] Windows 与 WSL base 定向 pytest/Ruff/mypy 实际通过，结果准确区分为开发合同，不声称正式 HK Gate。
- [ ] 只有白名单文件变化，其他既有脏文件原样保留。

执行 Agent 的交付报告必须按 `.ai/task_template.md` 给出“标准 → 代码/测试证据”、实际命令结果、未验证真实依赖、范围审查和停止项。实现 Agent 不得宣布 Gate 通过。随后由未参与实现的新外部 Agent 只读初验并增加对抗反例；初验通过后再由主 Agent 最终验收。

## 15. R2：retained bytes fresh digest 与异常链脱敏（2026-08-09）

### 失败闭环

- 现象一：合法 projection 构造后用 `object.__setattr__` 篡改某个 frozen raw file 的 `content`，保留旧
  `content_sha256`；消费者 `_validate_bundle` 只检查 dataclass 类型、排序和 bundle 自哈希，selector 仍接受。
- 根因一：只在 `HkCorporateActionRawFile.__post_init__` 计算 bytes digest，fresh 消费入口没有逐文件重算
  content/metadata SHA-256；frozen 值对象被低层篡改后形成 stale capability。
- 现象二：hostile adapter 在 active `RuntimeError("SECRET_SENTINEL")` 中抛稳定
  `HkCorporateActionError`；公共入口 `except HkCorporateActionError: raise` 直接重抛，导致公开异常的
  `__context__` 保留内部 marker。
- 根因二：把稳定错误类型误当成稳定异常链；在 active except 中重抛仍携带原上下文。

### 最小返工规则

1. `_validate_bundle` 每次调用都必须对每个 raw file 的 `content` 与 `metadata` fresh 计算 SHA-256，并与保留
   digest 精确相等；该检查发生在 bundle identity、projection、selection 或 adapter 结果被消费之前。
2. raw file 的 role/type/bytes/digest 也必须 fresh exact 验证，不能只依赖构造期 `__post_init__`；content 或
   metadata 任一漂移均统一 fail closed。
3. adapter preflight、projection factory、selector、result verifier 等所有公开边界捕获
   `HkCorporateActionError` 时只保存稳定 `code`，离开 active `except` 后重新构造并 `raise ... from None`；
   非稳定异常映射到各入口冻结的通用稳定码。对外 `__cause__`、`__context__` 均为空，traceback 不含 marker。
4. 不改变 schema、identity 算法、revision/as_of 选择语义、Protocol 或已冻结错误码；不引入通用异常框架。

### 新增测试与通过条件

- 分别低层篡改 raw content、metadata、两者及对应旧 digest，projection/selector/result verifier 全部拒绝；
- hostile adapter 直接抛稳定错误，以及在 ValueError/RuntimeError active context 中抛稳定错误，公开入口固定
  code、空 cause/context、marker 不进 traceback；
- projection factory/selector/result verifier 的稳定错误嵌套反例同样满足空异常链；
- 既有 revision、withdrawal、tombstone、no-lookahead、whole-result 与 schema 回归保持绿色；
- Windows 与 WSL base `/mnt/f` 定向 pytest/Ruff/mypy 通过，DrvFS 非 ext4。返工后必须由未参与 R2 实现的
  全新独立 Agent 复验 PASS，才可关闭 P0 开发合同。

## 16. R3：内容绑定的 adapter attestation（2026-08-09）

### R2 失败闭环

- 现象：把 retained raw 改成另一组 bytes，重算 raw file digest、bundle identity、candidate raw links、
  projection digest，并复用旧全局 `_SEAL`，selector 仍接受并输出原 candidates 派生结果。
- 根因：全局 `_SEAL` 只证明“拿到了同一个模块对象”，不绑定 adapter 当时验证的具体 bundle/candidate 内容；
  全部公开摘要又处于同一可整体重算域。
- 应遵循规则：adapter factory 产出的只是待 source wrapper 确认的 parsed projection。只有
  `verify_hk_corporate_action_source` 在 fresh adapter 返回、完整闭包 exact 重验后，才能签发与具体内容身份
  绑定的进程内 capability；selector 不接受 factory-only 或旧 attestation 复用到新内容。

### 冻结 R3 设计

1. 保留 `HkCorporateActionSourceAdapter.verify_retained(...) -> VerifiedHkCorporateActionProjection` 签名和
   adapter-facing factory，避免让 fixture/未来真实 adapter 自行实现私有构造器；但 factory 返回值标记为
   `adapter_parsed`，不能直接传给 selector/result verifier。
2. `verify_hk_corporate_action_source` fresh 重验 capability/query/bundle/candidates/projection digest 后，创建新的
   `source_verified` projection，并附加不可序列化、repr/compare 排除的 content-bound attestation。
3. attestation 使用模块进程内随机密钥与 HMAC-SHA256（或等价不可由公开摘要单独重算的窄机制），payload 精确
   绑定 source、adapter version、query identity、bundle identity、candidate table digest 与 projection digest。
   selector、result verifier 每次 fresh 重算 payload/HMAC 并 constant-time 比对；content 任一变化、旧 token
   复用、factory-only projection、复制后重哈希均 fail closed。
4. 进程内密钥不导出、不进入 dataclass repr/equality、日志、artifact 或文档。不得提供“签任意 projection”的
   公共 helper；HMAC 签发只发生在 source wrapper 成功路径。
5. 这是进程内 capability 防替换，不是外部数据源数字签名、跨进程持久证书或 WORM。projection 不序列化；
   进程重启必须再次调用 source wrapper 对 retained bytes fresh verification，报告必须如实披露。
6. R2 fresh digest 与异常链修复保持；不改变 schema/revision/as_of/selection/错误码，不引入网络或真实 adapter。

### R3 必测与通过条件

- R2 独立复验的 raw→bundle→candidate→projection 全链合法重哈希 + 旧 seal/token 复用必须失败；
- factory-only projection 直接 selector/result verifier 失败；经 source wrapper 返回的 exact projection 正常通过；
- 旧 attestation 分别复用到改 content、metadata、bundle source issue、candidate row、projection digest 的对象均失败；
- whole-result、future withdrawal、tombstone、异常矩阵与 R2 fresh digest 回归保持绿色；
- monkeypatch HMAC/adapter hostile 异常仍稳定脱敏、cause/context 为空且 token/key 不泄露；
- Windows 与 WSL base `/mnt/f` 定向 pytest/Ruff/mypy 通过，DrvFS 非 ext4。全新独立复验 PASS 后才可关闭 P0。
