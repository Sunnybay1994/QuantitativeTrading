# M3 G1 BENCH-B1B-R3：合同证据闭包与 Readiness 快照绑定返工任务单

## 1. 现象—根因—应遵循规则

R2A/R2B 外部只读分片审计确认 B1B 核心 mapper、分红对账和 v2 发布结构大体到位，但仍有一个确定生产
缺口和若干测试证据空洞：

- readiness 只检查 `source_snapshot_id` 唯一非空，任意伪造字符串仍可通过；根因是函数没有接收上游已
  验证的期望 snapshot identity；应遵循 B1B §2.2/§5 的“身份不匹配 fail closed”。
- 3185→3190 只有恒真算术断言；三 benchmark 身份、三段 adj、五响应 snapshot 任一变化、窗口首日除息、
  完整 OHLC 和 label 持有期边界仍缺直接证据。

R2A/R2B 报告是诊断证据，不是独立初验。本轮由一个全新外部实现 Agent 完成最小返工并写原 B1B 正式
交付报告；随后必须再由另一个全新外部会话独立初验。

## 2. 冻结生产接口

`audit_m3_readiness` 新增必填关键字参数：

```python
expected_benchmark_source_snapshot_id: str
```

合同：

- 必须是精确 64 位小写十六进制 SHA-256；bool、非 str、空串、大写、非 hex、长度错误均 fail closed；
- 该值由调用方从上游已验证候选/发布身份取得，不得从本次 `benchmark_bars` 自己提取后回传形成恒真校验；
- clean benchmark 的唯一 `source_snapshot_id` 必须与期望值精确相等；不唯一、非法或不等分别产生稳定的
  benchmark snapshot ERROR，函数仍按既有约定返回 issues 而不抛出契约异常；
- 不把 `VerifiedRawResponse` 或 raw receipt 对象引入 `quant.research`，不在 readiness 复制 mapper 的 canonical
  hash 算法。

建议保留 `BENCHMARK_SNAPSHOT_INVALID` 处理结构/格式错误，新增
`BENCHMARK_SNAPSHOT_MISMATCH` 处理唯一合法实际值与合法期望值不一致；具体消息不得包含完整 identity。

## 3. 白名单

生产：

- `src/quant/research/m3/readiness.py`

测试：

- `tests/unit/test_m3_readiness.py`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_g1_mappers.py`
- `tests/unit/test_m3_labels.py`

报告：

- `docs/framework/agent/M3_G1_BENCH-B1B_510300总回报映射与全链身份重基线外部实现交付报告.md`

除上述文件外只读。不得修改 mapper/candidate/release/config 生产实现，不得联网、调用真实 API、写正式数据
或发布。所有写入保持 LF；不得整文件重排、重新格式化或制造与本轮无关的行尾噪声。

## 4. 必须补齐的测试证据

1. readiness：实际 snapshot 双值、空/非法值、伪造但合法的唯一 64-hex 与期望不一致、非法期望值均 fail
   closed；实际值与上游期望相同才不产生 snapshot ERROR。测试 helper 必须显式传期望值。
2. mapper 三段闭包：用跨 2015–2018、2019–2022、2023–结束日的 1+3+1 响应；缺中段、重复/重叠、乱序
   输入分别验证。乱序但闭包相同的输出 OHLC 和 snapshot 必须稳定。
3. snapshot 敏感性：分别改变 `fund_daily`、任一 `fund_adj`、`fund_div` 的 verified stable response identity，
   snapshot 都必须变化；不得只测 div。
4. OHLC：open/high/low/close 四列都精确等于 raw×同日 factor，禁止只断言 close。
5. 分红首日：窗口首日恰为 `ex_date` 且窗口内无可比较前一交易日时不猜测失败；其他无事件跳变规则不变。
6. label 持有期：entry/exit 不变时，改变中间会话不得改变 open-to-h-close 结果；并与禁止额外 `+cash` 的
   既有断言共同证明无二次计入。
7. planning：显式断言 `benchmark_mode`、`benchmark_method_version`、
   `benchmark_dividend_reconciliation_version` 三字段进入 build spec/序列化身份。
8. 3190：用 637 个确定、合法、唯一的合成 A 股代码构建 legacy 与 ETF 正式窗口 plan，实际断言 equity
   request 数为 3185、request_id 集合与 legacy 去除 `index_daily` 后完全相同、基金为 1+3+1、总数 3190、
   无 H00300/index_daily。该单测证明算法闭包；真实 `S=637` 与实际新 plan 的 3190 仍由主 Agent 后续零网络
   生产状态验证，不把合成单测冒充真实数据证据。

## 5. 验证与交付

实现者先运行新增定向测试、Ruff、mypy 和 `git diff --check`。已知大 candidate/release fixture 很慢，不得
机械启动全量，也不得虚报未完成长测。正式交付报告必须逐项映射原 B1B §2/§3/§5、R1 与本 R3，列出真实
命令/结果和主 Agent 待验项，不得宣布 B1B/G1 Gate。

独立初验必须使用另一全新 `cursor-grok-4.5-high` 会话，只写自己的唯一报告，并增加实现者未使用的
snapshot 格式/错配或三段边界反例。
