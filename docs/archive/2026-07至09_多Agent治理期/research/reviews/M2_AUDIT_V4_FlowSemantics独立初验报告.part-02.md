1. publisher 当前未见 raw economic `union_by_name=True`；`_snapshot_b1_group_union` 按 evidence schema signature 分组，复用 audit `_projection_for_schema_group`，再套既有 `_projection_sql`，canonical snapshot 列序/schema 仍由 `_validate_partition` 锁定。该项生产表示已对齐，但混合 schema 的 publisher 端到端行为证据仍不足，见 P1-R5-3。
2. `test_two_stage_projection_contract_and_mixed_source_types_are_safe:1737` 已改为真实 `pl.DataFrame.write_parquet`、真实 `duckdb.connect`、真实 `_flow_source_identity`/`_materialize_safe_projection`，并核对实际窄列、8 行、source filename、三种 schema signature 与文件输入顺序不变；`test_b2_observation_relation_binds_parallel_sequences_and_uses_one_canonicalizer:1933` 也走真实 B1 表及 `_flow_observations`，核对四序列逐索引值和 canonicalizer 调用。可是测试没有记录每个文件的真实 read 次数，没有反转 Parquet 行后再比较，且没有用混合 schema 调用 publisher 的 `_snapshot_b1_group_union`；其结果排序还会遮蔽 relation 原始行序变化。故不能据此闭合“单读/single homogeneous union/行序不变”的完整合同，见 P1-R5-3。
3. `test_publisher_real_chain_rejects_identity_schema_and_post_audit_drift:639` 通过公共 publisher 路径检查 evidence filename/duplicate/schema/pre-post SHA 的拒绝和目录边界；`test_manifest_and_audit_bytes_sha_forgery_is_rejected_before_public_object:874` 检查 audit bytes、manifest audit SHA、missing SHA 和 canonical bytes。真实 required nested/binary source 到 audit BLOCKED 的调用链没有被测试，且 strict validator 与 manifest counter 仍有可伪造缺口，见 P1-R5-1、P1-R5-2、P1-R5-3。
4. 生产代码现在只按 required economic field 将 nested/binary/untokenizable 放入 `untokenizable`，projection 不带 extra 列，publisher `_validate_source_type_evidence` 也不再无条件拒绝 extra nested/binary；边界方向正确。但 audit 测试只直接注入 `_FlowSourceIdentity`，publisher 测试只合成 audit dict，未实际写入 nested/binary Parquet 并穿过 `_source_schema_for_file`→`_audit`→publisher，故 BLOCKED、source evidence 保留、C zero-call 和 audit-invalid/invalid-numeric 三边界尚未由真实调用链证明。
5. `_FlowKey` 及 current/type2/previous lookup 当前静态顺序为 `(symbol,end_date,report_type,comp_type)`，本轮生产修复可见；但现有 selection fixture 的 `comp_type` 恒为 `"1"`，没有直接断言 `_flow_key` 或用 `(report,comp)=(1,2)/(2,1)` 区分顺序，既有 P1-R4-5 的回归合同未被测试锁定，见 P1-R5-5。
6. `_audit` 已显式传递 `_quality_summary(..., threads=threads)`，A/B/C 短路、early-empty SHA、flow numeric quarantine 与 balancesheet numeric blocking、12 bucket/funnel/cent/Decimal/untokenizable 聚合及 public `audit_sha256` 三路径的生产形态均可静态对应；`complete_rows == quality.raw_rows` 也已加入 strict validator。但 publisher 对质量 schema/manifest counters 的完整 strict 守恒仍不闭合，见 P1-R5-1、P1-R5-2、P1-R5-6。

### P1-R5-1：publisher 未完整严格校验 quality schema/byte evidence 与 column-set 守恒

