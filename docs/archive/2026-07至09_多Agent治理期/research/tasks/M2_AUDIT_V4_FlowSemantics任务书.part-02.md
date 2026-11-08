1. **publisher snapshot safe projection**：snapshot projection 禁止对 raw economic columns 使用
   `union_by_name=True`。publisher 必须先按 per-file schema signature 分组，将每组显式投影到既有
   canonical snapshot schema，再只对同构 projection 执行 `UNION ALL`。它与 audit B1 共享同一个
   safe-projection 公共合同与字段类型规则；禁止复制第二套科学语义，也禁止把 B2 token/classification
   relation 当作 clean output。publisher projection 阶段每个 raw file exact 读取一次，整体仍保持
   `pre audit -> strict validate -> mkdir/projection -> post audit` 三遍，不新增第四遍经济全表 I/O；output
   file set、schema、列顺序和 row count 必须不变。无法稳定投影时 fail closed 并申请扩围。
2. **真实 mixed relation 反例**：BOOLEAN/VARCHAR/DOUBLE 必须由受控真实 Parquet 与真实 DuckDB connection
   执行 B1 relation，逐字锁定 actual columns、rows、source filename、每文件单读、single homogeneous
   union、file/schema/row order invariance，以及 B2 四条 parallel sequence 的逐索引绑定和唯一
   canonicalizer。SQL 字符串、`inspect.getsource`、fake connection 或纯 helper 不能替代此行为证据。
3. **真实身份/漂移调用链**：测试必须沿真实生产调用链覆盖 source filename 不在 frozen inventory、duplicate
   filename、per-file schema drift、pre/post source-evidence SHA drift、required nested/binary 的
   `BLOCKED` 与 invalid-numeric/audit-invalid 边界，以及 audit bytes drift、missing/invalid audit SHA、
   manifest canonical drift。每个反例必须证明在 snapshot mkdir 或 public object 返回前 fail closed；
   delivery 只能声称实际 test node 覆盖的边界。
4. **required-field 边界**：publisher 仅在 exact required economic field 的 source type 为
   nested/binary/untokenizable 时接受 `BLOCKED` 语义。non-required extra nested/binary 只保留 provenance，
   不参与 safe projection/flow，也不得单独阻断；required nested/binary 仍须保留 source evidence、按
   distinct pair 聚合、economic stage C zero-call，并在 snapshot mkdir 前拒绝。
5. **economic key 唯一身份**：唯一 SSOT 为
   `(symbol, end_date, report_type, comp_type)`。current/type2/previous selection、lookup、stable sort、类型标注
   和测试必须全链使用该 exact 顺序；禁止内部一致但与合同顺序不同的替代 tuple。
6. **publisher v3 cross-field 守恒**：每个 dataset 必须满足
   `complete_rows == quality.raw_rows`。所有相关 counter 继续要求 exact `type(x) is int`、nonnegative、拒绝
   bool；任一非负整数漂移也必须在 snapshot mkdir 前失败。第 11 节的其他 row/date/dimension/byte、quality
   domain、request/status 与 flow funnel 守恒均不得削弱。

