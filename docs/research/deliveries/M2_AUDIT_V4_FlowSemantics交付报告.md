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

经理复核发现，上一轮 `STATIC_REWORK4` 交付文字曾提前描述 A/B/C 与 v3-equivalent quality 调用已闭合，
但 `_audit` 的实际 `_quality_summary` 调用仍遗漏 `threads=threads`；由于该参数是 quality helper 的必需
合同参数，A 闭合后的 B 路径不能按审计线程配置到达质量统计。另一个缺陷是 `_flow_bucket` 在唯一 latest
current conflict 时将 `current` 置为 `None` 后继续走统一返回构造，返回字段仍读取 `current.dataset`，会
产生异常而不是返回 `latest_current_conflicts=1` 的结构化 bucket。

### 根因

质量调用点没有把 `_audit` 已验证的线程参数沿 B 阶段显式传递给 v3-equivalent quality helper；bucket 返回
逻辑错误地把当前观测实例当作 dataset identity 的来源，未使用稳定的 `field -> dataset` 映射。上一轮报告
把静态实现意图写成已闭合结果，未识别这两处仍存在于生产路径的遗漏；该表述在本轮予以更正，不删除历史。

### 应遵循规则

按任务书 §3、§5.2、§12：A 闭合后 `_quality_summary(..., threads=threads)` 必须真实可达并接收原始
`_audit` 线程值，保持 v3 quality 在安全视图上的既有语义；latest current conflict 属于结构化漏斗证据，
必须无 fallback、无 `None` 解引用，并按请求的 flow field 稳定输出 dataset。不得削弱 A/B/C 短路、TWO_STAGE
安全投影、field-domain、exact 12 bucket、publisher 或既有 fail-closed 合同。

### 最小复现

- 使用 A 闭合的 fake plan/ledger/complete，通过 `_audit(..., threads=3, verify_bytes=True)`，在 quality
  spy 中读取 `kwargs["threads"]`；正确值必须对四个 dataset 全部为 `3`，且调用顺序仍在对应 safe
  projection 之后。
- 构造同一 available date、同一 current key、两个不同 canonical token 的 cashflow type1 observations，
  调用 `_flow_bucket(..., field="n_cashflow_act", fiscal_bucket="Q1")`；正确结果为 dataset
  `cashflow`、`latest_current_conflicts=1`、无异常、无 partial fallback。

### exact 改动

- `src/quant/data/audit_tushare_financials.py`：在 `_audit` 的每次 `_quality_summary` 调用中传入既有
  `threads=threads`；在 `_flow_bucket` 入口先由稳定 `_FLOW_FIELDS` field mapping 确定 dataset，质量、
  selection、chain、difference 和最终 bucket identity 均不再从可能为 `None` 的 current 观测推导。
- `tests/unit/test_audit_tushare_financials.py`：将 v3 quality 行为测试扩展为记录四个 dataset 收到的精确
  threads 值；将 latest current conflict 测试改为直接接收完整 bucket，断言 `dataset == "cashflow"`、
  `latest_current_conflicts == 1`，从而覆盖实际 None-conflict 返回路径而非源码文本。
- 未修改 publisher、schema/output、TWO_STAGE、field-domain、12 bucket 顺序、R3/PIT/shared evaluator 或
  其他路径；本轮继续只使用 exact5。

### 新增测试与通过条件

后续授权验证时，A 闭合必须按 projection → quality 顺序调用四次 `_quality_summary`，每次线程值与 `_audit`
输入完全一致；latest current conflict 必须产生可被 publisher strict validator 接受的结构化 bucket，
不抛 `AttributeError`/`UnboundLocalError`，并保留冲突计数、无 fallback。通过条件还包括上一轮 A/B/C、safe
projection、field-domain、untokenizable aggregation、exact order、publisher strict/audit SHA 测试继续
保持原合同结果；本轮未运行这些测试。

### 对上一轮 premature fixed 声明的更正、未运行事项与结论上限

上一节 `STATIC_REWORK4` 的“已闭合”措辞只应理解为当时的计划性静态改动记录，不能作为这两处生产缺陷
已经消失的证据。当前记录明确更正：本轮才补齐 quality threads 传递和 current-conflict 稳定 dataset
返回；仍未进行运行时验证。除 exact5 外没有新增写路径，manager taskbook、roadmap、review 继续只读，
reviewer 未启动。

