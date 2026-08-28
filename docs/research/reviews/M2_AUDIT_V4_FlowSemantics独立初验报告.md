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

   `audit_tushare_financials.py::_audit` 先完成 `verify_bytes is True`、lease=0、四表 exact COMPLETE/ledger closure，随后才打开 `_flow_source_identity`、`_materialize_safe_projection` 和 `_quality_summary`；未闭合时直接使用 `_not_evaluated_flow()`，得到 `NOT_EVALUATED`、`buckets=[]`、空 source evidence、exact early-empty SHA 和 `publication_allowed=false`，C helpers 不调用。`test_parameter_window_mismatch_blocks_instead_of_silently_quarantining`（audit tests:509）在同一真实 `_build_root` fixture 上先走 `verify_bytes=False` 并用 spies 锁定零调用，再走 `verify_bytes=True`，实际 B quality 报告 `request_window_mismatches=1`/`INCOME_REQUEST_WINDOW_MISMATCH`，且 economic helpers 仍为零。独立 early-short-circuit node（:1223）还逐项锁定 exact early-empty SHA。

2. **physical-row-drift A/B 双分支：闭合。**

   `test_per_request_physical_row_drift_has_verified_and_short_circuit_branches`（:569）实际读取并重写 income Parquet 为重复两行，只同步 bytes/checksum/size，保持 metadata/ledger rows=1；`verify_bytes=False` 仍是 A 短路，`verify_bytes=True` 才沿 B safe relation 计算 `row_count_mismatch=1` 并 top `BLOCKED`，两次都锁定 C zero-call。测试没有通过修改 ledger rows 将重复行合法化，故未削弱 v3 physical-row 语义。

3. **statement exact10、真实 safe projection 与 B1/B2 行为：闭合。**

   production `_projection_for_schema_group` 仅使用 schema-group 的 `read_parquet([...], filename=true, union_by_name=false, hive_partitioning=false)` 和显式窄投影；publisher `_snapshot_b1_group_union` 复用该生产 projection，再由 `_projection_sql` 保留 statement exact10：`symbol,ann_date,f_ann_date,available_date,end_date,report_type,comp_type,update_flag,n_cashflow_act,source`。`test_two_stage_projection_contract_and_mixed_source_types_are_safe`（:1873）在测试体内实际创建 BOOLEAN、VARCHAR、DOUBLE 受控 Parquet，使用真实 `duckdb.connect`，调用 audit B1 与 publisher B1 生产函数并执行 SQL；它读取实际 relation columns/rows/source filename，解析 JSON profile 的 `READ_PARQUET/PARQUET_SCAN` 与 `Total Files Read`，锁定 3 个 schema groups 的 `[1,1,2]` scan/file counts 和总 4 文件 disjoint cover，并反转 file list、schema-map order、每个 Parquet row order 后比较 evidence、rows、exact columns 与 publisher exact10。若运行时 profile 缺 operator/count，测试 helper 明确失败，不会降级为 SQL 字符串或静态声称。`test_b2_observation_relation_binds_parallel_sequences_and_uses_one_canonicalizer`（:2187）继续从真实 B1 relation 到 `_flow_observations`，逐索引检查四个 parallel sequences，并以 spy 证明每个 operand 只经 `_canonicalize_operand`。

4. **cashflow/income exact required schema 与缺字段 fail-closed：闭合。**

   `test_numeric_tokens_and_source_evidence_file_order_are_invariant`（:2475）使用真实 production `_flow_source_identity`，仅把 metadata schema reader 替换为合同明确的 fake schema：cashflow 恰有 `n_cashflow_act`，income 同时恰有 `n_income` 与 `n_income_attr_p`；正反文件顺序的 evidence/SHA 相同。随后删除 income 的 `n_income_attr_p`，同一 production identity 构造路径以 `KeyError` fail-closed，测试没有 catch 或改为 `.get()` 静默接受。该 fake 只用于 exact required-field schema contract；混合类型与 nested 的实际 Parquet/DuckDB 路径由第 3、6 项节点覆盖。

5. **public verifier import 与 baseline→mutation→restore：闭合。**

   publisher tests 顶层显式导入 `verify_tushare_financial_snapshot`。`test_public_snapshot_verifier_rejects_manifest_counter_and_file_metadata_drift`（:691）由 `_write_valid_snapshot_for_manifest_tests` 写出实际 audit/manifest/Parquet baseline，先调用 public verifier 成功路径，再逐项变异 request/dataset/file rows、size 和 audit file entry，沿 public `_verify_snapshot` 拒绝，最后把 manifest 恢复为 canonical baseline 并再次调用 public verifier。`_verify_snapshot`（:439）在 audit.json 分支内先完成 canonical/bytes/audit SHA、`_validate_audit(audit)`、`_source_identity` 及 plan/inventory/request closure 校验，然后保留 `continue`；非 audit partition 分支只做真实 Parquet/schema/rows 校验，不调用 audit validator。既有 publish/verify/reuse 节点继续锁 audit SHA 三路径同值、audit bytes/SHA/manifest canonical drift 的 fail-closed 边界。

