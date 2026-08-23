# M1-HK-CA-P1-PRE：实施事实与 HK 行情 Capability 任务单

日期：2026-08-09  
状态：**R3 实施事实 Capability 的实现、独立复验与主 Agent 验收 PASS；HK bar capability 仍 blocked，后续由 PRE-B 闭环；本包不代表正式 HK 数据、HK60、复权或 M1 Gate**（见 [`M1_HK_CA_P1_PRE_R3_实施事实Capability主Agent最终验收报告.md`](M1_HK_CA_P1_PRE_R3_实施事实Capability主Agent最终验收报告.md)）  
性质：来源无关开发合同；不是正式 HK 数据 Gate、HK60、复权或 M1 Gate

## 1. 目标

在计算港股 PIT gross total-return 之前，先补齐两个不可由调用方自报的上游事实：

1. `VerifiedImplementedHkCorporateActionSet`：证明 P0 选中的公司行动在给定 `as_of` 前，已由来源明确确认实施；
2. `VerifiedHkBarBundle`：证明下游消费的是某个 HK history plan/finalize 对应的精确、不复权、可知时点闭包。

本包只建立 fresh-verifiable capability。不得计算 total-return，不得决定现金再投资日、同日事件顺序、FX、
RIGHTS 投资者政策或归一化锚点。

## 2. 已确认的现状

- P0 的 `ACTIVE` 仅表示 PIT 修订链中截至查询时点被选中的版本；`ex_date/pay_date/stock_list_date` 已过去
  不等于来源证明“已实施”。
- `finalize_hk_history` 当前校验 exact expected keys 并写 `finalize.json`，但没有公开 loader/capability 供下游
  fresh 绑定 plan、finalize bytes、clean bars 和可用时点。
- `Bar1dSchema` 不含 availability 字段；`ResearchPrice1dSchema.TOTAL_RETURN_DIVIDEND` 也不足以表达包含
  BONUS/SPLIT 的版本化 HK gross total-return。

因此本包不得把日期推断当作实施证据，也不得把一个普通 `Bar1dSchema` frame 当作 verified HK bar 输入。

## 3. 权威依赖与禁止复用

### 3.1 必须复用

- `CorporateActionSchema`、`HkCorporateActionRevisionEvidenceSchema`；
- `HkCorporateActionSelectionResult`、`VerifiedHkCorporateActionProjection` 及
  `verify_hk_corporate_action_selection_result`；
- `HKHistoryPlan` 的 `plan_sha256`、v1/v2 expected/effective keys；
- `Bar1dSchema`；
- `finalize_hk_history` 已发布 clean 内容和 canonical `finalize.json` 形态；
- 项目既有 canonical JSON、SHA-256、strict schema、稳定脱敏异常和 process-local content-bound
  attestation 模式。

### 3.2 禁止复用

- A 股 CNINFO/Tushare `div_proc`、A 股实施状态、entitlement、整数送股、账户账本或 factor reconciliation；
- `AkshareResearchPriceMapper`、`ArchivedEtfTotalReturnConnector`、`ResearchPriceUpdatePipeline`；
- 通过 `pay_date <= today`、`stock_list_date <= today`、当前时间或调用方布尔值自报实施；
- 从目录、glob、网络、token、URL 或 `data/legacy` 自动发现实施证据；
- 把路径、dataclass 类型名、可重算摘要或普通 DataFrame 当作 capability；
- 在本包写正式 HK60 plan/journal、正式 clean 根、正式 artifacts，或发起真实网络请求。

## 4. 实施事实合同

### 4.1 Schema

在 `src/quant/domain/schemas.py` 新增 `HkCorporateActionImplementationEvidenceSchema`，并从
`quant.domain` 导出。每个 P0 canonical `event_id` 精确一行，最少字段：

- `event_id`：64 位小写 SHA-256；
- `symbol`、`action_type`、`source`、`source_event_id`、`source_revision_id`；
- `implementation_status`：只允许 `IMPLEMENTED`；
- `implementation_effective_date`：来源明确陈述的实施生效日；
- `implementation_confirmed_at`：aware UTC，且 `<= query.as_of`；
- `source_observed_at`：aware UTC，且不早于 confirmed time；
- `source_record_id`、`raw_selector`；
- `raw_file_sha256`、`raw_metadata_sha256`、`raw_bundle_sha256`；
- `p0_actions_content_sha256`、`p0_evidence_content_sha256`、`p0_query_sha256`；
- `implementation_evidence_sha256`：绑定本行全部语义字段的 canonical digest。