- 现象：`publish_tushare_financials.py::_validate_quality_domain:693-721` 只把 `column_set_count` 纳入 nonnegative exact-int 检查，却不读取或校验 `column_set_sha256s`、`required_numeric_union_types`，也不要求 quality exact key set、`column_set_count == len(column_set_sha256s)` 或每个 schema digest 为 canonical lowercase hex64。`_validate_audit` 因而可接受缺失或伪造的 v3 schema/byte quality evidence。
- 根因：REWORK5 只补了列举的 counter 范围和 `complete_rows` 交叉等式，没有把 v3 quality 的列集合与 required numeric union type evidence 纳入 strict consumer contract。
- 应遵循规则：任务书 §11、§12.1(6) 要求 v3 row/date/dimension/byte/quality evidence 继续 fail-closed；所有派生计数和其 evidence 必须 exact、nonnegative、拒 bool，并在 mkdir/public object 前拒绝漂移。
- 最小复现：以真实合法 audit 为基线，保持 structural/dimension/flow 全部不变，将任一 dataset 的 `quality["column_set_count"]` 改为 `2` 而保留一条 digest，或删除 `column_set_sha256s`/`required_numeric_union_types`；静态沿 `_validate_audit`→`_validate_quality_domain` 可见这些字段没有检查，候选仍可进入 publisher strict validation。
- 新增测试：`tests/unit/test_publish_tushare_financials.py::test_publisher_rejects_quality_schema_evidence_and_column_set_drift_before_snapshot_mkdir`；从完整 audit payload 变异列集合计数、digest 列表、required union type 缺失/非法/乱序，并通过公共 publisher 断言不创建 snapshot。
- 通过条件：quality exact schema、列集合 digest/数量、required numeric union type 与审计产出一致；任何非负整数 drift、缺失/非法 evidence 均在 snapshot mkdir 前拒绝，既有 row/date/dimension/flow 守恒不削弱。

### P1-R5-2：`_verify_snapshot` 仍允许 manifest counter 的负值及 bool 等值混入

- 现象：`publish_tushare_financials.py::_verify_snapshot:450-455` 仅检查 `manifest["request_count"]` 是 exact `int`，没有 nonnegative 或与 raw closure 的等式；`files` entry 的 `rows`/`size_bytes` 在 `:481`、`:514` 只做 Python 相等比较，没有 exact-int/nonnegative 检查。因此 `True == 1` 可使一行分区的 `rows=True` 通过，`request_count=-1` 也没有直接拒绝。
- 根因：manifest bytes/SHA/canonical 检查已补齐，但 manifest 内计数仍被当作普通可比较值，没有沿 §12.1(6)/§12(13) 执行 exact type、范围和 cross-field validation。
- 应遵循规则：所有 publisher 对外证据计数均须 `type(x) is int`、nonnegative、reject bool，并在 public `TushareFinancialSnapshot` 返回前验证与 audit/file rows 的守恒。
- 最小复现：在已有合法 snapshot 上只重写 canonical `manifest.json`，将 `request_count` 设为 `-1`；或把某个 `dataset=.../year=...` file entry 的 `rows` 设为 `True` 且原文件 height 为 `1`。现有 `_verify_snapshot` 的控制流仍可走到 `TushareFinancialSnapshot(...)`。
- 新增测试：扩展 `tests/unit/test_audit_tushare_financials.py::test_manifest_and_audit_bytes_sha_forgery_is_rejected_before_public_object`，分别变异 manifest request/file counters 为负值、bool 和不守恒整数，并断言 verify/publish 均在 public object 前拒绝。
- 通过条件：manifest `request_count`、file `rows`/`size_bytes` 等均 exact nonnegative int，且分别与 raw closure、实际 Parquet bytes/rows 交叉一致；bool、负值、非 canonical 或不守恒均 fail-closed。

### P1-R5-3：§12.1 所要求的真实 mixed/publisher/nested 行为矩阵仍不完整

- 现象：mixed B1/B2 节点确实使用真实 Parquet 与 DuckDB，但没有真实 read-count 证据、行顺序扰动证据或 publisher 混合 schema 输出证据；required nested/binary 仍由 `test_untokenizable_identity_preserves_evidence_but_blocks_flow:1569`、`test_untokenizable_blocking_aggregates_distinct_pairs_in_dataset_order:1593` 的私有对象/stub 注入覆盖，publisher `test_publisher_required_nested_is_blocked_but_extra_nested_is_provenance_only:436` 也只操作合成 audit dict。
- 根因：实现测试把“真实 B1 audit relation”与“真实 publisher B1 及真实 source-type BLOCKED”分成了 helper/validator 测试，未形成 §12.1 要求的端到端受控 Parquet 调用链；输入逆序测试还在 SQL 查询中排序后再比较，不能证明 relation 行序不变量。
- 应遵循规则：§12.1(2)(3)(4) 明确禁止 SQL 字符串、fake connection、纯 helper 作为行为替代；必须实际执行受控 Parquet+DuckDB 生产路径，锁定 per-file one-read、同构 union、row/file/schema order、source filename 及 required nested BLOCKED/pre-mkdir。
- 最小复现：新增一个 real fixture，分别写 BOOLEAN、VARCHAR、DOUBLE 和相同 BOOLEAN schema 文件，反转文件/列/行顺序后调用 publisher 的真实 `_build_temp_snapshot`；另写 required `STRUCT`/`BLOB` economic field，调用公共 audit/publish，观察当前测试矩阵没有对应 actual relation/rows/read-count/`BLOCKED` 断言。
- 新增测试：`test_publisher_mixed_schema_projection_preserves_real_output_and_single_reads`、`test_real_nested_required_field_blocks_before_snapshot_mkdir`，并在 mixed relation 测试中记录真实 DuckDB query/read evidence（不使用 fake connection/inspect）。
- 通过条件：真实生产调用链锁定 actual columns/rows/source filename、每文件恰一次经济读取、single homogeneous union、输入文件/schema/row 顺序不改变结果；required nested/binary 保留 evidence、聚合 distinct pair、C zero-call 并在 mkdir 前拒绝，extra nested/binary 仅 provenance 且不阻断。

