# M3 G1 B2A 请求计划与 Journal 交付报告

日期：2026-07-13  
任务书：[`M3_G1_B2A请求计划与Journal实现初验任务单.md`](M3_G1_B2A请求计划与Journal实现初验任务单.md)  
契约 SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) 4.10  
状态：实现 Agent 已完成实现与自测；等待独立初验和主 Agent 最终验收，不代表 B2、G1 或 M3 通过

## 1. 交付范围

本次只实现 B2A 的确定性请求计划、单请求 immutable raw、journal 三态恢复、严格 receipt、项目安全阈值、
串行限频和分类重试。未读取 `_old/`，未读取 `configs/tushare.local.toml`，未联网，也未使用真实 token。

修改文件：

- `src/quant/data/m3_backfill.py`：新增 B2A 公共契约与实现；
- `src/quant/data/storage.py`：保持旧 `RawStore.write` 语义不变，仅新增确定 request raw 能力；
- `tests/unit/test_m3_backfill_requests.py`：新增请求、恢复、receipt、限频、脱敏反例；
- `tests/unit/test_storage.py`：新增 request raw 和旧 API 回归；
- 本报告。

未修改 connector 聚合行为、Schema、mapper、C0/E3/G8、路线图或 Gate 状态。

## 2. 冻结签名逐项符合

| 契约 | 实现情况 |
|---|---|
| `EndpointPolicy` | frozen dataclass；严格正整数阈值及 `ALLOW/REJECT` 枚举；`ENDPOINT_POLICIES_V1` 精确含七 endpoint |
| `TushareRequestSpec.create` | endpoint + 排序字符串参数生成 64 位小写 SHA-256；`__post_init__` 重算 ID |
| `TushareRequestBatch` | 严格 schema/phase、按 request ID 排序唯一、重算 batch hash，并限制 phase 内 endpoint |
| `G1RequestPlan` | 精确包含 weight/history batch，拒绝跨 batch request ID 冲突并重算 plan hash |
| `TushareRequestIntentV1` | 绑定 spec 与 parameters hash；严格 JSON 重读 |
| `TushareRawCandidateV1` | 绑定 request、物理 raw 路径/hash/大小/行列和逻辑内容 hash；固定 candidate 文件 |
| `TushareRequestReceipt` | 在 candidate 物理证据外增加不含时间、路径和 metadata hash 的 stable digest，并自验真 |
| `VerifiedRawResponse` | 绑定 spec、receipt、receipt bytes hash 和重读 Parquet frame |
| `HistoryWindow` | 严格 date、闭区间和顺序 |
| `plan_index_weight_requests` | 完整自然月；跨年和闰年；signal 月中不截断 |
| `resolve_history_window` | signal 边界必须在严格递增唯一 SH sessions；向前 60/向后 10 等调用参数精确取 session |
| `plan_history_requests` | 成分去重排序；每证券 daily/adj/stk/dividend，单 benchmark，suspend 按完整自然月 |
| `execute_tushare_batch` | 签名显式接受 policies、clock、sleep、classifier；先验真再 IO；串行、限频、分类重试和 journal 恢复 |
| `verify_tushare_receipt` | 严格 reader；重读 raw metadata、Parquet、bytes hash、内容 hash、行列及安全策略 |

`RawStore` 新增 `request_paths/write_request/verify_request`，目录固定为
`<raw_root>/tushare/<endpoint>/request=<request_id>/{data.parquet,metadata.json}`。两文件都使用不覆盖创建；
完整且 incoming Parquet hash/行列相同才复用，单边、额外条目、hash 不符或内容冲突均失败。原有
`RawStore.write` 未改签名、身份或返回语义。

## 3. 请求、内容和身份语义

- 七 endpoint 只有一份 `TUSHARE_FIELDS` 生产常量；executor 在任何 IO 前验证参数键集合、固定 fields、
  日期、A 股六位代码和 `suspend_type=S`，不能把 factory 生成的任意参数送到 connector。
- request ID 不含配置 hash、限频、重试、时间、路径、client 或 token。
- raw 保留供应商行序和重复行；测试以两个完全重复的 raw 行确认 Parquet 仍为两行。
- `response_content_sha256` 绑定 endpoint、列顺序、Polars dtype 标签和规范值；按 endpoint 业务键、再按
  完整规范行稳定排序。date/datetime 用 ISO，float 必须 finite，`-0.0` 归一为 `0`，null 保留。
- `stable_response_sha256` 只绑定 request ID、endpoint、parameters hash、逻辑内容 hash、rows 和 columns。
  两个不同 raw/journal root 的同一响应 stable digest 相等，而 metadata hash 不同；改值、dtype 或列顺序
  均改变内容 digest。

## 4. Journal、故障注入与并发

每个 request 只允许：

```text
<journal_root>/<request_id>/intent.json
<journal_root>/<request_id>/candidate.json
<journal_root>/<request_id>/receipt.json
```

JSON 使用严格 UTF-8 reader，拒绝 unknown/missing/duplicate key、字符串数字和 NaN/Infinity；路径只允许
受控相对 POSIX 路径，拒绝绝对路径、`..`、反斜杠、控制字符和 symlink。journal 使用全局单 writer lock；
JSON 先完整写临时普通文件，再用 hard-link 方式原子、不覆盖发布，竞态不调用 `os.replace` 覆盖证据。