REWORK5 的实现写集合仍仅为 production2、tests2 与 delivery；taskbook、roadmap、review 只读。实现与复验均
保持 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`，不得运行 Python、DuckDB/Parquet、pytest、Ruff、mypy、
cold、network、stage 或 commit。交付后必须恢复同一独立 reviewer，在原 review 文件追加逐项复验；只有
`REVIEW_PASS` 后才可申请 validation-only。

### 12.2 STATIC_REWORK6 冻结合同

首轮至 REWORK5 的全部任务书、delivery、review、P0/P1 与返工历史继续永久保留。本节追加中央对 REWORK5
独立复验的最终裁定，状态为 `STATIC_REWORK6_CONTRACT_APPROVED`；当前仍禁止 validation、真实 audit、
snapshot、R3、PIT、stage 或 commit。实现者不得将本节缩减成单点补丁，必须同时闭合以下六项：

1. **publisher quality strict evidence**：每个 dataset 的 quality 必须使用 exact key set。
   `column_set_count == len(column_set_sha256s)`；digest 列表顺序必须与 audit canonical 顺序一致，每个值均为
   exact lowercase hex64，禁止重复、别名或内部排序后接受。`required_numeric_union_types` 必须以 exact
   key/order/type/value family 与该 dataset 的 required numeric fields 完整对应。缺失、额外、乱序、非法、
   count/digest/type 漂移均须在 snapshot mkdir 前拒绝，第 11 节其余 v3/flow 守恒不得削弱。
2. **public snapshot manifest counters**：`_verify_snapshot` 必须对 manifest `request_count`、每个 file entry 的
   `rows`/`size_bytes` 以及全部其他计数执行 exact `type(x) is int`、nonnegative、reject bool。
   `request_count` 与已验证 raw/request closure 相等；file rows/bytes 与实际 Parquet height/文件 bytes 相等；
   dataset/file totals 与 manifest/audit closure 交叉一致。任何类型、范围或守恒漂移均在 public
   `TushareFinancialSnapshot` 返回前拒绝。
3. **合法 publisher fixture 先闭合**：`fina_indicator` 必须带 exact empty `report_type_counts`、
   `comp_type_counts`、`report_type_comp_type_counts`。每组 mutation test 必须先断言未变异 baseline 能通过
   strict validator，再只改变目标字段；禁止以本来就非法的 fixture 冒充目标反例已到达。
4. **economic key 可区分回归**：用同 symbol/end_date 的 `(report_type,comp_type)=("1","2")` 与
   `("2","1")` 直接断言 `_flow_key == (symbol,end_date,report_type,comp_type)`，并覆盖 current/type2/previous
   lookup 与 stable sort 不交叉匹配。测试必须能使旧 comp-before-report 顺序失败。
5. **flow derived bounds**：publisher strict validator 还必须拒绝不可能但 nonnegative 的派生计数：
   `distinct_symbols <= current_type1_candidates`、`fiscal_years <= comparable_observations`，且
   `comparable_observations == 0` 时 `fiscal_years == 0`。所有反例必须沿公共 publisher 在 snapshot mkdir 前
   fail closed，同时保留第 10 节漏斗等式、coverage 和 status 复算。
6. **真实行为与 single-read 证据**：
   - 使用真实受控 Parquet、真实 DuckDB connection 执行生产 audit B1 与 publisher projection query，并读取
     actual result。required STRUCT/BLOB 必须沿真实 source schema 到 `_audit` 形成
     `BLOCKED`、保留 evidence、economic C zero-call，再沿公共 publisher 在 mkdir 前拒绝；extra nested 仅
     provenance 且不阻断。
   - “每文件 single read”唯一含义是每个 stage/query 内的逻辑 economic scan membership exact1，不要求 OS
     handle open 次数，也不要求 DuckDB 未排序 relation 保持物理 raw 行序。schema grouping 必须是 frozen
     inventory 的 exact、disjoint、complete partition；每个 canonical relative file 只属于一个 schema-group
     `READ_PARQUET` input。
   - 对同一真实 production SQL 使用当前 DuckDB 可用的 JSON EXPLAIN/profiling operator evidence，优先使用
     profiling 的 `READ_PARQUET` operator 与 `Total Files Read`。每个 schema group 必须 exact 一个
     `READ_PARQUET` economic scan，所有 scan 的 file-count 总和等于 inventory count，且不存在第二 economic
     scan。若当前版本不稳定输出逐文件名，允许用真实 operator 的 `Total Files Read` 加 production grouping
     exact disjoint-cover 联合证明；禁止 fake connection、`inspect`/source 字符串或 OS trace。
   - 分别反转 file list、schema-group 顺序及各 Parquet 内部 row 顺序；比较 canonical-sorted actual relation、
     canonical snapshot schema/rows/file set/semantic hashes 等价。只有既有 publisher 已冻结 deterministic
     bytes 的产物才要求 byte exact，不新增物理 raw-row-order 不变量。
   - 若 EXPLAIN/profiling 无法在现有依赖与白名单内稳定提供 operator/count 证据，立即
     `STOP / EVIDENCE_CONTRACT_UNIMPLEMENTABLE` 回中央；不得降级为字符串断言或新增 instrumentation/shared
     module。

REWORK6 delivery 必须按“现象—根因—应遵循规则—最小复现—新增测试—通过条件”逐项记录，并更正
REWORK5 对真实调用链/per-file read 的过度覆盖措辞。唯一实现写集合仍为 production2、tests2、delivery；
taskbook、roadmap、review 只读。实现与复验继续 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`，不得运行
Python、DuckDB/Parquet、pytest、Ruff、mypy、cold、network、audit、snapshot、PIT、stage 或 commit。只有同一
原独立 reviewer 最终 `REVIEW_PASS` 后才可申请 validation-only。