### P1-R5-4：publisher 新增边界测试的合法 audit fixture 静态缺少 fina_indicator dimension evidence

- 现象：`tests/unit/test_publish_tushare_financials.py::_valid_audit_payload:366-376` 只为 `_STATEMENTS` 添加 `report_type_counts`、`comp_type_counts`、`report_type_comp_type_counts`；`fina_indicator` 不在 `_STATEMENTS`，其 quality 缺少这三个空列表。可是 `publish_tushare_financials.py::_validate_audit:681` 对每个 dataset 都调用 `_validate_dimension_evidence`，该函数随后把缺失值传给 `_validated_counts:1090`，静态必然在 `None` 上抛错。
- 根因：fixture 没同步 publisher 对 non-statement dataset 的 exact empty dimension evidence contract。
- 应遵循规则：合法 fixture 必须与 audit `_empty_quality_summary` 的完整 v3 shape 一致；边界测试必须先通过合法基线，才能真实命中 extra nested、required BLOCKED、counter 和 pre-mkdir 路径。
- 最小复现：`test_publisher_required_nested_is_blocked_but_extra_nested_is_provenance_only:451` 和 `test_publisher_rejects_bool_and_negative_audit_counters_before_snapshot_mkdir:500` 都先调用 `financial_publication._validate_audit(valid)`；该 `valid` 包含上述不完整的 `fina_indicator` quality，因而新增反例尚未到达其目标分支。
- 新增测试：修正同一 fixture 的 non-statement 空 dimension fields，并增加 `test_valid_audit_payload_matches_all_v3_quality_fields`，确认合法基线先通过，再逐项变异。
- 通过条件：所有新增 publisher 边界测试的合法基线完整通过 strict validator；每个反例分别在指定 mkdir/public-object 边界失败，delivery 不把未触达节点描述为已覆盖。

### P1-R5-5：exact economic-key 顺序已修生产代码但没有可区分的回归测试

- 现象：`audit_tushare_financials.py::_flow_key:1716` 当前返回合同顺序，`type2_key:1830`、`previous_key:1850` 也一致；但是现有 `test_selection_conflicts_missing_drift_and_chain_have_no_fallback:1496` 的 helper 固定 `comp_type="1"`，未直接断言 key tuple。此前错误的 `(symbol,end_date,comp_type,report_type)` 实现不会被该 fixture 区分出来。
- 根因：REWORK5 修了 source symbol，却没有补 taskbook §12.1(5) 要求的 `(1,2)` 与 `(2,1)` 可区分测试。
- 应遵循规则：selection、type2/previous lookup、stable sort、类型标注与测试必须全链使用唯一 `(symbol,end_date,report_type,comp_type)`，禁止仅凭内部一致性接受 alternate ordering。
- 最小复现：构造同一 symbol/end_date 的 `report_type="1",comp_type="2"` 与 `report_type="2",comp_type="1"` observation，直接断言 `_flow_key` 位置 3/4；当前测试没有此断言。
- 新增测试：`tests/unit/test_audit_tushare_financials.py::test_flow_key_uses_exact_report_then_comp_order`，并覆盖 type2/previous lookup 不因位置互换发生匹配。
- 通过条件：测试明确观察 `(symbol,end_date,"1","2")`，所有 current/type2/previous 路径和 stable sort 均保持同一 exact order，漏斗守恒与 bucket 顺序不变。

