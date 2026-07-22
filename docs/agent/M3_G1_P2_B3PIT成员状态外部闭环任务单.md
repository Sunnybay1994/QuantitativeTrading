# M3 G1-P2：B3 PIT 成员状态外部实现—独立复验闭环任务单

> 2026-07-17 真实 INDEX 数据修订：本任务书中“每个 signal session 必须恰好 300”以及“生命周期裁剪为
> 299 必须失败”的条款已被
> [`M3_G1_R1C-B_INDEX身份合同返工任务单.md`](M3_G1_R1C-B_INDEX身份合同返工任务单.md) 取代。
> 每个供应商 observation 仍必须精确 300；生命周期裁剪后的 eligible keys 可短暂少于 300，但必须非空且
> 不得超过 300。该修订来自真实月频 PIT 与月中退市证据，不得用未观测替补证券填平。

日期：2026-07-14  
状态：已通过主 Agent 最终验收；见 [`M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md`](M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md)  
主契约：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md)  
上游已验收：[`M3_G1_B2A主Agent最终验收报告.md`](M3_G1_B2A主Agent最终验收报告.md)、
[`M3_G1_P1主Agent最终验收报告.md`](M3_G1_P1主Agent最终验收报告.md)  
配置前置：[`M3_G1_P2_0主Agent最终验收报告.md`](M3_G1_P2_0主Agent最终验收报告.md)

## 1. 任务目标与边界

本包只完成 G1 的 B3：把已经验真的 Tushare CSI300 月度 `index_weight` 响应，转换为可审计的标准观察、
保守 PIT 成员区间和研究样本资格键。它在 pipeline 中位于 B2A raw/receipt 之后、B4 全局审计与不可变发布
之前。

