# M2-AUDIT-V4-FLOW-SEMANTICS 交付报告

## 交付结论

**IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT**

本报告是该交付文件的首条记录；原文件不存在，因此没有历史内容可覆盖。本次实现严格绑定任务书
`docs/research/tasks/M2_AUDIT_V4_FlowSemantics任务书.md`，工作区为
`F:\\AI_Coding\\QuantitativeTrading\\artifacts\\dev_worktrees\\m2-audit-v4-flow-semantics`，
基线为 `f6eade1fb9434673947dbc7b887c5110fe85466f`。

没有发现需要扩展写路径、修改任务书/SSOT 或放宽 v3 失败语义的真实合同冲突；因此本报告不记录
`STOP / CONTRACT_DRIFT`。实现仍未达到可执行验收、真实审计、snapshot READY、R3 READY 或 PIT
结论。

## exact5 范围

允许写入且本任务涉及的 exact5 为：

1. `src/quant/data/audit_tushare_financials.py`
2. `src/quant/data/publish_tushare_financials.py`
3. `tests/unit/test_audit_tushare_financials.py`
4. `tests/unit/test_publish_tushare_financials.py`
5. `docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`

未修改 manager taskbook、roadmap、review、schema、repository、facade、PIT、shared evaluator、
governance SSOT、配置、依赖或其他路径。

## exact 改动

### audit_tushare_financials.py

- 将审计 schema 标识升级为 `tushare-financial-raw-audit-v4`，保留 v3 的 plan、ledger、raw closure、
  structural、dimension、quality、bytes、blocking 与 fail-closed 语义。
- 增加基于 metadata-only schema 的 source type provenance：按冻结 raw 相对路径、request identity、
  完整 logical schema 生成规范化证据及小写 hex64 的
  `flow_source_type_evidence_sha256`。
- 增加安全 normalized union：按完整 logical schema 分组、每组只读一次并做显式窄投影，再通过单一
  `UNION ALL` 安全视图承接 v3 质量统计和 flow 经济计算；不再使用原经济数据
  `union_by_name=True` 读取路径。
- 增加唯一 canonicalizer 与 conflict token 语义，覆盖 VARCHAR finite/nonfinite、数值源、BOOLEAN、
  unsupported scalar、overflow、blank、null、`+0/-0` 及同日多版本冲突；不填零、不静默转换、不回退
  冲突值。
- 增加 `income.n_income`、`income.n_income_attr_p`、`cashflow.n_cashflow_act` 的 Q1/Q2/Q3/FY
  固定顺序 12 bucket，包含 current/type1、type2、previous-chain、available-date drift、缺失/非法/
  nonfinite/resolution-loss、comparable、mismatch、coverage、funnel 与派生 status。
- 增加 Decimal `0.01` 固定容差、Float64 cent-resolution 判定、Q1 与后续季度链式 operands、coverage
  的整数比例判定及 `CONTRADICTED` / `INSUFFICIENT` / `PASS` 派生。
- 对 nested/binary/不可 token 化 source type 保持 BLOCKED、`NOT_EVALUATED`、空 bucket 且不运行经济
  helper；所有 flow 计算仍受 v3 bytes、lease、complete、结构/日期/维度/ledger Gate 约束。
- 保持 v3 的 I/O 遍数、raw closure、blocking 与 publication 基础门禁，不改变 R3/PIT/shared evaluator。

### publish_tushare_financials.py

- 在 `TushareFinancialSnapshot` 增加 additive public field `audit_sha256`。
- 增加 v4 audit 的 strict validation：顶层 schema、source evidence/SHA、normalized projection contract、
  token algorithm/version、12 bucket 固定身份/顺序、funnel、coverage、mismatch、bucket status、flow
  status/publication 及既有 v3 证据均须一致；不接受未知键、缺失键、顺序漂移、bool 伪装整数、重复 bucket
  或伪造 source identity。
- `_verify_snapshot` 只接受已校验 manifest 的 `audit_sha256`，并使 publish-new、reuse-existing、
  verify 三条路径返回同一审计 SHA；保留 pre-audit → snapshot projection → post-audit equality 以及
  manifest 语义。