### 12.3 Validation1 STOP 与 STATIC_REWORK7（tests-only）

Windows Validation1 使用最终稳定 exact8 执行，并在首个可信产品阶段失败后立即停止。权威 evidence root 为
`artifacts/agent_runs/m2-audit-v4-validation1-20260828T151956Z`；summary SHA256 为
`0985a9444bd5a594bd946d63c30e2975800879d960890012f07639c087a90544`，pytest stdout SHA256 为
`cc9a2be97f2964806319d05346984cb2d6f2723898fb7e2c5fd57e790e5e319e`。identity PASS，collect-only
54 collected，两个 unit 文件合计 6 failed / 48 passed / 14.09s；Ruff、mypy、cold、scope closure 均
UNRUN。资源已释放，Python/0xF00 为 0，fresh basetemp 与 no-clobber evidence 保留；未运行真实 audit、
snapshot、R3、PIT 或 network，未 stage/commit。本轮没有 carrier failure，六项失败均为既有测试、fixture 或
import 与 REWORK6 合同同步缺口；当前证据不支持修改 production 或判定授权 publisher 路径 fail-open。

STATIC_REWORK7 只允许同一原 implementer 修改：

- `tests/unit/test_audit_tushare_financials.py`；
- `tests/unit/test_publish_tushare_financials.py`；
- `docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`。

production2、roadmap、taskbook（实现阶段）与 review 均只读。不得夹带独立 reviewer 已登记的
`Q1 latest_previous_conflicts` P2 债，亦不得借修 fixture 放宽 strict validator。六项冻结如下：

1. **parameter-window A/B 双分支**
   - 现象：既有测试以默认 `verify_bytes=False` 调用 future announcement fixture，期待 `BLOCKED`，实际 top
     status 为 `READY`。
   - 根因：第 3 节 A prerequisites 已要求 `verify_bytes is True`；A 未闭合时 source identity、safe projection
     与 economic helpers 全部 0-call。旧测试仍按旧 v3 默认调用期待 B base-quality 执行。
   - 应遵循规则：同一反例必须同时锁两条分支。默认 false 时要求 flow `NOT_EVALUATED`、`buckets=[]`、empty
     source evidence、`publication_allowed=false` 且 B/C helper 0-call；显式 true 时进入 B，必须 top
     `BLOCKED`、`request_window_mismatches==1` 并包含 `INCOME_REQUEST_WINDOW_MISMATCH`。不得只把 expected
     改成 `READY` 而删除 fail-closed 反例。
   - 最小复现：income `ann_date=20250101`、`f_ann_date=20250102`，request window 仍为冻结 fixture window。
   - 通过条件：false 短路身份与 true BLOCKED 计数/错误码均逐字闭合；production 不变。

2. **physical-row-drift A/B 双分支**
   - 现象：既有测试把 income Parquet 从 1 row 改为 2 rows，只同步 bytes/checksum/size、不改 ledger/metadata
     rows；默认 false 调用期待 `BLOCKED`，实际 `READY`。
   - 根因：与第 1 项相同，`row_count_mismatch` 由 B safe relation 计算，A 未闭合时不得运行。
   - 应遵循规则：默认 false 必须锁同一 NOT_EVALUATED/publication-false/zero-call 边界；显式 true 必须
     `BLOCKED` 且 `row_count_mismatch==1`。不得修改 ledger rows 或把 duplicate row 当合法修订。
   - 最小复现：保留当前受控 Parquet duplicate、checksum/size 同步和 ledger row count=1。
   - 通过条件：两条分支同时通过并证明 safe projection 未削弱 v3 physical-row drift 检测。