供应商依据为 [Tushare 指数成分和权重官方文档](https://tushare.pro/document/2?doc_id=96)：该接口明确为月度
数据，并建议以自然月首尾作为请求范围。本项目在此基础上采用更保守的 PIT 可知时点，不把月度观察冒充指数
公司逐日生效事件。

本包刻意不包含：

- B2C `stk_limit/dividend` 规则 mapper；
- B4 candidate、全局质量报告、跨源对账和 release publisher；
- G2 provider、标签、因子、策略、回测或交易；
- 真实 Tushare 网络请求、配置读取和任何 clean/raw 文件写入。

这样拆分不是降低能力要求，而是把一个高风险时间语义包做完整。实现者应一次完成接口、失败语义、身份摘要、
测试和报告；不得用占位实现把问题推给 B4。

### 1.1 主 Agent 真实只读探针

2026-07-14 主 Agent 在 WSL Miniforge base 使用本地 ignored token 对 `index_weight` 做了六个完整自然月的
只读聚合探针；未保存响应、未输出 token 或证券明细：

- 2016-01/02/03 与 2024-05/06/07 均为每月一个 observation date、每次 300 行；日期分别落在当月最后
  SH session；
- 六次权重和位于 `99.992..100.004`，支持当前 `[99,101]` fail-closed 边界；
- 2024-05→06 的相邻成分交集为 288，2024-06→07 为 300，证明月度状态既可能变化也可能完全延续，不能
  按季度硬编码调仓或为每月强造新区间；
- calendar 探针确认 `2016-01-01` 闭市、`2016-01-04` 开市、`2026-06-26` 开市，因此旧示例起点与
  `resolve_history_window` 的 session 契约冲突，必须先由 P2-0 修正。

探针只证明这些样本，不替代完整 batch/receipt 校验、自动测试或最终真实 G1 release 验收。

## 2. 外部闭环职责

1. 实现 Agent 按本任务书实现、自测并生成
   `docs/M3_G1_P2_B3PIT成员状态交付报告.md`；不得宣称 B3/G1/Gate 通过。
2. 未参与实现的独立初验 Agent 只读审查生产代码与已提交测试，并增加实现报告未使用的临时对抗性反例，生成
   `docs/M3_G1_P2_B3PIT成员状态独立初验报告.md`。
3. 若初验不通过，报告必须逐项写明“现象—根因—应遵循规则—最小复现—新增测试—通过条件”，退回实现
   Agent；二者循环直到独立复验通过。
4. 独立复验通过后停止，不更新路线图，不勾选 G1，由主 Agent 做最终验收。

实现与初验必须是不同 Agent/独立上下文，且两者均显式使用 `cursor-grok-4.5-high`，不得使用任何
`*-fast` 变体；报告记录实际模型标识。Agent 进程运行在 Windows，但所有 Python、pytest、Ruff、mypy 和
项目脚本必须通过 `wsl.exe` 在 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 下使用 WSL Miniforge `base` 执行，
禁止 Windows Python/conda。P2-0 已通过主 Agent 最终验收。外部 Agent 开始前依次完整阅读：根 `AGENTS.md`、`karpathy-guidelines.md`、
本任务书、主契约 §4.10，以及上述两个上游最终验收报告。不得读取 `_old/` 或本地 token 配置。

## 3. 本包冻结的系统不变量

### 3.1 请求闭包先于数据内容

原草案只向 normalize 传 `Sequence[VerifiedRawResponse]`，无法证明整批请求是否少了一个月。本包修正为同时
传入完整 `TushareRequestBatch`。normalize 在读任何 frame 值之前必须证明：

- batch 是重建后仍有效的 `INDEX_WEIGHT` batch；
- batch 中每个请求都是 `index_weight`、`index_code=000300.SH`，fields 与 `TUSHARE_FIELDS` 完全一致；
- 每个请求精确覆盖一个完整自然月，月份唯一且连续；
- responses 的 request ID 多重集合与 batch 精确相等：少、增、重复、跨 batch 均失败；
- 每个 `VerifiedRawResponse` 在消费边界重新构造并验真 spec/receipt/receipt bytes hash/frame content 闭包，
  不能把 frozen dataclass 的首次构造当成永久可信。

不得从“当前收到的 response 月份”反推完整计划，也不得因为现有测试 fixture 恰好完整而省略 batch。

### 3.2 观察、可知信号和成交是三个时点

- `observation_date` 是供应商 `trade_date`，不是请求月首日。
- observation 后的第一个 SH 开市日，成员状态只在该日收盘后成为可用信号；`eligible_keys.as_of` 可以包含
  该日。
- 使用该 `as_of` 的最早成交是再下一个 SH session 的 open。本包不下单，但必须固定跨模块 fixture：
  Friday observation → Monday `as_of` → Tuesday earliest open execution。
- 禁止把 observation 状态向前回填到 observation 当日、月首或下一 session 的开盘前。

方法版本精确为 `tushare_monthly_observed_next_session_close_v1`；旧
`tushare_monthly_observed_next_open_v1` 与上述语义冲突，P2-0 后必须在 config、build spec 与 P4 identity
全链拒绝。

### 3.3 历史数据域不等于样本资格域

B3 只生成 `eligible_keys`，不裁剪 provider 历史。调入前或两次成员区间之间的 bar 可在后续 provider 中保留，
但不能产生资格键。B3 不得 import 或调用 Qlib/provider 代码。

### 3.4 缺证据默认失败

CSI300 v1 的每个 observation 必须恰好 300 个唯一 A 股证券，权重均为正 finite，权重和包含边界地落在
`[99, 101]`。每个请求自然月至少一个 observation；同月多 observation 全部保留。不得用 250–350、
补齐、前填、去重 `keep=last` 或选择月末一条来提高覆盖率。

## 4. 冻结公共接口

新增 `src/quant/data/index_membership.py`：

```python
class M3IndexMembershipError(ValueError):
    code: str

@dataclass(frozen=True)
class ObservedMembershipResult:
    observations: pl.DataFrame
    membership: pl.DataFrame
    eligible_keys: pl.DataFrame
    observations_sha256: str
    membership_sha256: str
    eligible_keys_sha256: str

def normalize_index_weight_observations(
    *,
    batch: TushareRequestBatch,
    responses: Sequence[VerifiedRawResponse],
    universe: str,
) -> pl.DataFrame: ...

def build_observed_membership(
    *,
    observations: pl.DataFrame,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    universe: str,
    signal_start: dt.date,
    signal_end: dt.date,
    expected_constituent_count: int,
) -> ObservedMembershipResult: ...

def verify_observed_membership_result(
    *, batch: TushareRequestBatch,
    responses: Sequence[VerifiedRawResponse],
    result: ObservedMembershipResult,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    universe: str,
    signal_start: dt.date,
    signal_end: dt.date,
    expected_constituent_count: int,
) -> None: ...
```

新增 `src/quant/data/m3_identity.py`：

```python
class M3CleanTableIdentityError(ValueError):
    code: str

def clean_table_content_sha256(
    *, table_name: str, frame: pl.DataFrame,
) -> str: ...
```

这两个模块不得接受 `config_path`、裸 raw DataFrame、source 参数或任意 benchmark/index code。`source` 固定为
`tushare`，成分指数代码固定为 `000300.SH`，universe 只接受
`CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1`，`expected_constituent_count` 必须精确等于 300；调用方不能通过参数
放宽首版契约。

在 `quant.data` 包根导出上述两个函数、result 和两个错误类型；在 `quant.domain` 包根导出新增 Schema。
不得为此重排包根的无关导出。

## 5. `IndexConstituentObservationSchema`

在 `src/quant/domain/schemas.py` 新增并以代码作为字段 SSOT：

| 列 | dtype/约束 |
|---|---|
| `universe` | Utf8，精确为 `CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1` |
| `observation_date` | `pl.Date` |
| `symbol` | Utf8，精确六位 `000001.SZ/600000.SH` 形式 |
| `weight` | Float64，正且 finite |
| `source` | Utf8，精确为 `tushare` |
| `source_snapshot_id` | Utf8，小写 64 位 hex |

Schema 必须 `strict=True/coerce=True`，唯一键为
`(universe, observation_date, symbol, source)`。Schema 只定义逐行和唯一键约束；恰好 300、权重和、月完整等
集合规则由 B3 消费边界显式执行。调用 Schema 后必须消费 validator 返回的 frame，不得继续使用验证前对象。

## 6. normalize 的确定行为

### 6.1 原始范围与字段

- raw 精确列顺序为 `index_code,con_code,trade_date,weight`，missing/extra/reorder 均失败；
- response 行的 `index_code` 必须等于请求的 `000300.SH`；
- `trade_date` 必须是八位日期字符串、是真实日期、位于该 response 的请求自然月内；
- `con_code` 必须是精确六位 `.SH/.SZ` A 股代码；
- weight 允许供应商正常数值或可无损解析的十进制字符串；拒绝 bool、null、空串、NaN/Infinity、List/Struct、
  非数值和非正值；
- 任何跨 response 的重复观察键都失败，raw 重复不得静默删除。

### 6.2 月与 observation 集合

- 每个 batch 月至少产生一个 observation date；空 response、缺月均失败；
- 同月多个 observation date 全部保留，按日期处理；
- 每个 observation date 恰好 300 个唯一 symbol；先按 symbol 排序，再对 Python float 使用 `math.fsum`，
  以该确定性结果检查闭区间 `[99,101]`；禁止使用依赖输入行序/线程分块的普通浮点 reduce；
- 99 和 101 精确通过，任何更小/更大值失败；不得先 round 再比较。

### 6.3 输出

输出精确六列，顺序与 Schema 相同；`source_snapshot_id` 来自对应 verified receipt 的
`raw_snapshot_id`。结果通过 Schema 后按
`(observation_date,symbol,source,source_snapshot_id)` 稳定排序。输入 response/行顺序改变不得改变输出内容摘要。

## 7. build 的确定行为

### 7.1 输入信任边界

读字段前依次验证并只消费返回 frame：

1. observations 通过 `IndexConstituentObservationSchema`，且非空、universe/source 单一；再次执行每个日期
   300 个唯一证券与权重和 `[99,101]`，防止 direct caller 绕过 normalize；
2. calendars 通过 `TradeCalendarSchema`；
3. instruments 通过 `InstrumentSchema`；
4. `signal_start/signal_end` 是 exact `date`、`start<=end` 且都是 SH 开市日。

P2 是不读取 research config 的 data-layer 纯函数，因此不得硬编码
`2016-01-04/2026-06-26`，也无法自行证明 caller 传入值与某份配置相等。它只负责证明两个 exact date 是已验真
calendar 中的 SH session，且首版绝不把自然日向前或向后对齐。真实 stage/G2 消费边界再负责把这两个值与同一
`LoadedM3Config.data.start_date/end_date` 精确比较；当前示例由 P2-0 修正为上述日期。单元测试可以使用任意满足
同一 session 合同的小型日期域，不能为了示例值提交十年日历 fixture。

令 `calendar_anchor=max(max(observation_date), signal_end)`，从已验证 calendar 中取得严格晚于 anchor 的第一
个 SH 开市日作为 `calendar_proof_end`；缺失即 `CALENDAR_COVERAGE_INVALID`。calendar 在
`min(observation_date)..calendar_proof_end` 的每个自然日必须同时含 SH/SZ 一行，二者日期集和 `is_open`
必须一致；少日、重复、求并集或沪深冲突均失败。这样最后一个 observation 的严格下一 session 也有完整证据，
不能仅凭“日期表到 observation 当日”为它推断 activation。SH `is_open=true` 的严格递增日期序列是本包唯一
session SSOT。

每个 observation date 必须是 SH 开市日。若日历无法证明其后第一个 session，则不得猜测自然次日。

### 7.2 instrument 生命周期

每个 observation symbol 必须在 instrument 中恰有一行，并满足：

- suffix 与 market 一致，market 为 SH/SZ；
- `instrument_type=STOCK`、`currency=CNY`；
- `list_date <= observation_date`；
- `delist_date` 为空或不早于 observation date。

成员状态与 `[list_date,delist_date]` 取交集；`list_date` 映射为首个 `>= list_date` 的 SH session，非空
`delist_date` 映射为最后一个 `<= delist_date` 的 SH session，二者都不得用自然日直接冒充 session。
若对应方向不存在 session，或映射后起点晚于终点，则该生命周期在审计域为空。若一个本应在 signal window 有效的
观察成员因生命周期没有任何可用 session，或生命周期裁剪导致任一 signal session 的资格数不再是 300，
则 fail-closed，不发布 299 只的隐式状态。历史上已退市但当时生命周期合法的证券必须保留。

### 7.3 状态和区间

- 每个 observation 的状态从严格下一 SH session 的收盘后开始；
- 下一 observation 状态生效时，前一状态结束于其前一个 SH session；
- 先生成状态区间，再与 `[signal_start,signal_end]` 和 instrument 生命周期相交；本包输出的 membership 全部
  裁剪到 signal window；
- 持续成员在相邻 SH session 上的区间合并；中间任何状态调出后再调入必须保留两段；
- `effective_to` 在 B3 输出中一律非 null，最后状态精确截到 `signal_end`；
- 同一 `(universe,symbol)` 区间不得重叠；相邻可合并区间不得残留为两行；
- signal_start 必须已有更早 observation 推导出的状态。首个可生效日晚于 signal_start 时为 warmup 缺失；
- 生效日在 signal_end 之后的 observation 保留在 observations 证据中，但不改变 membership/eligible。

membership 精确为 `UniverseMembershipSchema` 四列，并额外要求本包的非 null、signal-window、无重叠/可合并残留
规则；按 `(universe,symbol,effective_from,effective_to)` 排序。

### 7.4 `eligible_keys`

`eligible_keys` 只有 `as_of: pl.Date,symbol: pl.Utf8` 两列。对 signal window 的每个 SH 开市日，展开当天有效
membership；每个 `as_of` 恰好 300 个唯一 symbol，全表 `(as_of,symbol)` 唯一，按该键排序且非空。

调入前、调出后和两个成员区间之间不能出现资格键。不要因为某证券 bars 中有历史数据而添加资格键，也不要
从 bars 反推 membership。

## 8. clean table 内容身份

`clean_table_content_sha256` 是 B3/B4 clean 逻辑表的唯一内容摘要工具，与 B2A 的供应商 raw response hash
职责不同，不修改或替代 `response_content_sha256`。

冻结算法版本 `m3-clean-table-content-v1`：

1. `table_name` 必须是非空受控小写 snake_case，进入 hash envelope；
2. envelope 包含版本、table name、按 frame 当前精确顺序记录的列名和 dtype；
3. 每个 scalar 使用显式类型标签；v1 只支持 null、bool、int、finite float、date、string；其他类型和
   非 finite float 失败；
4. 日期 ISO；float 用 Python 稳定 round-trip 十进制，`-0.0` 归一为
   `0.0`；JSON `allow_nan=false`；
5. 每行编码为规范 JSON，按完整规范行 bytes 排序后进入 envelope；重复行保留多次，不去重；
6. JSON 使用 UTF-8、排序 object key、紧凑分隔符，结果为小写 64 位 SHA-256 hex；
7. 行顺序变化 hash 不变；列顺序/dtype/任一值/重复次数/table name 变化 hash 改变。

`ObservedMembershipResult` 使用固定 table name：

- `index_constituent_observation`；
- `universe_membership`；
- `eligible_keys`。

构造时重验三张表和三个 digest。由于 frozen dataclass 不会冻结其内部 DataFrame，且三张自洽表本身不能证明
它们来自指定 raw/calendar/instrument，`verify_observed_membership_result` 必须使用完整冻结签名重新执行
batch/response normalize 和 membership build，再逐 frame/digest 比较。不得只检查 hex、只验三表内部关系或
信任 result 自报日期。构造后通过 `object.__setattr__` 漂移 frame/hash，以及把 membership/eligible 整套错移
一个 session 后同步重算三个 digest 的反例都必须失败。

值对象构造本身也必须消费三张 validator 返回的规范 frame：先全部验证，再将 observations、membership、
eligible_keys 三个返回对象写回 frozen dataclass，最后仅基于实际公开 frame 重算和比较三个 digest。不得用
规范 frame 算摘要却继续暴露预验证 frame。该规则及返工证据见
[`M3_G1_P2_B3PIT成员状态初验一次返工任务单.md`](M3_G1_P2_B3PIT成员状态初验一次返工任务单.md)。

## 9. 稳定失败语义

`str(error)` 只能是下列稳定 code，`repr` 不得包含输入值、路径、token 或底层异常。所有 Pandera/Polars/
类型/日期转换异常在模块边界 `from None` 脱敏；不要用 `except Exception` 吞掉编程错误。

```text
G1_MEMBERSHIP_BATCH_INVALID
G1_MEMBERSHIP_RESPONSE_SET_MISMATCH
G1_MEMBERSHIP_RESPONSE_INVALID
G1_MEMBERSHIP_REQUEST_SCOPE_INVALID
G1_MEMBERSHIP_COLUMNS_INVALID
G1_MEMBERSHIP_VALUE_INVALID
G1_MEMBERSHIP_DUPLICATE_KEY
G1_MEMBERSHIP_MONTH_MISSING
G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID
G1_MEMBERSHIP_WEIGHT_SUM_INVALID
G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID
G1_MEMBERSHIP_CALENDAR_INVALID
G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID
G1_MEMBERSHIP_CALENDAR_MISMATCH
G1_MEMBERSHIP_INSTRUMENT_INVALID
G1_MEMBERSHIP_LIFECYCLE_INVALID
G1_MEMBERSHIP_SIGNAL_RANGE_INVALID
G1_MEMBERSHIP_WARMUP_MISSING
G1_MEMBERSHIP_INTERVAL_INVALID
G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID
G1_MEMBERSHIP_RESULT_INVALID
G1_TABLE_IDENTITY_INVALID
```

错误类型构造器本身要拒绝未知 code。无需为纯诊断再细分更多 code；本包优先保证 fail-closed 和主业务语义。

## 10. 允许修改的文件

- `src/quant/data/index_membership.py`（新增）；
- `src/quant/data/m3_identity.py`（新增）；
- `src/quant/domain/schemas.py`；
- `src/quant/data/__init__.py`、`src/quant/domain/__init__.py`（仅新增导出）；
- `tests/unit/test_index_membership.py`（新增）；
- `tests/unit/test_m3_identity.py`（新增）；
- 本包交付/复验报告。

不得修改 B2A/B2B 已验收生产代码、现有 fixture 期望以迁就实现、路线图勾选项、G0–G9 状态或配置。若发现
必须改变冻结接口，停止扩大实现，先在交付报告提交最小证据给主 Agent。

## 11. 实现 Agent 必测矩阵

至少覆盖：

1. batch 构造后 identity drift、少/多/重复 response、跨 batch response、response 构造后 frame/receipt/spec
   drift，均在读值前稳定失败；
2. 非完整自然月、月份不连续、空月；同月多 observation 保留；输入 batch/response/row 顺序稳定；
3. raw missing/extra/reordered columns；row index/symbol/date 跨 scope；bool/null/NaN/inf/List/Struct weight；
4. 重复观察键；299/301；权重和 99/101 通过、边界外失败；同一组近边界浮点权重的行序排列不得改变结果；
5. 2016-01-29 Friday observation 在 2016-02-01 Monday 形成 `as_of`，不在 Friday 形成资格；跨模块 fixture
   明确最早成交为 2016-02-02 Tuesday open；
6. 调入不前视、调出止于前一 session、持续成员合并、调出后重入两段、同月两次状态；
7. signal 起点无 warmup、最后区间截断、所有 effective_to 非 null、闭市日不生成 eligible；
8. calendar 缺自然日、SH/SZ 缺侧、`is_open` 冲突、重复日、observation 非开市日、最后 observation 后缺
   `calendar_proof_end`；
9. instrument 未知、重复、市场/类型/币种不符、尚未上市、已退市、生命周期裁剪导致 299；周末/闭市日
   list date 向后映射、delist date 向前映射；历史合法退市成员保留；
10. membership 区间不重叠、每个 signal session 资格恰好 300、调入前 bars 存在也不影响资格；
11. clean digest 对行序稳定，对列序/dtype/value/duplicate count/table name 敏感，拒绝 datetime、
    unsupported/nonfinite；
12. result 构造必须把三张 validator 返回 frame 写回后再验 digest，公开 frame 的重算摘要必须逐表等于公开
    digest；消费时从 batch/responses/calendar/instruments 重新闭合；三种 frame/hash 漂移及整套合法表错移
    一天并同步改 digest 均失败；
13. 异常 message/repr/cause/traceback 不出现绝对路径、token 样例或原始恶意输入；
14. 生产模块无网络、文件写入、research/provider/Qlib 反向 import。

300 只证券 fixture 应以测试 helper 机械生成，避免提交巨型手写 CSV；但测试必须对关键证券和日期做显式断言，
不能只断言 row count。

## 12. 独立初验 Agent 的未公开反例

初验不能只重跑实现者测试，至少临时增加下列八类中六类，且不得提前把具体数据交给实现者：

- batch hash/spec/receipt/frame 多层同时漂移后尝试自洽伪造；
- 请求 ID 集相同但其中一个月 scope 被换，或两个 full-month 请求跳过中间月；
- 同月两 response 含相同 observation key，单表各自无重复但合并后冲突；
- Schema 可 coercion 的 dtype 与不可 coercion List/Struct，验证后确认实际消费返回 frame；
- Friday→Monday 的 observation 同时含调入/调出，检查 Monday 有且 Friday 无；
- delist_date 落在闭市日、调出后重入、连续相同状态三者组合；
- signal_start 前有 observation 但其 next session 晚于 start，证明仍是 warmup 缺失；
- clean digest 中 `-0.0/0.0`、Unicode、datetime 拒绝、重复相同行；
- result 构造后只换一个 DataFrame、只换一个 hash、frame/hash 同时换成另一合法表；
- 恶意字符串/底层异常携带本机绝对路径和 token marker，扫描 cause 与 traceback。

初验报告逐项映射接口、生产代码、测试和临时反例。发现 P0/P1 必须退回；不影响主业务流程的 P2 可记录后置，
但不能把身份闭包、PIT 时间、300 只、生命周期、Schema-first 或异常泄露降为 P2。

## 13. 验证命令与交付门槛

全部命令只在 WSL Miniforge base 运行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_index_membership.py tests/unit/test_m3_identity.py \
  tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_mappers.py
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

实现报告必须列出：修改文件、每个冻结签名、测试数量、全量/Ruff/mypy、import 隔离、是否联网、token 脱敏、
未实现项和任何契约疑问。独立报告必须写明实现者未使用的反例及结果。两份报告互相链接并保留返工历史。

本包通过外部闭环只表示“可交主 Agent 终验”，不表示 B2/B3/G1/M3/Gate 完成。后续顺序为：

1. G1-P3：B2C 涨跌停与公司行动规则 mapper；
2. G1-P4：按
   [`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md)
   依次执行 P4A candidate/主审计、P4B 跨源证据、P4C 不可变 release；
3. 真实小范围 Tushare/BaoStock 验证与 G1 总体验收。