### P1-R5-6：flow bucket strict validator 未拒绝不可能的派生计数

- 现象：`publish_tushare_financials.py::_validate_flow_bucket:954-994` 检查了非负整数和三组漏斗等式，却没有检查 `distinct_symbols <= current_type1_candidates`、`fiscal_years <= comparable_observations`（以及 comparable=0 时 fiscal_years 必须为 0）。因此合法 `_valid_flow()` 的某 bucket 将 `fiscal_years` 从 `3` 改为 `4`，或将 `distinct_symbols` 从 `100` 改为 `101`，仍满足现有 equations/status，可被 strict validator 接受。
- 根因：只验证了加法守恒和下限 coverage，没有验证由真实 observation 集合定义的派生上界。
- 应遵循规则：§7、§10、§11 的 distinct symbols/fiscal years/comparable 是同一 funnel 的派生计数；publisher 必须拒绝不可能的 counter 伪造，而不是只接受能凑出 PASS 的数字。
- 最小复现：复制 `_valid_flow()`，保持 `current_type1_candidates=100`、`synchronized_type2_pairs=100`、`comparable_observations=100`、`status=PASS`，将第一 bucket `fiscal_years=4`；`_validate_flow_semantics` 的 `_validate_flow_bucket` 当前没有上界检查。
- 新增测试：`tests/unit/test_publish_tushare_financials.py::test_publisher_rejects_impossible_flow_derived_counters`，分别覆盖 `distinct_symbols > current`、`fiscal_years > comparable`、`comparable=0,fiscal_years>0`，并沿公共 publisher 断言 snapshot mkdir 前拒绝。
- 通过条件：所有派生计数满足真实可实现上界与漏斗等式；任何不可能但 nonnegative 的 counter/status 组合均在 strict validation 阶段 fail-closed。

### 独立新增静态对抗反例

- 选择反例：manifest partition `rows=True`（原文件行数为 1），并配套 `manifest["request_count"]=-1`。
- source symbol：`publish_tushare_financials.py::_verify_snapshot:452,481,514`；现有 test node `test_manifest_and_audit_bytes_sha_forgery_is_rejected_before_public_object:874` 未变异这两个 counter。
- 现象：`type(True) is not int` 的语义没有在 file entry 上执行，且 Python `True == 1` 使 row comparison 通过；request_count 只做 type 检查，负值也可继续构造 public snapshot summary。
- 根因：manifest integrity 校验覆盖了 canonical bytes/SHA，却遗漏了 counter exactness/range/cross-field conservation。
- 应遵循规则：所有 publisher counter 必须 exact int、nonnegative、reject bool，并在 public object 返回前与实际文件/audit closure 交叉一致。
- 最小复现：只 canonical 重写既有 manifest，保持 audit、partition bytes、目录名和 manifest file set 不变，分别注入上述值。
- 新增测试：扩展 `test_manifest_and_audit_bytes_sha_forgery_is_rejected_before_public_object` 的 manifest mutation matrix。
- 通过条件：两种 mutation 均在 `_verify_snapshot` 返回 `TushareFinancialSnapshot` 前拒绝；合法 new/reuse/verify 的 audit SHA 三路径仍保持同值。

### delivery 与范围诚实性

delivery 修正后的 STATIC_REWORK5 段落已把 required nested/binary 与 non-required extra 的方向写对，并保留首轮、REWORK1—4、P0/P1、MANAGER_SCOPE_REWORK4、未运行事项、exact scope 和结论上限；没有发现本轮越界写入。可是其“真实 publisher 调用链”“per-file read/行为覆盖”表述超出当前 test node 能直接证明的范围，必须按上述 P1-R5-3/P1-R5-4 收窄或补齐后再宣称覆盖。报告继续明确未运行 Python、DuckDB/Parquet、pytest、Ruff、mypy、cold、audit、snapshot、PIT、network、stage/commit。

### REWORK5 最终判定

`REVIEW_READY / REVIEW_FAIL(P1)`。P1-R5-1 至 P1-R5-6 中任一项均阻止通过；返工必须回同一实现链，补齐 strict counter/evidence 校验、真实行为测试和 exact-key 回归锁定，再由本独立 reviewer 复验。即使后续验证全绿，仍只能保持 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不得据此声称 audit-v4、snapshot、R3、PIT 或 Gate 已通过。

