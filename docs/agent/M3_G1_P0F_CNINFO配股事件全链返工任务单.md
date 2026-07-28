# M3 G1 P0F：CNINFO 配股事件全链返工任务单

状态：**主 Agent 合同冻结，等待外部实现 Agent**

证据与裁定：
[`20260728_M3_G1_P0F_000661配股真实证据与设计裁定.md`](20260728_M3_G1_P0F_000661配股真实证据与设计裁定.md)

## 1. 目标

将 CNINFO 已实施 A 股配股接入 G1 的 raw-first、可恢复 journal、candidate 来源闭包和
公司行动对账，使 `000661.SZ@2016-04-27` 以
`MATCHED_EVENT_MARKET_REFERENCE` 闭合，同时保持无来源资本事件 fail closed。

本轮包括 fake/fixture 实现与真实 HISTORY 补抓能力；外部实现自测不得直接运行 637 证券正式
网络补抓。独立初验和主 Agent 通过后，再由主 Agent执行真实有界 HISTORY。

## 2. 权威来源与 raw 合同

### 2.1 请求

新增 CNINFO request family，不冒充 Tushare：

```text
source=cninfo
endpoint=stock_allotment
adapter=akshare_cninfo_p_stock2232_v1
parameters:
  symbols=<排序、唯一、去 .SH/.SZ 后逗号连接，1..50 个>
  start_date=YYYYMMDD
  end_date=YYYYMMDD
```

request id 必须绑定 source、endpoint、adapter method version 和规范化参数。历史证券排序后
每 50 只一批；同一证券恰好属于一个 batch。正式 637 证券应形成 13 个 request。

### 2.2 响应

生产连接器只允许在 `quant.data.connectors` 内 import AKShare/HTTP 依赖。默认路径访问官方
`p_stock2232`，使用 AKShare 当前 Enckey 适配；测试必须注入 fake client/enckey，不访问网络。

响应进入 raw 前必须验证：

- HTTP/JSON 成功；
- `resultcode` 精确为 200，`resultmsg` 精确为 `success`；
- `count`、`total` 为非负整数且 `count==total==len(records)`；
- 每个 record 是字典且字段集合精确匹配冻结 raw schema；
- `SECCODE` 属于请求集合；
- `SUBID` 在响应内唯一；
- 行数不超过配置上限；
- 空响应必须保留完整空 schema。

raw 保存官方字段码，不以 AKShare 中文列名作为生产合同。intent/candidate/receipt 需额外固化
resultcode/count/total；stable response hash 必须包含这些元数据和 raw 内容。禁止记录
Accept-Enckey、header、cookie 或任何凭据。

### 2.3 最小必需 raw 字段

冻结映射至少使用并严格验证：

```text
SUBID, SECCODE, SECNAME, DECLAREDATE,
F011D(record date), F012D(ex date),
F013D(payment start), F014D(payment end),
F005N(rights price), F004N(per-10 rights ratio),
F017N(actual shares, 10k shares),
F024N(pre total shares, 10k shares),
F025N(post total shares, 10k shares),
F052D(result announcement date), F038D(list date),
F002V(stock class), F001V(stock class code)
```

正式 connector 可以冻结全部 57 个当前字段；若上游字段集合漂移，必须以稳定 source-schema
错误停止，不能静默丢列。

## 3. 计划、journal 与恢复

1. 在现有 G1 plan 中显式加入 CNINFO rights batch；不得仅靠目录自动发现。
2. 计划 identity、derived plan hash、primary candidate key 和 manifest 必须绑定 rights batch
   与 receipt。
3. `history --max-new-requests N` 的预算同时覆盖本轮新 CNINFO identity；旧 3190 个 Tushare
   identity 不得重取。
4. 新路径固定为：

   ```text
   data/raw/m3_g1/cninfo/
   data/run_state/m3_g1/cninfo/
   ```

