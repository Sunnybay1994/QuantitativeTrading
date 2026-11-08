# M2-AUDIT-V4 财务累计流量语义审计任务书

> 状态：`TASKBOOK_READY / STATIC_ONLY`
> task id：`M2-AUDIT-V4-FLOW-SEMANTICS`
> 结论上限：`IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`
> exact base：`f6eade1fb9434673947dbc7b887c5110fe85466f`
> branch：`codex/m2-audit-v4-flow-semantics`
> worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-audit-v4-flow-semantics`
> 当前资源：`STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`

## 1. 已满足前置与目标

UA-M2-001 已权威闭合：`balancesheet`、`cashflow`、`fina_indicator`、`income`
各 `COMPLETE=44,296`，合计 `177,184`；`PENDING/RUNNING/RETRYABLE/FAILED/SPLIT_REQUIRED=0`，
active lease 为 0，writer 已自然退出。exact 1,365 条 bounded recovery 的冻结前态 full digest 仍为
`45523530323690e8ecf9f1a7649e0efbdac9ce9c99de3e5fef0f572e0f4ec966`，恢复后均为
`attempts=4 / COMPLETE`。

本包把现有 `tushare-financial-raw-audit-v3` 升级为 v4，增加 plan-bound、bytes-verified 的
type1 累计流量与 type2 单季流量语义审计，并让 publisher 在 snapshot mkdir 前逐项重算和拒绝伪造证据。
它只实现与验证审计/发布合同；真实 audit-v4 读取与 snapshot 发布必须由中央另发资源授权。

本包不等同于：financial snapshot READY、`M2-EVAL-STOP-001` 关闭、R3 完成、首个 PIT 获准、
任何研究 trial 或 PAPER 获准。

## 2. exact 8、角色与禁止项

最终提交只允许以下 exact 8：

1. 经理：`docs/research/tasks/M2_AUDIT_V4_FlowSemantics任务书.md`；
2. 经理：`docs/research/roadmaps/M2_策略与因子库并行建设路线图.md` 的 audit-v4 exact hunk；
3. 实现者：`src/quant/data/audit_tushare_financials.py`；
4. 实现者：`src/quant/data/publish_tushare_financials.py`；
5. 实现者：`tests/unit/test_audit_tushare_financials.py`；
6. 实现者：`tests/unit/test_publish_tushare_financials.py`；
7. 实现者：`docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`；
8. 不同独立 reviewer：`docs/research/reviews/M2_AUDIT_V4_FlowSemantics独立初验报告.md`。

不得交叉写 owner 文件。禁止新增 Python 模块、依赖、config/schema/repository/facade 路径；禁止修改 PIT
runner/config、financial PIT selector、共享 evaluator、lightweight run verifier、governance SSOT。禁止读取
partial raw、运行 audit/snapshot/PIT、访问网络、恢复 writer、修改 ledger 或创建 snapshot。

## 3. v4 顶层与短路

- `SCHEMA_VERSION` 升级为唯一 exact `tushare-financial-raw-audit-v4`。
- 顶层保留 v3 全部 plan/inventory/ledger/structural/bytes/dimension evidence；新增 exact
  `flow_semantics` 和其 source-type identity。不得削弱 v3 fail-closed 行为。
- `flow_decimal_absolute_tolerance` 唯一为字符串 `"0.01"`；无 relative tolerance、scale、字段、bucket
  或 dataset 特例，也不是 public 可调参数。
- 调用边界固定为 A/B/C 三阶段；本段立即 supersede 任务书及历史消息中“base quality 前 source/safe
  全部 0-call”与“v3 base quality 回退原始 `union_by_name=True`”的过严/冲突表述：
  - A cheap prerequisites：`verify_bytes is True`、active lease=0、四表 ledger exact COMPLETE 且无其他状态、
    plan/request/raw byte closure 闭合。任一失败时 source identity、safe projection、economic helpers 全部
    0-call；返回 `NOT_EVALUATED`、`buckets=[]`、`publication_allowed=false`，source evidence=[] 且使用第 5 节
    early-empty SHA。
  - B safe base-quality：A 全部通过后才允许 metadata source identity、per-schema safe normalized projection
    及 v3-equivalent row/date/dimension/base numeric quality。禁止回退原始经济列
    `union_by_name=True`。mixed BOOLEAN/VARCHAR/DOUBLE 必须进入安全同构投影与可审计漏斗，不能因 DuckDB
    common-supertype 异常提前终止。若 structural/date/dimension 失败或 source untokenizable，则 economic
    selection/chain/difference 0-call；untokenizable 按第 9 节 BLOCKED 保留真实 source evidence，不输出
    partial buckets。
  - C economic flow：只有 B 按第 7/10/11 节字段域规则闭合且 source tokenizable，才执行
    selection/chain/difference 并评价 12 buckets。
- 已评价时：任一 bucket `CONTRADICTED` 则 flow top `CONTRADICTED`；否则 12 bucket 全 PASS 才为
  `PASS`；其余为 `INSUFFICIENT`。
- `publication_allowed` 仅在 base audit READY、`verify_bytes=true` 且 flow PASS 时为 true。

## 4. 固定 12 bucket、字段与排序

固定 dataset/field exact 顺序：

1. `cashflow.n_cashflow_act`；
2. `income.n_income`；
3. `income.n_income_attr_p`。

每个字段固定 `fiscal_bucket` 顺序 `Q1,Q2,Q3,FY`，总计 12 行；最终稳定排序为
`cashflow.n_cashflow_act(Q1,Q2,Q3,FY)`，随后
`income.n_income(Q1,Q2,Q3,FY)`，最后
`income.n_income_attr_p(Q1,Q2,Q3,FY)`。禁止字典序、input order 或实现者自行重排。
统一使用美式字段名 `synchronized_type2_pairs`，废止 `synchronised` 拼写。

每个 bucket exact evidence 至少包含且 publisher 必须独立重算：

`dataset, field, fiscal_bucket, chain_applicable, current_type1_candidates, distinct_symbols,
fiscal_years, synchronized_type2_pairs, previous_chain_eligible, missing_type2, missing_previous,
latest_current_conflicts, latest_type2_conflicts, latest_previous_conflicts, available_date_drift,
missing_operands, invalid_numeric_operands, nonfinite_operands, float64_cent_resolution_lost,
comparable_observations, mismatch_count, status`。

除 Q1 的 `previous_chain_eligible`、`missing_previous` 必须为 null 外，计数均为 exact nonnegative int，
拒绝 bool。`fiscal_years` 固定为 comparable observations 中 distinct `end_date.year` 数量。

## 5. source schema/type provenance 与 safe normalized union

### 5.1 每文件 metadata identity

- 对冻结 request inventory 的每个 raw parquet，用 metadata-only schema 读取每个 required economic
  column 的 per-file logical type，并绑定 canonical relative filename 与 request identity。
- 形成 canonical per-file evidence 列表及 lowercase hex64
  `flow_source_type_evidence_sha256`。列表、normalized projection contract、token algorithm/version 进入 v4
  audit identity；pre/post audit 与 publisher 均调用同一权威 helper 重算，SHA 必须相同。
- source evidence schema/version exact：`tushare-financial-flow-source-type-evidence-v1`；normalized projection
  version exact：`tushare-financial-flow-normalized-projection-v1`；token algorithm exact：
  `float64-decimal-str-canonical-v1`，其 version exact 字符串 `"1"`。缺失、别名、大小写或其他版本拒绝。
- 严格短路下的 empty source evidence 必须使用 exact lowercase SHA256
  `793cd498f4dbca6b28661417f49606323248da0cdf8e838575df9f7ef4d0d5db`；禁止运行 source helper后再清空，
  也禁止使用任意空 JSON/list 的其他 SHA。
- financial raw 读取必须保留受控 hidden filename provenance，使每行按真实 source file 取得其 logical
  type；filename 必须 path-contained 且属于冻结 inventory。未知、重复映射、schema 缺失/漂移或 pre/post
  identity 漂移走现有公共 `TUSHARE_FINANCIAL_AUDIT_INVALID`，不得伪装质量报告。

### 5.2 safe union

- 禁止先对原始经济列 `read_parquet(..., union_by_name=True)` 再分类。
- 本节 two-stage contract 立即 supersede 先前“单一 SQL relation 同时包含 canonical/conflict token”的表述；
  不强制 DuckDB UDF，也不允许把 Python canonicalizer 复制成 SQL 算法。
- Stage B1 `safe_source_relation`：每个 dataset 独立。先按 per-file logical schema signature 分组，每组文件
  只读一次并投影同构窄关系；之后只对 schema-group projections 做 `UNION ALL`，原经济列不得参与 DuckDB
  common-supertype 推断。每个文件经济数据每次 audit 只读一次，不得额外经济全表扫描。
- B1 exact 基础列顺序：
  `_flow_dataset, ts_code, ann_date, f_ann_date, end_date, report_type, comp_type, update_flag,
  _request_id, _source_file`。随后按 `_NUMERIC_COLUMNS[dataset]` 冻结字段顺序，对每个 field 依次追加：
  `_flow_source_type_<field>, _flow_raw_<field>, _flow_projected_<field>`。
- dataset field order exact：
  `balancesheet=[total_assets,total_hldr_eqy_exc_min_int]`、
  `cashflow=[n_cashflow_act]`、`fina_indicator=[]`、
  `income=[n_income,n_income_attr_p]`。
- Stage B2 `canonical_observation_relation`：runner-local immutable `_FlowObservation` sequence。
  每个 observation 的 `source_types/raw_values/projected_values/canonical_values` 长度必须精确等于对应 dataset
  field order，且逐索引绑定；`available_date` 在本阶段按现有 ann/f_ann 语义唯一计算。
- `_CanonicalOperand.token` 是唯一 same-day conflict token；`.category` 是唯一 operand classification；
  `.projected` 是后续经济运算唯一 projected value。token/category/projected 仅由
  `_canonicalize_operand` 生成，禁止 SQL/Python 双实现。selection/chain/difference 只消费 B2，不得重读 raw
  或再次扫描 B1。
- `normalized_projection_contract` exact payload 必须为：

```text
{
  "version": "tushare-financial-flow-normalized-projection-v1",
  "representation": "TWO_STAGE",
  "stage_b1": {
    "name": "safe_source_relation",
    "base_columns": [
      "_flow_dataset","ts_code","ann_date","f_ann_date","end_date",
      "report_type","comp_type","update_flag","_request_id","_source_file"
    ],
    "dataset_field_order": {
      "balancesheet": ["total_assets","total_hldr_eqy_exc_min_int"],
      "cashflow": ["n_cashflow_act"],
      "fina_indicator": [],
      "income": ["n_income","n_income_attr_p"]
    },
    "per_field_columns": [
      "_flow_source_type_<field>","_flow_raw_<field>","_flow_projected_<field>"
    ],
    "union": "UNION_ALL_OF_SCHEMA_GROUP_PROJECTIONS",
    "raw_file_reads_per_file": 1
  },
  "stage_b2": {
    "name": "canonical_observation_relation",
    "python_type": "_FlowObservation",
    "parallel_field_sequences": [
      "source_types","raw_values","projected_values","canonical_values"
    ],
    "canonical_operand_fields": ["token","category","projected"],
    "single_canonicalizer": "_canonicalize_operand",
    "available_date_rule": "MAX_ANN_DATE_F_ANN_DATE"
  }
}
```

  exact key/array order由 canonical JSON 固化；缺失、额外、别名、顺序或其他 value 均拒绝。
- 单次 audit 形成一条 union-of-group-projections 查询，禁止按字段重复经济全表扫描。metadata-only schema
  读取不算第四遍经济扫描；publisher 仍保持 pre audit → strict validate → mkdir/projection → post audit，
  不新增第四遍大 I/O。
- v3 row count/date/dimension/base numeric quality 必须在安全视图上保持既有语义。

### 5.3 exact source type family

- 支持：有/无符号整数、FLOAT/DOUBLE、DECIMAL 等 numeric primitive，以及符合第 6 节 grammar 的 VARCHAR。
- BOOLEAN 无条件归 `invalid_numeric_operands`，即使 union 后呈现 0/1/0.0/1.0。
- 可形成稳定标量 token 的普通 unsupported scalar 归 `invalid_numeric_operands`。
- identity 可信但 required field 为 nested/binary 或其他无法形成跨平台 stable token 的类型，按第 9 节
  整体 `BLOCKED`；禁止 `repr` 或 `hash(repr)`。

## 6. 单一 canonicalizer、VARCHAR grammar 与 conflict token

classification 与 same-day conflict 必须复用同一个 runner-local canonicalizer 和同一 trim 规则，不得各写一套。

VARCHAR finite grammar exact：

```text
[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?
```

- 允许科学计数和前导零；拒 Unicode digit、underscore、hex、locale comma、尾随垃圾。
- trim 后空为 `MISSING`。
- trim 后 case-insensitive exact `[+-]?(nan|inf|infinity)` 为 nonfinite。
- grammar 合法但 TRY_CAST DOUBLE 为 NULL 或 Inf 的有限词法溢出为 invalid overflow。

canonical conflict token：

- valid finite numeric primitive/DECIMAL/VARCHAR：先投影 Float64，再用
  `Decimal(str(projected_float))` 形成 canonical numeric token；`+0/-0` 统一 `0`。INT 1、DOUBLE 1、
  VARCHAR `1e0` 经济 token 相同。
- NULL/blank：`MISSING`。
- BOOLEAN：`INVALID_BOOLEAN:true` / `INVALID_BOOLEAN:false`。
- 可稳定非法 scalar：`INVALID:<canonical source type>:<exact canonical trimmed lexical>`。
- NaN（不区分 sign）：`NONFINITE:NAN`；正负无穷分别 `NONFINITE:+INF`、`NONFINITE:-INF`。
- 有限词法溢出：`INVALID_OVERFLOW:<exact canonical trimmed lexical>`。

同一 economic key 的 latest available date 上，所有 required economic field token 逐字段完全一致才可按现有
`update_flag` 稳定折叠；任一 token 不同即 corresponding latest conflict，整 key 排除且不 fallback。conflict
发生在 missing/invalid/nonfinite/resolution/comparable 之前。因此 null/null 折叠后 missing，null/0 conflict；
true/true 折叠后 invalid，true/false conflict；NaN/NaN 折叠后 nonfinite，NaN/Inf conflict。投影到同一
Float64 的大数可视为同 token，但仍须 cent-resolution Gate。

## 7. 唯一 selection/chain 漏斗

- economic key=`(symbol,end_date,report_type,comp_type)`。
- `current_type1_candidates` 是存在至少一个 current type1 候选的 distinct economic keys，尚未扣除 latest
  conflict；`distinct_symbols` 同样基于此 pre-exclusion candidate set。
- 每 key 独立 latest。latest 同日 required economic fields 任一 token conflict →
  `latest_current_conflicts`，排除且不 fallback。
- 对剩余 key，type2 独立 latest：missing → `missing_type2`；latest conflict →
  `latest_type2_conflicts`；latest `available_date` 与 current 不逐字相同 → `available_date_drift`；其余进入
  `synchronized_type2_pairs`。不得回退旧同日版本。
- Q1 `chain_applicable=false`、previous helper 0-call。
- Q2/Q3/FY predecessor 按 current synchronized-pair `available_date` cutoff 选择 exact prior quarter：
  `Q2<-Q1`、`Q3<-Q2`、`FY<-Q3`。missing → `missing_previous`；latest conflict →
  `latest_previous_conflicts`；不 fallback；其余进入 `previous_chain_eligible`。

数值分类必须按整组 required operands 的唯一互斥优先级：

1. 任一 NULL 或 trim 后 blank → `missing_operands`；
2. 否则任一 source type/value 不受支持、尤其 bool、canonical numeric string 失败、有限词法 Float64 溢出
   或类型非法 → `invalid_numeric_operands`；
3. 否则任一明确 NaN/Inf → `nonfinite_operands`；
4. 否则任一失去双侧 cent resolution → `float64_cent_resolution_lost`；
5. 否则 → `comparable_observations`，只有此类执行 Decimal economic mismatch。

禁止 missing 填 0、bool 转 0/1、静默丢弃或把排除项当 economic contradiction。

v3 quality evidence 中 `required_numeric_parse_rows` 与 `required_numeric_nonfinite_rows` 必须保留，但 v4
Gate 按字段域分开：

- 仅 `cashflow.n_cashflow_act`、`income.n_income`、`income.n_income_attr_p` 三个 flow 字段的
  parse/nonfinite 不进入 `blocking_issues`，也不阻断 B 阶段 base prerequisite；由 12 bucket 漏斗归入
  missing/invalid/nonfinite/resolution/comparable。flow 最终 PASS 时，这些 numeric exclusion 不得单独阻止
  publication。
- `balancesheet` 与 `fina_indicator` 没有对应 flow buckets，其 required numeric evidence 继续保持 v3
  blocking；不得把本包的 bucket-level 规则扩散为全局 numeric 放宽。

## 8. Float64 cent resolution 与 Decimal mismatch

- operand 必须 `type(x) is float` 且 `math.isfinite(x)`，拒 bool/NaN/Inf。
- `lower=math.nextafter(x,-math.inf)`、`upper=math.nextafter(x,math.inf)`；任一 neighbor nonfinite 则整组
  non-comparable。
- `down/up` 只用 `Decimal.from_float` 精确度量 binary spacing；
  `max(down,up) <= Decimal("0.01")` 才具备双侧分级分辨率。
- Q1 检查两 operand；Q2/Q3/FY 检查三 operand。任一失败只计
  `FLOAT64_CENT_RESOLUTION_LOST`，不进入 comparable/mismatch/CONTRADICTED。
- economic value 唯一用 `Decimal(str(x))`，`+0/-0` 统一 `Decimal(0)`；
  `Decimal.from_float` 不用于经济值。
- Q1：`abs(type1_current-type2_current) <= Decimal("0.01")`。
- Q2/Q3/FY：`abs(type1_current-type1_prior-type2_current) <= Decimal("0.01")`。
- exact 0.01 PASS；任何 >0.01（含 0.010000...1）mismatch。无相对容差、sum-ULP 或 scale 特例。

真实 binary64 通常不存在 spacing 恰好 0.01；私有纯 Decimal threshold helper 用 synthetic down/up 锁
exact 0.01 PASS、>0.01 FAIL，真实 nextafter 路径锁 0、subnormal、正负二次幂、阈值两侧量级及 max finite。
不得把 threshold 暴露为 public input。

## 9. untokenizable source 的 BLOCKED 语义

当 per-file path/schema/inventory identity 可信，但 required field 的 source logical type 是 nested/binary 或其他
无法形成跨平台 token 的类型：

- top-level `status="BLOCKED"`；
- `flow_semantics.status="NOT_EVALUATED"`、`buckets=[]`；
- `publication_allowed=false`；
- source schema/type evidence 与 SHA 可保留；
- economic selection/chain/difference helper 0-call；
- publisher 在 snapshot mkdir 前拒绝。

`blocking_issues` 按既有 dataset 固定顺序输出，code exact
`<DATASET>_FLOW_SOURCE_TYPE_UNTOKENIZABLE`，dataset 使用项目 canonical uppercase token；count 为该 dataset
下 distinct `(canonical relative_file, required_field)` 对数。同一对只计一次，file order 不影响。

filename 越界/不在 inventory、重复映射、schema/type evidence 漂移或身份不可信仍走公共 audit invalid；BOOLEAN、
可稳定普通 unsupported scalar、非法 VARCHAR 仍走完整漏斗 invalid，不触发 BLOCKED。

## 10. 漏斗守恒、coverage 与 bucket status

publisher 必须逐项复算以下 exact 等式与互斥分类：

```text
current_type1_candidates =
  latest_current_conflicts + missing_type2 + latest_type2_conflicts +
  available_date_drift + synchronized_type2_pairs

Q1:
synchronized_type2_pairs =
  missing_operands + invalid_numeric_operands + nonfinite_operands +
  float64_cent_resolution_lost + comparable_observations

Q2/Q3/FY chain:
synchronized_type2_pairs =
  missing_previous + latest_previous_conflicts + previous_chain_eligible

Q2/Q3/FY numeric:
previous_chain_eligible =
  missing_operands + invalid_numeric_operands + nonfinite_operands +
  float64_cent_resolution_lost + comparable_observations
```

- pair coverage=`synchronized_type2_pairs/current_type1_candidates`。
- chain coverage（仅 Q2/Q3/FY）=`previous_chain_eligible/synchronized_type2_pairs`；Q1 不评价。
- 80% 固定用整数关系 `5*numerator >= 4*denominator`；denominator=0 → INSUFFICIENT。exact 80% 与
  exact 100% 均通过。
- `minimum_current_symbols=100` 作用于 pre-exclusion current candidates 的 distinct symbols。
- `minimum_fiscal_years=3` 作用于 comparable observations 的 distinct fiscal years。
- `minimum_comparable_observations=100` 作用于 comparable rows。
- bucket PASS 需要所有适用 coverage/count thresholds 满足且 mismatch_count=0。
- 只有 comparable mismatch_count>0 可使 bucket `CONTRADICTED`；选择、日期、冲突、finite/resolution 问题
  只能降低 coverage/comparable 并可能 `INSUFFICIENT`。

这些固定阈值可作为只读 evidence 字段输出并逐字验证，但不得成为 public 可调参数或测试旋钮。

## 11. publisher strict validation 与公共 audit identity

- `_validate_audit` 必须严格验证 top-level exact schema、12 bucket exact集合/顺序、source-type evidence SHA、
  normalized projection/token versions、全部漏斗守恒、coverage、bucket/top status、publication_allowed，及
  v3 三个 statement dimension evidence；不能只检查计数范围。
- 保持 pre audit → strict validate → snapshot mkdir/projection → post audit==pre，不新增第四遍经济全表 I/O。
- snapshot manifest 继续使用既有 `audit_sha256`，不新增/重命名 manifest flow 字段；完整 canonical v4 audit
  bytes SHA 继续绑定 snapshot identity。
- public `TushareFinancialSnapshot` 新增 additive field `audit_sha256: str`。唯一取值来源是
  `_verify_snapshot` 对已严格解析、canonical 且完成 manifest fields/bytes 校验后的
  `manifest["audit_sha256"]`。
- publish new、existing reuse、public verify 三条返回路径必须产生相同 exact audit SHA；禁止从
  `manifest_sha256` 推导、caller 注入或 research 层重读 manifest。
- tests 锁 dataclass exact additive contract、唯一生产构造点、三路径同值；audit bytes drift、manifest audit
  SHA 伪造、missing/invalid SHA、manifest canonical drift 均在返回对象前拒绝。
- snapshot schema、output 文件集合和 publisher I/O 遍数不变。

Publisher 对 dataset quality 的 exact 域规则：

- 所有 dataset 的 structural/date/dimension counters 必须 exact 0；所有 int 均须 exact int、拒绝 bool。
- `cashflow`/`income` 允许 numeric-only quarantine，但必须同时满足
  `0 <= eligible_rows <= raw_rows`、`quarantined_rows == raw_rows - eligible_rows`，且
  `max(required_numeric_parse_rows, required_numeric_nonfinite_rows) <= quarantined_rows <=
  required_numeric_parse_rows + required_numeric_nonfinite_rows`。
- `balancesheet`/`fina_indicator` 继续要求 numeric counters=0、`eligible_rows==raw_rows`、
  `quarantined_rows==0`。
- missing/blank 不得伪装 structural blocker或填0；仍由 flow operand funnel处理。最终 publication 无论如何
  都必须 `flow_semantics.status == "PASS"`。

此公共字段是后续 R3 唯一合法的 `financial_audit_sha256` 来源；R3 不得打开 snapshot manifest 或 import data
私有 helper。本包不修改 R3。

## 12. 必测对抗反例

实现测试至少覆盖：

1. terminal/bytes/base-quality 任一前置失败时 flow helper 0-call、NOT_EVALUATED/buckets=[]；
2. exact 12 buckets、Q1/Q2/Q3/FY 固定顺序、顶层 PASS/INSUFFICIENT/CONTRADICTED 优先级；
3. pair/chain exact80%、exact100%、denominator0、minimum symbols/years/comparable；
4. current/type2/previous latest conflict、missing、available-date drift、无 fallback 与全部守恒；
5. null、blank、bool、非法字符串、Unicode digit、有限词法溢出、NaN/Inf、分类混合优先级；
6. BOOLEAN+DOUBLE 分文件 union 后 bool 仍 invalid；VARCHAR true/1/1.0/1e0/blank/NaN/overflow；
7. null/null、null/0、true/true、true/false、NaN/NaN、NaN/Inf 的 exact conflict 行为；
8. numeric primitive/DECIMAL/VARCHAR 等值 token、+0/-0、科学计数、row/file/schema order invariance；
9. source filename 不在 inventory、重复映射、per-file schema drift、pre/post source-evidence SHA drift；
10. nested/binary BLOCKED exact status/code/count/distinct 去重、schema evidence 保留、flow 0-call 和 publisher
    pre-mkdir rejection；并锁 audit-invalid/invalid-numeric/BLOCKED 三边界互不混用；
11. safe projection 每文件每 audit 只读一次、single canonicalizer、required fields 逐字段 token comparison；
12. Decimal tolerance 的负值、大额、零、科学计数等价、exact 0.01、>0.01；nextafter 的 synthetic 与真实边界；
13. publisher 对每个计数/状态/顺序/阈值/identity 的伪造、缺失、重复、乱序和不守恒均在 snapshot mkdir 前拒绝；
14. publish/verify/reuse 返回同一 audit SHA，manifest/audit drift 反例；
15. v3 现有 row/date/dimension/plan/inventory/byte/lease/immutability 测试继续通过。

另外必须锁定独立初验发现的执行路径，不得用 `inspect.getsource` 或字符串存在性替代行为证据：

- A 闭合后 `_quality_summary(..., threads=threads)` 的真实调用可达；
- 唯一 current latest conflict 返回结构化 bucket，`latest_current_conflicts=1`，不得解引用 `None`；
- mixed BOOLEAN/VARCHAR/DOUBLE B1 的 actual columns/rows、每文件单读、schema/file order invariant，以及 B2
  parallel sequence 长度/索引绑定和 single canonicalizer 调用；
- filename 不在 inventory、重复 filename、per-file schema drift、pre/post source-evidence SHA drift；
- nested/binary BLOCKED 的 publisher pre-mkdir 拒绝与 audit-invalid/invalid-numeric/BLOCKED 三边界；
- audit bytes、manifest audit SHA、missing/invalid SHA、manifest canonical drift；
- top-level `active_lease_count`、dataset `request_count`、`status_counts` 及所有其他 counters exact int、
  nonnegative、拒绝 bool，并在 snapshot mkdir 前 fail-closed。

独立 reviewer 必须新增至少一个实现者未使用的对抗反例，并具体映射 source symbol 与 test node，不得只复述
delivery 或测试数量。

### 12.1 STATIC_REWORK5 冻结合同

首轮 `REVIEW_FAIL`、REWORK1—4、P0/P1 发现及其交付/复验历史永久保留。本节根据同一独立 reviewer 的
REWORK4 最终复验追加，状态为 `STATIC_REWORK5_CONTRACT_APPROVED`；它不抹除历史，也不表示已获得
validation、真实 audit、snapshot、R3 或 PIT 授权。REWORK5 必须同时闭合以下六项，任何一项在现有白名单
内无法无歧义实现时立即 `STOP / CONTRACT_DRIFT`，不得由实现者猜测或自行新增 shared module/schema。