6. **required/extra nested 的派生 identity、精确拒绝与 pre-mkdir：闭合。**

   `_flow_source_identity` 只把 required economic type 放入 `untokenizable`，`_projection_for_schema_group` 不投影 extra nested。`test_required_nested_or_binary_real_source_blocks_before_economic_stage`（:2277）实际写 STRUCT/BLOB Parquet 并走 public audit，保留 source schema evidence，得到 exact `BALANCESHEET_FLOW_SOURCE_TYPE_UNTOKENIZABLE` count=1、top `BLOCKED`、flow `NOT_EVALUATED`/空 bucket 和 economic C zero-call；`test_extra_nested_real_source_is_provenance_only_and_does_not_block_safe_projection`（:2337）实际走 audit 并确认 extra evidence 保留、无 blocking issue。publisher nested node（:751）同步 extra 的 column-set digest，required candidate 同步 schema、required types、flow evidence SHA、column digest 与 union type，再以 exact blocking code/`_validate_audit` rejection 和公共 publisher 的 clean snapshot 目录不存在锁定 pre-mkdir 拒绝；:2364 的真实 publisher boundary 继续覆盖 required STRUCT/BLOB、invalid numeric、audit-invalid 三边界。

### 其余合同、冻结与 evidence honesty

- A/B/C、`_quality_summary(..., threads=threads)` 可达性、v3 quality/raw-row 守恒、flow-vs-balancesheet/fina numeric domain、cashflow-first 12 bucket/funnel/status、exact economic key `(symbol,end_date,report_type,comp_type)`、canonicalizer/token/cutoff、cent-resolution/Decimal 与 public `audit_sha256` 三路径的生产表示及既有测试节点未见本轮回归。
- `complete_rows == quality.raw_rows`、所有顶层/dataset/quality/manifest/bucket counters 的 exact int/nonnegative/reject-bool、schema/digest/union/manifest/bytes closure 仍由当前 strict validators 与测试矩阵覆盖。production2、taskbook、roadmap 在 STATIC_REWORK7 中保持冻结。
- taskbook §12.3 与 delivery `STATIC_REWORK7` 对 Validation1 STOP 的 evidence root、summary/stdout SHA、identity/collect-only/6 failed + 48 passed、Ruff/mypy/cold/scope closure UNRUN、资源释放、fresh basetemp/no-clobber 保留以及后续不得运行的 real audit/snapshot/R3/PIT/network/stage/commit 边界逐字一致；delivery 六项均保留“现象—根因—应遵循规则—最小复现—新增测试—通过条件”，没有把本轮静态测试代码改动写成已运行通过。
- 历史 review 中的 Q1 `latest_previous_conflicts` P2 文本按用户/§12.3 要求完整保留，但本轮不重新登记、不以其改变当前 P0/P1 判定，也不声称该历史债务已通过 executable validation。

### 本轮新增静态对抗反例（实现者未使用，P2；非 latest_previous_conflicts）

- **现象：** 真实 public A 分支节点 `test_parameter_window_mismatch_blocks_instead_of_silently_quarantining` 与 `test_per_request_physical_row_drift_has_verified_and_short_circuit_branches` 只断言 `source_type_evidence == []`，没有在真实 `_audit` fixture 上断言 early-empty SHA；exact SHA 断言位于 `test_flow_prerequisites_short_circuit_all_flow_helpers_and_use_early_sha`（:1223），该节点通过 patched plan/ledger/load 直接调用 private `_audit`。因此一个只在真实文件型 A 短路路径生成错误空 evidence SHA、而不改变 evidence/bucket/publication 字段的回归，现有真实双分支节点可漏过。
- **根因：** exact early-empty identity 的值断言与真实 parameter/physical public fixture 分离，测试矩阵同时有调用链与常量断言，却没有把二者绑定在同一真实 A failure。
- **应遵循规则：** 每个 A 前置失败的真实 public audit 结果都必须同时满足 zero-call、`NOT_EVALUATED`、`buckets=[]`、空 evidence、`publication_allowed=false` 和 exact lowercase early-empty SHA；不能只验证 list 为空。
- **最小复现：** 在现有 `_build_root` 的 future-announcement 或 duplicate-row fixture 上调用 `audit_tushare_financials(..., verify_bytes=False)`，分别观察其 flow `flow_source_type_evidence_sha256`；保持其余短路字段不变，仅令该真实分支返回任意非合同空 SHA，即应被新断言捕获。
- **新增测试：** 扩展上述两个真实 public A/B 节点，在 false 分支断言 `flow_source_type_evidence_sha256 == 793cd498f4dbca6b28661417f49606323248da0cdf8e838575df9f7ef4d0d5db`，并保留现有 helper spies 与 true 分支 B failure 断言。
- **通过条件：** 两个真实 A failure 的 exact SHA、零调用和 publication-false 边界同时闭合；该测试缺口不构成当前 production P0/P1，故列为 P2，且不是历史 `latest_previous_conflicts` 项。

### STATIC_REWORK7 最终判定

`REVIEW_READY / STATIC_REWORK7_REVIEW_PASS`。本轮未发现 P0/P1；P2 仅为上述新增的真实 A early-empty SHA 测试绑定加固项。允许的最终状态仍只能是 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不得据此宣称 executable validation、真实 audit、snapshot、R3、PIT 或 Gate 通过。

## STATIC_REWORK8_REVIEW_PASS（2026-08-29）

### 结论与审查边界

