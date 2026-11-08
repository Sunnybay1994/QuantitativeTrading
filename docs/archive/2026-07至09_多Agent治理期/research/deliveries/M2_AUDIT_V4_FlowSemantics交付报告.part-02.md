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