## STATIC_REWORK6_REVIEW_PASS（2026-08-28）

### 结论与审查边界

- `REVIEW_READY`。
- 本轮最终结论：`STATIC_REWORK6_REVIEW_PASS`；未发现 P0/P1。实现状态上限仍为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。
- 本节由同一原独立 reviewer 追加；首轮 `REVIEW_FAIL`、REWORK4/REWORK5 全部历史、P0/P1 发现及本报告原有内容均未改写。
- 本轮严格为 STATIC_ONLY / CPU NONE：未运行 Python、DuckDB/Parquet、pytest、Ruff、mypy、cold、audit、snapshot、PIT、network、stage 或 commit；不宣称 executable validation、真实 audit、snapshot/R3/PIT 或 Gate 通过。

### 绑定、稳定性与实际 diff

本轮开始及写入前两次只读复核的绑定结果稳定：

- taskbook：A0F61943EF79B6866F42974A60A7BB4B91FBAA3532B93F117FC4A181B54939BF，36408 bytes；
- roadmap：CA1CA28CCE9355AB75AD52C41C082230DC2951007ABA78D2679FC395686ACD9F，47764 bytes；
- audit production：AB88443298BA8D23700A3895EBB0327FC1DD7EF13F30C3D42B96E075A9836981，80420 bytes；
- publisher production：AE9EE9198654994499E317181451B746BF82BAB33F1922D612A77889A068CC9C，59855 bytes；
- audit tests：1DEB183BDF4448A8A3DE674E2D1A5AC24962DFC908A10E4FF253CEDFC7B76514，90642 bytes；
- publisher tests：8B1B9EFD8C25CF6C0F1C0B0276313870C5087D02A0102BEAD70BE35D25AC17D3，32343 bytes；
- delivery：4BDC392449AA1493426A8AC891DEC4B6089A55AFC36F107228099D140CE703F7，50169 bytes；
- 既有 review（写入前）：F80EDE77AE0A6F38A5384BB82417F5E0C11B0DE057D21A5393EA3022CE46FDDE，43678 bytes。

实际 diff 检查确认 production2、tests2 与 delivery 的内容对应当前返工；taskbook、roadmap、review 是受保护的 manager/reviewer 文件。review 写入前未发现本 reviewer 造成的越界修改；本节只追加本既有 review 文件。

### §12.2 六项静态复验

1. **quality exact schema/digests/union types：闭合。**
   publish_tushare_financials.py 的 _validate_quality_evidence（764-835）先锁 quality exact key set，再锁 column_set_count、lowercase hex64、长度、重复和 canonical 顺序，并由 source evidence 重算 column-set digest；required_numeric_union_types 锁 exact dataset field order、canonical logical type 与 union value。_validate_quality_domain（838-903）及 dimension validator 继续要求全部 counters exact int、nonnegative、拒绝 bool，并保持 flow numeric quarantine 与 balancesheet/fina blocking 的域边界。行为节点 test_publisher_quality_evidence_is_exact_and_rejects_drift_before_mkdir（537-642）及 quality-domain tests（290-349）先验证合法 fixture，再沿 publish 前校验拒绝 mutation。

2. **manifest exact-int、bytes/rows/request closure：闭合。**
   _verify_snapshot（439-598）对顶层 request_count、request_counts、dataset_rows、每个 file entry 的 rows/size_bytes 做 exact int/nonnegative 校验并拒绝 bool；读取并校验真实 manifest/audit/partition bytes，逐文件复算 SHA、Parquet height，交叉核对 audit raw closure、plan request counts、dataset quality raw_rows 与输出 totals。test_public_snapshot_verifier_rejects_manifest_counter_and_file_metadata_drift（684-742）先走合法 baseline，再走 public verify 的真实拒绝路径；audit bytes/canonical/audit SHA drift 由既有 manifest/audit forgery 节点继续覆盖。

3. **合法 fina_indicator baseline：闭合。**
   _valid_audit_payload（352-465）为 fina_indicator 保留 exact empty report_type_counts、comp_type_counts、report_type_comp_type_counts；test_publisher_quality_evidence_is_exact_and_rejects_drift_before_mkdir（537-642）先调用 _validate_audit(valid)，随后只改变目标字段；_write_valid_snapshot_for_manifest_tests（468-534）并由 public verifier baseline 路径（684-692）确认合法 fixture 不是预先非法的载体。production 的 _validate_dimension_evidence 同时保持非 statement 三个维度 evidence 必须为空。