- 本节由同一原独立 reviewer 追加；首轮、REWORK4、REWORK5、REWORK6、REWORK7 全部历史保留，未改写。
- 当前结论：`REVIEW_READY / STATIC_REWORK8_REVIEW_PASS`；当前 P0=0、P1=0、P2=0。历史报告中的 P2 文本继续保留，但本节不重新登记、也不把它作为 STATIC_REWORK8 scope finding。
- 结论上限仍为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。本轮没有运行 Python、DuckDB/Parquet、pytest、Ruff、mypy、cold、audit、snapshot、PIT、network、data I/O、stage 或 commit；PASS 不代表 Validation4、真实 audit 或任何 Gate 通过。
- 当前静态绑定：taskbook `21F80BFB111A35F7E34E3DBB1CA179BCDFC367472CC10AA486D6816C346C3307`（48432 bytes），roadmap `CA1CA28CCE9355AB75AD52C41C082230DC2951007ABA78D2679FC395686ACD9F`（47764 bytes），audit production `AB88443298BA8D23700A3895EBB0327FC1DD7EF13F30C3D42B96E075A9836981`（80420 bytes），publisher production `AE9EE9198654994499E317181451B746BF82BAB33F1922D612A77889A068CC9C`（59855 bytes），audit tests `72CCF54EF0CDB824B17041E5BED05AA0C8B7957A4A8D9956114BE347578F8F7C`（94983 bytes），publisher tests `8E14CEBB1E8B82E92816D29940092D21098F29FDE863174C8E27025D2FE50632`（33300 bytes），delivery `3C5BE435E8BCD072679E742BB0EEBA9283B5FB4BCE82C8E8D86325A6E3597E57`（61185 bytes）。写入前既有 review 为 `F20CC20A74C5C5624FA55671B8EE3BE31972CA1A10521251F929A61DA5B434C5`（65139 bytes）。
- 本轮只读确认 production2、publisher test、taskbook、roadmap、delivery；生产文件、publisher test、taskbook 与 roadmap 内容保持此前绑定，唯一新增写入仍是本既有 review。

### §12.4 STATIC_REWORK8 六项静态复验

1. **唯一机械代码变化：闭合。**

   `tests/unit/test_audit_tushare_financials.py:1683-1684` 当前恰为冻结文本：

   ```python
   def finite(value: float) -> financial_audit._CanonicalOperand:
       return financial_audit._CanonicalOperand("x", "finite", value)
   ```

   这是原位置 `finite = lambda ...` 的局部替换；其后的 `_flow_mismatch` 调用、参数、数值断言及该测试节点位置未移动。补丁 hunk 没有新增 `Any`、`cast` 或 `type: ignore`，没有移动/泛化 helper，也没有 production、publisher test 或其他业务 diff。`_CanonicalOperand` 的 token=`"x"`、category=`"finite"`、projected=`value` 三字段保持不变。

2. **行为与调用点未改变：闭合。**

   当前 `test_decimal_tolerance_and_float64_resolution_boundaries_are_exact` 仍以同一局部 callable 调用 Q1 exact `0.01`、超容差与负值 mismatch，随后执行 synthetic spacing 和真实 `nextafter` 边界断言；只改变 callable 的 Python 表达形式，不改变输入、输出或断言。未发现把局部函数抽出、泛化为公共 helper、改参数类型为 `Any`、增加 cast 或用忽略指令绕过 Ruff 的迹象。

3. **Validation3/交付边界诚实：闭合。**

   当前 taskbook §12.4 与 delivery `STATIC_REWORK8` 均记录：POSTFIX Validation3 的 Parser/identity/collect-only 及两个 unit 文件 `54 collected / 54 passed` 是历史 evidence；Ruff 首个失败为 audit test line 1683 的 E731，V3 mypy、cold、scope UNRUN，资源已释放、cached0 与 ordinary `git diff --check` PASS；本轮只做 tests-only 机械修复，未运行该命令或任何执行性工具，Validation4 仍未申请/未运行。delivery 明确没有新增行为测试，也没有把 Validation3 的历史绿灯写成当前 Ruff/mypy/cold/Gate 通过。

4. **production2、publisher test 与旧语义未被触碰：闭合。**

   audit production、publisher production、publisher test 与 roadmap 的当前哈希分别保持 `AB884432...6981`、`AE9EE919...CC9C`、`8E14CEBB...0632`、`CA1CA28C...ACD9F`；taskbook 的变化是经理新增 §12.4 合同，delivery 只追加本轮 STOP/修复记录。此前已静态闭合的 A/B/C、v3 quality、safe projection、flow bucket、strict publisher、audit SHA、nested/pre-mkdir 与 manager-return 语义没有出现新的生产或 publisher-test diff。

### 独立静态对抗反例（实现者未使用；非 P2 发现）

- **现象：** 当前 `test_decimal_tolerance_and_float64_resolution_boundaries_are_exact` 的 `finite` 返回对象只间接被 `_flow_mismatch` 消费其 `.projected`；若有人把机械修复错误改成 `return _CanonicalOperand("drift", "invalid", value)`，现有 mismatch 数值断言可能仍看不见 token/category 漂移。该反例未被本轮实现者新增或使用。
- **根因：** style-only 行为测试关注数值差值与 resolution，未直接断言局部 `_CanonicalOperand` 的三个字段；类型注解也不是运行时字段校验。
- **应遵循规则：** §12.4 冻结的是完整返回对象与调用行为，token/category/projected 均须逐字保持；机械修复不得借数值断言掩盖对象字段漂移。
- **最小复现：** 将当前局部 return 的 token 或 category 任一字面量改动，保持 `projected=value`、调用点和所有 mismatch/spacing 输入不变；静态上可绕过现有数值断言，但已违反允许的唯一 hunk。
- **新增测试：** 若后续需要加强测试，可在同一节点增加 `finite(1.25) == _CanonicalOperand("x", "finite", 1.25)` 的字段级断言；本轮 §12.4 明确为 style-only，不据此新增行为测试或扩大实现范围。
- **通过条件：** 当前局部 def 的 exact return 字面量、参数/位置和所有调用/断言保持不变；该对抗样例由静态 exact-hunk 复核覆盖，未形成当前 P0/P1/P2 缺陷。