遵循 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`，本轮未运行 Python、pytest、Ruff、mypy、cold import、
DuckDB/Parquet、audit、snapshot、PIT、真实数据、网络、stage、commit、merge 或其他真实 I/O。最高结论仍
只能是 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不得声称 audit-v4 PASS、snapshot READY、R3 READY、
PIT authorization 或真实数据质量/平台通过。

## STATIC_REWORK5 P0_THREE_STAGE_AND_FIELD_DOMAIN（§12.1 本次收束追加）

### 现象

更新后的 §12.1 冻结了 publisher snapshot 的第三阶段约束、真实 mixed relation 行为证据、required-field
边界、economic key 唯一顺序和 v3 cross-field 守恒。现有实现需要把 publisher 的 raw economic projection
从 `union_by_name=True` 路径收束为按 schema signature 的 B1 安全投影；既有 B1/B2 测试仍有 fake
connection/SQL 字符串形态，不能证明真实 BOOLEAN/VARCHAR/DOUBLE、source filename、行数和顺序不变量。
同时，publisher 对 source evidence 的结构列边界和 `complete_rows == quality.raw_rows` 守恒需要在 mkdir 前
严格拒绝；额外非 required nested/binary 不应被误报为 blocking，而 required nested/binary 必须维持
`BLOCKED`/`NOT_EVALUATED`/C zero-call 边界。此前报告中“已闭合”措辞仍只是历史静态改动记录，本节不把它
升级为运行时通过证据。

### 根因

publisher 原 snapshot 构建直接把 raw relation 作为经济列输入，未复用 audit B1 的 per-file schema-group
投影合同；publisher strict validator 只验证了 required economic field，未同时锁定 v3 structural schema
边界和 dataset complete/raw 行数交叉字段。测试以 fake relation 验证了查询形态，却没有沿真实 Parquet 与
DuckDB B1/B2 路径观察实际列、实际行和实际 filename。经济 key 的 internal tuple 也必须显式与冻结顺序
一致，不能仅凭内部排序“看起来稳定”。

### 应遵循规则

按任务书 §3、§5.2、§7、§9、§11、§12.1：publisher 先按 per-file schema signature 分组，每组调用既有
B1 safe projection，每个 raw file 在 projection 阶段只读一次，再对同构 canonical snapshot projection
执行 `UNION ALL`；禁止 raw economic `union_by_name=True`，禁止 B2 token/classification 进入 clean output，
并保持 `pre audit -> strict validate -> mkdir/projection -> post audit`、既有 snapshot schema/列序/文件集/行数
和 I/O 遍数。真实测试必须使用受控 Parquet 与真实 DuckDB；不得用 SQL 字符串、`inspect.getsource` 或 fake
connection 替代行为证据。

required economic nested/binary/untokenizable 仍是可保留 evidence 的 blocking 边界；非 required extra
nested/binary 只能进入 provenance，不能阻断 B1/flow。唯一 economic key 为
`(symbol, end_date, report_type, comp_type)`，current/type2/previous selection、lookup、stable sort、
类型标注和测试均遵循该顺序。publisher 每个 dataset 必须满足 `complete_rows == quality.raw_rows`，所有
相关计数均须 `type(x) is int`、nonnegative、拒绝 bool，并在 snapshot mkdir 前 fail closed。

### 最小复现

- 将不同 raw 文件的同一 economic field 分别写成 BOOLEAN、VARCHAR、DOUBLE，另写一个同 schema BOOLEAN 文件，
  并打乱文件、列和行顺序。正确 B1 结果必须保留实际 source filename/type/raw/projected、产生三个 schema
  signature group、输出固定窄列序、8 行且两次输入顺序结果相同；BOOLEAN 不能因 common supertype 变成合法
  economic operand。
- 在真实 B1 表上执行 B2 income 双字段 observation：`source_types`、`raw_values`、`projected_values`、
  `canonical_values` 必须等长并按 frozen field index 绑定，所有 token/category/projected 必须来自唯一
  `_canonicalize_operand`。
- 将 audit source evidence 的 request filename 改为不在 frozen raw inventory、重复同一 filename，或删除
  per-file structural column；更新 evidence SHA 也不得绕过 strict validation，均须在 snapshot mkdir 或 public
  object 返回前失败。pre/post source evidence SHA 不一致同样不得产生 public snapshot。
- 将 required `total_assets`/flow field 改为 STRUCT 或 BLOB，audit 必须保留 source evidence、触发
  top-level `BLOCKED`/flow `NOT_EVALUATED`/C zero-call，且 publisher 必须在 snapshot mkdir 前拒绝该
  BLOCKED audit；将 non-required extra field 改为 STRUCT/BLOB，strict audit validation 必须通过而不单独
  阻断；flow invalid numeric 仍只影响 flow funnel，不能与 audit-invalid/BLOCKED 混用。
- 将 dataset `complete_rows` 改成 bool、负值或与 `quality.raw_rows` 不同的非负整数，或将任意 structural/
  dimension/quality counter 改成 bool/负值，均须在 mkdir 前拒绝。审计 bytes 漂移、missing/invalid audit SHA
  和 manifest 非 canonical bytes 均须在 public verify/reuse 返回前拒绝。

### exact 改动

- `src/quant/data/publish_tushare_financials.py`：新增 publisher B1 输入解析和 schema-signature 分组，复用
  audit `_projection_for_schema_group` 生成 canonical snapshot projection；删除 raw economic
  `union_by_name=True` 依赖，保留既有 output projection、partition、schema、文件集、row count 和 pre/post
  audit 流程。strict validation 在 mkdir 前核验实际 complete raw paths、required structural schema、
  `complete_rows == quality.raw_rows`，并继续锁定所有 exact-int/nonnegative/flow-domain/audit identity
  规则。non-required extra nested/binary 只保留 provenance；required economic nested/binary 仍触发 BLOCKED
  audit，并在 snapshot mkdir 前拒绝。
- `src/quant/data/audit_tushare_financials.py`：本轮不改变既有 v3/A-B-C/安全投影/flow 生产语义；继续保持
  current/type2/previous 全链 exact key `(symbol, end_date, report_type, comp_type)`、source/projection/token
  exact identity、cashflow-first 12 bucket 顺序、untokenizable distinct-pair BLOCKED 聚合和 v3 numeric
  blocking 边界。
- `tests/unit/test_audit_tushare_financials.py`：将 B1 mixed-source 和 B2 parallel-sequence 测试改为受控
  真实 Parquet + 真实 DuckDB connection 的行为路径，观察 actual columns/rows/source filename、schema/file
  order invariance、混合类型安全投影、B2 长度/逐索引绑定及 canonicalizer 调用；扩充 publisher 真实生产
  调用链的 filename inventory、duplicate evidence、schema drift 和 pre/post evidence SHA 失败路径；保留
  quality threads、A/B/C zero-call、early-empty SHA、untokenizable 聚合、conflict、funnel、cent、BLOCKED、
  exact bucket order 和现有 snapshot/audit SHA 测试，并增加 audit bytes/missing/invalid/canonical manifest
  drift 反例。
- `tests/unit/test_publish_tushare_financials.py`：更新完整 audit payload 的 structural schema，增加 extra
  nested/binary provenance-only 与 required nested/binary rejection 的 strict 行为测试；增加
  `complete_rows == raw_rows` drift、bool/negative counter 及 pre-mkdir public publisher rejection 路径。
- `docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`：保留首轮 `REVIEW_FAIL`、REWORK1—4、
  P0/P1、MANAGER_SCOPE_REWORK4 全部历史，本节追加现象—根因—规则—最小复现—测试—通过条件并更正任何
  premature fixed 语义；未写 taskbook、roadmap、review 或其他路径。

### 新增测试与通过条件

新增/调整的行为节点包括 `test_two_stage_projection_contract_and_mixed_source_types_are_safe`、
`test_b2_observation_relation_binds_parallel_sequences_and_uses_one_canonicalizer`、
`test_publisher_real_chain_rejects_identity_schema_and_post_audit_drift`、
`test_publisher_required_nested_is_blocked_but_extra_nested_is_provenance_only`，以及现有 ready publish、
counter、manifest/audit SHA 和 flow-domain 节点的扩展。后续授权验证的通过条件是：真实 B1/B2 路径满足上述
实际列/行/filename/顺序/单 canonicalizer 证据；publisher 只生成既有 canonical snapshot schema，所有
identity、schema、row/date/dimension/byte、field-domain、flow funnel 和 SHA drift 反例均在规定边界前
fail closed；同一 audit 的 new/reuse/verify 三路径仍返回同一 `audit_sha256`。

### exact scope、未运行事项与结论上限

本轮唯一写集合仍为 exact5：上述 production2、tests2 和本 delivery；没有新增 shared module、依赖、config、
schema、repository、facade、PIT、R3、shared evaluator 或治理路径，也未修改 manager taskbook、roadmap、review。
严格遵循 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`：未运行 Python、pytest、Ruff、mypy、cold import、
DuckDB/Parquet 实际读取、audit、snapshot、PIT/PIT runner、真实数据、网络、writer、stage、commit、merge 或
其他真实 I/O；本节测试定义不是测试通过证据。仍有待授权的独立 review、validation-only、平台差异和真实
audit 风险。

