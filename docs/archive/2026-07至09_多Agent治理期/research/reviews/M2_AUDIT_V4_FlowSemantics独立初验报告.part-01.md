# M2-AUDIT-V4-FLOW-SEMANTICS 独立初验报告

## 结论

- `REVIEW_READY`
- 审查结论：`REVIEW_FAIL`
- 实现状态上限：`IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`

发现 P0/P1，不能 `REVIEW_PASS`。本报告不宣称执行验证、真实 audit-v4、snapshot/R3/PIT 或任何 Gate 通过。

## 审查边界与现场

- reviewer 为本任务全新、未参与实现及三轮返工的独立上下文；未读取旧 review，未创建第二 reviewer、实现 agent、外部会话或 worktree。
- fixed worktree：`F:\\AI_Coding\\QuantitativeTrading\\artifacts\\dev_worktrees\\m2-audit-v4-flow-semantics`
- 仅读取任务书、路线图、两个 production 文件、两个 unit test 文件和 delivery；唯一写入本报告。
- 遵守 `READ_ONLY_STATIC / CPU NONE / REAL DATA I/O NONE`：未运行 Python、pytest、Ruff、mypy、cold、DuckDB/Parquet、audit/snapshot/PIT、网络、writer、stage、commit、merge。
- 写报告前 exact7 SHA-256 与初始快照一致，Git 状态仍只有任务书、路线图、两个 production、两个 test、delivery 七个 scope 路径；现场结果为 `EXACT7_STABLE_NO_SCOPE_BREACH`。

## P0/P1 发现

### P0-1：B 阶段实际调用遗漏必需的 `threads` 参数

- 现象：`_quality_summary` 在 `src/quant/data/audit_tushare_financials.py:973-981` 将 `threads` 设为必需参数，但 `_audit` 在 `:344-349` 调用时没有传入 `threads`。任何 A 已闭合且走真实 B 阶段的 audit 都会在质量统计前抛出 `TypeError`，公共入口随后统一转为 `TUSHARE_FINANCIAL_AUDIT_INVALID`；因此真实 flow C、12 bucket 和可发布 audit 均不可达。
- 根因：三阶段收束时修改了 quality helper 签名，调用点没有同步。
- 规则：A 闭合后必须完成四表 safe-projection quality，再按 B field-domain/tokenizable 闭合条件进入 C；不能以异常替代 B/C 结果。
- 最小复现：任一 `verify_bytes=True`、无 active lease、四表全 `COMPLETE` 的输入到达 `_audit:344` 即满足该静态调用条件。现有 `test_complete_four_table_fixture_is_ready_and_byte_bound` 与 `test_latest_revision_collision_is_reported_for_clean_quarantine` 使用真实 `_quality_summary` 路径，理论上会在此处失败；`test_a_b_c_stage_order_and_b_failure_short_circuits_economic_helpers` 通过 monkeypatch 替换了该 helper，未覆盖此问题。
- 通过条件：B 阶段真实调用可带入冻结的 `threads`，并能继续产出四表 quality；再由定向运行证据证明 C/12 bucket 可达。

### P0-2：current latest conflict 会在 bucket 组装时解引用 `None`

- 现象：`_flow_bucket:1792-1796` 在 `_select_latest_observation` 返回 `(None, True)` 时把 `current` 置为 `None` 并继续计入 `latest_current_conflicts`；若该冲突组是最后一个或唯一一个 current group，`:1876-1879` 因 `current_groups` 非空而执行 `current.dataset`，抛出 `AttributeError`，不能返回冲突 bucket。
- 根因：返回 dataset 依赖循环变量 `current`，没有使用稳定的字段/输入 dataset 来源。
- 规则：latest current conflict 必须计数、排除且不 fallback，最终仍须返回该 bucket；不得把可预期数据冲突变成 audit-invalid。
- 最小复现：现有 `test_selection_conflicts_missing_drift_and_chain_have_no_fallback` 在 `:1281-1286` 传入同 key、同 available date、值为 10/11 的 `current` 与 `conflict`，正好使唯一 current group 返回 conflict 并触发该静态路径。
- 通过条件：该测试节点能返回 `latest_current_conflicts == 1`，且 audit 在 current/type2/previous 各类 conflict 下保持结构化 bucket 与正确 top status。