4. **economic key exact 全链：生产表示闭合，行为反例已锁定。**
   audit_tushare_financials.py 的 quality SQL key（1130-1134）、_flow_key（1732-1738）、type2 lookup（1846-1847）、previous lookup（1866-1870）均使用唯一顺序 (symbol, end_date, report_type, comp_type)，未见 comp-before-report alternate。test_flow_key_orders_report_type_before_comp_type_for_distinct_selection（2302-2321）用同 symbol/end_date 的 (2,1)/(1,2) 直接使旧顺序失败；既有 selection/chain 节点（1540-1587）继续覆盖 current/type2/previous latest、missing、drift、previous cutoff 与 no-fallback。

5. **flow derived bounds：闭合。**
   _validate_flow_derived_bounds（985-998）在 bucket funnel/status 校验后拒绝 distinct_symbols > current_type1_candidates、fiscal_years > comparable_observations，以及 comparable_observations=0 且 fiscal_years 非 0；_validate_flow_semantics（906-983）仍保留 bucket exact order、守恒、coverage 与 status priority。test_publisher_rejects_derived_flow_bounds_before_snapshot_mkdir（645-681）逐项沿 publisher pre-mkdir 路径验证拒绝。

6. **真实 Parquet + DuckDB B1/B2/profile/inventory 证据：静态代码路径闭合，运行结果仍待验证。**
   B1 生产路径 _source_schema_for_file、_safe_projection_query、_materialize_safe_projection（1234-1408）按完整 schema signature 组内使用 union_by_name=false 的显式窄 projection；publisher _snapshot_b1_group_union（264-290）复用同一 _projection_for_schema_group，不使用 raw economic union_by_name=True。test_two_stage_projection_contract_and_mixed_source_types_are_safe（1781-2088）实际创建 BOOLEAN/VARCHAR/DOUBLE Parquet，使用真实 duckdb.connect，调用 audit B1 与 publisher projection，读取 actual columns/rows/source file，反转 file/schema-group/Parquet row order，并解析 JSON profiling 的 READ_PARQUET/PARQUET_SCAN 与 Total Files Read；profile reads 的 schema-group count、文件总数及实际 source rows 共同形成 production grouping 的 disjoint-cover 证据。test_b2_observation_relation_binds_parallel_sequences_and_uses_one_canonicalizer（2091-2177）实际走 B1 表到 _flow_observations，逐索引核对四个 parallel sequences，并 spy 唯一 _canonicalize_operand。required STRUCT/BLOB 的 test_required_nested_or_binary_real_source_blocks_before_economic_stage（2181-2238）实际走 public audit 到 BLOCKED/NOT_EVALUATED/C zero-call；test_public_publisher_real_chain_rejects_each_invalid_boundary_before_mkdir（2265-2299）沿 public publisher 拒绝 required nested、invalid numeric、audit-invalid；extra nested 的 production audit 节点保持 provenance-only。测试代码中的 fake/stub 仅用于 A/B/C 短路、线程参数与事件顺序，不替代上述真实 B1/B2/profiling 行为证据。

### manager-return 控制流

publish_tushare_financials.py 的 _verify_snapshot（538-578）保持 audit.json 专属 block：先解析并 canonical 校验 audit bytes，再调用 _validate_audit(audit)、_source_identity(audit) 与 plan/inventory/request closure 校验，最后保留 continue；非 audit selector 直接进入 partition selector、真实 Parquet bytes/rows/schema 校验，不调用 audit validator。test_public_snapshot_verifier_rejects_manifest_counter_and_file_metadata_drift 的合法 baseline 实际穿过 audit entry 后的 continue 与后续 partition entries；因此该修复不是 source-string 或 inspect 声称。

### 独立新增静态对抗反例（实现者未使用，P2）