### STATIC_REWORK8 最终判定

`REVIEW_READY / STATIC_REWORK8_REVIEW_PASS`。本轮确认唯一允许的 E731 mechanical closure，未发现 P0/P1/P2，也未发现越界写。PASS 后不得由本 reviewer 自行启动 Validation4；仍只能保持 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`，不得宣称执行验证、真实 audit、snapshot、R3、PIT 或 Gate 通过。

## STATIC_REWORK9_REVIEW_PASS（2026-08-29）

### 结论与审查边界

- 本节由同一原独立 reviewer 追加；首轮 `REVIEW_FAIL`、REWORK4/REWORK5、STATIC_REWORK6/7/8 的全部历史、发现与 P2 文字均保留，未改写。
- 当前结论：`REVIEW_READY / STATIC_REWORK9_REVIEW_PASS`；当前 P0=0、P1=0、P2=0。历史 P2 不在本轮重新登记，也不因本轮静态通过而声称已完成 executable validation。
- 结论上限仍为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。本轮未运行 Python、pytest、Ruff、mypy、cold、DuckDB/Parquet、audit、snapshot、PIT、network、data I/O、stage 或 commit；不得由本 reviewer 自行启动 Validation5，不宣称任何 Gate 通过。

### 绑定证据与 scope/diff-check

本轮写入前的绑定哈希与字节数如下；均与用户给定证据一致：

| 文件 | SHA256 | bytes |
|---|---|---:|
| taskbook | `0816ddddac408e250870bab67a686709d40637047f7560afb024d62a2b23eb60` | 56122 |
| roadmap | `ca1ca28cce9355ab75ad52c41c082230dc2951007aba78d2679fc395686acd9f` | 47764 |
| audit production2 | `368a9de216dd39818f8a4ce3bddfb28413a3fc2142d949955959473549973767` | 80512 |
| publisher production2 | `2dd31a6ed82d8b39f28a7873ee26f2a0e1ef7140acf44c1c4d02fada17dbaee2` | 60065 |
| audit test | `72ccf54ef0cdb824b17041e5bed05aa0c8b7957a4a8d9956114be347578f8f7c` | 94983 |
| publisher test | `8e14cebb1e8b82e92816d29940092d21098f29fde863174c8e27025d2fe50632` | 33300 |
| delivery | `c7181d382f3ea6b475b17f6e4e2587469785ce59e45ff1dc3970ce732624f4ab` | 67544 |
| review（写入前） | `c35f3455439c88a8f4542df538b388bc437a17ce81e4cb8254c1ad3074459208` | 71202 |

当前 dirty scope 仍仅包含既有任务包、roadmap、两个 production、两个 tests、delivery 与该 review；本轮 reviewer 只写入既有 review 文件，未发现越界路径。cached0 与 ordinary `git diff --check` 维持用户绑定的 PASS，未将其扩展解释为执行验证。

### §12.5 四项 STATIC_REWORK9 静态复验

1. **audit numeric-pair 联合容器：闭合。**

   `audit_tushare_financials.py:1862-1879` 的 `previous_pairs` 仍按 `(current, type2, previous)` 建立，Q2/Q3/FY 的 previous cutoff、冲突跳过、`latest_previous_conflicts` 计数和顺序未重排。`audit_tushare_financials.py:1888-1893` 只有一个
   `numeric_pairs: list[tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]]` 显式联合容器；Q1 comprehension 仍逐项生成 `(current, type2, None)`，else 仍直接使用 `previous_pairs`。后续 `None` 插入 operand、分类计数、comparable/mismatch 计数均保留原位置与分支。

2. **publisher source-evidence locals 先验证后收窄：闭合。**

   `_snapshot_b1_inputs` 的实际代码在 `publish_tushare_financials.py:191-203` 先读取 `raw_dataset`、`raw_request_id`、`raw_relative`，再按原顺序执行 exact `str` 类型、dataset membership、request-id hex64、relative 类型与 canonical-relative 等式检查；只有全部通过后，`204-206` 才把它们绑定为后续使用的 `dataset`、`request_id`、`relative`。未见提前强转、truthiness、弱化 identity、增加/删除 cast、Any 或 type-ignore。

3. **path membership、一次消费与最终空集守恒：闭合。**

   `publish_tushare_financials.py:156-178` 仍对输入 raw path 做 dataset/request-id/文件名检查并拒绝重复 relative；`207-209` 明确先以 `relative not in path_by_relative` fail closed，再执行无 default 的单次 `path_by_relative.pop(relative)`。`260-261` 仍以剩余 path 非空或任一 dataset 未分组拒绝，故 duplicate/missing/未消费 evidence 的错误顺序与最终空集守恒未改变，未引入 Optional mapping 或复制转换。

4. **manifest `request_count` stable local：闭合。**

   `_verify_snapshot` 在 `publish_tushare_financials.py:448-450` 对 `request_count` 只作一次 `manifest.get` stable local；`492-493` 保留 `type(request_count) is not int or request_count < 0`，因此 bool、负数和缺失值均 fail closed，未使用 `int(...)` 或 truthiness。`569-576` 的 manifest/raw closure 与 `sum(request_counts.values())` 交叉校验仍在 audit evidence 分支中，public snapshot 返回前的拒绝语义没有后移或削弱。

### 类型-only 范围与 delivery 诚实性

- 当前四处 production hunk 没有新增或删除 `cast`、`Any`、`type-ignore`、强转、truthiness、Optional mapping 或复制转换；没有逻辑重排，也没有改变调用、previous-chain、path 消费、closure 计数和错误顺序。文件中既有的其他类型注解/转换不被误报为本轮新增。
- audit test、publisher test 的绑定哈希与此前 R8 相同；R9 没有新增行为测试、测试修复或 P2 夹带。taskbook §12.5 与 delivery `STATIC_REWORK9` 均诚实保留 Validation4 首失败为 production2 mypy 六项错误、此前 Validation3 的历史 evidence，以及 Validation5/mypy/Ruff/cold/scope 和真实 audit/snapshot 等当前 UNRUN 边界；未把静态修正写成绿色验证。

### 独立静态对抗反例（实现者未使用；非 P2 发现）

- **现象：** 若有人在 `_snapshot_b1_inputs` 的 `raw_request_id` guard 前加入 `str(raw_request_id)`，一个 64 位十进制整数 request id 可能被转换成满足 hex64 的字符串；同时 `raw_relative` 使用该字符串且 `raw_paths` 目录同名时，错误实现会接受原本必须拒绝的非字符串 source identity。该变体未被本轮实现者使用。
- **根因：** 先转换会抹掉 evidence identity 的 exact-type 边界，且十进制数字字符也是合法 hex 字符集，不能依靠 `_is_hex64` 追回原始类型错误。
- **应遵循规则：** 必须先按原顺序执行 `type(raw_request_id) is str`、hex64 与 canonical-relative guard，guard 通过后才允许将值收窄为字符串；禁止任何强转或用 truthiness 替代检查。
- **最小复现：** 在 `tests/unit/test_publish_tushare_financials.py::test_publisher_real_chain_rejects_identity_schema_and_post_audit_drift` 的真实 publisher 链 fixture 中，将 evidence 的 `request_id` 改为 64 位十进制整数、保持 `relative_file` 与 raw path 的 64 位字符串一致；当前代码应在 `raw_request_id` exact-type guard 处拒绝，错误的 `str(...)` 修复则可能继续到 path consume/projection。
- **新增测试：** 后续 Validation5 可在该既有行为节点加入此非字符串 request-id mutation，并断言 pre-mkdir/return-object 前拒绝；本轮 §12.5 禁止修改 tests2，因此这里只记录反例，不伪造测试已运行。
- **通过条件：** 当前 `raw_request_id` 在转换前 exact-type 检查，非字符串整数不进入 narrowed locals、path pop 或 publication object；当前实现满足该静态条件，故该反例不形成 P0/P1/P2。

### STATIC_REWORK9 最终判定

`REVIEW_READY / STATIC_REWORK9_REVIEW_PASS`。本轮未发现 P0/P1/P2 或越界写；全部历史 review 仍保留。PASS 后不得自行 Validation5，且不得把本报告表述为执行验证、真实 audit/snapshot、R3/PIT 或 Gate 已通过。

## STATIC_REWORK10_REVIEW_PASS（2026-08-29）

### 结论与审查边界

- 本节由同一原独立 reviewer 追加；首轮 `REVIEW_FAIL`、REWORK4/REWORK5、STATIC_REWORK6/7/8/9 的全部历史、发现与 P2 文字均保留，未改写。
- 当前结论：`REVIEW_READY / STATIC_REWORK10_REVIEW_PASS`；当前 P0=0、P1=0、P2=0。历史 P2 不在本轮重新登记，也不因本轮静态复验而宣称已完成 executable validation。
- 结论上限仍为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`。本轮未运行 Python、pytest、Ruff、mypy、cold、DuckDB、Parquet、真实 data/audit/snapshot、network、stage 或 commit；不得由本 reviewer 自行启动 Validation6，不宣称任何 Gate 通过。