### P1-1：safe normalized projection 没有实现任务书要求的 canonical/conflict projection 列

- 现象：任务书 §5.2 要求每个 schema group 的同构投影包含 source logical type、canonical raw token、projected `DOUBLE`、classification/conflict token。`_FLOW_NORMALIZED_PROJECTION_COLUMNS` 在 `audit_tushare_financials.py:118-134` 声明了 `canonical_token`，但 `_projection_for_schema_group:1389-1428` 实际只投影 `_flow_source_type_*`、`_flow_raw_*`、`_flow_projected_*`；canonical token 在 Python 的 `_flow_observations:1646-1657` 才生成，conflict 则在 `_select_latest_observation:1716-1719` 再比较。声明的 normalized projection contract 与实际投影不一致。
- 根因：把“安全投影”与后续 Python canonicalization 混成两层，未兑现 §5.2 的投影字段合同。
- 规则：safe projection 必须是单一、可审计的同构中间关系；canonicalizer/conflict 规则必须在合同声明的投影字段上有可追溯实现。
- 测试缺口：`test_safe_projection_contract_retains_hidden_filename_types_and_single_union` 仅用 `inspect.getsource` 检查几个字符串，未检查 `canonical_token`、classification/conflict 列，也未执行 mixed BOOLEAN/VARCHAR/DOUBLE 的真实投影。
- 通过条件：projection contract、SQL/中间关系字段和 single-canonicalizer 设计逐字一致，并有实际 mixed-type/row/file/schema order 测试。

### P1-2：publisher strict validation 对顶层 counter 的 BOOLEAN 不 fail-closed

- 现象：`_validate_audit:393-399` 用 `value.get("active_lease_count") != 0`，没有先要求 `type(...) is int`；Python 中 `False == 0`，所以一个 otherwise-valid audit 将接受 `active_lease_count=False`。同一 strict validator 对 dataset `status_counts` 值和 `request_count` 也主要使用相等比较，未统一执行 exact-int/non-bool 检查。
- 根因：quality bucket counter 已使用 `type(...) is int`，但 top-level/dataset counters 没有复用同一严格类型规则。
- 规则：任务书 §4、§10、§11 要求计数 exact nonnegative int，拒绝 bool；伪造 audit 必须在 snapshot mkdir 前被拒绝。
- 通过条件：顶层 lease、dataset request/status counters 与 quality/bucket counters 一致执行 exact-int/non-bool 校验，并有 pre-mkdir 反例。

## §12 覆盖与 delivery 诚实性

当前测试没有真实覆盖任务书声称的全部 15 类对抗反例，不能把字符串断言或测试名称当作实现路径证据：

- mixed BOOLEAN/VARCHAR/DOUBLE 的真实 safe union、每文件只读一次、single union、canonicalizer 调用/复用未执行；相关测试主要是 `inspect.getsource` 或直接调用纯 helper。
- filename 不在 inventory、重复 filename 映射、per-file schema drift、pre/post source-evidence SHA drift 没有完整实现路径测试。
- nested/binary `BLOCKED` 的 publisher pre-mkdir rejection，以及 audit-invalid / invalid-numeric / BLOCKED 三边界没有端到端测试。
- publisher 对所有 counter、状态、顺序、阈值、identity、缺失、重复、乱序和不守恒的完整伪造矩阵没有覆盖；audit.json bytes drift、missing/invalid audit SHA、manifest canonical drift 也没有完整覆盖。
- Decimal 大额/科学计数等价与全部 nextafter 边界仅部分覆盖；top-level strict counter 的 BOOLEAN 漏洞未被现有 `test_publisher_quality_domain_rejects_bool_nonconservation_and_balance_numeric_drift` 命中。

delivery 报告正确保留了三轮返工历史、STATIC_ONLY 未运行边界、exact scope 与剩余真实平台风险；但其 `STATIC_REWORK2`/合同映射把 BOOLEAN 分文件 union、safe projection 与测试闭合描述得比实际测试强，需在返工后改为与真实 test node 覆盖一致的表述。delivery 没有越过结论上限，这一点保留。

## 独立新增静态对抗反例（实现者未使用）