SSOT 曾同时写“固定 `candidate.json`”和“多个 candidate 失败”。按主 Agent 后续冻结的 v1 机械语义实现：

- candidate 固定且只允许 `candidate.json`；
- candidate 不存在且无 raw 才联网；完整一致 raw 对可重建 candidate；
- candidate 与 raw 冲突失败；任何额外 candidate-like 或未知 journal 普通文件失败；
- 同 writer/不覆盖创建拦截并发发布。

四个故障点均有回归：

| 故障点 | 重跑行为 | API 调用 |
|---|---|---|
| data 写后、metadata 写前 | raw 孤儿，fail-closed，等待人工处理 | 重跑 0 次 |
| metadata 写后、candidate 写前 | 重读完整 raw，补 candidate/receipt | 重跑 0 次 |
| candidate 写后、receipt 写前 | 严格验真 candidate/raw 后提交 receipt | 重跑 0 次 |
| receipt 原子发布前 | 严格验真 candidate/raw 后提交 receipt | 重跑 0 次 |

receipt 命中不只验证 receipt 本身，还要求 intent、candidate、raw 和 receipt 形成完整闭包；缺 intent 或
candidate 的“孤立 receipt”立即失败，不能成为绕过中间证据的捷径。

## 5. 限频、重试与脱敏

- 首次网络尝试立即执行；相邻网络尝试受 `60 / request_rate_per_minute` 间隔约束。
- 重试最早时间精确取“上次尝试开始 + rate interval”和“失败时间 + exponential backoff”的较晚者。
- 仅 `NETWORK/RATE_LIMIT/TRANSIENT_SERVER` 重试；permission、contract、unknown 和 classifier 自身失败
  都不重试。达到 max attempts 返回稳定错误码。
- receipt 缓存和 candidate/raw 恢复不调用 connector、`monotonic` 或 `sleep`。
- 对外错误只包含稳定分类码。网络原异常通过 `raise ... from None` 切断；并发和 IO 的原始 OSError cause
  同样不进入 traceback，避免 token、client repr、供应商原始值和本机路径泄漏。回归把 secret、Windows
  私有路径和 client repr 放进原异常，确认 message、repr 和格式化 traceback 均不含它们。
- 模块未新增日志；因此也没有 token 或原始响应值日志面。

## 6. 首轮失败与实现自审闭环

### 6.1 首轮定向测试 26 通过、13 失败

13 个失败均由测试设计不符合冻结契约造成，未通过放宽生产代码消除：

| 现象 | 根因 | 应遵循规则 | 修正与通过条件 |
|---|---|---|---|
| 7 个 endpoint empty-policy 测试落入 permanent failure | fixture 用 `marker` 代替真实 endpoint 参数，dispatch 在目标分支前失败 | 反例也必须使用真实规范参数 | 改为各 endpoint 精确参数，并同时断言 fields 透传 |
| 3 个 transient deadline 预期 1 秒，实际 2 秒 | 测试只看 rate deadline，忽略更晚的 2 秒 backoff | 两个 deadline 取最大值 | 保留生产实现，断言 2 秒并写明计算依据 |
| 2 个“IO 前失败”断言 `tmp_path` 不存在 | pytest 会预先创建 fixture root | 应检查业务 raw/journal 未创建 | 改断言 `<tmp>/raw` 与 `<tmp>/journal` 不存在 |
| 1 个非开市边界先触发日期倒置 | 所选 2030 日期晚于 signal end | 反例应只改变一个目标条件 | 换成早于 end 但不在 open dates 的日期 |

修正后定向测试 39/39；继续补充七 endpoint 阈值、严格 JSON 和自审反例后最终为 68/68。

### 6.2 实现自审发现

| 现象 | 根因 | 被破坏的不变量 | 新增测试与修复 |
|---|---|---|---|
| 同 request、同参数但新 frame 不同仍复用旧 raw | 已存分支只验真落盘证据，未比较 incoming payload | 只有完全相同 raw 对才可复用 | 新增同参数改值反例；比较 incoming Parquet hash、行数和列后才复用 |
| receipt 存在时没有强制 intent/candidate 仍完整 | receipt 快路径早于 journal 闭包检查 | 提交态不能绕过完整证据闭包 | 删除 intent/candidate 反例；命中 receipt 前逐层验真并比较 candidate→receipt |
| writer/IO 错误链可能携带物理路径 | 稳定顶层错误仍用原 OSError 作为 cause | 脱敏覆盖 traceback，不只覆盖 message | writer lock 路径反例；对外边界使用 `from None`，保留稳定分类码 |

## 7. 验证结果

全部命令均在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
68 passed in 4.87s

python -m pytest -q
369 passed, 1179 warnings in 11.12s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 均来自既有 Pandera/Polars `concat(how="horizontal")` deprecation 路径，本次代码没有
新增该调用，也没有把 warning 记作失败或通过证据。

## 8. 未实现项与待验收边界

- 未实现 suspension/price-limit/dividend mapper、B3 membership、B4 candidate/audit/release 或 BaoStock 对账；
- 未调用真实 Tushare，未验证 2000 积分账户在七 endpoint、完整历史区间和真实 dtype 下的行为；
- 未把 B2A mock 通过表述为 B2/G1/M3 通过；
- 未更新路线图、Gate 或其他包状态；
- 当前结果仍需未参与实现的初验 Agent 增加至少 8 个新对抗反例，再由主 Agent 最终验收。