- flow 未达到 PASS 时保持 fail-closed，禁止 publication。

### tests/unit/test_audit_tushare_financials.py 与 tests/unit/test_publish_tushare_financials.py

- 测试文件保持在 exact5 范围内，作为 v4 静态测试承载位置；本收束阶段未启动测试或其他执行性验证。
- 未以测试绿灯、import 成功或 fixture 结果推导 Gate 通过结论。

## 合同证据映射

- 版本与兼容性：v4 只增加 flow/source provenance 与 snapshot additive SHA，v3 基础字段和 fail-closed
  路径保留。
- source identity：证据按冻结 raw relative path/request identity/schema 顺序规范化，未知、重复、漂移
  和不可 token 化类型不会被静默降级。
- flow scope：固定三字段、四 fiscal bucket、12 bucket 及固定字段顺序；Q1 previous-chain 字段按合同
  使用 `null`，后续 bucket 使用整数。
- canonicalization：同一语义值先折叠 token，再决定 missing/invalid/nonfinite/resolution/conflict；
  同日多版本任一 token 不同即 conflict，冲突不会 fallback。
- accounting/coverage：仅 comparable operands 参与 mismatch；Decimal 差值 `<= 0.01` 才通过；coverage
  使用 `5*numerator >= 4*denominator`，分母为 0 为 insufficient。
- publication：只有 v3 audit READY、bytes verified、flow PASS 且 pre/post 审计相等时允许发布；
  BLOCKED/NOT_EVALUATED/INSUFFICIENT/CONTRADICTED 均保持禁止发布。
- I/O：safe projection 只允许每个 schema group 一次经济读取和一次审计 union 逻辑；metadata-only
  schema discovery 不计作经济读取，且未新增 data/state 路径。

## 未运行事项

遵循 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`，本交付未运行：

- Python、pytest、Ruff、mypy、cold import 或任何执行性检查；
- DuckDB/Parquet 实际读取、真实 raw/state/financial 数据清理或 writer；
- audit、snapshot、PIT、PIT runner、UA-M2-001 或真实数据质量流程；
- 网络、Tushare、stage、commit、merge 或其他外部状态操作。

因此不存在运行时、真实数据、网络、性能或平台 Gate 证据，不能据此声称 audit-v4 PASS、snapshot READY、
R3 READY、PIT READY 或真实数据质量通过。

## schema、I/O 与平台边界

- 未修改 `src/quant/domain/schemas.py`、PIT 或 shared evaluator；v4 新增字段只在本任务审计/发布边界内
  产生，`audit_sha256` 为 snapshot public additive field。
- 未新增配置、依赖、模块、repository/facade 路径或 raw/clean/state 写入路径；现有 manifest、目录和
  I/O 遍数语义保持不变。
- 本次只有静态代码与文档变更，未证明 DuckDB 版本差异、Windows/WSL 文件语义、Parquet logical type
  实际返回形态或真实源数据覆盖，因此不能将静态结果外推为平台终验。

## 剩余风险与后续验收边界

- 尚未验证 DuckDB metadata/schema 描述、显式 projection、`filename` provenance、Decimal/Float64
  边界及 source type family 在目标运行环境中的实际行为。
- 尚未验证真实四表 raw closure、type1/type2 版本、available date、季度链与 12 bucket 覆盖率。
- 尚未验证 publisher 三路径、manifest SHA 真实性、外部文件漂移和 snapshot post-audit equality 的
  运行时行为。
- 后续必须由授权的独立初验/目标平台验证与真实 audit 继续；在此之前状态只能保持
  `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。

## STATIC_REWORK P0_SHORT_CIRCUIT_ORDER_TEST_CLOSURE（历史追加）

### 现象

初始静态实现曾在 v3 base quality 完成前创建 flow connection，并通过 flow source identity/safe
projection 路径承接质量统计；同时 flow 字段初始顺序为 income → income_attr_p → cashflow，未满足更新后
任务书规定的 cashflow → income → income_attr_p 固定顺序。早退 flow 也没有冻结到任务书指定的 empty
source-evidence SHA，publisher 对该分支的校验顺序不完整。

### 根因

