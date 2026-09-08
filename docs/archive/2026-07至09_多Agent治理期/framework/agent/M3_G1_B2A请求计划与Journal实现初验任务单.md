# M3 G1 B2A 请求计划与 Journal 实现初验任务单

日期：2026-07-13  
状态：已通过独立六次复验和主 Agent 最终验收；见
[`M3_G1_B2A主Agent最终验收报告.md`](M3_G1_B2A主Agent最终验收报告.md)  
契约 SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) 4.10  
上位任务：[`M3_G1数据实现与初验任务单.md`](../../archive/M3_G1数据实现与初验任务单.md) B2
设计审查：[`M3_G1_B2-B4契约独立设计审查报告.md`](M3_G1_B2-B4契约独立设计审查报告.md)

## 1. 本包目标与边界

实现“确定请求计划 → 串行抓取 → raw 不可变留证 → journal candidate → 严格 receipt”最小闭环。
本包不映射 clean、不构建 membership、不做 BaoStock 对账、不发布 G1 release、不调用真实网络。

允许修改：

- `src/quant/data/m3_backfill.py`（新建）；
- `src/quant/data/storage.py`（只新增 B2A 需要的确定 request raw 写入/验真能力，不改旧 API 语义）；
- `tests/unit/test_m3_backfill_requests.py`（新建）；
- `tests/unit/test_storage.py`（仅新增 request raw 反例）；
- 交付报告。

禁止修改 connector 聚合行为、Schema、mapper、C0/E3/G8、路线图、Gate 状态或其他任务包。

## 2. 冻结公共契约

实现且导出 SSOT 中以下类型/函数：

- `EndpointPolicy`；
- `TushareRequestSpec.create`；
- `TushareRequestBatch`；
- `G1RequestPlan`；
- `TushareRequestIntentV1`；
- `TushareRawCandidateV1`；
- `TushareRequestReceipt`；
- `VerifiedRawResponse`；
- `HistoryWindow`；
- `plan_index_weight_requests`；
- `resolve_history_window`；
- `plan_history_requests`；
- `execute_tushare_batch`；
- `verify_tushare_receipt`。

公开 dataclass 的 `__post_init__` 必须重算并验证自报 hash/ID、tuple 排序、唯一性、字段类型与枚举。
不得让 direct caller 构造 A ID+B 参数或非规范 batch/plan。所有 identity 是 64 位小写裸 hex。

## 3. 请求计划

1. 代码中只有一份七 endpoint `fields` 常量，与 SSOT 顺序逐字符相等；planner 不接受 fields 覆盖。
2. request ID 只 hash `endpoint` 与排序规范参数；fields 是参数之一。不含 config hash、重试、时间、路径或 token。
3. weight batch 从 signal-start 月向前推一个完整自然月，到 signal-end 月；每月首尾一个 request。
4. history window 要求 signal 边界本身是 SH open date；start 向前精确 60 session，end 向后精确 10 session。
   日历不足或边界非开市日失败，不自动对齐。
5. history batch 对排序唯一的历史成分并集生成：每 symbol 各一个 daily/adj_factor/stk_limit/
   dividend，基准一个 index_daily，suspend_d 每完整自然月一个全市场请求。
6. A 股 symbol 精确六位数字加 `.SH/.SZ`；成分输入乱序不改 plan hash。
7. `G1RequestPlan` 包含 weight/history 两 batch，任一 request 重复或跨 batch ID 冲突失败。

## 4. Raw 与 journal

每 request 的 journal 固定为：

```text
<journal_root>/<request_id>/intent.json
<journal_root>/<request_id>/candidate.json
<journal_root>/<request_id>/receipt.json
```

- `intent.json` 在首次网络调用前原子发布；已存在时必须严格验真与 spec 一致。
- request raw 使用确定的 request 子目录。完整 data+metadata 验真后才原子发布 candidate。
- 预检时：有效 receipt 直接复用；损坏 receipt 立即失败；无 receipt 且固定的 `candidate.json` 一致则恢复；
  candidate 冲突或 journal 目录存在额外 candidate-like/未知普通文件时失败；受控 request raw 目录中
  只有 data 或只有 metadata 是孤儿，失败并等待人工处理，不得联网。只有 intent 而无 raw/candidate
  可重试网络。