5. journal 必须沿用现有 no-clobber、intent-first、candidate→receipt、同 identity 幂等恢复、
   symlink/reparse containment、单写者锁和错误脱敏语义。
6. `status` 只读、零网络；缺任一 CNINFO receipt 时只能报告 HISTORY incomplete，不能自动请求。
7. Windows 可作开发反馈；journal lock/路径校验须 Linux+Windows 兼容。平台特有 Gate 仍在 WSL。

## 4. 配股事件投影

将 rights 与现有 dividend 统一到 corporate-action ledger/evidence，而不是新增旁路。

必须新增或扩展的字段语义：

```text
action_type: DIVIDEND_DISTRIBUTION | RIGHTS
rights_price: nullable positive float
rights_ratio: non-negative float, per one old share
vendor_record_id: nullable stable string
```

规则：

- dividend：rights_price=null、rights_ratio=0；保留现有 cash/stock/pay/list 规则。
- rights：cash=0、stock_ratio=0、rights_price>0、rights_ratio>0；
  record<ex，payment_start<=payment_end<ex，announce<=record；
  actual/pre/post 均正，`post-pre` 与 actual 在严格数值容差内一致；
  result announcement 不晚于或等于 ex date；list date 不早于 ex date；
  A 股类别必须明确。
- `rights_ratio = F004N / 10.0`；F004N 非有限、<=0 或无法证明“每 10 股”均拒绝。
- economic event / candidate / event id 必须包含 action type、SUBID、symbol、关键日期、
  rights price/ratio、actual/pre/post；不得与 dividend id 碰撞。
- 重复 SUBID、同经济事件核心字段冲突、同 symbol/ex_date 多条不一致 rights 均 fail closed。
- ledger/evidence/source receipt 必须闭包；攻击者同步重算表 digest 也不能替换 SUBID 或经济参数。

## 5. 对账通式

同 symbol/effective_date 的 dividend 与 rights 可以合并：

```text
rights_subscription_cash_per_share = Σ(rights_price_i × rights_ratio_i)
declared_ratio =
  previous_close × (1 + Σstock_ratio + Σrights_ratio)
  / (previous_close - Σcash_per_share_gross
     + rights_subscription_cash_per_share)
```

必须：

- denominator、declared、actual、market 均为正且有限；
- actual/market 使用 P0E `supported_ratio` 和相对误差规则；
- 有 daily 且 actual/market 匹配时：
  - declared 也匹配 → `MATCHED_EVENT_DECLARED_FORMULA`；
  - declared 超差 → `MATCHED_EVENT_MARKET_REFERENCE`；
- 无 daily 仍只允许 FULL_DAY 且 declared 匹配；
- event ids 同时覆盖 dividend 与 rights；
- reconciliation 输出显式记录总 rights_ratio 与
  rights_subscription_cash_per_share；
- 没有 dividend/rights 事件的 jump 继续
  `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。

000661 固定验收形状：

```text
previous_close=103.20
rights_price=45.68
rights_ratio=0.3
daily.pre_close=90.09
actual=3.66/3.195
status=MATCHED_EVENT_MARKET_REFERENCE
```

不得硬编码证券、日期或数值。

## 6. 版本与身份

至少显式升级：

- corporate-action selection method：加入 CNINFO rights 的新版本；
- corporate-action reconciliation：v4 → v5；
- mapper/schema/build spec 中受新增字段影响的版本；
- G1 request/derived plan schema；
- receipt projection source 允许 `cninfo`；
- release/manifest 读取、写入、磁盘复验所需结构版本。

旧版本、旧 manifest、缺 rights batch 或只含 Tushare receipt 的新候选不得冒充新语义。
源码树哈希导致 primary key 改变是预期行为；不得复用旧 baostock reference journal 或旧
prepare/publish 产物。

## 7. 错误与失败语义

新增错误码须分层且稳定：

- connector/network/response schema；
- CNINFO request/journal/receipt identity；
- rights event mapping/selection；
- reconciliation mismatch；
- workflow HISTORY incomplete/failed。

所有异常必须脱敏、无 URL query/header/Enckey；外部 SDK 原始异常不得穿透稳定边界。
空响应是合法事实，但缺 receipt、截断、目标外代码、字段漂移和冲突不是空响应。

## 8. 文件白名单

生产代码可修改：

- `src/quant/data/connectors/cninfo.py`（新增）
- `src/quant/data/connectors/__init__.py`
- `src/quant/data/m3_backfill.py`
- `src/quant/data/m3_execution_facts.py`
- `src/quant/data/m3_g1_candidate.py`
- `src/quant/data/m3_release.py`
- `src/quant/domain/schemas.py`
- `src/quant/data/__init__.py`
- `src/quant/research/m3/g1_planning.py`
- `src/quant/research/m3/g1_workflow.py`
- `src/quant/research/m3/run_g1.py`
- `configs/research/m3_qlib_example.toml`

测试可新增/修改：

- `tests/unit/test_cninfo_connector.py`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_g1_workflow.py`
- `tests/unit/test_m3_g1_cli.py`
- `tests/unit/test_m3_release.py`
- `tests/unit/test_m3_reference.py`
- `tests/unit/test_schemas.py`