`_audit` 的旧调用图把 source identity 和 safe projection 放在 v3 quality 之前，且原始 v3
`union_by_name=True` 质量路径没有被独立保留为唯一 base quality 路径；publisher 的 expected bucket
comprehension 依赖了错误的共享字段顺序，empty identity 又复用了普通 evidence hash 算法。

### 应遵循规则

严格按更新任务书 §3、§4、§5、§11、§12 执行：仅在 `verify_bytes is True`、active lease 为 0、四表全
`COMPLETE`、v3 structural/bytes base quality closed 后调用 flow identity、safe projection 和经济
helper；任何早退必须保持 `NOT_EVALUATED`、空 buckets、空 evidence、exact early-empty SHA
`793cd498f4dbca6b28661417f49606323248da0cdf8e838575df9f7ef4d0d5db` 和 publication false。v3 base
quality 继续使用合流前原始读取路径，flow 与 publisher 共同使用唯一固定 12 bucket 顺序及 exact
identity strings。

### 最小复现

在 `_audit` 的 fake plan/ledger/complete/base-quality 边界上分别设置 `verify_bytes=False`、active lease
非零、pending ledger 状态或 structural quality 非零，并对
`_flow_source_identity`、`_materialize_safe_projection`、`_flow_semantics`、`_flow_observations`、
`_flow_bucket`、identity/projection contract helpers 安装 fail-on-call spy。正确结果是所有 spy 均为
零调用，flow 为 `NOT_EVALUATED`、buckets 为 `[]`、evidence 为 `[]`、SHA 为上述 exact 值。

### 新增测试

- `tests/unit/test_audit_tushare_financials.py`：加入短路 zero-call/early SHA、v3 原始 quality 路径隔离、
  exact 12 bucket 顺序、80%/100%/零分母/最低 coverage、canonicalizer grammar 与分类优先级、BOOLEAN
  分文件 union、null/blank/bool/非法字符串/Unicode/overflow/NaN/Inf、同日 canonical conflict、type2
  drift/no fallback、previous chain、Decimal tolerance、nextafter 边界、source evidence file order、
  safe projection provenance、untokenizable BLOCKED，以及 publisher pre-mkdir flow forgery、三路径
  audit SHA 和 manifest/audit bytes forgery 场景。
- `tests/unit/test_publish_tushare_financials.py`：加入 `TushareFinancialSnapshot` additive
  `audit_sha256` exact dataclass contract、publisher flow strict validator 的顺序/identity/threshold/
  funnel/count/status/empty-SHA/alias/duplicate rejection。
- 原有 v3 row/date/dimension/plan/inventory/bytes/lease/immutability 测试仍保留；只有需要真正发布的
  one-row fixture 通过测试内的受控 synthetic flow evidence 进入 publisher 路径，因为该 fixture 按合同
  本身只能产生 flow `INSUFFICIENT`，没有修改生产 tolerance、formula 或 output schema。

### 通过条件

由后续授权 validation-only 阶段实际运行上述定向测试、Ruff/mypy/cold/scope evidence，并由独立 reviewer
核对调用图、原始 v3 quality path、12 bucket order、early SHA、source identity、safe union、BLOCKED 和
publisher 三路径；再由中央另行授权真实 audit-v4。当前这些条件均未执行，因此这里只记录静态实现闭合，
不把它们表述为已通过。

## exact5 声明纠正

初始记录中的“exact5”是本实现 Worker 的可写实现集合，不是更新任务书 §2 的完整 exact8 owner map。更新
任务书仍包含 manager taskbook、manager roadmap 与独立 reviewer report 三个只读/他人 owner 路径；本
Worker 仅写以下五个路径，且未写 manager、reviewer、SSOT 或其他路径：

1. `src/quant/data/audit_tushare_financials.py`
2. `src/quant/data/publish_tushare_financials.py`
3. `tests/unit/test_audit_tushare_financials.py`
4. `tests/unit/test_publish_tushare_financials.py`
5. `docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`