最高结论仍只能是 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`；不得宣称 audit-v4 PASS、snapshot READY、
R3 READY、PIT authorization 或真实数据质量/网络/平台通过。
## STATIC_REWORK6

### 现象

本轮冻结要求同时闭合六项 §12.2 证据与发布约束：publisher quality evidence 与 snapshot manifest counters 必须逐字段 fail-closed；有效 publisher fixture 必须先通过完整严格校验；经济 key 必须保持 `(symbol, end_date, report_type, comp_type)`；派生边界必须在 public publisher 的 pre-mkdir 路径拒绝；B1/snapshot projection 必须按 schema signature 做 safe homogeneous projection，且行为测试必须使用真实 Parquet、真实 DuckDB production query 的实际结果与 JSON profiling 中的 READ_PARQUET/Total Files Read 证据。

### 根因

此前实现已完成 safe B1、两阶段 B2、来源类型 provenance、v3 quality conservation、strict publisher 与 audit SHA 的主体闭环，但 strict quality 字段/摘要证据、manifest 全计数器、派生 bounds 和可审计的真实 single-read/profile test 证据仍未全部落到当前 exact5。STATIC_REWORK5 交付中的“real path/per-file single read”措辞超出了当时已有测试（尚无 JSON profiling/operator/count 断言）的实际证据范围。

### 应遵循规则

1. A/B/C 短路、v3 原始 quality path、required economic nested/binary BLOCKED 边界、non-required extra nested/binary provenance-only 边界、单一 canonicalizer、来源/投影/token identity、cashflow-first 12 bucket order 与既有 schema/output/I/O 语义均保持不变。
2. quality key set 必须精确；column-set digest 必须为 canonical lowercase hex64、无重复且按 canonical order，`column_set_count` 必须与列表长度相等；`required_numeric_union_types` 必须精确匹配字段顺序及 provenance 类型族。
3. manifest 的 request/dataset/file rows、size、SHA 及 audit/request/raw closure 必须 exact-int/non-negative/一致；bool 不得作为 int；每个实际 Parquet 文件的 rows/bytes 必须与 manifest 一致。
4. 生产 snapshot query 不得 raw economic `union_by_name=True`；每个 schema group 只执行一个 homogeneous safe projection，inventory 必须是 disjoint cover；B2 token/classification 不得污染 clean output。
5. 真实行为证据必须由实际 Parquet 与真实 DuckDB connection 执行 production query 产生，读取 JSON EXPLAIN/profiling 的 READ_PARQUET（兼容 DuckDB 的 PARQUET_SCAN/Function 表示）与 `Total Files Read`；不得用 SQL 字符串、fake connection、inspect/source text、OS handle 或物理 row order 替代。

### 最小复现

- 将任一 quality counter、digest list/hex/order/duplicate、required type union、manifest request/dataset/file counter 或 file rows/size 改为 bool、负数、缺失、别名、顺序漂移或 closure drift；strict audit/verifier/public publisher 均须在 snapshot mkdir 或 public object return 前拒绝。
- 将 flow bucket 的 `distinct_symbols` 大于 `current_type1_candidates`、`fiscal_years` 大于 `comparable_observations`，或 `comparable_observations == 0` 且 `fiscal_years != 0`；publisher strict recomputation 须拒绝。
- 使用真实 cashflow Parquet 的 BOOLEAN、VARCHAR、DOUBLE required field，打乱 file list/schema-group order，并反转实际 Parquet row order；audit B1 与 publisher B1 projection 必须返回相同 canonical schema/rows/evidence，JSON profiling 须显示每个 schema group 一个 READ_PARQUET/PARQUET_SCAN 及 `Total Files Read`，总数覆盖 inventory 且不重复。
- 使用真实 required `STRUCT`/`BLOB` economic column；audit 保留 source evidence、返回 BLOCKED/flow NOT_EVALUATED、C economic helpers zero-call，public publisher 在 pre-mkdir 拒绝。使用 non-required extra nested/binary 时只保留 provenance，不得阻断 safe projection/flow。

### 本轮 exact5 改动

- `publish_tushare_financials.py` 增加 strict quality evidence 校验：精确 quality key set、column-set SHA 列表长度/hex/去重/canonical order、由 source evidence 重算的 column-set digest，以及按 `_ECONOMIC_COLUMNS` 顺序和 canonical logical type 校验 `required_numeric_union_types`。
- `publish_tushare_financials.py` 收紧 `_verify_snapshot`：manifest request_count/request_counts/dataset_rows 与每个 file entry 的 rows/size_bytes 均 exact int、非负并拒绝 bool；audit request/raw/plan closure、dataset totals 与真实 Parquet height/byte length 交叉一致。
- `publish_tushare_financials.py` 增加 publisher flow 派生 bounds；严格保留 exact economic key 与现有 v3 row/date/dimension/byte/flow conservation。snapshot B1 继续使用按 schema signature 的显式 safe projection/UNION ALL，不回退到 raw economic union。
- `audit_tushare_financials.py` 提取 `_safe_projection_query` 供生产 `_materialize_safe_projection` 使用，使真实行为测试能够执行同一 production B1 query 并读取 profiling；未改变 public schema、output、manifest 或 I/O 遍数。
- `tests/unit/test_audit_tushare_financials.py` 增加真实 mixed BOOLEAN/VARCHAR/DOUBLE Parquet + DuckDB B1 actual result、schema-group/file/row-order invariance、inventory group coverage、audit B1 与 publisher B1 profiling 的 READ_PARQUET/PARQUET_SCAN/Total Files Read 断言；增加真实 required STRUCT/BLOB BLOCKED/C zero-call、extra nested provenance-only、public pre-mkdir invalid-boundary、exact economic key 行为覆盖。
- `tests/unit/test_publish_tushare_financials.py` 增加严格 quality evidence mutation、真实 Parquet snapshot manifest counter/file metadata mutation、有效 fixture 先闭合与 public verifier 拒绝路径；保留 required nested BLOCKED 与 extra nested provenance-only 反例。

### 新增测试与通过条件

新增测试均留在现有 tests2，覆盖 §12.2 六项以及历史 §12 行为：真实 B1/B2 path、safe homogeneous union、single canonicalizer/parallel sequence binding、exact source/projection/token identity、short-circuit zero-call、v3 original quality path、12 bucket order、untokenizable distinct-pair aggregation、field-domain/quarantine、latest-current conflict、BLOCKED/provenance boundary、strict counters/conservation、audit SHA 三路径与 forgery rejection。当前 STATIC_ONLY 下未运行这些测试；未来允许执行时，必须首先证明依赖实际提供上述 JSON profiling operator/count，并逐项获得 actual result、inventory disjoint-cover、schema/row/file-set/semantic-hash 一致性，所有 production tests 与定向验证通过后方可更新状态。

### 未运行边界与结论

本轮没有运行 Python、DuckDB、Parquet、pytest、Ruff、mypy、cold import、audit、snapshot、PIT、network、data I/O、stage 或 commit；因此没有运行时、真实数据、网络、Linux Gate、snapshot READY、R3 READY、PIT authorization 或 Gate 通过证据。若目标依赖在实际环境不能稳定产生 JSON profiling 的 READ_PARQUET/Total Files Read operator/count，必须停止并记录 `STOP / EVIDENCE_CONTRACT_UNIMPLEMENTABLE`，不得退化为字符串/fake/inspect/OS 证据。

最高结论仍为：`IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。
## STATIC_REWORK6_MANAGER_RETURN