禁止 `PENDING/ANNOUNCED/APPROVED/COMPLETED_BY_DATE` 等近似状态进入 verified set。withdrawn、future
confirmation、缺失或重复 event 都必须 fail closed。

### 4.2 来源无关值对象与 Protocol

新增 `src/quant/data/hk_corporate_action_implementation.py`，公共接口至少包括：

- `HkCorporateActionImplementationQuery`：绑定 P0 query identity、排序唯一 event ids、aware UTC `as_of`；
- `HkCorporateActionImplementationCapability`：source/version，以及可证明 exact scope、实施状态、修订/
  correction、撤回、published/observed time、retained bytes 的 required booleans；
- `HkCorporateActionImplementationRawFile/RawBundle`：调用方显式传入不可空 bytes/metadata、canonical roles
  和 fresh hashes；不接受路径发现；
- `HkCorporateActionImplementationSourceAdapter(Protocol)`：只解释显式 retained bundle；
- parsed-only projection factory；
- `verify_hk_corporate_action_implementation_source(...)`：唯一签发 source-verified capability 的入口；
- `select_implemented_hk_corporate_actions(...) -> VerifiedImplementedHkCorporateActionSet`；
- `verify_implemented_hk_corporate_action_set(...)`：fresh 重验入口。

source wrapper 必须先 fresh 调用 P0 verifier，再验证 adapter capability、raw bundle、exact event set、证据表
和内容摘要，最后签发与 P0 result + implementation bytes/content 精确绑定的 process-local attestation。
factory-only projection、旧 token 复用、pickle/reload 后对象均不得通过消费者 verifier。

### 4.3 exact scope

- query event ids 必须与 P0 canonical actions 的 event ids 精确相等；不得只提供“已实施子集”。
- 每个 event 精确一条 IMPLEMENTED evidence；额外、缺失、重复、跨 symbol/type/source/revision 均拒绝。
- source 必须声明且证明 scope completeness；空结果不等于完整。
- `implementation_confirmed_at <= query.as_of`，未来确认不能改写较早 as-of。
- implementation evidence 必须引用 P0 exact event/revision；不能只按 `(symbol, ex_date)` 猜 same-event。

## 5. HK bar publication capability

### 5.1 公共类型

在 `hk_history_backfill.py` 增加窄公共、冻结且不可序列化的 `VerifiedHkBarBundle`，至少绑定：

- resolved `journal_root` 与 `clean_root` identity；
- exact `HKHistoryPlan` / `plan_sha256`；
- canonical `finalize.json` 原始 bytes 及 SHA-256；
- exact expected/effective `(symbol, trade_date)` keys 及 digest；
- canonical `Bar1dSchema` frame、row count、content digest；
- 每行 `bar_available_at` 证据及其 content digest；
- process-local content-bound attestation。

新增：

```python
load_verified_hk_bar_bundle(
    *,
    plan: HKHistoryPlan,
    journal_root: Path,
    clean_root: Path,
    availability: pl.DataFrame,
    as_of: datetime,
) -> VerifiedHkBarBundle

verify_hk_bar_bundle(
    bundle: VerifiedHkBarBundle,
    *,
    plan: HKHistoryPlan,
    journal_root: Path,
    clean_root: Path,
    as_of: datetime,
) -> None
```

若为保持依赖方向需要把 capability 放在新的 `hk_bar_bundle.py`，允许重新冻结后采用该位置；不得复制
`HKHistoryPlan` hashing/expected-key 规则形成第二套 SSOT。

### 5.2 availability evidence

在 schemas 新增 `HkBarAvailabilityEvidenceSchema`，每个 expected/effective key 精确一行：

- `symbol`、`trade_date`；
- `bar_available_at`：aware UTC；
- `source`、`source_record_id`；
- `raw_request_id` 或 exact retained request identity；
- `raw_file_sha256`、`raw_metadata_sha256`、`request_receipt_sha256`；
- `availability_evidence_sha256`。

这是来源/收据投影，不是调用方任意填写的时间表。loader 必须 fresh 复验对应 request receipt/retained raw
闭包，或仅接受由受信 source verifier 签发的 content-bound capability。若现有 request receipt 没有足够字段，
应停止并提交缺口证据，不得猜测 availability。

### 5.3 fresh loader 规则

loader/verifier 必须：