文档：

- 新建唯一外部实现交付报告。

若需要修改白名单外生产文件，停止并提交接口冲突证据；不得自行扩大到增发、重整或 G2。

## 9. 最小测试矩阵

1. connector 两代码、50 代码规范参数；返回目标外代码拒绝。
2. resultcode 非 200、count/total/records 不等、字段漂移、重复 SUBID 均拒绝。
3. empty response 形成完整 raw/receipt，重放零网络且不新增请求。
4. journal crash 点、candidate 已落盘恢复、同 identity 冲突、并发锁、Windows/Linux 路径安全。
5. 637 symbol → 13 个稳定 batch；输入顺序变化不改变 plan/hash。
6. 000661 fixture 输出 RIGHTS ledger 和 `MATCHED_EVENT_MARKET_REFERENCE`。
7. 理论公式与 market 都匹配时输出 declared 状态。
8. rights 事件缺 daily 且非 FULL_DAY 拒绝；FULL_DAY 但 declared 超差仍拒绝。
9. 远低于 1 的 actual/market 即使相互匹配仍拒绝。
10. 无 rights/dividend 的 000661 形状继续 fail closed。
11. F004N 单位未除 10、rights price/ratio/date/股本非法、发行失败均拒绝。
12. dividend + rights 同日通式正确；事件顺序变化不改变 digest。
13. 篡改 SUBID、rights price/ratio、event ids 并重算表 digest，candidate verify/audit 拒绝。
14. status 零网络；CNINFO receipt 缺失报告 HISTORY incomplete。
15. max-new-requests 只提交预算内 CNINFO identity；不重取旧 Tushare。
16. v5/新 mapper/schema/plan/manifest 传播；旧版本和旧 manifest 拒绝。
17. 发布磁盘复验包含新字段和 CNINFO receipt 来源闭包。
18. Windows 与 WSL 可导入；默认单测不访问真实网络。

独立初验必须增加实现者未使用的反例，至少覆盖响应截断伪装为空、同步重算 digest 的 rights
经济参数篡改、同日 dividend+rights 顺序不变量和旧 manifest 降级攻击。

## 10. 验收顺序

外部实现 Agent：

1. 定向 connector/request/journal 测试；
2. execution facts + candidate/release 定向测试；
3. planning/workflow/CLI 定向测试；
4. 白名单 Ruff、生产文件 mypy、diff check；
5. 只提交白名单和唯一交付报告。

独立初验 Agent 使用另一全新 `cursor-grok-4.5-high` 会话，只读生产/实现者测试，仅写唯一
初验报告。两者通过后，主 Agent 才执行真实 13-request HISTORY、主验、正式 status。

本轮通过不等于 G1、Windows publish、VerifiedG1Release 或 Linux Gate 通过。
