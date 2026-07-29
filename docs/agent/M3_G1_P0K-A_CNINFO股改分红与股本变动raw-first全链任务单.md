# M3 G1 P0K-A：CNINFO 股改分红与股本变动 raw-first 全链任务单

状态：**冻结，待外部实现**

日期：2026-07-29（Asia/Shanghai）

实现模型：`cursor-grok-4.5-high`
实现角色：全新外部实现 Agent
后续初验：另一全新外部 Agent，只读生产代码与实现者测试

## 1. 背景与目标

P0J 后正式首败见
[`20260729_P0J后正式首败_600733股改对价复牌因子.md`](20260729_P0J后正式首败_600733股改对价复牌因子.md)：

```text
600733.SH
2018-09-27
no-event
actual=9.36/8.192=1.142578125
G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED
```

CNINFO `p_sysapi1139` 独立证明 `承诺补偿 10送5`，`p_stock2215` 独立证明
`2018-08-23 / 股权分置` 股本变动。当前正式 workflow 只支持 CNINFO
`p_stock2232 stock_allotment`，无法 raw-first 保存这两类事实。

本任务只完成 P0K-A：

1. 新增两个 CNINFO 官方端点的 connector、deterministic plan、raw/metadata、intent、
   candidate、receipt、journal、恢复与 verified response；
2. 把两类 receipt 纳入 G1 request plan、workflow HISTORY 闭包和 candidate 身份；
3. 保留正式 raw 官方字段码及响应计数，不依赖中文投影；
4. 不选择公司行动、不生成新 ledger、不改变 reconciliation。

P0K-B 才处理股份对价选版、跨源去重、停牌期间多事件基数归一化和 600733 越过。

## 2. 不可变边界

### 2.1 保留既有配股合同

以下现有公开类型及 schema/version 不得迁移、重命名或放宽：

- `CninfoRequestSpec`
- `CninfoRequestBatch`
- `CninfoRequestIntentV1`
- `CninfoRawCandidateV1`
- `CninfoRequestReceipt`
- `VerifiedCninfoRawResponse`
- `CninfoBatchExecutionResult`
- `m3-g1-cninfo-*-v1`
- endpoint=`stock_allotment`
- adapter=`akshare_cninfo_p_stock2232_v1`

既有 `data/run_state/m3_g1/cninfo` journal 和 raw receipt 必须继续可验证。不得把新端点塞进这些
Literal 或通过兼容分支重解释旧 v1。

### 2.2 新类型

新增独立公开类型，名称冻结为：

- `CninfoCorporateActionRequestSpec`
- `CninfoCorporateActionRequestBatch`
- `CninfoCorporateActionRequestIntentV1`
- `CninfoCorporateActionRawCandidateV1`
- `CninfoCorporateActionRequestReceipt`
- `VerifiedCninfoCorporateActionRawResponse`
- `CninfoCorporateActionBatchExecutionResult`

schema/version 冻结为：

```text
m3-g1-cninfo-corporate-action-request-v1
m3-g1-cninfo-corporate-action-request-batch-v1
m3-g1-cninfo-corporate-action-intent-v1
m3-g1-cninfo-corporate-action-candidate-v1
m3-g1-cninfo-corporate-action-receipt-v1
```

新 spec 的 endpoint/adapter 只允许：

| endpoint | adapter |
|---|---|
| `stock_dividend` | `akshare_cninfo_p_sysapi1139_v1` |
| `stock_share_change` | `akshare_cninfo_p_stock2215_v1` |

request id 必须哈希 `schema_version/source/endpoint/adapter/normalized parameters`；两个 endpoint
相同参数不得碰撞。

## 3. Connector 合同

继续只在 `quant.data.connectors` 内 import `requests` / `akshare.datasets` /
`py_mini_racer`。AKShare 只用于 `Accept-Enckey` 生成，不得调用其 DataFrame 投影函数作为生产 raw。

### 3.1 `stock_dividend`

```text
POST https://webapi.cninfo.com.cn/api/sysapi/p_sysapi1139
params={"scode": six_digit_code}
```

请求参数只允许：

```text
symbol=六位数字，无 .SH/.SZ
```

每个 request 精确一个证券。端点的多证券能力未获验证；不得使用逗号批量。

官方字段集合及顺序冻结为：

```text
F001V,F006D,F007V,F010N,F011N,F012N,F018D,F020D,F023D,F025D,F044V
```

### 3.2 `stock_share_change`

```text
POST https://webapi.cninfo.com.cn/api/stock/p_stock2215
params={
  "scode": six_digit_code,
  "sdate": YYYY-MM-DD,
  "edate": YYYY-MM-DD,
}
```

spec 参数冻结为：

```text
symbol=六位数字
start_date=YYYYMMDD
end_date=YYYYMMDD
```

每个 request 精确一个证券。官方字段集合及顺序冻结为：