3. **mixed safe projection 的 authoritative statement exact10 schema**
   - 现象：真实 DuckDB production query 已执行到 actual result；测试错误期待六列，实际从 index 2 开始包含
     `f_ann_date`，并保留 `report_type`、`comp_type`、`update_flag`。
   - 根因：测试把 statement canonical snapshot schema 写成旧的缩减形态；authoritative base/current
     `_projection_sql` 均保持 statement exact10，production 没有 schema 回归。
   - 应遵循规则：cashflow exact columns 必须为
     `symbol,ann_date,f_ann_date,available_date,end_date,report_type,comp_type,update_flag,n_cashflow_act,source`。
     继续用真实 BOOLEAN/VARCHAR/DOUBLE Parquet 和真实 DuckDB production query，锁 actual columns/rows、
     JSON profile `READ_PARQUET/PARQUET_SCAN`、`Total Files Read`、schema-group disjoint cover，以及 file list、
     group order、Parquet row order invariance。禁止删 production 身份列迎合测试。
   - 最小复现：沿既有 mixed-source node 的 first/second publisher projection。
   - 通过条件：exact10、canonical rows、scan 分组/文件总数及全部 order invariance 闭合。

4. **source-evidence order fixture 的 exact required fields**
   - 现象：order-invariance test 的 fake income `_SourceSchema` 只提供 `n_income`，production 按 exact required
     fields 读取 `n_income_attr_p` 时触发 `KeyError`。
   - 根因：旧 fake fixture 不满足 REWORK6 exact required economic field closure；不是 production 应放宽的
     输入。
   - 应遵循规则：cashflow fake schema/economic types 必须含 exact `n_cashflow_act`；income 必须同时含 exact
     `n_income` 与 `n_income_attr_p`。正反 file order 的 evidence 与 SHA 必须相同；另保留缺任一 required field
     fail-closed 反例，禁止 catch `KeyError` 或让 production `.get()` 静默接受。
   - 最小复现：现有 income+cashflow stub items 与正反 order 调用。
   - 通过条件：完整 fixture 无 KeyError且 identity order invariant；缺字段路径稳定拒绝。

5. **public verifier import**
   - 现象：合法 snapshot baseline 首次调用 `verify_tushare_financial_snapshot` 即 `NameError`，production 尚未
     被测试。
   - 根因：publisher test 的 public import list遗漏 verifier。
   - 应遵循规则：仅补 public verifier 的显式 import，或按文件既有风格使用 module-qualified public symbol；
     不改 production。
   - 最小复现：既有合法 snapshot baseline。
   - 通过条件：baseline 先 PASS；随后 request/dataset/file counters、rows/size/actual bytes drift 逐项在 public
     object 前拒绝；恢复 baseline 后再次 PASS。

6. **required/extra nested fixture 的全部派生 identity 同步**
   - 现象：extra non-required `STRUCT` 追加到 source schema 后只重算 flow source evidence SHA，strict
     `_validate_quality_evidence` 从 schema 重算 column-set digest 时发现 quality 仍为旧 digest并拒绝。
   - 根因：fixture mutation 未同步所有由 source schema 派生的 quality/source identity；strict production 拒绝
     stale digest 是正确行为。
   - 应遵循规则：extra nested 候选必须同步对应 dataset 的 `column_set_count/column_set_sha256s`，required union
     保持不变，形成自洽 audit 后 `_validate_audit(extra)` 必须通过；required STRUCT/BLOB 候选必须同步 schema、
     `required_economic_types`、flow evidence SHA、quality column digest 与 `required_numeric_union_types`，再证明其
     因 exact required untokenizable 边界被拒且 public publisher 在 snapshot mkdir 前停止。禁止以 stale digest
     造成的任意 `ValueError` 冒充 required nested Gate。
   - 最小复现：既有 balancesheet source evidence 首项的 `extra_nested` 与 `total_assets` mutation。
   - 通过条件：extra nested provenance-only 正向验证通过；required nested 的拒绝原因精确，且 clean snapshot
     目录不存在。

实现者必须在 delivery 为六项逐一记录“现象—根因—应遵循规则—最小复现—新增测试—通过条件”，并保留
Validation1 全部有效阶段、SHA、后续 UNRUN 和 evidence/basetemp 保留边界。STATIC_REWORK7 仍为
`STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`：零 Python、DuckDB/Parquet 执行、pytest、Ruff、mypy、cold、
network、audit、snapshot、R3、PIT、stage、commit。交付后由同一原独立 reviewer 仅写原 review 复验；只有
REVIEW_PASS 后才可向中央申请新的 postfix validation，禁止直接重跑 Validation1。