### 现象

`_verify_snapshot` 的 `audit.json` 分支中，`_validate_audit(audit)` 曾错误退到 `if selector == "audit.json":` 外层，而其后的 source identity、plan/request closure 校验仍保持 audit 分支缩进，导致非 audit selector 可能落入 audit 校验路径并破坏分支结构。

### 根因

STATIC_REWORK6 的结构性编辑造成单行缩进漂移：audit payload 校验与紧随的 identity/request-closure/`continue` 未作为同一个 audit-only block 保持闭合。

### 应遵循规则

只有 `selector == "audit.json"` 时，才允许解析并调用 `_validate_audit(audit)`，随后校验 source identity、plan/inventory/request closure，并以该分支的 `continue` 结束；非 audit selector 必须直接进入 partition Parquet 校验，不能调用 `_validate_audit(None)`、读取 audit closure 或误落入 audit 分支。除该缩进恢复外，不改变任何合同、语义、schema、output 或 I/O 边界。

### 最小复现

遍历 manifest files 时先遇到任一非 `audit.json` selector；在修复前，dedented `_validate_audit(audit)` 与 audit closure block 的缩进不一致，非 audit 路径不再满足 audit-only 控制流，并可能在静态解析/运行时产生错误路径。

### 本轮改动与通过条件

仅将 `_validate_audit(audit)` 恢复到 `if selector == "audit.json":` 内，保留其后的 source identity/request closure 与 `continue`；未改其他 exact5 文件。通过条件是 audit entry 才执行 audit validation/closure，所有非 audit entries 仅执行真实 partition validation，且既有 v3 fail-closed、manifest、snapshot 与 I/O 遍数语义保持不变。

### 未运行边界与结论

本轮未运行 Python、pytest、Ruff、mypy、cold import、DuckDB、Parquet、检查、真实 I/O、data/audit/snapshot/PIT、network、stage 或 commit。故不声称 audit-v4 PASS、snapshot READY、R3 READY、PIT authorization 或真实数据质量通过；最高结论仍为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。
## STATIC_REWORK7

本轮仅同步现有 tests2 与本 delivery；production2、taskbook、roadmap、review 均未修改，也未夹带 reviewer 登记的 `Q1 latest_previous_conflicts` P2 债。起点是 Validation1 STOP：evidence root 为 `artifacts/agent_runs/m2-audit-v4-validation1-20260828T151956Z`，summary SHA256 为 `0985a9444bd5a594bd946d63c30e2975800879d960890012f07639c087a90544`，pytest stdout SHA256 为 `cc9a2be97f2964806319d05346984cb2d6f2723898fb7e2c5fd57e790e5e319e`；identity PASS，collect-only 54 collected，两个 unit 文件 6 failed / 48 passed / 14.09s，Ruff/mypy/cold/scope closure UNRUN，资源已释放且 Python/0xF00 为 0，fresh basetemp/no-clobber evidence 保留。以下逐项闭合 §12.3 六项测试合同。

### 1. parameter-window A/B 双分支

- 现象：future-announcement income fixture 的旧测试使用默认 `verify_bytes=False`，却期待 `BLOCKED`；验证反馈实际 top status 为 `READY`。
- 根因：`verify_bytes is True` 是 A prerequisite；默认 false 必须在 A 短路，不能进入 B 的 request-window quality。
- 应遵循规则：同一 fixture 同时覆盖两条分支。默认 false 锁定 flow `NOT_EVALUATED`、`buckets=[]`、source evidence `[]`、`publication_allowed=false` 与全部 flow identity/projection/economic helper zero-call；显式 true 才允许 B，必须 top `BLOCKED`、`request_window_mismatches==1` 和 `INCOME_REQUEST_WINDOW_MISMATCH`。
- 最小复现：income `ann_date=20250101`、`f_ann_date=20250102`，其余 request window 保持受控 fixture。
- 新增测试：扩展 `test_parameter_window_mismatch_blocks_instead_of_silently_quarantining`，加入 helper spies、默认 false 短路断言及显式 true BLOCKED 断言。
- 通过条件：两次调用都经过原 production path；false 分支所有 helper 计数为零，true 分支只进入 identity/safe projection/v3 quality，B 日期失败后 economic helpers 仍为零。

### 2. physical-row-drift A/B 双分支