本次追加没有改变结论上限。结论仍严格为
`IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不代表 audit-v4 PASS、snapshot READY、R3 READY、
PIT authorization 或真实数据/网络质量通过。

## STATIC_REWORK2 P0_THREE_STAGE_AND_FIELD_DOMAIN（本次收束追加）

### 现象

更新任务书明确指出，前一轮 P0 历史记录中“base quality 前 source/safe 全部 0-call”及“v3 base quality
回退原始 `union_by_name=True`”均已被最新三阶段合同 supersede。当前实现还把质量统计放在 A 闭包判断前，
并且 publisher 对四表数值域使用了统一的 `eligible == raw` / `quarantine == 0` 约束，无法表达 flow
字段的允许性数值隔离。

### 根因

`_audit` 原调用图在 quality、flow source identity、安全 projection 与 economic flow 之间没有形成明确的
A/B/C 边界；v3 质量函数仍包含 raw multi-file `union_by_name=True` 路径；flow 数值字段与
balancesheet 数值字段未按最新 field-domain 合同分流。测试也把 structural failure 当成 A 早退场景，
未覆盖更新后的“B 可执行但 C 必须短路”顺序。

### 应遵循规则

按最新任务书作为唯一合同执行：A 只在 verify bytes、active lease、四表 exact `COMPLETE`、plan/request/raw
closure 均闭合后才开放 B；A 失败时 source identity、safe projection、economic helpers 全部 zero-call，
flow 必须为 `NOT_EVALUATED`、`buckets=[]`、`publication_allowed=false`、空 source evidence 与 exact
early SHA `793cd498f4dbca6b28661417f49606323248da0cdf8e838575df9f7ef4d0d5db`。B 在 A 后以 metadata
identity、每 schema group 的 homogeneous safe projection 和同口径 v3 row/date/dimension/base quality
闭合；不得对 raw economic files 使用 `union_by_name=True`。B structural/date/dimension failure 或
untokenizable source 时 C 的 selection/chain/difference/economic helpers 必须 zero-call，并保留已有
source evidence。cashflow/income flow 数值 parse/nonfinite 只进入 coverage/quarantine，不单独阻塞 B 或
publication；balancesheet/fina numeric domain 仍保持 v3 blocking。publisher 必须逐表严格验证这些域、
exact int/non-bool counter、12 bucket 顺序以及最终 flow `PASS`。

前一节 `STATIC_REWORK P0_SHORT_CIRCUIT_ORDER_TEST_CLOSURE` 的原始文字作为历史保留；其中与上述最新
任务书冲突的旧规则不再作为当前实现合同，未被删除或改写。

### 最小复现

- A 边界：fake plan/ledger/complete 分别设置 `verify_bytes=False`、active lease 非零或任一 ledger 非
  `COMPLETE`，对 `_flow_source_identity`、`_materialize_safe_projection`、`_quality_summary`、
  `_flow_semantics`、`_flow_observations`、`_flow_bucket` 和 identity/projection contract helpers 安装
  fail-on-call spy；必须得到 early empty flow 与 exact SHA，所有 flow/B helper zero-call。
- B→C 边界：A 闭合后按四表记录 identity、四次 safe projection、四次 quality；若 structural/date/dimension
  或 balancesheet numeric domain 失败，必须保留 B 证据且 economic spy zero-call；若 B 闭合才允许 C。
- 字段域边界：cashflow/income 的 parse/nonfinite 与 `eligible/raw/quarantine` 满足合同关系时可继续，
  balancesheet/fina 的 numeric counter 非零、bool 伪装或 non-conservation 必须拒绝/`BLOCKED`。

### exact 改动

- `audit_tushare_financials.py`：将 cheap A closure 放到全部 flow identity/projection/economic helper 之前；
  A 失败直接生成 exact early empty flow。A 通过后按四个 dataset 生成安全同质 projection，质量统计只消费已
  物化表，删除 raw `union_by_name=True` v3 质量路径；C 通过显式 `tables` 消费 B 结果，不重复 materialize。
  flow numeric parse/nonfinite 仅保留证据，balancesheet numeric domain 与 structural/date/dimension 继续
  加入 blocking；保持 source/projection/token identity strings、fixed 12 bucket order、formula/tolerance、
  output/schema 与 I/O 边界不变。
- `publish_tushare_financials.py`：新增逐表 `_validate_quality_domain`，强制 structural/date/dimension
  counters 为 exact zero；cashflow/income 只允许有守恒且有界的 numeric quarantine；balancesheet/fina 要求
  numeric counters 为零、`eligible == raw`、quarantine 为零；所有 domain counters 拒绝 bool。
- 两个现有 unit test 文件：补充 A zero-call、B→C 顺序与 B failure economic zero-call、safe projection
  质量路径、flow numeric coverage-only、balancesheet BLOCKED，以及 publisher flow quarantine、bool、
  non-conservation/domain rejection；保留并继续覆盖 exact bucket/source/token/funnel/cent/BLOCKED/
  `audit_sha256` 三路径与 forgery 场景。测试内容已写入，但按 STATIC_ONLY 未运行。

### 新增测试与通过条件

新增/修订的最小测试覆盖：A 三类早退与 early SHA；B 四表 projection/quality 到 C 的严格顺序；B structural
failure 与 balancesheet numeric failure 的 economic zero-call；safe homogeneous union 与 source-type
provenance；cashflow/income invalid numeric 只降低 flow coverage；publisher flow numeric quarantine 的
exact integer/non-bool/conservation 约束及 balancesheet/fina fail-closed。通过条件是后续授权 validation-only
阶段运行两份定向测试、Ruff/mypy/cold/scope evidence，并由未参与实现的 reviewer 逐项复核 A/B/C 调用图、
安全投影、12 bucket、field-domain、BLOCKED、publisher 三路径和真实 audit 边界；这些条件当前均未执行。

### 未运行事项与结论上限

本次仍未运行 Python、pytest、Ruff、mypy、cold import、DuckDB/Parquet 实际读取、audit/snapshot/PIT、真实
数据、网络、writer、stage、commit、merge 或其他外部状态操作。仅做了 exact5 范围内的受限文本/diff 现场
核对，不将其作为运行时验证或 Gate 证据。当前最高结论继续保持
`IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`；不得据此声称 audit-v4 PASS、snapshot READY、R3 READY、
PIT authorization 或真实数据质量/网络通过。

## STATIC_REWORK3 P1_UNTOKENIZABLE_BLOCKING_AGGREGATION（本次收束追加）

### 现象

`_audit` 原先遍历 `source_identity.untokenizable` 时，每个 pair 都直接追加一条
`<DATASET>_FLOW_SOURCE_TYPE_UNTOKENIZABLE`，固定 `count=1`。因此同一 dataset 的多个文件/字段不能
聚合，重复 pair 也会重复输出，且 blocking issue 的顺序会受 source identity 输入顺序影响。

### 根因

实现把 untokenizable tuple 当成最终 blocking issue，而不是先按 canonical dataset、canonical relative
file 和 required field 形成 distinct pair 集合；缺少 dataset 级聚合和稳定排序边界。

### 应遵循规则

按更新任务书 §9：每个 dataset 最多一条该类 blocking issue；count 等于该 dataset 的 distinct
`(canonical relative_file, required_field)` pair 数；同 pair 去重，不同文件或不同 required field 分别计数；
输出严格按现有 `_DATASETS` canonical 顺序，不能被 identity/input tuple 顺序改变。identity-trusted、invalid
scalar、untokenizable `BLOCKED` 边界及 C 阶段 economic helper zero-call 语义保持不变。

### 最小复现

使用 fake A-closed ledger/complete 与真实形态 source evidence，注入：cashflow 两个文件同一 required
field、income 一个文件两个 required field、重复 cashflow pair，以及按逆序排列的跨 dataset pair。正确
结果是各 dataset 各一条 issue，count 分别按 distinct pair 聚合，issue 顺序保持
`balancesheet → cashflow → fina_indicator → income`；flow 保留 source evidence、`buckets=[]`、
`publication_allowed=false`，`_flow_semantics`、observation、bucket 等 economic spies 均为 zero-call。

### exact 改动

- `src/quant/data/audit_tushare_financials.py`：将 untokenizable pair 先放入按 dataset 分桶的 set，再按
  `_DATASETS` 逐 dataset 生成至多一条 blocking issue；对不属于 canonical dataset 的内部 identity 输入
  fail closed，不修改其他 blocking、identity、投影、token、flow 或 publication 语义。
- `tests/unit/test_audit_tushare_financials.py`：增加两文件同 field、单文件双 field、重复 pair、跨 dataset
  顺序、shuffled input invariance、source evidence 保留、空 buckets、publication false 与 economic
  helper zero-call 的实现路径测试。
- `tests/unit/test_publish_tushare_financials.py`：本轮无额外修改；既有 publisher strict/domain、三路径
  `audit_sha256` 与 forgery 测试继续保留。

### 新增测试与通过条件

新增测试必须在 `_audit` 的 A/B/C 受控路径中观察聚合后的 `blocking_issues`，而不是只检查报告文字；通过
条件是重复 pair 只计一次、两个 distinct 文件计二次、单文件两个字段计二次、跨 dataset 与逆序输入输出
完全一致，并同时满足 untokenizable `BLOCKED`、source evidence 保留和所有 economic helper zero-call。
后续授权 validation-only 阶段仍需运行定向测试并由独立 reviewer 对 source identity 信任边界与真实 audit
输出复核；本轮未运行这些验证。

### 未运行事项与结论上限

遵循 STATIC_ONLY / CPU NONE，本轮未运行 Python、pytest、Ruff、mypy、cold import、DuckDB/Parquet、audit、
snapshot、PIT、真实数据、网络、stage、commit、merge 或其他真实 I/O。最高结论仍为
`IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不表示 audit-v4 PASS、snapshot READY、R3 READY、PIT
authorization 或真实数据质量/网络通过。