- 现象：publisher 接受伪造的顶层布尔 lease counter。
- 根因：`src/quant/data/publish_tushare_financials.py:_validate_audit` 只比较 `active_lease_count != 0`，未拒绝 `False`。
- 应遵循规则：所有计数必须是 exact `int`，`bool` 不能作为计数；必须在 snapshot mkdir 前拒绝。
- 最小复现：在已有合法 publishable audit 的副本上执行静态等价变异 `candidate["active_lease_count"] = False`，随后调用 `_validate_audit(candidate)`；当前实现没有该字段的类型拒绝。
- 新增测试：`tests/unit/test_publish_tushare_financials.py::test_publisher_strict_validation_rejects_boolean_top_level_counters`，并覆盖 pre-mkdir 不产生 snapshot 目录。
- 通过条件：该节点抛出 `ValueError`/公共 publish invalid，且 snapshot 目录不存在；同时 request/status counters 的 BOOLEAN 变体也被拒绝。

## 结论边界

P0-1 与 P0-2 已足以 `REVIEW_FAIL`；P1-1、P1-2 及 §12 覆盖缺口进一步证明当前不能进入 validation-only 后的通过宣称。返工应回到同一实现链，先修复上述现象并补充对应反例，再由未参与实现的上下文复验。即使后续定向测试全绿，仍只能在真实 audit-v4 与平台边界验证完成前保持 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。

## REWORK4 FINAL STATIC RE-REVIEW（2026-08-28）

### 结论与范围稳定性

- `REVIEW_READY`
- 本轮最终结论：`REVIEW_FAIL`
- 实现状态上限仍为：`IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`
- 首轮 `REVIEW_FAIL`、P0/P1 历史和本文件原有内容均未改写；本节为最终 REWORK4 追加。
- 复核仍限定在固定 worktree 与 taskbook/roadmap、production2、tests2、delivery；未创建 reviewer、实现
  agent、外部会话或第二 worktree。本轮唯一写入仍是本 review 文件。
- 写入本节前 exact7 输入稳定为 `EXACT7_STABLE_NO_SCOPE_BREACH`。本轮快照：taskbook
  `858786B494803FA3E54550894431BDC5965D52E19B7A52B75C158503670F63C4`，roadmap
  `CA1CA28CCE9355AB75AD52C41C082230DC2951007ABA78D2679FC395686ACD9F`，audit source
  `3B5ED9E9374CD7F562151F237DAB2EA740721A413C71856473D0DABFD64D2251`，publisher source
  `ACBBE3811531111DF4A135DE1084ABEF90977EF3EA8F7691C9B6CD7413965B0D`，audit tests
  `A674B4FE44E800944B5A638ED144CA8754E067B0D18DB56C888B4893777EFB58`，publisher tests
  `44DCEB44E615165F988BFEAA45536FCC3DCA73A295313B0C2EB73BDCEF2AC144`，delivery
  `8F7E7B17B932E26346B3B697382403E93A5BDA48FE5310084AC43EE3F11C5E34`。
- 遵守 `READ_ONLY_STATIC / CPU NONE`：未运行 Python、pytest、Ruff、mypy、cold、DuckDB/Parquet、audit、
  snapshot、PIT、网络、真实数据、stage、commit 或 merge。

### 首轮两项 P0 的 REWORK4 静态闭合

- P0-1 已修复：`audit_tushare_financials.py:367-374` 的 `_audit` 真实调用显式传递
  `threads=threads`；`test_v3_quality_consumes_the_already_materialized_safe_projection:1032-1067`
  通过 `_audit` 路径记录四个 dataset 收到的线程值，并断言投影先于 quality。该行为测试证明调用点
  可达，但仍未执行。
- P0-2 已修复：`audit_tushare_financials.py:1794-1830` 先由 `_FLOW_FIELDS` 得到稳定 dataset；
  current latest conflict 在 `current is None` 时计数后继续返回，不再解引用观测对象。现有
  `test_selection_conflicts_missing_drift_and_chain_have_no_fallback:1348-1397` 直接调用该路径并断言
  `dataset == "cashflow"`、`latest_current_conflicts == 1`，不是源码字符串断言。

### 当前仍未闭合的 P1

#### P1-R4-1：publisher snapshot projection 仍对 raw economic columns 使用 `union_by_name=True`