- 所有 JSON 都严格拒绝 unknown/missing/duplicate key、字符串数字、NaN、绝对路径、`..`、symlink 和非 UTF-8。
- 生产首版是单 executor；journal root 检测到另一活动 writer 或同 request 并发竞态时 fail-closed，不用
  `os.replace` 覆盖已存证据。

`RawStore` 新增能力必须保持旧 `write` 语义不变。request raw data 和 metadata 使用不覆盖创建；
完全相同的已存对可验真复用，单边存在、hash 不符或目录多普通文件均失败。

## 5. Receipt 和逻辑身份

- receipt 物理字段绑定 raw snapshot/path/file hash/metadata hash/bytes，并重读 Parquet 验证 rows/columns。
- `response_content_sha256` 按 SSOT 的列顺序、业务键排序、类型标签、ISO date、finite float/
  `-0.0`、null 规范算法计算，不用 Parquet bytes，不在 raw 中去重。
- `stable_response_sha256` 只绑定 request ID、endpoint、parameters hash、content hash、rows、columns；
  不含 fetched_at、snapshot ID、raw path 或 metadata hash。
- 相同逻辑响应落在不同物理日期/路径时 stable digest 不变；改一个值/dtype/column/order-contract 必变。

## 6. 限频、重试与 endpoint policy

- `endpoint_policies` 必须恰含七 endpoint，row limits 与 C0 v1 冻结值精确相等。
- empty policy：`index_weight/daily/adj_factor/index_daily/stk_limit=REJECT`；`suspend_d/dividend=ALLOW`。
- 返回行数 `== row_limit` 即可能截断并失败；`>` 同样失败。
- 只重试 classifier 显式返回的 `NETWORK/RATE_LIMIT/TRANSIENT_SERVER`；未知异常默认永久失败。
- 首次网络尝试立即；后续尝试等到 rate deadline 和 exponential-backoff deadline 较晚者。缓存/恢复
  不调 `sleep/monotonic`。
- max attempts 耗尽后报稳定脱敏错误；不回显 token、请求 client repr、本机路径或供应商原始响应值。

## 7. 必需测试

至少覆盖：

1. 七组 fields 精确透传；伪造 request/batch/plan hash 在 IO 前失败。
2. 2015-12 到 2016-02、闰年 2020-02、signal 月中边界仍按完整自然月。
3. 精确 60-session warmup/10-session tail；非开市 signal 边界、日历不足失败。
4. 成分乱序/重复，六位 A 股代码，各 endpoint 数量与参数。
5. receipt 命中零 API；intent-only 可继续；candidate 恢复零 API；损坏 receipt、额外 candidate-like/
   未知普通文件、孤儿 data/metadata、路径逃逸、symlink、多文件全失败。
6. data 后、metadata 后、candidate 后、receipt 临发布前四个故障注入点。
7. 同物理 raw 重用；物理路径/时间改变 stable digest 不变；值、dtype、列改变 digest 变。
8. empty policy 七 endpoint 覆盖；row count 为 limit-1/limit/limit+1。
9. fake clock 精确验证限频与退避 deadline；三类 transient、permission、contract、unknown error。
10. secret/path/client repr 不进 message、repr、traceback 或日志。
11. 旧 `RawStore.write` 回归不变，`quant.data` 不 import `quant.research`。

所有 fake connector 必须保留重复行；本包不用真实 token/网络。

## 8. 验证与交付

在 WSL Miniforge base 运行：

```bash
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
python -m pytest -q
python -m ruff check src tests
python -m mypy src
```

交付报告命名 `docs/M3_G1_B2A请求计划与Journal交付报告.md`，包含函数签名对照、修改文件、测试数量、
故障注入证据、脱敏证明、未实现项与新契约问题。不得宣称 B2/G1/M3 通过，不得更新路线图或 Gate。

独立初验 Agent 不改代码，除逐条契约映射外至少使用 8 个实现报告未出现的临时对抗反例，输出
`docs/M3_G1_B2A请求计划与Journal独立初验报告.md`。通过后仍需主 Agent 最终验收。