### 绑定证据与 scope/diff-check

本轮写入前哈希与字节数如下，且在静态读取期间稳定：

| 文件 | SHA256 | bytes |
|---|---|---:|
| taskbook | `e6fbc0efdf69e2e73657610be847318bd841dd152adb9e22b87d70ad0ad6a065` | 61424 |
| roadmap | `ca1ca28cce9355ab75ad52c41c082230dc2951007aba78d2679fc395686acd9f` | 47764 |
| audit production2 | `f1ecadb31060a1f53a99909681808fc0ccae53ea99012d5665b5cc0c7ca776e0` | 80516 |
| publisher production2 | `2dd31a6ed82d8b39f28a7873ee26f2a0e1ef7140acf44c1c4d02fada17dbaee2` | 60065 |
| audit test | `72ccf54ef0cdb824b17041e5bed05aa0c8b7957a4a8d9956114be347578f8f7c` | 94983 |
| publisher test | `8e14cebb1e8b82e92816d29940092d21098f29fde863174c8e27025d2fe50632` | 33300 |
| delivery | `c07267a749f9b0b67b38b80b5a475e093f5393c607705d3c6dc1b55ebf88436f` | 70527 |
| review（写入前） | `a57bf52bd847094f220dd8a010f2c5ed4aac35b07889baf75e5cc9df09198153` | 78343 |

R9 历史中记录的 audit production2 为 `368a9de216dd39818f8a4ce3bddfb28413a3fc2142d949955959473549973767` / 80512 bytes；当前仅增加 4 bytes，与 `list`→`Sequence` 的单一注解替换一致。publisher production、tests2 与 roadmap 的绑定内容未漂移；本轮 reviewer 只写入既有 review 文件，未发现越界路径，ordinary `git diff --check` 保持 PASS。

### §12.6 STATIC_REWORK10 静态复验