- 现象：`publish_tushare_financials.py:_build_temp_snapshot:168-222` 在严格 audit 后仍执行
  `connection.read_parquet(list(raw_paths[dataset]), union_by_name=True)`，随后由 `_projection_sql` 对原始
  经济列做输出投影。审计 B1 虽按 schema group 做了安全窄投影，但 publisher 的实际 snapshot 路径绕过
  B1，重新对 mixed raw economic columns 做 common-supertype union。
- 根因：安全投影只替换了 audit 的旧质量/flow读取，没有覆盖同一发布链中的 raw snapshot projection。
- 应遵循规则：任务书 §3、§5.2 的原始经济列 `union_by_name=True` 禁止及 mixed BOOLEAN/VARCHAR/DOUBLE
  的安全同构投影约束必须覆盖发布所消费的 raw economic path；publisher 应复用/等价实现 per-schema
  projection，并保持 pre-audit → validate → mkdir/projection → post-audit 边界。
- 最小复现：同一 cashflow dataset 准备 BOOLEAN、VARCHAR、DOUBLE 三个 economic source file，并提供
  足够其余 comparable rows 使 flow numeric quarantine 仍可满足 PASS；`_audit` 的 B1 可为其建立安全
  source relation，但 `_build_temp_snapshot` 仍把三文件一次 `union_by_name=True`，可能 common-cast、报
  类型错误或把被 flow quarantine 的值静默转成输出数值。
- 新增测试：`tests/unit/test_publish_tushare_financials.py::test_snapshot_projection_uses_safe_mixed_type_relation`
  （当前不存在）；应真实构造 mixed raw files，走 publisher projection，观察列/行/source provenance，禁止
  raw common-supertype union。
- 通过条件：发布路径不再对原始经济列使用 `union_by_name=True`，mixed source 通过安全 per-schema
  projection 产生确定输出，且仍只有合同允许的 I/O 遍数；或在 mkdir 前按合同明确拒绝并留下可审计失败，
  不能静默 common-cast。

#### P1-R4-2：B1 mixed-type 测试仍是 SQL 文本/伪 connection，不是实际 relation/row 行为证据

- 现象：`test_two_stage_projection_contract_and_mixed_source_types_are_safe:1589-1690` 的
  `_Connection.execute` 只保存 SQL 字符串，断言 `read_parquet`、`filename=true`、`union_by_name=false`、
  `UNION ALL` 和表达式出现次数；没有创建或读取 BOOLEAN/VARCHAR/DOUBLE Parquet，也没有观察 B1 实际
  columns/rows、hidden filename mapping、schema-group union 结果。`test_v3_quality_consumes...` 同样以
  fake quality 观察参数，不能替代真实 `_quality_summary` 关系行为。
- 根因：实现者把“生成了预期 SQL”当成“安全 relation 已执行且产生正确 rows”；这正是任务书 §12 要求
  排除的 string-presence substitute（虽然旧的 `inspect.getsource` 已删除）。
- 应遵循规则：§5.2、§12 要求 actual B1 columns/rows、每文件单读、single union、file/schema order
  invariance 及 B1→B2 绑定的行为证据；测试不能只检查字符串或测试名称。
- 最小复现：将 `_projection_for_schema_group` 改成任意无效 SQL、错列别名或丢行实现，上述 fake
  `_Connection` 测试仍可按字符串通过；因此当前测试不能证伪该实现缺陷。
- 新增测试：`tests/unit/test_audit_tushare_financials.py::test_mixed_boolean_varchar_double_projection_and_observation_rows`
  （当前不存在）；用真实受控 Parquet/connection 或等价执行级 fixture，断言三类 source type 的实际
  B1 rows/columns、`_source_file`、union 结果、顺序不变，并继续由 B2 观察到逐字段序列。
- 通过条件：测试真实执行 B1 relation，证明 mixed rows 不经 common-supertype union 丢失语义、每文件只读
  一次、source filename 正确，且 B2 四条 parallel sequence 与实际 row 逐索引一致。

#### P1-R4-3：§12 的 source drift、BLOCKED 边界和 audit/manifest SHA 反例仍未由实现路径覆盖

- 现象：当前 audit tests 没有对 `_source_schema_for_file`/`_flow_source_identity` 施加 filename 不在
  inventory、duplicate filename、per-file schema drift、pre/post source-evidence SHA drift 的实际失败
  路径；`test_untokenizable_identity...` 与 distinct-pair 测试直接注入 `_FlowSourceIdentity`，没有实际
  nested/binary schema 到 BLOCKED。publisher tests 的 malformed evidence 只直接调用 validator，没有
  nested/binary public pre-mkdir 边界。`test_manifest_and_audit_bytes_sha_forgery...` 只改 manifest 的
  `audit_sha256`，没有 audit.json bytes drift、missing/invalid audit SHA 或 manifest canonical drift。