- **现象：** _validate_flow_bucket（1136-1142）对 Q1 只要求 previous_chain_eligible 与 missing_previous 为 null，却未要求不适用的 latest_previous_conflicts 必须为 0；该字段也不参与 Q1 的 funnel equation。保持其余字段、status=PASS 与所有 Q1 守恒不变，将第一 bucket 的 latest_previous_conflicts 改为 1，静态路径上 _validate_flow_semantics/_validate_audit 仍可能接受该结构化伪造。
- **根因：** Q1 的 previous helper 在生产计算中不会运行并输出 0，但 publisher strict validator 没有把 chain_applicable=false 时的所有 previous-chain counters 归零规则写成拒绝条件。
- **应遵循规则：** chain_applicable=false 时，previous_chain_eligible、missing_previous 必须为 null，latest_previous_conflicts 必须 exact 0；任何不适用阶段的可计数 evidence 都必须 fail-closed。
- **最小复现：** 复制 tests/unit/test_publish_tushare_financials.py::_valid_flow（51-95），只将 buckets[0].latest_previous_conflicts 从 0 改为 1，保持其余 12 bucket、Q1 pair/numeric equations 与 status 不变，再送入 _validate_flow_semantics 或 public publisher audit validation。
- **新增测试：** 在 test_publisher_flow_validator_rejects_order_identity_funnel_and_status_forgery（109-168）或 derived-bound mutation matrix 中加入 Q1 latest_previous_conflicts=1，并沿 public pre-mkdir 路径断言拒绝。
- **通过条件：** validator 在返回 public snapshot 或创建 snapshot output 前拒绝该 mutation；合法 audit 仍输出 Q1 latest_previous_conflicts=0。该项只影响 forged strict evidence，不改变当前生产计算结果，故列为 P2，不阻断本轮 PASS。

### delivery 诚实性与最终判定

delivery 的 STATIC_REWORK6 与 STATIC_REWORK6_MANAGER_RETURN 保留全部首轮至 REWORK5 历史，明确未运行 Python/DuckDB/Parquet/pytest 等执行性验证、真实 audit/snapshot/R3/PIT/Gate 边界，并将 profiling/operator/count 作为后续 validation 前置条件；没有把静态 test node 结果写成运行通过。其 required nested/BLOB 与 extra provenance-only 方向已保持正确，manager-return 缩进说明与当前 source 一致。

最终判定：`REVIEW_READY / STATIC_REWORK6_REVIEW_PASS`。保留 P2-R6-1 作为严格 evidence 的后续债务；没有 P0/P1，因此允许的结论仍仅为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不得据此声称 executable validation、真实 audit、snapshot READY、R3、PIT 或 Gate 已通过。

## STATIC_REWORK7_REVIEW_PASS（2026-08-28）

### 结论与审查边界

- 本节由同一原独立 reviewer 追加；首轮 `REVIEW_FAIL`、REWORK4/REWORK5/REWORK6 全部历史均保留，未改写。
- 当前结论：`REVIEW_READY / STATIC_REWORK7_REVIEW_PASS`；P0=0，P1=0，P2=1（仅为本节新增的实际调用链测试覆盖加固项，不阻断当前静态通过）。
- 结论上限仍为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。本轮没有执行 Python、DuckDB/Parquet、pytest、Ruff、mypy、cold、audit、snapshot、PIT、network、stage 或 commit，也不宣称任何 Gate/真实 audit 已通过。
- 当前绑定哈希：taskbook `5FA394FC73168370E74A047FB2BB245B1B0ADDE23D731ACB6D4C3232758EB920`（44326 bytes），roadmap `CA1CA28CCE9355AB75AD52C41C082230DC2951007ABA78D2679FC395686ACD9F`（47764 bytes），audit production `AB88443298BA8D23700A3895EBB0327FC1DD7EF13F30C3D42B96E075A9836981`（80420 bytes），publisher production `AE9EE9198654994499E317181451B746BF82BAB33F1922D612A77889A068CC9C`（59855 bytes），audit tests `0D2139B82E895B36CB5D1E4F3FE2A350369AC6E692B3493474EEDA5EF2A5D045`（94928 bytes），publisher tests `8E14CEBB1E8B82E92816D29940092D21098F29FDE863174C8E27025D2FE50632`（33300 bytes），delivery `B53FCA4BD00C79FF46E1ACDFBCB7A7F344A26E2D788937CE1862962C67D12FF8`（58971 bytes）。写入前既有 review 为 `26FAADFE143A89504FA8E56318C48F478BBAEC4CE665A209D3E0C6AF775169C2`（53763 bytes）。
- 本轮静态读取期间上述 taskbook、roadmap、production2、tests2、delivery 内容保持稳定；唯一写入仍是本 review 文件。本节不把历史 `Q1 latest_previous_conflicts` P2 重新作为当前发现，历史文字仅按合同保留。

### §12.3 六项静态复验

1. **parameter-window A/B 双分支：闭合。**