1. **唯一 covariant read-only 注解：闭合。**

   `src/quant/data/audit_tushare_financials.py:16` 的 `collections.abc` 既有导入包含 `Sequence`，没有新增、删除或改写 import。`_flow_bucket:1813` 内 `numeric_pairs:1888` 只有一个注解，精确为
   `Sequence[tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]]`。当前没有第二个同名容器注解或 runtime conversion。

2. **Q1/Q2/Q3/FY 的对象、alias、顺序与 `None`：闭合。**

   `previous_pairs:1862-1879` 仍是实际的 `list[tuple[_FlowObservation, _FlowObservation, _FlowObservation]]`，按 `(current, type2, previous)` 追加，并保持 previous cutoff、冲突跳过与 `latest_previous_conflicts` 计数。`numeric_pairs:1889-1893` 的 Q1 comprehension 仍产生实际 list `(current, type2, None)`；else 仍直接 alias `previous_pairs`；后续仍只有一次 `for current, type2, previous in numeric_pairs`。operand 的 `None` 插入、分类/比较/mismatch 计数、`previous_eligible = len(previous_pairs)` 与错误顺序均保持原样。Sequence 只改变静态消费接口，不复制或改变任一 runtime list。

3. **禁止项与实际差异：闭合。**

   当前 numeric-pair hunk 未出现 `append`、`extend`、`cast`、`Any`、`type-ignore`、`list(...)`/其他容器转换或强转；未见分支、alias、逻辑、错误顺序或 P2 夹带。`numeric_pairs` 在当前 production 中仅有注解、两处分支赋值和一次迭代，未被当作可变容器使用。相对于 R9 绑定 bytes 的 +4 变化与单一类型词替换相符，未见其他 production/test 变更；delivery 对此限制与通过条件的记录也与当前源一致。

4. **Validation5/Validation6 边界诚实：闭合。**

   当前 taskbook §12.6 与 delivery `STATIC_REWORK10` 明确记录 Validation5 Parser/identity/focused6 历史 PASS、mypy 唯一 list-invariance 首失败、Ruff/cold/exact8 scope UNRUN，以及合同内 `resource_release.log` 为 `MISSING` 且不得伪补；Validation6 尚未运行。delivery 没有把 focused6 历史 PASS 或外层资源旁证写成本轮 mypy、资源 artifact 或 Validation6 PASS，并保留后续新的 no-clobber/资源修正边界。

### 独立静态对抗反例（实现者未使用；非 P2 发现）

- **现象：** 若 `_flow_bucket` 后续消费者尝试执行 `numeric_pairs.append(...)` 或把它传给要求 `MutableSequence[...]` 的 helper，当前 `Sequence[...]` 应在静态类型检查阶段暴露非法可变消费；若为“消除错误”把注解改回 `list[...]`，则重新隐藏只读契约并回到原 list invariance 缺陷。该反例未被本轮实现者使用。
- **根因：** `numeric_pairs` 在运行时确实由两个 list/alias 提供，但消费者只需单次遍历；把实现容器类型泄露为 mutable list 会同时放宽 API 约束并重新触发协变不成立的问题。
- **应遵循规则：** 保留既有 `Sequence[T_co]` 注解，禁止在该 alias 上 append/extend/复制转换；需要改变生产元素时必须另行修改实际 producer 分支并重新冻结合同，不得在 R10 通过改回可变容器。
- **最小复现：** 在 `src/quant/data/audit_tushare_financials.py:_flow_bucket` 的 `for` 之前加入 `numeric_pairs.append((current, type2, previous))`，或调用参数为 `MutableSequence[...]` 的 helper；静态上应拒绝该消费。将注解改回 `list[...]` 会掩盖这一反例，但违反 §12.6。
- **新增测试/验证节点：** 以 `tests/unit/test_audit_tushare_financials.py::test_flow_and_publisher_bucket_order_is_exact_and_stable` 继续锁 runtime bucket 顺序，并在未来 Validation6 的 mypy production2 阶段保留该负向类型边界；本轮 §12.6 禁止修改 tests2，故不伪造测试或 mypy 已运行。
- **通过条件：** 当前 `Sequence[...]` 唯一注解保持不变，numeric_pairs 只被两处分支赋值及一次迭代消费；非法 append/MutableSequence 需求不能通过静态类型闭合，且 Q1/Q2/Q3/FY 的 runtime 对象、alias、顺序、`None`、operand 与计数不变。当前实现满足，故该反例不形成 P0/P1/P2。

### STATIC_REWORK10 最终判定

`REVIEW_READY / STATIC_REWORK10_REVIEW_PASS`。本轮未发现 P0/P1/P2 或越界写；全部历史 review 保留。PASS 后不得自行 Validation6，且不得把本报告表述为执行验证、真实 audit/snapshot、R3/PIT 或 Gate 已通过。

## FINAL_EVIDENCE_REVIEW_PASS（2026-08-29）

### 最终结论与边界

- 本节由同一原独立 reviewer 追加；首轮 `REVIEW_FAIL`、REWORK4/REWORK5、STATIC_REWORK6/7/8/9/10 及其全部 P0/P1/P2、STOP、UNRUN 与历史证据均保留，未删除或改写。
- 最终结论：`FINAL_EVIDENCE_REVIEW_PASS`；当前 P0=0、P1=0、P2=0。未发现证据 SHA、边界或 scope 漂移，也未发现越界写。
- 允许的最终边界仅为 `Windows development validation / IMPLEMENTED_PENDING_REAL_AUDIT`。本节不把任何 carrier scope STOP、scope-only 闭包或 delivery 文字提升为真实 audit-v4、snapshot READY、R3/PIT、Linux/WSL Gate 或真实财务数据质量通过。
- 本轮仅做静态文件/证据内容与元数据核对；未运行 Python、pytest、Ruff、mypy、cold、DuckDB/Parquet、真实 data/audit/snapshot、network、stage、commit 或 cleanup。