- 现象：income Parquet 从 1 row 改为重复 2 rows 后，旧测试默认 false 期待 `BLOCKED`，但实际为 `READY`。
- 根因：physical `row_count_mismatch` 属于 B safe relation；A 未以 `verify_bytes=True` 闭合时不得运行 B。
- 应遵循规则：保留受控 Parquet duplicate、同步 bytes/checksum/size、保持 ledger/metadata rows=1；默认 false 必须与项 1 相同短路，显式 true 才必须 `BLOCKED` 且 `row_count_mismatch==1`，不得修改 row ledger 使重复行合法化。
- 最小复现：既有 `test_per_request_physical_row_drift_is_detected` fixture 与 duplicate Parquet mutation。
- 新增测试：将其改为 `test_per_request_physical_row_drift_has_verified_and_short_circuit_branches`，加入双分支 helper spies 与 B physical counter 断言。
- 通过条件：false 分支 source evidence/桶/发布许可/zero-call 闭合；true 分支进入 B 并报告一条 row-count drift，未污染 v3 原始 quality 语义。

### 3. mixed safe projection 的 authoritative statement exact10 schema

- 现象：真实 DuckDB production query 的实际 statement projection 从 index 2 起包含 `f_ann_date`，并保留 `report_type`、`comp_type`、`update_flag`；旧测试错误期待六列。
- 根因：测试 fixture/assertion 使用旧的缩减 snapshot 形状，production authoritative `_projection_sql` 与 safe B1 schema 没有回归。
- 应遵循规则：cashflow publisher projection 的 actual columns 必须逐字为 `symbol,ann_date,f_ann_date,available_date,end_date,report_type,comp_type,update_flag,n_cashflow_act,source`；继续以真实 BOOLEAN/VARCHAR/DOUBLE Parquet、真实 DuckDB production query、JSON profile `READ_PARQUET/PARQUET_SCAN`/`Total Files Read` 和 file/group/row order invariance 验证，不能删身份列迁就旧断言。
- 最小复现：既有 mixed-source node 的 first/second publisher projection 与 manifest verifier baseline。
- 新增测试：修正 mixed B1 publisher actual-column assertion为 exact10；同步 valid snapshot Parquet fixture 写入 statement `f_ann_date`，使 baseline schema 与生产 canonical output 一致。
- 通过条件：first/second actual result 的 schema、canonical rows、scan group/file totals、source evidence/SHA 及 file list/group/row order invariance 全部一致。

### 4. source-evidence order fixture 的 exact required fields

- 现象：order-invariance test 的 fake income `_SourceSchema` 只提供 `n_income`，production 构造 required evidence 时读取 `n_income_attr_p` 触发 `KeyError`。
- 根因：fake fixture 未满足 REWORK6 exact required economic field closure；这是测试输入缺口，不是 production 应以 `.get()` 或 catch `KeyError` 放宽的理由。
- 应遵循规则：cashflow fake schema/economic_types 精确包含 `n_cashflow_act`；income 精确同时包含 `n_income` 与 `n_income_attr_p`。正反 file order 的 evidence/SHA 必须相同；缺任一 required field 的路径必须稳定拒绝。
- 最小复现：既有 income+cashflow stub items 调用 `_flow_source_identity`，再让 income fake schema 删除 `n_income_attr_p`。
- 新增测试：修正 `test_numeric_tokens_and_source_evidence_file_order_are_invariant` 的 fake schema 为完整 required fields，并增加 `missing_required_schema` 的 fail-closed `KeyError` 反例。
- 通过条件：完整 fake fixture 正反顺序 identity/SHA 相同；缺字段不被静默接受、不被 catch 成可发布 evidence。

### 5. public verifier import

- 现象：合法 snapshot manifest baseline 首次调用 public `verify_tushare_financial_snapshot` 即因测试文件遗漏显式 import 产生 `NameError`，尚未触及 production verifier。
- 根因：publish test import list 未同步既有 public symbol。
- 应遵循规则：只从既有 publisher public API 显式导入 verifier，先验证合法 baseline，再逐项验证 request/dataset/file counters、rows/size/actual bytes drift 在 public object return 前拒绝，并恢复 baseline 再次通过；不改 production。
- 最小复现：既有 `_write_valid_snapshot_for_manifest_tests` baseline 与 `test_public_snapshot_verifier_rejects_manifest_counter_and_file_metadata_drift`。
- 新增测试：补充 `verify_tushare_financial_snapshot` import；保留 baseline→mutation→restore baseline 的 public verifier 测试路径。
- 通过条件：测试不再因 import 缺失失败，合法 baseline 首次和恢复后均能调用既有 public verifier，各 manifest drift 仍 fail-closed。

### 6. required/extra nested fixture 的全部派生 identity 同步

- 现象：extra non-required `STRUCT` 加入 source schema 后旧 fixture 只重算 flow source evidence SHA；strict `_validate_quality_evidence` 按 schema 重算 column-set digest，正确拒绝 stale quality。required `STRUCT`/`BLOB` candidate 也未同步 required union/column digest，无法把拒绝原因归因到 exact required untokenizable boundary。
- 根因：fixture mutation 没有同步 source schema 派生的 `column_set_count/column_set_sha256s` 与 `required_numeric_union_types`。
- 应遵循规则：extra nested 只保留 provenance，必须同步该 dataset 的 column-set digest 后由 strict `_validate_audit(extra)` 通过，required union 不变；required economic nested/binary 必须同步 schema、`required_economic_types`、flow evidence SHA、column digest 与 required union，然后由 exact required untokenizable 校验拒绝，并在 public publisher snapshot mkdir 前停止。不得以 stale digest 的任意 `ValueError` 冒充 required nested Gate，也不得放宽 strict validator。
- 最小复现：既有 balancesheet source evidence 首项追加 `extra_nested`，以及将 `total_assets` 改为 `STRUCT`/`BLOB` 的 blocked candidates。
- 新增测试：同步 publish nested test 的 extra column-set digest；同步 required candidates 的 column-set digest 与 `required_numeric_union_types["total_assets"]`，再断言 `_validate_audit` 拒绝原因、public publisher pre-mkdir 拒绝与 clean 目录不存在。
- 通过条件：extra nested provenance-only 正向 audit strict validation 通过；required STRUCT/BLOB 在 evidence 保留的前提下由 required boundary 拒绝，未以 stale derived field 造成错误 Gate 证据。

### 本轮未运行边界与结论