## STATIC_REWORK4 P0_SHORT_CIRCUIT_AND_FIELD_DOMAIN（本次收束追加）

### 现象

修订后的 §5.2 已将 normalized projection 冻结为 TWO_STAGE：B1 是安全同构 source relation，B2 是
runner-local immutable `_FlowObservation` sequence。此前实现虽已具备安全投影、A/B/C 门控和 publisher
域校验，但 contract 仍是旧的单层 `columns/union` 形态，B2 返回可变 list 且没有显式锁定四条并行 field
sequence 的长度关系；已有一处测试还使用 `inspect.getsource`，不能作为执行路径证据。publisher 的部分
top-level/dataset counter 只用相等比较，count 为 `1` 时可能让 bool 借由 Python 相等规则混入。

### 根因

contract 常量没有随 §5.2 两阶段重冻同步，观察关系的实现边界停留在“按索引构造”而未把不可变结果和
sequence closure 明确化；publisher 计数校验缺少 `type(x) is int` 与非负边界的统一前置检查。测试重点
此前偏向静态文本存在性，未充分把安全投影、B2 绑定、A/B/C 顺序和 pre-mkdir rejection 连接成行为路径。

### 应遵循规则

按任务书 §3、§5.2、§7、§11、§12：A 未闭合时 source identity、safe projection、selection/chain/
difference 及 canonicalizer 全部 zero-call，并返回 exact early-empty SHA；A 闭合后 B1/B2 必须按 exact
TWO_STAGE contract 执行，B2 的 `source_types/raw_values/projected_values/canonical_values` 逐字段、
逐索引、等长且只由 `_canonicalize_operand` 产生，C 只能消费 B2。publisher 所有 counter 必须 exact
nonnegative int、拒绝 bool，且在 snapshot mkdir 前 fail-closed。flow numeric exclusion 仍只影响
cashflow/income 漏斗，balancesheet/fina numeric 与 v3 structural/date/dimension 规则不放宽。