- 根因：测试把 unit helper fixture、有限字段变异和 delivery 文字当作 §12 的完整行为矩阵；delivery 的
  `STATIC_REWORK4` 仍把 filename/schema drift、safe mixed projection 和 publisher SHA closure 描述得比
  当前 test nodes 实际覆盖更强。
- 应遵循规则：§12 第 9、10、13、14 项及其追加条款要求 source identity trust boundary、nested/binary
  BLOCKED 与 audit-invalid/invalid-numeric 三边界、audit bytes/manifest canonical/SHA 缺失伪造均在
  真实实现路径 fail-closed；delivery 只能声称 test node 实际覆盖的范围。
- 最小复现：只运行（静态阅读）现有 `test_two_stage...`、`test_untokenizable...` 和
  `test_manifest_and_audit_bytes...` 的代码路径，任何一个实际 drift/bytes/blocked bug 都没有对应的
  反例断言可失败；三路径 `audit_sha256` 的正常 new/reuse/verify 断言虽存在于
  `test_ready_batch_publishes_and_strictly_reuses_typed_snapshot:555-611`，但不补齐上述伪造矩阵。
- 新增测试：增加实际 `test_source_filename_schema_and_pre_post_evidence_drift_fail_closed`、
  `test_nested_binary_blocked_and_invalid_boundaries_reject_before_mkdir`、
  `test_audit_bytes_missing_invalid_sha_and_manifest_canonical_drift_reject_before_public_object`，并在
  现有三路径测试中保留 exact returned `audit_sha256` 等值断言。
- 通过条件：每一反例在真实调用链观察到规定的公共错误或 pre-mkdir 无 snapshot；BLOCKED 保留 source
  evidence 且 C zero-call；audit bytes/manifest canonical/missing-invalid SHA 均在返回 public object 前
  拒绝；delivery 的覆盖描述与实际节点一一对应。

#### P1-R4-4：publisher 把“非 required 的 nested/binary 列”错误升级为无效 source evidence

- 现象：audit 的 `_flow_source_identity:1264-1302` 只把 required economic type 加入
  `untokenizable`，`_projection_for_schema_group:1392-1448` 只投影结构列和 required economic fields，
  因而一个 path/schema 可信、required fields 全部 tokenizable、但含额外 nested 列的 source 可以完成 B/C。
  publisher `_validate_source_type_evidence:678-752` 却对完整 `schema` 的每一列无条件执行
  `_is_untokenizable_logical_type` 拒绝，导致同一份 audit 的 producer/publisher 合同不闭合。
- 根因：把“required economic field 不可 token 化则 BLOCKED”误实现成“任意未参与 flow 的额外列也拒绝”。
- 应遵循规则：任务书 §9 的 BLOCKED 条件限定为 required field；非 required extra schema 应保留在 evidence
  但不参与安全投影/flow classification。若要拒绝所有 nested 列，必须先修改权威 taskbook，而不是在
  publisher 私自扩大边界。
- 最小复现：以现有 `tests/unit/test_publish_tushare_financials.py::_valid_audit_payload` 为合法
  publishable audit，在任一 evidence 的 `schema` 追加
  `{"name":"extra_payload","logical_type":"STRUCT"}`，重算其 source-evidence SHA，保持所有
  required economic types 为 VARCHAR；audit producer 的 source helper/投影路径不会把该列列入
  `untokenizable`，但 `_validate_audit` 会在 publisher evidence validator 处拒绝。
- 新增测试：`tests/unit/test_publish_tushare_financials.py::test_non_required_nested_schema_column_is_ignored_by_safe_projection`
  （当前不存在），并配套 required nested field 的 BLOCKED/reject case。
- 通过条件：非 required nested/binary extra 列不破坏 tokenizable audit 的 publisher validation；required
  nested/binary 仍保留 evidence、形成 distinct BLOCKED pair 并在 mkdir 前拒绝。

#### P1-R4-5：flow economic key 的 tuple 顺序不符合冻结的 exact identity