本轮仍为 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`，未运行 Python、DuckDB/Parquet、pytest、Ruff、mypy、cold、network、audit、snapshot、R3、PIT、data I/O、stage 或 commit；Validation1 的有效阶段、SHA、UNRUN 项、basetemp 与资源释放边界按上文保留。未声称任何 audit-v4 PASS、snapshot READY、R3 READY、PIT authorization、真实数据质量或网络通过。最高结论保持 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。
## STATIC_REWORK8 — P0 exact4 E731 mechanical closure

### 现象

POSTFIX Validation3 已完成 Parser/identity/collect-only 与两份单元测试行为阶段（54 collected、54 passed），但 exact4 在 Ruff 首个可定位缺陷处停止：`tests/unit/test_audit_tushare_financials.py:1683` 使用了局部 lambda 赋值并触发 E731。该轮因此不能把样式闭合误报为验证完成；V3 mypy、cold import 与 scope 检查仍为 UNRUN。

### 根因

这是审计测试中一个局部、单行 lambda 赋值的 Ruff 风格违规，不是生产 flow semantics、publisher 或数值断言变更。机械修正前，局部 callable 的类型未显式表达。

### 应遵循规则

按 taskbook §12.4，仅将该行在原位置逐字替换为带返回类型的局部函数：

```python
def finite(value: float) -> financial_audit._CanonicalOperand:
    return financial_audit._CanonicalOperand("x", "finite", value)