### 最小复现

- A：`verify_bytes=False`、active lease 非零或四表中任一 ledger 非 `COMPLETE`；对 identity、projection、
  quality、canonicalizer、selection、chain、difference、observation、bucket 安装 fail-on-call spy，必须
  得到 `NOT_EVALUATED`、空 buckets、空 source evidence 与 SHA
  `793cd498f4dbca6b28661417f49606323248da0cdf8e838575df9f7ef4d0d5db`。
- B/B2：为同一 cashflow dataset 提供 BOOLEAN、VARCHAR、DOUBLE 三种 per-file schema，验证各 schema
  group 只生成安全窄投影并统一 `UNION ALL`；再用 income 双字段 row 验证 B2 四条 sequence 的长度、索引
  绑定、`MAX_ANN_DATE_F_ANN_DATE` 和 canonicalizer 调用次数。
- publisher：将 active lease、request count、status count、complete rows 或 quality counter 改为 bool/
  负值，必须在 snapshot 目录创建前拒绝。

### exact 改动

- `src/quant/data/audit_tushare_financials.py`：把 normalized projection contract 更新为任务书 exact
  TWO_STAGE payload（包括 B1 base/field order、per-field columns、schema-group union、单文件读取次数、
  B2 sequence/canonicalizer/date rule）；early-empty 分支直接携带同一 contract，不调用 projection/identity
  helper。`_flow_observations` 现在返回 tuple of frozen `_FlowObservation`，并显式校验四条 parallel
  sequence 与 dataset field order 等长；`_flow_semantics` 的 C 路径只消费已物化 B1 table 形成的 B2，保持
  cashflow-first 的 exact 12 bucket 顺序和既有公式/tolerance/fail-closed 语义。