- 现象：任务书 §7 冻结 economic key 为 `(symbol,end_date,report_type,comp_type)`；
  `audit_tushare_financials.py:_flow_key:1713-1719` 实际返回
  `(symbol,end_date,comp_type,report_type)`。selection/type2/previous lookup 目前内部使用同一错误顺序，
  但它仍违反 exact key representation，并改变多 report/comp 组合的稳定排序顺序。
- 根因：实现按旧字段顺序复用了 `comp_type`、`report_type`，未随任务书 exact identity 收束同步。
- 应遵循规则：所有 selection、chain 和稳定排序均使用任务书规定的 key 字段/顺序；不能仅因当前
  counter 输出通常相同就忽略 identity drift。
- 最小复现：构造同一 symbol/end_date 下 `(report_type="1", comp_type="2")` 与
  `(report_type="2", comp_type="1")` 的 observations，直接观察 `_flow_key` 返回值/排序；第三、四
  tuple positions 为 comp→report，而合同要求 report→comp。
- 新增测试：`tests/unit/test_audit_tushare_financials.py::test_flow_key_uses_exact_report_then_comp_order`
  （当前不存在）。
- 通过条件：`_flow_key` 及其 type2/previous lookup、排序测试均显示 exact
  `(symbol,end_date,report_type,comp_type)`，并保持无 fallback、漏斗计数和 cashflow-first bucket order。

#### P1-R4-6：publisher 未校验 dataset `complete_rows` 与 quality `raw_rows` 的 v3 交叉一致性

- 现象：`publish_tushare_financials.py:_validate_audit:501-519` 只要求 `complete_rows` 是 nonnegative
  exact int，没有要求 `complete_rows == report["quality"]["raw_rows"]`；因此 otherwise-valid audit 可带
  一个伪造的 dataset complete-row counter 而通过 strict validator。现有
  `test_publisher_rejects_bool_and_negative_audit_counters_before_snapshot_mkdir:388-428` 只覆盖
  `complete_rows=True`/负值，不覆盖非负但不守恒的整数。
- 根因：publisher 对 counter 做了类型/范围修补，但未完成 dataset report 与 quality/raw closure 的
  v3 cross-field conservation。
- 应遵循规则：§11 的 strict v3 evidence validation 应独立拒绝 counter drift；`complete_rows`、quality
  `raw_rows`、raw closure 和 request-level row closure 必须保持实现产出的交叉关系。
- 最小复现：复制 `_valid_audit_payload()`，设置
  `candidate["datasets"]["cashflow"]["complete_rows"] = 999`，保持其他字段及所有 SHA 合法，直接
  调用 `_validate_audit(candidate)`；当前检查只见到 exact int/nonnegative，不会因与 quality `raw_rows`
  不一致而拒绝。
- 新增测试：`tests/unit/test_publish_tushare_financials.py::test_complete_rows_quality_rows_mismatch_rejects_before_mkdir`
  （当前不存在）。
- 通过条件：任何非负 integer cross-field drift 在 snapshot mkdir 前被拒绝，并保持合法 audit 的
  `complete_rows == quality.raw_rows` 及既有 row/date/dimension/byte evidence。

### 其他合同项的静态核对结果

- A/B/C 顺序目前符合更新后的主线：A 在 `verify_bytes`、lease、ledger complete 后才打开 source identity、
  B1 projection 与 quality；B structural/date/dimension 或 balancesheet/fina numeric domain 未闭合时，
  C 的 observation/selection/chain/difference/bucket 不调用；A early branch 使用 `NOT_EVALUATED`、
  `buckets=[]`、空 evidence、exact early-empty SHA、publication false。对应 A/B→C tests 是真实 `_audit`
  调用路径的 monkeypatch behavior tests，但未执行。
- B1/B2 的 TWO_STAGE payload、B1 base/field order、schema-group `UNION ALL`、`filename=true`、B2 frozen
  `_FlowObservation`、parallel sequence length/index closure、single `_canonicalize_operand` 和
  `MAX_ANN_DATE_F_ANN_DATE` 在 production representation 上已对齐；上述 P1-R4-2 说明 test evidence
  仍不足以证明 actual relation/rows。