### 当前 exact7 与 review 写入前绑定

写入前的当前文件哈希/字节数如下；taskbook、roadmap、production2、tests2、delivery 在本轮读取期间保持稳定：

| 文件 | SHA256 | bytes |
|---|---|---:|
| taskbook | `3f14c07f86da3ec547d5dfe13fbd4e763656881b2e111b489326f50c8a3085de` | 67073 |
| roadmap | `ca1ca28cce9355ab75ad52c41c082230dc2951007aba78d2679fc395686acd9f` | 47764 |
| audit production2 | `f1ecadb31060a1f53a99909681808fc0ccae53ea99012d5665b5cc0c7ca776e0` | 80516 |
| publisher production2 | `2dd31a6ed82d8b39f28a7873ee26f2a0e1ef7140acf44c1c4d02fada17dbaee2` | 60065 |
| audit test | `72ccf54ef0cdb824b17041e5bed05aa0c8b7957a4a8d9956114be347578f8f7c` | 94983 |
| publisher test | `8e14cebb1e8b82e92816d29940092d21098f29fde863174c8e27025d2fe50632` | 33300 |
| delivery | `80c087d4e8c6168ca506375ac465bbb709a736c8fe71853ef5ddf9b5e5d9c7c4` | 76176 |
| review（写入前） | `5db38084d506bae3467fd586715487e14c7b3c3de2736b95d830b1f1e10ad68e` | 84866 |

本轮 reviewer 只写入既有 review 文件；所有 evidence/temp/cache 仅读取。V9 的 `01_status_paths.txt` 仍是既有 exact8 路径集合，当前 review 内容变化不改变 status path 集合；未观察到新的 dirty path。

### 中央 grant 与原生 evidence 的逐项核对

1. **Validation6：产品阶段绿色，但不是全绿。**

   taskbook §12.7 与 delivery 同样记录 Validation6 的 Parser、identity、focused2、mypy production2、Ruff exact4、cold 均 PASS；实际 V6 `summary.log` 也逐项记录 `01_identity=0`、`02_focused2=0`、`03_mypy=0`、`04_ruff=0`、`05_cold=0`。关键原生文件 SHA 经静态核对一致：focused2 `3ed6fd346dfc27ee652c412ba643af3d0da21f1402843af29da686c1fa3151bf`/100 bytes，mypy `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2`/44，Ruff `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`/19，cold `f2fa5abb3a94f7638617a512fe5f805721df611e0918049ef9780a23a332da3b`/18，runner `f289fc52c44c43cd6faf290a729de50621261cf6758ad5f8b469b8e5b9d7c493`/9676，summary `ef8b723f5fdf86f83d5c4b08b75a4f1d5b37417e0d52c893c944bde73521320c`/233。

   V6 的 raw status 是含 NUL 终止符的 464-byte stdout；`summary.log` 的最终 STOP 为 PowerShell 5.1 对空尾 record 执行 `Substring(3)` 时的 scope-carrier 异常。因此权威状态只能是 `PRODUCT_GREEN / SCOPE_CARRIER_STOP`，不能改写为 Validation6 全绿。resource finalization 的五个 SHA 也与 taskbook/delivery 原文一致：terminal `722594f855bb9a887c3a9c5416e98a87bbfef79d253ae5d93d400abae4cc1003`、self-restored `b454c9068b3b6c7fd4106f99da44dbb95a60ece0e816b7b8f9d2c8f8ef2d6037`、known-children `edc19edf4c9d775707e2981842dba49711c3dc08f8af5da46b3dd3914d97d100`、python-presence `d950b4e86f37941c3520e2f6072e72fac7dd04015e53cf27644030cfef1c1216`、finalization `e8a04bf0a88930c2a0d5d2e95cf84b0ed16c357615f11c3e4ca7e2571aec9800`。该 finalization 不补写 Validation5 缺失的 `resource_release.log`。

2. **Validation7：过严 cache preflight STOP，不是产品/taskbook 失败。**

   V7 原生 `summary.log` SHA 为 `4d150ae26e6b73ff9d36a7fd38ebd638c57bc5d9b8f0509ad40b779512566a69`，内容为 `STOP:APPROVED_CACHE_NOT_ABSENT`、`PRODUCT_STAGES=NOT_RUN`、`SCOPE_STATUS=UNRUN`；cache preflight 原文记录 `.pytest_cache`、`.ruff_cache`、`.mypy_cache` 存在。taskbook/delivery 均明确 §12.6 没有冻结“worktree 根级 cache 必须不存在”的 absent 条件，因此 V7 只能是 `PREFLIGHT_STOP / SCOPE_NOT_EVALUATED`。cache、V7 evidence root 与这段历史不得被 cleanup 或文档删除后重新包装成产品失败/成功。