```text
DECLAREDATE,F001V,F002V,F003N,F004N,F005N,F006N,F007N,F008N,F009N,
F010N,F011N,F012N,F013N,F014N,F015N,F016N,F017N,F018N,F019N,F020N,
F021N,F022N,F023N,F024N,F025N,F026N,F027C,F028N,F029N,F030N,F031N,
F032N,F033N,F034N,F035N,F036N,F037N,F038N,F040N,F049N,F050N,
ORGNAME,SECCODE,SECNAME,VARYDATE
```

每行 `SECCODE` 必须精确等于请求证券；foreign/missing code fail closed。

### 3.3 通用响应失败语义

两端点均必须精确验证：

```text
payload keys == {resultcode,resultmsg,count,total,records}
resultcode == 200
resultmsg == "success"
type(count) is int and type(total) is int
count == total == len(records) == frame.height
0 <= count <= row_limit
每条 record 的 key 集合精确等于端点字段集合
```

不得把缺 key、多 key、截断、非 list records、HTTP/JSON 失败或超时当空数据。

错误码沿用 connector 分层：

- 参数：`CNINFO_REQUEST_PARAMS_INVALID`
- 依赖：`CNINFO_DEPENDENCY_MISSING`
- Enckey：`CNINFO_ENCKEY_INVALID`
- 网络：`CNINFO_NETWORK_FAILED`
- schema/count/字段：`CNINFO_RESPONSE_SCHEMA_INVALID`

异常和日志不得含 URL query、header、Enckey、个人路径或响应正文。

## 4. Deterministic plan

新增：

```python
plan_cninfo_corporate_action_requests(
    *,
    symbols: Sequence[str],
    history: HistoryWindow,
) -> tuple[
    CninfoCorporateActionRequestBatch,  # stock_dividend
    CninfoCorporateActionRequestBatch,  # stock_share_change
]
```

规则：

- 输入必须是标准 `dddddd.SH/SZ`，排序去重；
- 每个证券生成一个 `stock_dividend` 请求（无日期参数）；
- 每个证券生成一个 `stock_share_change` 请求，日期精确为 history start/end；
- 每个 batch 非空、只含单一 endpoint、按 request_id 排序且唯一；
- 同一证券不得因同时出现在多个指数观察日而重复请求；
- 默认 `row_limit=5000`，沿用当前 frozen workflow 常量；不新增 TOML knob；
- 637 个 history symbol 应得到 637 + 637 个新请求，不假装批量。

`G1RequestPlan` 升级为 `m3-g1-request-plan-v3`，新增字段：

```text
cninfo_dividend_batch
cninfo_share_change_batch
```

原 `cninfo_rights_batch` 保留。plan hash、跨 batch request-id 唯一性和所有派生身份必须包含五个
batch：INDEX、Tushare HISTORY、CNINFO rights、CNINFO dividend、CNINFO share change。

旧 v2 plan 对新代码必须 fail closed，不得静默补默认空 batch。

## 5. Raw-first / receipt 合同

新端点使用独立 raw table：

```text
data/raw/cninfo/stock_dividend/<request_id>.json
data/raw/cninfo/stock_dividend/<request_id>.metadata.json
data/raw/cninfo/stock_share_change/<request_id>.json
data/raw/cninfo/stock_share_change/<request_id>.metadata.json
```

独立 journal：

```text
data/run_state/m3_g1/cninfo_dividend
data/run_state/m3_g1/cninfo_share_change
```

raw JSON 只保存官方字段码 records；metadata/receipt 必须保存 endpoint、adapter、parameters、
resultcode/resultmsg/count/total、columns、内容/文件/metadata digest。raw 不可覆盖，request-id
内容寻址和 intent/candidate/receipt 提交原语沿用既有 fail-closed 规则。

`VerifiedCninfoCorporateActionRawResponse` 必须重建 spec/receipt、验证 receipt hash、raw content
hash、精确 columns、row/count/total 闭包；endpoint 与字段集合交叉错配必须拒绝。

允许复用内部通用 helper，禁止复制一套弱化的写入/验证逻辑。

## 6. Workflow / 预算 / 恢复

`VerifiedG1WorkflowStateV1` 增加：

```text
cninfo_dividend_responses
cninfo_share_change_responses
```

现有 `cninfo_responses` 继续只表示 rights，禁止改义。

HISTORY 顺序冻结：

1. Tushare history；
2. CNINFO rights；
3. CNINFO stock_dividend；
4. CNINFO stock_share_change；
5. 全部 complete 后才构建 candidate。

`max_new_requests` 是四段 HISTORY 数据源共享的总提交预算；每段接收剩余预算。前一段 incomplete 时
不得启动后一段。`new_requests_committed` 是所有来源本次新提交总数。

CLI `m3-g1-cli-result-v1` 和 `history_requests` 字段保持不变；`history_requests` 继续表示 Tushare
history plan 数，不在本轮新增 CLI 字段。新 CNINFO 数量由 request plan 和 journal 闭包表达。

inspect/recovery：