### 12.4 Validation3 STOP 与 STATIC_REWORK8（audit test style-only）

POSTFIX Validation2 在任何 Python/affinity/产品阶段前因 PowerShell runner 的变量邻接冒号语法错误停止；其
产品状态为 NOT_EVALUATED，不改变 REWORK7 的静态结论。随后中央仅修正 carrier 中两处
`${Name}`/`${name}` 变量消歧，并用新的 no-clobber evidence/temp roots 执行 POSTFIX Validation3。Validation3
权威 evidence root 为
`artifacts/agent_runs/m2-audit-v4-postfix-validation3-20260828T155444Z`，temp root 为
`artifacts/validation_tmp/m2-audit-v4-postfix-validation3-20260828T155444Z`（首失败保留）；runner SHA256 为
`c525772c9684d724ea7a75c64a75874750362375cd3810594660843822e18a66`，summary SHA256 为
`f3affdd125c1715f0f37af847bb21c03445484130476468b4c376e4bda086d20`，pytest stdout SHA256 为
`6fc1aa5e87194bbcb8d89f77d69bacadc016b59e98273c51f0eb8ed76e9367f8`，Ruff stdout SHA256 为
`c5fb83b6375c6addfe1a0fea6a19bfa92c3d813a3fc436c6d25414718c1ae566`，Ruff empty stderr SHA256 为
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`，resource-release SHA256 为
`66962a6c85ff31fd199d274c09798760936e081f4005a7c00b2956d3c4800447`。

Validation3 的 Parser、identity 与 collect-only 均 PASS（54 collected / 2.69s），完整两个 unit 文件 PASS
（54 passed / 14.15s）。首个失败阶段为 Ruff exact4：唯一 `E731` 位于
`tests/unit/test_audit_tushare_financials.py:1683`，现有局部赋值
`finite = lambda value: financial_audit._CanonicalOperand("x", "finite", value)` 必须改为局部 `def`。mypy、
cold 与 scope 均 UNRUN；资源已释放并恢复 Normal/0xFFF，退出后 Python=0、0xF00=0、cached0，ordinary
`git diff --check` PASS。Validation1/2 evidence/temp 未覆盖，未运行真实 audit、snapshot、data、network，未
stage/commit。该 STOP 是 tests-only 静态风格缺口；production 与本轮 54 项行为证据保持绿色，但不得据此
宣称后续未运行阶段或真实 Gate 通过。

STATIC_REWORK8 只允许同一原 implementer 修改：

- `tests/unit/test_audit_tushare_financials.py`；
- `docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`。

`tests/unit/test_publish_tushare_financials.py`、production2、roadmap、taskbook（实现阶段）与 review 均只读。
唯一允许的代码变化是把上述局部 lambda 机械改为：

```python
def finite(value: float) -> financial_audit._CanonicalOperand:
    return financial_audit._CanonicalOperand("x", "finite", value)
```

返回对象、token/category/projected 数值语义、既有调用点、参数值和断言必须逐字保持；禁止新增 `Any`、
`cast`、`type: ignore`，禁止移动或泛化 helper，禁止修改 production 或其他测试节点。delivery 必须记录：

- **现象**：Validation3 完整 tests2 已 54 passed，Ruff 唯一 E731 指向该局部 lambda；
- **根因**：测试 fixture 用赋值 lambda 表达简单命名函数，不符合 Ruff E731；
- **应遵循规则**：用带 exact `float` 参数和 `_CanonicalOperand` 返回类型的局部 `def` 表达同一纯构造语义；
- **最小复现**：仅对该测试文件运行 Ruff 即命中 line 1683 E731；不得把完整单测 PASS 误写为 Ruff PASS；
- **新增测试/验证**：本次不新增行为节点；同一独立 reviewer 先静态确认唯一机械 diff，随后另申请
  POSTFIX Validation4；
- **通过条件**：audit test 与 delivery 之外无新业务 diff，局部 `def` 类型可解析，返回/调用/断言语义不变，
  review P0=P1=0。Validation4 仅需 identity → Ruff exact4 → mypy production2 → cold → exact8 scope，不重复
  Validation3 已绿的 collect/full tests2，除非 reviewer 发现行为漂移。

STATIC_REWORK8 继续 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`：零 Python、DuckDB/Parquet 执行、
pytest、Ruff、mypy、cold、network、audit、snapshot、R3、PIT、stage、commit。交付后由同一原独立 reviewer
仅写原 review 复验；PASS 后另向中央申请 POSTFIX Validation4，不得自行运行或自动重试。