3. **Validation8：baseline 可信，status-path return pollution 仍只影响 scope。**

   V8 原生 baseline manifest 为 exact 27 files、2694 bytes，manifest/digest 为 `a1fa6231c070d99c22851c1e8828a6d3e63a50c2e86a0899f23e9990d86a59ba`；实际 pre-manifest 与文档一致。native status stdout 为 464 bytes、SHA `c6612035a17758c9081e7facc4d9773af535187dccee39150314d91375b6fb3a`，V8 summary SHA 为 `440706fcafac64f0c15bf525f4e2cef72e1833de80905095664257dc8d849c0d`，原文先有 `CACHE_PRE=PASS`，随后为 `ReadAllBytes` path-format STOP。

   静态读取 V8 runner 可见 `Invoke-GitRaw` 中 `CopyToAsync(...).GetAwaiter().GetResult()` 的非合同返回未被抑制，调用方把 status path 作为多值对象传给 `ReadAllBytes`；V9 runner 改为显式输出路径参数并对非合同返回使用 `[void]`，与 delivery 所述 status-path pipeline pollution 相符。故 V8 权威状态仍为 `CARRIER_STOP / SCOPE_NOT_EVALUATED`，不能被写成产品/taskbook 合同失败，也不能因 V9 修复而删除 V8 历史。

4. **Validation9：仅 scope-only 闭包，无产品重跑。**

   V9 原生 `summary.log` SHA 为 `afabb0b4c30113db062c0462ea51004ae2908583d39412fdc4775e5d694a5c9c`，逐项记录 `CACHE_PRE=PASS`、`STATUS_EXACT8=PASS`、`CACHED_RAW_EMPTY=PASS`、`DIFF_CHECK=PASS`、`ROOTS_RETAINED_IGNORED=PASS`、`PROCESS=PASS;F00_NOT_ACQUIRED`、`CACHE_POST_IDENTICAL=PASS`。pre/post cache manifest 实际均为 2694 bytes、SHA `a1fa6231c070d99c22851c1e8828a6d3e63a50c2e86a0899f23e9990d86a59ba`；raw NUL status 两份均为 464 bytes、SHA `c6612035a17758c9081e7facc4d9773af535187dccee39150314d91375b6fb3a`；过滤唯一空尾后的 decoded exact8 path 文件为 448 bytes、SHA `c84195caefbeb1da2e69f6fb04411d8da1b22ebbb97844939b14b474850514cf`；cached raw 为 0 bytes、SHA `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；diff-check stderr 仅既有 LF→CRLF warning、SHA `e38e6f6335acd611aaaec8d8c5be4377785b8855f715218ebf1b176dadf0794b`。

   V9 runner/summary/terminal/process 关键 SHA 也与 delivery/taskbook 原文一致：runner `b025ecb61fccbd75e6faafb10319f207883a471906cc062adfab88d807375a2a`、summary `afabb0b4c30113db062c0462ea51004ae2908583d39412fdc4775e5d694a5c9c`、terminal `c26de83abdc9496cd1301470918ec39ecca1cf389ef0ae1c6504da1800d1c431`、process `8393b61af401a68f4b1beb9ba4b3ea40fdab36213c224b8f9af1af1e605b0031`。V9 evidence root、V1–V6 retained temp roots 与既有 cache 现场均存在；V9 没有 Python、产品测试、audit 或 snapshot 调用。因此 V9 只能证明 baseline-aware scope-only 闭包，不能冒充产品重跑或真实 audit 证据。

### 独立静态对抗反例（实现者未使用；非 P2 发现）

- **现象：** 一个不严谨的最终摘要器若只看到 V6 `01_identity..05_cold=0` 和 V9 多项 `PASS`，就可能把 V6 写成全绿；或把 V7/V8 的 carrier STOP 从 delivery/review 删除；或把 V9 的 scope-only `STATUS_EXACT8/CACHED_RAW_EMPTY/DIFF_CHECK` 写成 product/real-audit PASS。
- **根因：** 混淆阶段 exit code 与完整验证状态，混淆 carrier scope 与产品合同，混淆 scope-only Git/cache 证据与生产代码/真实数据执行证据；删除历史还会破坏可追溯性和 no-clobber 约束。
- **应遵循规则：** 必须同时保留 `Validation6 = PRODUCT_GREEN / SCOPE_CARRIER_STOP`、`Validation7 = PREFLIGHT_STOP / SCOPE_NOT_EVALUATED`、`Validation8 = CARRIER_STOP / SCOPE_NOT_EVALUATED`、`Validation9 = scope-only closure`；V7/V8 evidence/cache 不得删除，V9 不得冠以 product/audit/snapshot 语义，最终边界只能是 Windows development validation / `IMPLEMENTED_PENDING_REAL_AUDIT`。
- **最小复现：** 将 delivery §12.7 的 V6 STOP 行删掉、将 V7/V8 小节删掉，或把 V9 小节的“无 Python、无 0xF00、scope-only”替换为“产品验证通过”；再对照实际 V6 `summary.log`、V8 `terminal.log`、V9 `summary.log` 与各自 runner SHA，即可得到文档—原生 evidence 不一致。
- **新增检查：** 后续 evidence-review/SAFE_COMMIT 前应以固定表逐项比对三种状态字符串、root/summary/runner SHA 与“是否调用产品阶段”字段；本轮只读审查不修改 evidence、cache 或测试，也不伪造该检查已执行为 Validation10。
- **通过条件：** 当前 taskbook、delivery 与本 review 同时保留上述四种边界，关键原生 SHA/bytes 与实际 evidence 相符，V9 cache pre/post 双算一致且 exact8/cached0/diff/roots 证据不漂移；当前满足，故该反例不形成 P0/P1/P2。

### FINAL_EVIDENCE_REVIEW 最终判定

`REVIEW_READY / FINAL_EVIDENCE_REVIEW_PASS`。当前无 P0/P1/P2、无 SHA/boundary/scope 漂移、无越界写；全部历史 review 与 V6–V9 STOP/UNRUN 边界保留。该 PASS 不授权自行 Validation、SAFE_COMMIT 或真实 audit，不代表任何 Gate 通过。