```

保持原返回对象、调用点、数值断言、位置和行为完全不变；不引入 `Any`、`cast` 或 `type: ignore`，不移动或泛化 helper，不夹带 P2，不修改 production2 或 publisher test。

### 最小复现

在 exact4 Ruff 阶段检查该审计测试文件时，原局部 `finite = lambda ...` 赋值在第 1683 行触发 E731，导致后续 exact4、V3 mypy/cold/scope 阶段未执行。此次仅按冻结文本进行静态机械替换，未执行该命令。

### 本轮改动与验证边界

本轮仅写入 exact5 中允许的审计测试文件与本交付报告；未改生产文件、publisher 测试、taskbook、roadmap 或 review。未运行 Python、DuckDB/Parquet、pytest、Ruff、mypy、cold import、audit、snapshot、R3/PIT、网络、data I/O、stage 或 commit。POSTFIX Validation3 的历史行为证据仅作为历史记录保留，不能替代本轮执行；V3 mypy/cold/scope 继续明确为 UNRUN。

本轮没有新增行为测试；已有行为测试的调用点和断言未变。未来通过条件是 exact4 Ruff 不再报告该 E731，随后按任务书独立完成仍未运行的 mypy、cold、scope 及后续验证，并保持既有行为与合同边界不变。

### 结论

IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT

## STATIC_REWORK10 — P0 covariant read-only type closure

本轮严格按 taskbook §12.6 仅修改 `src/quant/data/audit_tushare_financials.py` 与本 delivery；publisher production、tests2、taskbook、roadmap、review 均未改，未夹带 P2，未自行启动 Validation6。

### 现象

Validation5 的 Parser、identity 与冻结 focused6 均已通过，但 mypy production2 在 audit numeric-pair assignment 首次失败：Q1 分支形成的 `list[tuple[_FlowObservation, _FlowObservation, None]]` 与 Q2/Q3/FY 分支的 `previous_pairs` 不能赋给既有 `list[tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]]`。其余 Validation5 后续阶段未据此宣称通过；V5 Ruff、cold、exact8 scope 均为 UNRUN，合同内 `resource_release.log` 为 MISSING。

### 根因

REWORK9 的联合元素类型表达已准确描述运行时数据，但 `list` 是 invariant；可变 list 的具体第三项 tuple 类型不能因包含 `None` 的联合目标而协变赋值。问题只在读遍历容器的静态类型表达，不是 Q1/Q2/Q3/FY 的运行时链语义。

### 应遵循规则

使用现有 `Sequence` import，将注解逐字改为：

```python
numeric_pairs: Sequence[tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]]
```

Q1 comprehension、else `previous_pairs`、后续 `for`、`None` 位置、previous-chain 顺序、operand 插入、mismatch 计数及错误顺序必须保持原样；禁止新增/删除 import、复制构造、extend、cast、Any、type-ignore、容器转换、逻辑重排或 P2。

### 最小复现

在 Validation5 mypy production2 中，audit line 1892 的 `numeric_pairs = previous_pairs` 报 list invariant assignment；同一函数的 Q1 分支先写入第三项为 `None` 的 comprehension。该命令本轮未重跑。

### 修正

仅将 REWORK9 的 mutable `list[...]` 注解机械替换为上述 covariant read-only `Sequence[...]` 单行注解，保留既有 import、两条赋值分支与所有后续代码逐字不变。tests2 未修改。

### 测试与未来通过条件

Validation5 focused6 的历史 PASS 继续保留，不能替代本轮验证；本轮未运行 Python、pytest、Ruff、mypy、cold、DuckDB、Parquet、真实 data/audit/snapshot、network、stage 或 commit。未来按 taskbook 先执行 Validation6 规定的 Parser/identity、两个直接 flow focused nodes 与 mypy，再按冻结顺序处理 Ruff、cold、exact8 scope、cached0、diff-check、evidence/temp 与资源证据；通过条件是 mypy assignment 消失且 Q1 的 `None`、Q2/Q3/FY 的 previous observation、对象顺序与计数行为保持不变。

V5 的 Ruff/cold/scope 仍明确为 `UNRUN`；合同要求的 `resource_release.log` 仍为 `MISSING`，不得以外层退出旁证伪补或冒充该 artifact。最高结论保持 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不声称 audit-v4 PASS、snapshot READY、R3 READY、PIT authorization、真实数据质量或网络通过。

### 12.7 Validation6–9 组合证据与最终 evidence-review 边界

Validation6 使用新的 no-clobber evidence/temp roots 执行，evidence root 为
`artifacts/agent_runs/m2-audit-v4-postfix-validation6-20260828T164359Z`，temp root 为
`artifacts/validation_tmp/m2-audit-v4-postfix-validation6-20260828T164359Z`。可信产品阶段全部 PASS：Parser
errors=0、identity PASS、冻结 focused2 PASS、mypy production2 PASS、Ruff exact4 PASS、cold PASS。关键 stdout
SHA256 分别为：focused2
`3ed6fd346dfc27ee652c412ba643af3d0da21f1402843af29da686c1fa3151bf`、mypy
`0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2`、Ruff
`82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`、cold
`f2fa5abb3a94f7638617a512fe5f805721df611e0918049ef9780a23a332da3b`。runner SHA256 为
`f289fc52c44c43cd6faf290a729de50621261cf6758ad5f8b469b8e5b9d7c493`，summary SHA256 为
`ef8b723f5fdf86f83d5c4b08b75a4f1d5b37417e0d52c893c944bde73521320c`。唯一 STOP 位于 exact8 scope
carrier：合法 NUL 协议终止符形成空尾 record，PowerShell 5.1 的 Split 调用未可靠移除空项，runner 在空项上执行
`Substring(3)` 失败。因此 Validation6 只能记为 `PRODUCT_GREEN / SCOPE_CARRIER_STOP`，不得写成全绿。

Validation6 resource finalization 已按 §12.6 分项持久化并闭合：terminal SHA256
`722594f855bb9a887c3a9c5416e98a87bbfef79d253ae5d93d400abae4cc1003`、self-restored SHA256
`b454c9068b3b6c7fd4106f99da44dbb95a60ece0e816b7b8f9d2c8f8ef2d6037`、known-children SHA256
`edc19edf4c9d775707e2981842dba49711c3dc08f8af5da46b3dd3914d97d100`、python-presence SHA256
`d950b4e86f37941c3520e2f6072e72fac7dd04015e53cf27644030cfef1c1216`、finalization SHA256
`e8a04bf0a88930c2a0d5d2e95cf84b0ed16c357615f11c3e4ca7e2571aec9800`。owner 恢复
Normal/0xFFF，known children started=5/exited=5，Python count=0，finalization errors=0；runner 外 fresh 旁证为
Python=0、exact0xF00=0。该证据不恢复 Validation5 缺失的 resource artifact，也不改变其历史 STOP。

Validation7 evidence root 为
`artifacts/agent_runs/m2-audit-v4-scope-validation7-20260828T164850Z`，summary SHA256 为
`4d150ae26e6b73ff9d36a7fd38ebd638c57bc5d9b8f0509ad40b779512566a69`。它在 scope 前因经理请求额外加入的
“worktree 根级 cache 必须不存在”条件而 STOP；taskbook §12.6 从未冻结该 absent 条件。`.pytest_cache`、
`.ruff_cache`、`.mypy_cache` 均为 ignored validation carrier residue，其中 Ruff/mypy cache 的时间落在 Validation6
窗口。故 Validation7 诚实记为 `PREFLIGHT_STOP / SCOPE_NOT_EVALUATED`，不是产品或 taskbook 合同失败，也不得
删除 cache 后改写历史。

Validation8 evidence root 为
`artifacts/agent_runs/m2-audit-v4-scope-validation8-20260828T165056Z`。baseline cache pre-manifest PASS：
exact 27 files，manifest bytes=2694，manifest SHA256/aggregate digest 均为
`a1fa6231c070d99c22851c1e8828a6d3e63a50c2e86a0899f23e9990d86a59ba`；三目录均 exists+ignored、无
reparse、无额外 root cache。native status 本身 exit0、stderr0、raw stdout 464 bytes，SHA256 为
`c6612035a17758c9081e7facc4d9773af535187dccee39150314d91375b6fb3a`。但 helper 的
`CopyToAsync(...).GetAwaiter().GetResult()` 非路径返回对象污染 PowerShell pipeline，使调用方的 status path
成为多值对象，故 raw NUL 解析及后续 scope UNRUN。runner SHA256
`9f1b06a14fd65e4f9483f2ca06b7d632e49163b93a7296b71f8aa066f8a186a7`，summary SHA256
`440706fcafac64f0c15bf525f4e2cef72e1833de80905095664257dc8d849c0d`。Validation8 只记为
`CARRIER_STOP / SCOPE_NOT_EVALUATED`。

Validation9 使用固定 caller 路径、helper 全部非合同返回显式抑制及显式过滤 NUL 空尾 record，完成无 Python、
无 0xF00 的 baseline-aware scope-only 闭包。evidence root 为
`artifacts/agent_runs/m2-audit-v4-scope-validation9-20260828T165408Z`。cache pre/post 均为 exact 27 files、
2694 bytes、SHA256/aggregate
`a1fa6231c070d99c22851c1e8828a6d3e63a50c2e86a0899f23e9990d86a59ba`，证明 V9 未写 cache。raw NUL
status 464 bytes、SHA256
`c6612035a17758c9081e7facc4d9773af535187dccee39150314d91375b6fb3a`，过滤唯一空尾后逐 record
Length/XY+space 均闭合，decoded exact8 paths SHA256
`c84195caefbeb1da2e69f6fb04411d8da1b22ebbb97844939b14b474850514cf`；exact8 count/set、cached raw
bytes=0、`git diff --check` exit0、V1–V9 evidence roots与V1–V6 retained temp roots exists+ignored 均 PASS。
diff-check stderr 仅既有 LF→CRLF warning，SHA256
`e38e6f6335acd611aaaec8d8c5be4377785b8855f715218ebf1b176dadf0794b`。runner SHA256
`b025ecb61fccbd75e6faafb10319f207883a471906cc062adfab88d807375a2a`，summary SHA256
`afabb0b4c30113db062c0462ea51004ae2908583d39412fdc4775e5d694a5c9c`，terminal PASS SHA256
`c26de83abdc9496cd1301470918ec39ecca1cf389ef0ae1c6504da1800d1c431`，process SHA256
`8393b61af401a68f4b1beb9ba4b3ea40fdab36213c224b8f9af1af1e605b0031`。

权威组合结论仅为：Validation6 产品链绿色 + Validation9 scope 闭包 PASS，形成 Windows development
validation 证据；Validation7/8 的 carrier STOP 历史永久保留。三个根级 tool cache 及全部 V1–V9 evidence/temp
在 final evidence review 与 SAFE_COMMIT 裁定前不得删除。该组合仍不代表真实 audit-v4、snapshot READY、R3
READY、PIT 授权、Linux/WSL Gate 或真实财务数据质量通过。实现者只可在既有 delivery 追加上述证据；同一原
reviewer 随后只写既有 review 做最终 evidence review。二者不得修改 production/tests/taskbook/roadmap、不得运行
Python/检查、不得 stage/commit；最终 review PASS 后才可申请 SAFE_COMMIT。

## STATIC_REWORK9 — P0 production type-only closure

本轮严格按 taskbook §12.5 仅修改两个 production 文件与本 delivery；tests2、taskbook、roadmap、review 未改，未夹带 P2。Validation5 未自行启动。

### 1. audit numeric-pair 联合容器注解

- 现象：`_audit` 的 Q1 comprehension 将 `numeric_pairs` 推断为第三项固定为 `None` 的列表，而互斥的 Q2/Q3/FY 分支赋入含 `_FlowObservation` 的 `previous_pairs`，触发 mypy 的 invariant list assignment 报错。
- 根因：互斥运行分支共享容器缺少第三元素联合类型注解；原有 previous-chain 顺序、`None` 语义、operand 插入和计数逻辑本身未改变。
- 应遵循规则：只在两个互斥分支之前增加 `list[tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]]` 显式注解；保留 Q1 comprehension 与 else `previous_pairs` 原样，禁止 cast、Any、type-ignore、复制转换或逻辑重排。
- 最小复现：对 audit production2 运行 mypy 时，`numeric_pairs` 的 Q1 推断类型与 else 的 `previous_pairs` 类型在 assignment 处不兼容。
- 修正：在 `numeric_pairs` 首次赋值前加入 taskbook 要求的显式联合容器注解；未改变任何运行时表达式、顺序或计数。
- 测试：未修改 tests2；既有 focused selection/bucket-order/identity 节点保留，待后续 Validation5 按冻结顺序执行。
- 未来通过条件：该 assignment 错误消失，Q1 的 `None`、Q2/Q3/FY 的 previous observation、operand 插入及 mismatch 计数保持原行为，并由后续 focused tests 与 mypy 证实。

### 2. publisher source-evidence identifiers 先验证后收窄

- 现象：`_snapshot_b1_inputs` 从 evidence `entry.get()` 读取 dataset、request id、relative file 时复用较早循环中的变量名，mypy 无法将赋值点收窄为 `str`，产生三项类型错误。
- 根因：原始 `Any | None` 值在现有联合 guard 之前写入了已被推断为字符串的名称；guard 不能反向收窄先前的赋值。
- 应遵循规则：三项先写入新的 raw locals；保留原 `type(...) is str`、dataset membership、hex64、canonical-relative 等式及错误顺序；guard 通过后才把已收窄的字符串绑定到后续使用的 names。禁止 cast、Any、type-ignore、truthiness、强转或放宽 identity。
- 最小复现：mypy publisher production2 在 evidence loop 的三项 `entry.get()` assignment 处报告类型错误；unknown dataset/request/relative、非法 hex64、canonical-relative drift 的 fail-closed 顺序必须不变。
- 修正：使用 `raw_dataset`、`raw_request_id`、`raw_relative` 完成读取和原 guard，guard 后再绑定 `dataset`、`request_id`、`relative`；其余 schema/evidence/group 逻辑未改。
- 测试：未修改 tests2；既有 filename inventory、duplicate、schema drift 与 source-evidence canonical-order focused coverage 保留，待后续 Validation5 执行。
- 未来通过条件：三项类型错误消失，合法 evidence 仍按原 canonical 顺序进入 projection，unknown filename、not-in-inventory、duplicate/schema drift 仍在 projection 前 fail closed。

### 3. publisher path 一次消费

- 现象：`path_by_relative.pop(relative, None)` 以 `None` 作为缺失默认值，但 mapping 的值域是 `Path`，触发 mypy overload/type mismatch。
- 根因：用 optional default 表达缺失检查，混淆了 mapping 已声明的非 Optional `Path` 值域。
- 应遵循规则：先用 `relative not in path_by_relative` 稳定拒绝，再无 default 执行 `path_by_relative.pop(relative)`；保持一次消费、duplicate/missing fail-closed、输入顺序及最终空集守恒。禁止 Optional mapping、cast 或复制 Path。
- 最小复现：mypy publisher production2 在带 `None` default 的 `pop` 处报告 overload 错误；相同 relative 的第二次 evidence 与缺失 relative 必须仍按原错误路径拒绝。
- 修正：将缺失 guard 前置并把 `pop` 改为无 default 的一次消费；未改变 path mapping 构造、evidence 顺序或后续 projection。
- 测试：未修改 tests2；既有 duplicate/missing evidence 反例保留，待后续 focused tests 与 mypy 执行。
- 未来通过条件：pop 类型闭合；存在项只消费一次，缺失/重复仍 fail closed，全部 evidence 消费后的空集守恒不变。

### 4. manifest request_count stable local

- 现象：`_verify_snapshot` 对 manifest `request_count` 进行了两次独立 `.get()`；第一次 exact-int 检查不能让 mypy 将第二次调用收窄，产生比较类型错误。
- 根因：方法调用返回值不是可关联的稳定 local，静态类型分析无法沿两次调用传递收窄结果。
- 应遵循规则：只读取一次 stable local，并严格保留 `type(request_count) is not int or request_count < 0`；拒绝 bool、负数、canonical drift 与 request/audit closure drift 的 fail-closed 语义不变。禁止 `int(...)`、truthiness、弱化检查或重排错误顺序。
- 最小复现：mypy publisher production2 在 `manifest.get("request_count") < 0` 的第二次调用处报告 `Any | None` 比较等价错误。
- 修正：增加一次条件读取的 `request_count` stable local，并以该 local 完成原 exact-int/nonnegative guard；manifest closure 比较、public object 返回前拒绝及其他 counters 未改。
- 测试：未修改 tests2；既有 public snapshot verifier 的合法 baseline、bool/negative/request closure drift 与 pre-mkdir fail-closed focused coverage 保留，待后续 Validation5 执行。
- 未来通过条件：comparison 类型闭合；合法 baseline 仍通过，bool/negative/request closure drift 仍在 public object 返回前拒绝，并由 focused nodes 与 mypy 证实。

### 本轮未运行边界与最高结论

本轮严格保持 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`：未运行 Python、pytest、Ruff、mypy、cold、DuckDB、真实 data/audit/snapshot、network、stage 或 commit；未自行启动 Validation5。此前 Validation4 的 mypy 首失败、Validation3 的 tests/Ruff 历史证据继续保留，不能被本轮静态修正冒充绿色验证。未声称 audit-v4 PASS、snapshot READY、R3 READY、PIT authorization、真实数据质量或网络通过。最高结论保持 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。