- 任一新 batch 缺 intent/candidate/receipt → HISTORY incomplete；
- partial batch 不得泄漏 verified response 到 workflow state；
- receipt 顺序必须精确等于 plan request_id 顺序；
- journal 内容/路径/endpoint/adapter/columns/count/digest 任一篡改 →
  `G1_WORKFLOW_JOURNAL_INVALID/HISTORY`；
- connector/network 执行失败映射为现有 HISTORY execution failure，不得折叠为 empty success。

## 7. Candidate 身份边界

`G1BuildInputs` 必须携带两个新 verified response tuple，并验证与 plan 精确闭包。

本轮只做 receipt projection 与身份传播：

- primary candidate key、build spec / plan hash、receipt projection digest 必须随任一新 raw
  content、receipt 或 request plan 变化；
- candidate body 暂不从新 frame 生成 ledger/evidence；
- P0K-A 后正式 candidate 仍允许以当前 600733 no-event 缺陷 fail closed；
- 不得为了让 P0K-A status 通过而跳过或降级该失败。

REFERENCE/PREPARE/PUBLISH 的 identity/receipt closure 若依赖 request plan 或 receipt projection，
必须同步适配 v3；不得复用旧 key 或旧 v2 build spec。

## 8. 文件白名单

实现 Agent 只可修改：

```text
src/quant/data/connectors/cninfo.py
src/quant/data/connectors/__init__.py
src/quant/data/m3_backfill.py
src/quant/data/m3_g1_candidate.py
src/quant/data/m3_reference.py
src/quant/research/m3/g1_planning.py
src/quant/research/m3/g1_workflow.py
src/quant/research/m3/run_g1.py
tests/unit/test_cninfo_connector.py
tests/unit/test_m3_backfill.py
tests/unit/test_m3_g1_candidate.py
tests/unit/test_m3_g1_planning.py
tests/unit/test_m3_g1_workflow.py
tests/unit/test_m3_reference.py
tests/unit/test_m3_run_g1.py
docs/agent/M3_G1_P0K-A_CNINFO股改分红与股本变动raw-first全链交付报告.md
```

若编译/测试证明另一个文件不可避免，停止并报告证据，不自行扩大白名单。

禁止修改：

```text
src/quant/domain/schemas.py
src/quant/data/m3_execution_facts.py
tests/unit/test_m3_execution_facts.py
configs/**
pyproject.toml
项目实施路线图.md
```

禁止读取或修改 `archive/legacy_pre_greenfield/`、`data/legacy/`。

## 9. 必测反例

至少覆盖：

1. 两端点 600733 raw shape 的 exact key/count success fixture；
2. payload 缺 key、多 key、`resultmsg!="success"`、count/total/records 不等；
3. row 超 5000；
4. share-change foreign/missing `SECCODE`；
5. endpoint/adapter 组合伪造；
6. stock_dividend 带日期参数、share_change 缺日期/反向日期；
7. 同证券重复输入只产生一对请求，输入顺序不影响 batch hash；
8. dividend/share-change 相同 symbol 不碰 request id；
9. v2 plan、旧类型伪装成新类型、旧 receipt 塞入新 batch 均拒绝；
10. raw/metadata/receipt 任一 digest、columns、endpoint、adapter、parameters、count 篡改；
11. `max_new_requests=0/1/跨段边界`，后段不得提前调用；
12. partial 新 batch inspect 不泄漏 verified tuple；
13. 改一行 F010N 或 VARYDATE 会改变 stable response / candidate key；
14. 旧 rights receipt/journal fixture 继续通过；
15. 新 raw frame 被 candidate 携带但不进入 ledger/reconciliation。

实现者未使用的对抗反例留给独立初验，不能把测试仅写成 600733 happy path。

## 10. 开发验证

Windows 原生 Miniforge：

```text
D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_cninfo_connector.py \
  tests/unit/test_m3_backfill.py \
  tests/unit/test_m3_g1_planning.py \
  tests/unit/test_m3_g1_workflow.py \
  tests/unit/test_m3_g1_candidate.py \
  tests/unit/test_m3_reference.py \
  tests/unit/test_m3_run_g1.py -q

D:\Miniforge3\python.exe -m ruff check <白名单源码与测试>
D:\Miniforge3\python.exe -m mypy <白名单源码>
git diff --check <实现基线> -- <白名单全部文件>
```

默认测试不得联网。实现 Agent 不运行 1274 请求正式 history，不读取本地 token，不改正式 journal。

## 11. 交付报告

报告必须压缩说明：

- 改动文件与公开 schema/version；
- connector exact fields/count/foreign-symbol 证据；
- request plan 数量、顺序、预算与 partial recovery 证据；
- 旧 rights 兼容证据；
- candidate identity 传播证据；
- 实跑命令、退出码、passed/skipped；
- 尚未运行的 WSL、正式网络 HISTORY、P0K-B 和 G1 Gate；
- `git status --short` 与 commit hash。

实现 Agent 必须提交一次边界清晰的 commit，但不得宣布主验、P0K、G1 或 Gate 通过。
