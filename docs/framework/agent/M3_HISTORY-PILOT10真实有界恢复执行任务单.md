# M3 HISTORY-PILOT10 真实有界恢复执行任务单

## 1. 状态与授权门槛

本任务单已冻结并获用户授权执行“最多 10 个新 request identity、最多 50 次含重试 Tushare API
attempt”。2026-07-18 用户进一步批准将后续任务书及其白名单代码/测试发送给 Cursor 外部服务；该批准不扩大
本任务的网络、请求身份或重试预算。

当前零网络已验收基线：

- `S=637`；HISTORY 计划 `3186`；可复用 receipt `114`；缺失 `3072`；
- `completed_stages=[INDEX]`；
- 旧全市场月窗 `suspend_d` 证据 5 个完整、1 个不完整，只作历史证据，不删除、不覆盖；
- H4 已验收 `history --max-new-requests N`，预算只计新 committed request identity；
- 配置 `request_rate_per_minute=60`、`max_attempts=5`、`retry_base_seconds=2.0`。

## 2. 外部执行 Agent

使用全新 `cursor-grok-4.5-high` 会话。Cursor 从 Windows 启动，项目命令只在 WSL
`/home/mabw/AI_Coding_win/QuantitativeTrading`（当前指向同一工作区）的 Miniforge `base` 执行。

执行前：

1. 完整读取 `AGENTS.md`、本任务单、H4 交付/独立初验报告和集中主验报告；
2. 当前 `.git` 不是有效 Git 仓库，故只核对 `.gitignore` 中存在 `configs/tushare.local.toml` 精确规则；不得读取、
   输出或复制该本地配置及 token，也不得把“存在 ignore 规则”表述为已完成 Git ignore 运行态验证；
3. 运行一次零网络 `status`，必须与上述 3186/114/3072/[INDEX] 基线一致；不一致立即停止；
4. 记录 raw/journal 相关计数和既有证据摘要，不读取 `data/legacy/`。

唯一获准网络命令：

```bash
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 10
```

边界：

- 最多新增 10 个 request identity；依照 `max_attempts=5`，最多 50 次含重试 API attempt；
- 禁止重复运行命令、自动扩大 N、启动 `reference/prepare/publish/run-all` 或调用其他数据源；
- 禁止代码、测试、配置变更；只允许正常 raw/journal/receipt 新增和唯一执行报告；
- 任一权限、截断、contract、网络或 journal 错误立即停止，不手工修文件、不放宽门禁；
- 命令完成或失败后立即停止，不自行启动下一批；长运行低频检查。

唯一报告：`docs/framework/agent/M3_HISTORY-PILOT10真实有界恢复执行报告.md`。报告只写稳定错误码、请求身份/endpoint
计数、committed 数和脱敏 receipt/raw 摘要，禁止原始响应长日志和凭据。

## 3. 外部独立验证 Agent

执行 Agent 停止后，使用另一全新 `cursor-grok-4.5-high` 会话。生产代码、测试、配置、raw、journal、receipt
全部只读，唯一允许写：

`docs/agent/M3_HISTORY-PILOT10真实有界恢复独立验证报告.md`

验证：

1. 用户授权上限未突破；API attempt 无法由 receipt 直接证明时必须如实标为“仅由执行日志/重试配置约束”；
2. 成功时恰新增 10 个 committed identity，旧 114 个不被计入，CLI 为 `INCOMPLETE`/0，阶段仍仅 `[INDEX]`；
3. 失败时核对 committed 数与错误前后守恒，不要求凑满 10；
4. 每个新增 receipt/request/raw identity、digest、endpoint policy 和 raw 文件闭合，既有 5+1 月窗证据不变；
5. 运行一次零网络 status 获取新的 reusable/missing 计数；成功时应为 124/3062；
6. 不运行 pytest、网络、下一批或任何修复。

验证通过只证明 pilot 证据闭合，不代表 HISTORY/R1C-B/G1/M3 Gate 完成。交回主 Agent 后，由主 Agent 决定
下一批上限或返工任务。
