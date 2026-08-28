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

POSTFIX Validation5 使用新的 ignored/no-clobber evidence/temp roots 执行；权威 evidence root 为
`artifacts/agent_runs/m2-audit-v4-postfix-validation5-20260828T162821Z`，temp root 为
`artifacts/validation_tmp/m2-audit-v4-postfix-validation5-20260828T162821Z`。Parser errors=0、identity PASS，
冻结 focused6 全部 PASS（6 passed）；focused6 stdout SHA256 为
`7e2fafef6fcf9fba6825daa9465b55bbf6db0564e46b486565b536ba21959a92`，stderr empty、exit0。mypy
production2 首失败为唯一 audit line 1892 list invariance：
`list[tuple[_FlowObservation,_FlowObservation,_FlowObservation]]` 不能赋给已注解的
`list[tuple[_FlowObservation,_FlowObservation,_FlowObservation | None]]`；mypy stdout SHA256 为
`67e324871a2ea3bdffd10162fdef62bd8ad955b34230fceb666c2ab8ebca371c`，stderr empty、exit1。Ruff、cold、
exact8 scope 均 UNRUN，不得冒充 PASS。

Validation5 runner SHA256 为
`7cc98ca4f66a681bfaa347de5e33150d4932cd42b675617e7ec82c1c7141fe3d`，summary SHA256 为
`8cfb6647088e40e52d0fa153b31ba055425bc711e86f686397f412cefbbd45f2`，runner stderr SHA256 为
`c1a60507145d7c7df86649714c4e1cf606f25b45ce7d96ce8f14b7ae90ba269d`。runner 在 finally 中已先恢复自身
priority/affinity，随后因全局枚举旁观进程的 `ProcessorAffinity` 遇不可读进程而中断；合同内
`resource_release.log` **MISSING**，禁止伪补或把外层旁证冒充该 artifact。外层 fresh 只读核证明退出后
Python/pythonw=0、exact0xF00=0、现有 shell Normal/0xFFF，故资源实际已释放；业务 exact8 未修改，cached0，
ordinary `git diff --check` exit0（仅既有 LF→CRLF warning）。

STATIC_REWORK10 只允许同一原 implementer 修改：

- `src/quant/data/audit_tushare_financials.py`；
- `docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`。

publisher production、tests2、roadmap、taskbook（实现阶段）与 review 均只读。唯一允许的代码修正是把
REWORK9 的 mutable list 注解机械替换为：

```python
numeric_pairs: Sequence[
    tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]
]
```

`Sequence` 已由 audit production 的 `collections.abc` 既有导入；不得新增、删除或改写 import。Q1
comprehension、else `previous_pairs`、后续 `for` 必须逐字保持。该变量只允许保持现有单次只读迭代；禁止
复制、`extend`、cast、Any、type-ignore、运行时容器转换、分支/alias/顺序/None/计数/逻辑变化或 P2 夹带。
原因与通过条件冻结如下：

- **现象**：扩大 tuple 第三元素后，外层 mutable list 仍因 invariance 被 mypy 拒绝；
- **根因**：`list[T]` 不协变，而两分支实际只需要一个只读可迭代接口；
- **应遵循规则**：使用既有 `Sequence[T_co]` 表达唯一消费方式，保留两个实际 list 对象及 alias；
- **最小复现**：Validation5 mypy line 1892 唯一错误；
- **测试**：Validation5 focused6 已 PASS；修正后 Validation6 只重跑两个直接 flow 节点并执行 mypy；
- **通过条件**：mypy production2 PASS，Q1 与 Q2/Q3/FY 的对象、顺序、None、previous cutoff、operand 与计数
  行为不变。

delivery 必须逐项记录上述现象—根因—规则—最小复现—修正—未来通过条件，并诚实保留 Validation5 的
Ruff/cold/scope UNRUN 与 resource-release artifact MISSING 边界。同一原 reviewer 仅写原 review 复验；不得由
实现者或 reviewer 自行启动 Validation6。

POSTFIX Validation6 必须使用新的 no-clobber evidence/temp roots，并修正 carrier 的 resource-finalization：