### 12.5 Validation4 STOP 与 STATIC_REWORK9（production type-only）

POSTFIX Validation4 使用新的 no-clobber evidence/temp roots，未重复 Validation3 已绿的 collect/full tests2。
权威 evidence root 为
`artifacts/agent_runs/m2-audit-v4-postfix-validation4-20260828T160859Z`，temp root 为
`artifacts/validation_tmp/m2-audit-v4-postfix-validation4-20260828T160859Z`（首失败保留）；runner SHA256 为
`a872d76a2c4f3f002ac98754343708c49985ac12127597e92689afc627d21cf9`，summary SHA256 为
`b0545b1e3a1dc6d629bc9e7322657560c2f089285febb12acee710c273ae7e60`，Ruff stdout SHA256 为
`82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`，mypy stdout SHA256 为
`92e8b35f0174b15f9fd09f048dab0230ce657b593e5c53394b0743d768ec0b33`，mypy empty stderr SHA256 为
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`，resource-release SHA256 为
`66962a6c85ff31fd199d274c09798760936e081f4005a7c00b2956d3c4800447`。

Validation4 Parser、identity 与 Ruff exact4 均 PASS；mypy production2 首失败为 6 errors，cold 与 scope
UNRUN。资源已恢复 Normal/0xFFF，退出后 Python=0、0xF00=0、cached0，ordinary `git diff --check` PASS；
Validation1–3 evidence/temp 未覆盖，未运行真实 data、audit、snapshot、network，未 stage/commit。六项错误归为
四处 production 类型表达缺口，不是 carrier 或业务合同矛盾；此前 tests54/Ruff 绿色不能冒充 mypy 通过。

STATIC_REWORK9 只允许同一原 implementer 修改：

- `src/quant/data/audit_tushare_financials.py`；
- `src/quant/data/publish_tushare_financials.py`；
- `docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`。

tests2、roadmap、taskbook（实现阶段）与 review 均只读。唯一允许的 production 修改如下：

1. **audit numeric-pair 联合容器注解**
   - 现象：Q1 comprehension 令 `numeric_pairs` 推断为
     `list[tuple[_FlowObservation,_FlowObservation,None]]`，else 将
     `list[tuple[_FlowObservation,_FlowObservation,_FlowObservation]]` 赋给同一变量时触发 mypy assignment。
   - 根因：互斥分支共享容器但缺少第三元素的显式联合类型；运行时分支和元素语义正确。
   - 应遵循规则：仅在互斥分支前增加
     `numeric_pairs: list[tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]]`；Q1
     comprehension 与 else `previous_pairs` 原样保留。禁止 cast、Any、复制转换或改变 previous-chain 顺序。
   - 最小复现：mypy production2 在 audit line 1891 报 list invariant assignment。
   - 通过条件：该 assignment 消失，Q1 的 `None`、Q2/Q3/FY previous observation、operand insert 与 mismatch
     计数行为不变。

2. **publisher source-evidence identifiers 先验证后收窄**
   - 现象：publisher lines 191–193 的 `entry.get()` 返回 `Any | None`，却复用本函数较早循环已推断为
     `str` 的 `dataset`、`request_id`、`relative` 名称，产生三项 assignment error。
   - 根因：函数作用域变量名复用使赋值点早于现有联合 guard，guard 无法反向收窄已失败的赋值。
   - 应遵循规则：使用新的 raw/value locals 读取三项；保持现有 exact `type(...) is str`、dataset membership、
     hex64 与 canonical-relative 等式及错误顺序；只有 guard 通过后才使用已收窄的 str。禁止新增或删除 cast、
     Any、type-ignore，禁止 truthiness、强转或放宽路径 identity。
   - 最小复现：mypy publisher lines 191–193 三项 assignment。
   - 通过条件：三项错误消失；unknown filename、not-in-inventory、duplicate/schema drift 仍在 projection 前
     fail closed，group/evidence canonical 顺序不变。

3. **publisher path 一次消费**
   - 现象：`dict[str, Path].pop(relative, None)` 的 default `None` 与 mypy 的 Path 值域不兼容。
   - 根因：用 optional default 表达 missing 检查，但 mapping 本身不是 Optional value mapping。
   - 应遵循规则：先以 `relative not in path_by_relative` 稳定拒绝，再无 default 执行
     `path_by_relative.pop(relative)`；保持一次消费、duplicate/missing fail-closed 与末尾空集守恒。禁止把 mapping
     改为 Optional、cast 或复制 Path。
   - 最小复现：mypy publisher line 204 的 pop overload error。
   - 通过条件：pop 类型闭合，存在与缺失两条运行语义及错误顺序不变。

4. **manifest request_count stable local**
   - 现象：validator 两次独立 `manifest.get("request_count")`；第一项 exact-int 检查不能让 mypy 将第二次调用
     收窄，line 489 报 `int > Any | None` 等价错误。
   - 根因：方法调用结果不是可关联的稳定 local。
   - 应遵循规则：只读取一次 stable local，并严格使用
     `type(request_count) is not int or request_count < 0`；拒 bool、nonnegative、manifest canonical 与
     public-object-before fail-closed 语义不变。禁止 `int(...)`、truthiness 或弱化 closure。
   - 最小复现：mypy publisher line 489。
   - 通过条件：comparison 类型闭合；合法 baseline 仍通过，bool/negative/request closure drift 仍在 public
     object 返回前拒绝。

四项均须在 delivery 按“现象—根因—应遵循规则—最小复现—测试—通过条件”记录。禁止逻辑重排、新增或
删除 cast、Any、type-ignore、强转、Optional mapping、复制转换、tests 修改、P2 夹带；若当前结构无法逐字满足，
立即 STOP 回中央。

同一原 reviewer 静态复验 PASS 后，POSTFIX Validation5 必须使用新 no-clobber evidence/temp roots；因
production2 字节发生变化，在 mypy 前只运行以下既有 exact focused nodes，不跑 full tests2：

1. `tests/unit/test_audit_tushare_financials.py::test_selection_conflicts_missing_drift_and_chain_have_no_fallback`
   ——直接覆盖 Q1 selection 与 Q2 previous cutoff/conflict；
2. `tests/unit/test_audit_tushare_financials.py::test_flow_and_publisher_bucket_order_is_exact_and_stable`
   ——锁定 Q1/Q2/Q3/FY 全部 bucket 调用顺序及 Q2/Q3/FY 均进入同一 previous-chain 分支身份；
3. `tests/unit/test_audit_tushare_financials.py::test_numeric_tokens_and_source_evidence_file_order_are_invariant`
   ——锁 source identity required fields、file-order invariance 与缺字段 fail-closed；
4. `tests/unit/test_audit_tushare_financials.py::test_publisher_real_chain_rejects_identity_schema_and_post_audit_drift`
   ——锁 filename 不在 inventory、duplicate evidence、schema drift 与 pre/post source identity drift；
5. `tests/unit/test_publish_tushare_financials.py::test_public_snapshot_verifier_rejects_manifest_counter_and_file_metadata_drift`
   ——锁合法 baseline、request_count bool/negative/closure mutation、file rows/size 与 baseline restore；
6. `tests/unit/test_publish_tushare_financials.py::test_publisher_rejects_bool_and_negative_audit_counters_before_snapshot_mkdir`
   ——锁 public pre-mkdir exact-int/nonnegative/reject-bool 邻接边界。

Validation5 顺序冻结为 Parser 零执行门禁 → identity → 上述 focused nodes → mypy production2 → Ruff exact4 →
cold → exact8 Unicode/NUL-safe scope、cached0、diff-check、Validation1–5 evidence/temp roots exist+ignored 与
process/resource evidence。首失败 STOP 并保留证据；全绿也保留证据待经理/中央复核。STATIC_REWORK9 及其
review 仍为 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`：零 Python、DuckDB/Parquet 执行、pytest、Ruff、
mypy、cold、network、audit、snapshot、R3、PIT、stage、commit；不得自行启动 Validation5。

### 12.6 Validation5 STOP 与 STATIC_REWORK10（covariant read-only type closure）