1. fresh 验证 plan 自身、journal binding、所有 request receipts 和 finalize canonical bytes；
2. 只读取 plan exact partitions/keys，不扫描整个 clean/data/legacy；
3. `Bar1dSchema.validate` 后要求全部 `symbol` 为 5 位 `.HK`，`adj_factor == 1.0`，source 与 plan/receipt 一致；
4. actual keys 与 v2 `effective_expected_dates`（v1 为 `expected_dates`）精确相等，row count 无重复；
5. fresh 重算 clean content digest，必须等于 finalize receipt；
6. availability keys 与 bar keys 精确一一对应，且每个 `bar_available_at <= as_of`；
7. capability 绑定 resolved root identity；复制 root、路径替换、symlink/reparse、TOCTOU、receipt/partition
   whole-rehash 均 fail closed；
8. hostile reader/schema/verifier 异常统一固定错误码并 `cause/context is None`。

不得因为 `trade_date < as_of.date()` 推断 bar 已可见。不能证明 retained receipt 到 availability 的映射时，
返回稳定 unsupported/invalid code，不签发 capability。

## 6. 失败语义

新增稳定错误类型，公开消息只能是下列代码或任务实现前冻结的更窄子集：

- `HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED`
- `HK_CA_IMPLEMENTATION_EVIDENCE_INVALID`
- `HK_CA_IMPLEMENTATION_SCOPE_INVALID`
- `HK_CA_IMPLEMENTATION_VERIFY_FAILED`
- `HK_BAR_CAPABILITY_UNSUPPORTED`
- `HK_BAR_PUBLICATION_INVALID`
- `HK_BAR_AVAILABILITY_INVALID`
- `HK_BAR_VERIFY_FAILED`

任意外部/hostile 异常必须在 active `except` 之外重构固定错误，`raise ... from None`，且公开异常
`__cause__`、`__context__` 均为 `None`；traceback 不得包含路径、raw bytes、marker、token 或凭据。

## 7. 写入白名单

允许：

```text
src/quant/domain/schemas.py
src/quant/domain/__init__.py
src/quant/data/hk_corporate_action_implementation.py
src/quant/data/hk_history_backfill.py
src/quant/data/__init__.py                 # 仅必要导出
tests/unit/test_schemas.py
tests/unit/test_hk_corporate_action_implementation.py
tests/unit/test_hk_history_backfill.py
docs/framework/agent/M1_HK_CA_P1_PRE_实施事实与HK行情Capability交付报告.md
```

这些文件已有未提交的 P0/HKEX/U0C 合法改动；实现者必须在修改前核对 diff，保留并兼容现有内容。

禁止：connectors、research_price/storage/mappers、backtest/execution、HK60/U0C/G1 正式 roots、任何
`data/legacy`、依赖与 enums、正式 journal/artifacts。

## 8. 最小 fixture

- 两个 HK 证券、至少三个连续交易日；
- 一个正常 DIVIDEND；
- 一个停牌期间 ex-date、下一 observed bar 才出现的 BONUS 或 SPLIT；
- 一个 future correction/withdrawal；
- 一个未实施/PENDING 或缺失 implementation evidence；
- 一个 v2 no-trade effective-key 例子；
- 全部 retained bytes 在测试临时目录或内存，无网络。

## 9. 必测反例

至少覆盖：

1. P0 ACTIVE 且日期已过，但 implementation evidence 缺失；
2. 调用方按日期伪造 IMPLEMENTED；
3. future confirmed/withdrawal 改写较早 as-of；
4. implementation event 缺失、额外、重复、跨 source/revision；
5. raw/content/metadata/receipt/P0 result whole-rehash 后复用旧 attestation；
6. factory-only、pickle、reload、合法另一 query/source 旧 token 置换；
7. bar `adj_factor != 1`、缺/多/重复 key、缺 baseline 所需历史行；
8. finalize bytes、plan、request receipt、clean parquet 任一漂移；
9. copied root、root rename/replacement、symlink/reparse、验证窗口 TOCTOU；
10. availability 缺/多/重复/future、自报日期推断、receipt identity 漂移；
11. hostile adapter/reader/schema 的 ValueError 与非 ValueError，错误链和 traceback 脱敏；
12. 对 exact 合法 fixture，builder 与 public verifier 均 fresh 成功。

## 10. 验证

Windows 原生定向：