1. finally 先分别、无条件尝试并持久记录 terminal 状态、owner `$self` priority/affinity 恢复、carrier 已记录的
   known-child PID 全部退出、以及 `Get-Process python,pythonw` presence count；各项使用独立 try/catch，任一
   真实 owner/known-child 恢复失败均明确 STOP，但一个字段失败不得抹除其他已形成 artifact。
2. runner 内只核已授权 owner 与其记录的 child PID；禁止 `Get-Process` 全局枚举后读取所有进程的
   `ProcessorAffinity`。旁观进程权限错误不得遮蔽 owner 已恢复的证据。
3. 全局 exact0xF00 只由 runner 外中央 fresh read-only 旁证并单独持久记录；它不能替代合同内 release artifact，
   也不能反向阻断该 artifact 先形成。

Validation6 顺序冻结为 Parser 零执行门禁 → identity →
`tests/unit/test_audit_tushare_financials.py::test_selection_conflicts_missing_drift_and_chain_have_no_fallback` →
`tests/unit/test_audit_tushare_financials.py::test_flow_and_publisher_bucket_order_is_exact_and_stable` → mypy
production2 → Ruff exact4 → cold → exact8 Unicode/NUL-safe scope、cached0、diff-check、Validation1–6
evidence/temp roots exist+ignored、owner/known-child/Python presence resource artifact 与 runner 外 exact0xF00
旁证。不跑 full tests2。首失败 STOP 并保留证据；全绿也保留证据待经理/中央复核。STATIC_REWORK10 与
review 继续 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`：零 Python、pytest、Ruff、mypy、cold、DuckDB、
真实 data/audit/snapshot、network、stage、commit。

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

## 13. 实现、验证和真实数据阶段

### 13.1 STATIC_ONLY

Worker 只实现 exact production2/tests2 并写 delivery；不得运行 Python、pytest、Ruff、mypy、cold、真实 audit
或 snapshot，不得 stage/commit。发现必须扩路径、DuckDB/Parquet 实际类型无法满足本合同、或 v3 语义无法在
safe projection 中保持时，立即 `STOP / CONTRACT_DRIFT`，由经理回中央重冻。

### 13.2 独立初验

STATIC_DONE 且经理 scope/合同核对通过后，由不同上下文只读审查 exact implementation6，唯一写 review。
reviewer 不改 production/test/delivery。P0/P1 退回同一实现链最小返工。

### 13.3 validation-only（另申请）

REVIEW_PASS 后向中央申请唯一 CPU8–11/0xF00 租约，BelowNormal、threads<=2、exact cwd/PYTHONPATH、项目内
ignored basetemp 和持久日志。建议顺序：

1. identity + collect-only；
2. focused audit flow/type/source/safe-union nodes；
3. focused publisher strict validation/audit-SHA nodes及所有既有邻接；
4. Ruff production2+tests2；
5. mypy production2；
6. cold import；
7. exact8 Unicode/NUL-safe scope、cached0、diff-check、temp/process evidence。

失败即 STOP 并保留证据；全绿也先保留日志，经理复核后才申请 SAFE_COMMIT。禁止 full suite、网络、真实
financial I/O、snapshot、PIT 或 PAPER。

### 13.4 真实 audit-v4（实现合流后另冻）

真实 audit 必须基于合流后的 latest clean main、权威 plan/catalog、terminal ledger 与 bytes verify，单次只读、
受控资源执行。结果若 `BLOCKED/INSUFFICIENT/CONTRADICTED/NOT_EVALUATED`，立即保持 snapshot/R3/PIT STOP，
不得按数据调 tolerance/threshold、fallback 或补值；只有 v4 PASS 且 public fresh verifier 闭合后，中央才根据
真实 `allowed_report_types` 证据冻结后续 snapshot/R3。该阶段不包含在本实现任务的资源授权中。

## 14. 交付与完成边界

delivery 必须用“现象—根因—应遵循规则—最小复现—新增测试—通过条件”记录所有返工或 STOP；列出 exact
改动、未运行事项、schema/I/O 边界及剩余平台风险。Worker 完成只回：

`DELIVERY_READY docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`

本包在实现/静态审查阶段的最高状态为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`；即使单测全绿也不得
宣称 audit-v4 PASS、snapshot READY、R3 READY 或 PIT 已授权。