- `src/quant/data/publish_tushare_financials.py`：除既有 quality domain、flow funnel、identity 和
  audit SHA 严格校验外，补齐 active lease、dataset status/request/complete counter 的 exact int、非负与
  bool rejection，继续在 snapshot mkdir 前拒绝伪造审计。
- `tests/unit/test_audit_tushare_financials.py`：将旧 `inspect.getsource` 断言替换为 A/B/C 行为路径；增加
  exact TWO_STAGE contract、BOOLEAN/VARCHAR/DOUBLE 安全投影生成、B2 tuple/parallel sequence/index
  binding/single canonicalizer、C 不重复 materialize 的测试，并扩充 A、B structural、untokenizable 的
  economic helper zero-call spy。保留 source evidence、filename/schema drift、latest conflict、funnel、
  Decimal/cent、BLOCKED、exact bucket order 与先前 untokenizable distinct-pair 聚合覆盖。
- `tests/unit/test_publish_tushare_financials.py`：增加完整 audit payload 的 pre-mkdir 行为夹具，覆盖
  top-level/dataset counter 的 bool/negative forgery、strict audit validation 与目录未创建；保留 flow
  numeric quarantine、non-conservation、field-domain、bucket/identity/audit SHA forgery 断言。

### 新增测试与通过条件

测试必须在后续授权执行时观察真实调用顺序和输出，而不是读取实现源码：A 所有失败组合均为 helper
zero-call；B 先 identity、按 `_DATASETS` 生成四张安全表、再运行 v3-equivalent quality；B 失败或
untokenizable 时保留真实 source evidence、无 partial buckets 且 C zero-call；B 闭合时 B2 sequence 等长、
逐索引绑定、single canonicalizer，C 不重读 raw/B1；publisher 对所有 counter、12 bucket、identity、
funnel、field-domain 与 audit SHA 伪造均在 mkdir 前拒绝。后续还须由独立上下文运行两份定向测试、Ruff/
mypy/cold/scope evidence，并在授权平台执行真实 audit/publisher；本轮不把静态测试内容当作通过证据。

### exact5 声明更正、未运行事项与结论上限

本报告前段“首条记录、原文件不存在”的初始声明仅描述最初交付文档现场，不能替代本轮返工历史；本轮
明确更正为：完整历史均保留，当前唯一可写集合始终是上述 exact5，未新增或扩展任何路径，也未修改 manager
taskbook、roadmap、review、schema、repository、facade、PIT、shared evaluator、配置或治理 SSOT。

遵循 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`，本轮未运行 Python、pytest、Ruff、mypy、cold import、
DuckDB/Parquet 实际读取、audit、snapshot、PIT、PIT runner、UA-M2-001、真实数据、网络、writer、stage、
commit、merge 或其他真实 I/O。未形成运行时、平台、真实数据质量、snapshot、R3 或 PIT 证据；最高结论仍
只能是 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不得声称 audit-v4 PASS、snapshot READY、R3
READY 或 PIT authorization。

## MANAGER_SCOPE_REWORK4 P0_QUALITY_THREADS_AND_CURRENT_CONFLICT（本次收束追加）

### 现象