- cashflow-first 的三字段/12 bucket 顺序、funnel conservation、80% integer coverage、status priority、
  latest/type2/previous no-fallback、cent `nextafter`、Decimal mismatch、missing/invalid/nonfinite/
  resolution/comparable 分类以及 flow-vs-balancesheet/fina numeric domain 在 source 与现有 targeted
  test nodes 中可静态对应。当前没有把这些静态对应写成 executable success 或 Gate 证据。
- source path/type/evidence、canonicalizer/version strings、previous available-date cutoff、untokenizable
  distinct `(dataset, relative_file, required_field)` aggregation、BLOCKED code/order、publisher strict
  pre-mkdir sequencing 及 public `audit_sha256` 的单一 `_verify_snapshot` 返回点均存在；P1-R4-3 仍要求补齐
  drift/forgery behavior matrix。
- publisher 现在对列出的 top-level/dataset/quality/bucket counters 使用 `type(x) is int` 与 nonnegative
  检查，已修复首轮 active-lease bool 缺陷；但 P1-R4-4/P1-R4-6 说明 strict identity/cross-field
  conservation 尚未完整闭合。正常 publish-new、reuse-existing、public verify 三路径的 audit SHA
  equality在 test code 中有断言，仍未执行。

### REWORK4 独立新增静态对抗反例（实现者未使用）

- 选择反例：非 required nested schema column。
- source mapping：producer `audit_tushare_financials.py::_flow_source_identity` 与
  `_projection_for_schema_group`；consumer `publish_tushare_financials.py::_validate_source_type_evidence`；
  proposed test node `test_non_required_nested_schema_column_is_ignored_by_safe_projection`。
- 现象：producer 只以 required economic types 决定 `untokenizable`，该 extra 列不进入 B1 economic
  projection；consumer 却扫描完整 schema 并拒绝，造成 tokenizable PASS audit 被 publisher 伪装成 source
  invalid。
- 根因：required-field BLOCKED 边界在 publisher 被扩大到非 required evidence 列。
- 应遵循规则：§9 只对 required nested/binary 形成 BLOCKED；extra non-required schema 保留 provenance
  但不得改变 flow。
- 最小复现：合法 `_valid_audit_payload` 的一条 evidence schema 加 `extra_payload: STRUCT`，重算
  `flow_source_type_evidence_sha256`，其他字段不变；当前 `_validate_audit` 在 publisher source evidence
  loop 拒绝，而 producer safe projection 不会用该列。
- 新增测试：上述 test node，并配套 required nested field 的 BLOCKED/reject node；两者必须分别落在
  tokenizable PASS 与 BLOCKED 边界。
- 通过条件：extra non-required nested column 的合法 audit 可被严格 publisher 接受；required nested
  field 仍保留 source evidence、按 distinct pair 聚合、C zero-call 且 pre-mkdir reject。

### 最终判定

P0-1/P0-2 的生产缺陷已有静态修复和行为测试节点，但 P1-R4-1 的 publisher raw union、P1-R4-4 的
required-field boundary 不一致、P1-R4-5 的 exact key order、P1-R4-6 的 strict cross-field gap，以及
P1-R4-2/P1-R4-3 的任务书 §12 行为测试不足，均不允许进入 validation-only。故最终仍为
`REVIEW_READY / REVIEW_FAIL`；本报告不宣称任何 executable validation、真实 audit-v4、snapshot/R3/PIT
或 Gate 通过。后续若返工，必须回同一实现链，补齐上述最小测试/实现并由独立上下文复验。

## STATIC_REWORK5_REVIEW_FAIL(P1)（2026-08-28）

### 结论与复验边界

- 本节由同一原独立 reviewer 追加；首轮 `REVIEW_FAIL`、REWORK4 全部历史及其发现均未改写。
- 最终结论：`REVIEW_FAIL(P1)`。未发现本轮新的 P0，但存在 P1，不能进入 validation-only。
- 状态上限仍为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`；本节不宣称执行测试、真实 audit、snapshot、R3、PIT 或 Gate 通过。
- 绑定 taskbook SHA256=`54b127ae029bd4529f1dc0f8088cfd43f1bb0b23ae08eac2338c0a7decb5e102`，delivery SHA256=`fc95f8758633c1b51b01751127906af39a7908c2126c1ffa952784daafcc9fbf`。本轮只读 exact7；写入范围仍只有本报告。

### §12.1 六项静态复验