```powershell
$env:PYTHONPATH='src'
D:\Miniforge3\python.exe -m pytest tests/unit/test_schemas.py tests/unit/test_hk_corporate_action_implementation.py tests/unit/test_hk_history_backfill.py -q
D:\Miniforge3\python.exe -m ruff check <改动文件>
D:\Miniforge3\python.exe -m mypy <改动生产文件>
```

WSL base 对应定向验证：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_schemas.py tests/unit/test_hk_corporate_action_implementation.py \
  tests/unit/test_hk_history_backfill.py -q
/home/mabw/miniforge3/bin/conda run -n base ruff check <改动文件>
/home/mabw/miniforge3/bin/conda run -n base mypy <改动生产文件>
```

当前 WSL 路径为 DrvFS；绿测只证明双平台开发合同，不宣称 ext4/M1 Gate。

## 11. 停止条件

出现以下任一情况必须停止扩大实现并回报证据：

- 现有 request/finalize receipt 不足以 source-verifiably 推导 `bar_available_at`；
- 需要猜测真实 HKEX/其他来源的实施状态字段或文件格式；
- 需要新增币种、action type、依赖或修改正式 history/HK60 journal；
- 需要决定 dividend 再投资日、同日事件顺序、FX、RIGHTS、税费或归一化锚；
- 需要改变现有 P0/HK history 已验收外部行为，而非增加窄 public verifier。

## 12. 通过条件与边界

- 两个 capability 都只能由 fresh source/retained closure verifier 签发，调用方不能自报；
- 所有 exact-set、root identity、whole-rehash、异常脱敏反例通过；
- Windows 与 WSL base 定向 pytest/Ruff/mypy 通过；
- 实现者交付报告与全新上下文独立初验均通过后，再由主 Agent 终验；
- 通过后只解锁 P1 total-return 的公式冻结与 fixture 工程，不关闭真实来源、HK60、复权、ext4 或 M1 Gate。

## 13. R2：retained 实施事实语义与 capability fresh 字段闭包（2026-08-09）

### 13.1 初验失败闭环

独立初验报告：`M1_HK_CA_P1_PRE_实施事实Capability独立初验报告.md`。

阻断一：实现测试的正向 `_ImplementationAdapter.verify_retained` 只确认 raw 为
`{"scope_complete":true}`，随后遍历 P0 `actions` 并自行填写 `IMPLEMENTED`、确认时间和 retained 摘要。
raw 中没有实施 record/status/confirmation/withdrawal，普通 P0 `ACTIVE` 仍可经 source wrapper 获得两条
verified implemented actions。现象证明的是 adapter 能合成一张自洽表，不是来源 retained bytes 证明已实施。

根因：fixture 把 P0“截至 as-of 仍 ACTIVE”错误提升为“来源确认 IMPLEMENTED”，绕过了本任务最核心的
来源语义边界。source-neutral wrapper不能理解所有未来来源格式，具体 approved adapter 必须承担并测试
“retained bytes → implementation candidates”的 strict parser/verifier责任；正向 fixture同样必须真实演示该责任。

阻断二：`_preflight` 只 fresh 重验 required booleans，没有重验 `source`、`adapter_version` 等 capability
构造不变量。低层把合法 capability 的 `adapter_version` 改为空串后，source wrapper仍新签发 attestation，
selector与public set verifier均通过。

根因：只信 dataclass `__post_init__` 的一次性校验；消费者没有 fresh 重建全部值对象不变量。

### 13.2 R2 最小返工

1. fixture raw 必须包含 canonical、exact-key implementation records；每条至少明确 event/revision、
   `implementation_status`、effective date、confirmed/observed time、source record id，以及必要 correction/
   withdrawal scope。adapter从 retained bytes strict parse，不得读取 P0 actions后补状态。
2. adapter 只能用 P0 result做 exact event/revision/source对账；implementation status与confirmed time必须来自
   parsed retained record。raw缺记录、只有scope flag、ANNOUNCED/PENDING、future、withdrawn、未知/重复字段、
   truncation均在 factory/source wrapper前失败。
3. positive fixture至少包含两个明确 `IMPLEMENTED` records；另含 PENDING/future/withdrawal retained反例。
   测试必须先删除 raw 中所有实施字段，证明即使 P0全 ACTIVE且日期已过也不能签发。
4. `_preflight` 及所有 fresh consumer重验 capability exact type、非空规范 `source/adapter_version`、排序唯一
   supported sets与全部required booleans；不得只重验booleans。
5. capability的 source/version低层改为空、空白、非法类型、错source/version，旧token与重新走source wrapper
   均拒绝。
6. 保持R1已通过的content-bound HMAC、whole-rehash、token置换、pickle/reload与异常脱敏行为；不得放宽。

### 13.3 新增测试与通过条件

- raw只有 `scope_complete` + P0 ACTIVE：拒绝，零 verified set；
- 删除/改写 retained status、confirmation、event/revision/source record：拒绝；
- retained PENDING/ANNOUNCED/future confirmation/withdrawal：拒绝或按 exact scope fail closed；
- 两条合法 retained IMPLEMENTED records：source wrapper→selector→public verifier通过；
- `source`/`adapter_version` 低层空串、空白、错值、非法类型：builder/source wrapper/selector/public verifier
  全部 fresh 拒绝；
- Windows与WSL base原定向组、Ruff、mypy通过；bar capability仍按PRE-B任务等待，不因R2伪造实现。

R2必须由实现角色返工，再由全新独立上下文复验。通过仍只表示来源无关实施事实开发合同，不表示存在真实
HK corporate-action implementation adapter、01065/HK60、复权或M1 Gate。

## 14. R3：exact capability type 与 withdrawal retained 因果闭包（2026-08-09）

R2独立复验报告：`M1_HK_CA_P1_PRE_R2_实施事实Capability独立复验报告.md`。结论仍为FAIL。

### 14.1 失败闭环

1. `_preflight` 对 `HkCorporateActionImplementationCapability` 使用 `isinstance`。普通Python子类可通过
   builder、source wrapper、selector与public verifier四个fresh边界并签发verified set，违反§13.2明确冻结的
   exact type规则。普通非子类mimic已拒绝，但不足以关闭子类携带额外行为/状态的边界。
2. fixture strict parser仍接受三种不可能/非canonical withdrawal retained record：
   - `source_record_id`只有空白；
   - `withdrawal_confirmed_at`晚于整个bundle的`source_observed_at`；
   - 完全相同future withdrawal重复出现。

这些记录虽不一定改变较早query as-of的选择结果，但会让“bundle在观察时点已持有的exact retained scope”自相
矛盾或不唯一；不能因为它们属于future就跳过结构和因果校验。

独立复验同时裁定：同进程exact-content capability clone/pickle若语义、token、query/raw/P0均完全不变，不单独
构成阻断；R3不得引入instance-unique随机身份或破坏合法content-bound copy。projection/verified set原有不可
pickle/reload边界继续保留。

### 14.2 R3 最小返工

- 所有fresh capability入口使用`type(value) is HkCorporateActionImplementationCapability`；构造factory、source
  wrapper、selector与public verifier不得通过子类。
- retained parser对所有required text执行type为`str`且`strip()`非空；canonical payload中保留原值前应要求
  `value == value.strip()`，拒绝首尾空白。
- 每个withdrawal `confirmed_at`必须aware UTC，且`<= bundle.source_observed_at`；同时按query as-of决定是否
  影响当前selection，不能混淆“已被bundle观察”与“截至query已生效”。
- withdrawal records采用任务实现已冻结的canonical排序键，完全重复与业务唯一键重复均拒绝；若来源允许
  多次不同withdrawal/correction，必须由不同source record/revision和严格时间顺序证明，不能静默去重。
- exact event scope验证必须遍历future withdrawal并做上述结构/时间/唯一性校验，再决定其不改写较早as-of。
- 保持R2已通过的only-scope拒绝、status矩阵、source/version四边界、whole-rehash旧token、hostile脱敏与
  exact clone语义。

### 14.3 新增测试与通过条件

- capability普通子类在builder/wrapper/selector/public verifier四边界全部拒绝，adapter调用次数为零（适用时）；
- withdrawal source record为空、全空白、首尾空白、非str均拒绝；
- withdrawal confirmed晚于source observed，即使晚于query as-of、不会影响当前选择，也必须拒绝；
- 完全重复与同业务键不同payload重复withdrawal拒绝；合法多个不同revision按canonical顺序处理；
- 较早query对合法future withdrawal保持原action；withdrawal在query as-of已知时对应event不得进入implemented set；
- Windows/WSL base三文件pytest、Ruff、mypy与diff check通过；history/bar仍不改。

R3仍需实现交付与全新独立复验。通过边界不变：只关闭来源无关实施事实开发合同，bar receipt v3、真实来源、
01065/HK60、复权、ext4与M1 Gate均开放。
