# M3 G1 P0K-A raw-first 合同缺口修复——主 Agent 最终验收报告

状态：**本地实现最终验收通过；正式网络 REAL1、P0K-B 与 G1 Gate 未通过**

日期：2026-07-30（Asia/Shanghai）

实现提交：`99889ca`（`Fix P0K-A CNINFO raw-first evidence closure`）

## 1. 结论与边界

P0K-A 的本地实现合同现已闭合：

- `stock_dividend` 与 `stock_share_change` 使用冻结的官方字段码和 exact envelope；
- 新 raw 精确落在 `data/raw/cninfo/<endpoint>/<request_id>.json` 及
  `<request_id>.metadata.json`，不再复用通用 Parquet 路径；
- raw、metadata、intent、candidate、receipt、journal、verified response 与候选身份形成
  fail-closed 闭包；
- HISTORY 仍按 Tushare → rights → dividend → share 顺序推进，共享预算支持
  `max_new_requests=0` 的只读恢复；
- 两类新 frame 只进入 receipt projection 和候选身份，不进入公司行动 ledger 或 reconciliation。

用户于 2026-07-30 明确要求本轮省略外部实现和外部独立初验，由主 Agent 自行实现、审查和验证。
本报告仅关闭 P0K-A 本地实现，不把 Windows 结果表述为 Linux Gate，也不包含 1,274 次正式网络请求。

## 2. 主验发现与修复闭环

| 现象 | 根因 | 应遵循规则 | 最小复现 / 新增测试 | 通过条件 |
|---|---|---|---|---|
| 新 CA raw 落入 `data/raw/m3_g1/cninfo/.../data.parquet` | 直接复用了通用 `RawStore.write_request` | P0K-A §5 的 JSON 官方 records 与独立 metadata 路径是冻结合同 | 执行空响应后检查精确 `.json`/`.metadata.json` 路径、内容和摘要 | JSON 只含官方 records；metadata 精确绑定 endpoint、adapter、parameters、resultcode/resultmsg、count/total、columns 与三类摘要 |
| `count == row_limit` 被拒绝 | backfill 使用 `>=` | 合法范围是 `0 <= count <= row_limit` | 2 行响应分别以 limit=2/1 验证 | 等于上限通过，超过上限报 `CNINFO_RESPONSE_ROW_LIMIT` |
| workflow 拒绝预算 0 | 公共 stage 校验使用 `<= 0` | 预算 0 是合法零网络/零写恢复探针 | INDEX 后调用 HISTORY `max_new_requests=0` | INDEX-only、提交数 0、无新 connector 调用或新 CA journal |
| 部分 journal 内容损坏只表现为 incomplete | recovery 只看 receipt 是否存在，未验证残余 intent/candidate/raw | partial 可以不完整，但已存在证据必须可验证；内容损坏归 `G1_WORKFLOW_JOURNAL_INVALID/HISTORY` | 删除已提交 receipt 并破坏 candidate，再以预算 0 恢复 | code=`G1_WORKFLOW_JOURNAL_INVALID`、operation=`HISTORY`、cause=`JOURNAL` |
| 语义相同但 physical receipt/raw metadata 漂移不改变候选 key | CA stable hash 只投影语义响应 | 任一新 raw content、receipt 或 request plan 变化必须传播到候选身份 | 仅替换合法 `raw_metadata_sha256`，frame 保持不变 | primary candidate key 改变，ledger/reconciliation 保持不变 |
| 八位伪日期可进入 connector/spec | 只验证长度和数字 | 日期必须是实际存在的公历日 | `20190229`、`20261340`、`20260100` | connector 报参数错误，冻结 spec 构造拒绝 |

同时修正 `p_stock2215` 官方字段数说明为 46；row 超限、foreign/missing `SECCODE` 统一按冻结合同返回
`CNINFO_RESPONSE_SCHEMA_INVALID`。

## 3. 对抗性验证

新增 raw/metadata/receipt 篡改矩阵覆盖：

- `raw_file_sha256`、`raw_metadata_sha256`、`response_content_sha256`；
- columns、endpoint、adapter、parameters、count；
- raw 文件字节变化与 metadata `resultmsg` 变化。

十种攻击均 fail closed。旧 `stock_allotment` rights 类型、stable hash 和 raw/journal 路径未改义。

## 4. 验证证据

### Windows 原生 `D:\Miniforge3\python.exe`

- connector + backfill 全文件：`163 passed, 11 skipped`；新增篡改矩阵：`10 passed`；
- workflow 预算/partial/journal 四项：四项均通过；
- CA physical digest 候选身份：`1 passed`，230.19 秒；
- planning + release CA 闭包：`4 passed`，511.86 秒；
- 五阶段 fake publish/inspect 闭包：`1 passed`，672.74 秒；
- Ruff：通过；
- mypy（4 个生产模块）：通过；
- `git diff --check`：通过。

### WSL Miniforge `base`

- connector、backfill、4 项 workflow、candidate identity、planning 定向集合：
  `180 passed`，268.74 秒；
- Ruff：通过；
- mypy（4 个生产模块）：通过。

测试均使用 fake connector 或本地 fixture，没有读取 token、发起正式网络请求、修改正式 journal
或发送订单。Windows symlink 权限相关 skip 沿用既有平台预期；WSL 定向集合已补充 Linux 原语证据。

## 5. 尚存风险与下一步

1. 正式 HISTORY 尚缺每个 endpoint 637 个请求，共 1,274 个新 CNINFO identity；
2. 完成 raw-first 后，600733 的股份对价选版、跨源去重和停牌期基数归一化属于 P0K-B；
3. 当前源码哈希已变化，旧 Windows release 只能作为历史产物，不代表当前 HEAD 的 Verified release；
4. Linux 全量 Gate、正式 REFERENCE/PREPARE/PUBLISH 与 G1 Gate 尚未重新执行；
5. Pandera/Polars 产生大量已知弃用 warning，本轮没有改变其行为，后续单独治理。

下一步先执行 P0K-A REAL1：只读 status 确认既有 Tushare/rights 闭包与新 batch 数量，再按冻结顺序
受控提交 637 个 dividend 和 637 个 share-change identity；随后以零网络 status 复验 raw/journal
闭包，并把预期的首个业务失败交给 P0K-B。
