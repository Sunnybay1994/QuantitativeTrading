# M3 HISTORY-BATCH25 真实跨 Endpoint 恢复执行任务单

日期：2026-07-18  
冻结角色：主 Agent  
状态：**待用户明确授权新增网络预算后执行**；用户 24 小时流程简化仅省略外部 Agent，不自动扩大网络预算

## 1. 前置事实

- [`M3_HISTORY-PILOT10真实有界恢复执行报告.md`](M3_HISTORY-PILOT10真实有界恢复执行报告.md) 与
  [`M3_HISTORY-PILOT10主Agent直接验证报告.md`](M3_HISTORY-PILOT10主Agent直接验证报告.md) 已确认首批成功。
- 当前权威 baseline：`history_requests=3186`、`verified_reusable=124`、`missing=3062`、
  `completed_stages=[INDEX]`、计划内 partial=0。
- 当前 WSL 路径 `/home/mabw/AI_Coding_win/QuantitativeTrading` 映射
  `F:\AI_Coding\QuantitativeTrading`；项目命令只在 WSL Miniforge `base` 运行。
- XP0 已通过；writer lock 不再是本批阻塞。

## 2. 批次选择与预算

按生产 HISTORY batch 的 canonical request-id 顺序，选择 baseline 中前 25 个缺失 identity。执行前重算时必须满足：

```text
next25 identity set sha256 = 14f548b16f0eb4e9a4e4bf763afb5047a378024f05f09a72c6127477215674d4
adj_factor = 2
daily      = 3
dividend   = 4
stk_limit  = 1
suspend_d  = 15
```

任何 identity 集合或 endpoint 计数漂移立即停止，不联网修正。

唯一拟授权网络命令：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 25
```

预算：最多 25 个新 committed request identity；冻结配置 `max_attempts=5`，故最多 125 次含重试 API attempt。
已有 124 个 verified receipt 不计入新额度。命令只运行一次；失败或部分提交后不得补跑余额。

## 3. 跨 endpoint 风险合同

| endpoint | 本批数量 | row limit | empty response |
|---|---:|---:|---|
| `adj_factor` | 2 | 6000 | REJECT |
| `daily` | 3 | 6000 | REJECT |
| `dividend` | 4 | 5000 | ALLOW |
| `stk_limit` | 1 | 5800 | REJECT |
| `suspend_d` | 15 | 5000 | ALLOW |

本批首次同时覆盖 `daily/adj_factor/stk_limit` 的非空门禁。任一权限不足、空响应被 REJECT、row-limit 截断、
网络/服务端、contract、journal、raw 或 receipt 错误：立即停止；不放宽 policy、不切换数据源、不改代码/配置、
不重复命令。

## 4. 执行前与执行后验证

执行前必须重新得到：

```text
3186 total / 124 verified / 3062 missing / [INDEX] / planned partial=0
```

全成功时预期：

```text
new_requests_committed = 25
verified_reusable = 149
missing = 3037
completed_stages = [INDEX]
outcome = INCOMPLETE
```

执行后必须使用生产 `verify_tushare_receipt` 逐条验证本批 25 个 identity 的 spec、request/raw identity、digest、
endpoint policy 与 raw bundle；验证总计守恒、计划内 partial 未新增、旧 5+1 月窗证据未变。实际 API attempt 精确
次数若无可验证日志，不得从 receipt 猜测，只报告单命令与 125 上限。

若只提交 `k < 25` 后失败，则必须满足：

```text
verified_reusable_after - 124 = k
3062 - missing_after = k
```

不得为了凑满 25 再运行命令。

## 5. 文件与外部状态边界

- 不修改生产代码、测试、配置、README、路线图、`.git`、既有报告。
- 只允许正常新增本批 raw/journal/receipt 与报告：
  `docs/agent/M3_HISTORY-BATCH25真实跨Endpoint恢复执行与主Agent验证报告.md`。
- 不读取、输出、复制或记录 token；只确认 ignored 本地凭据配置存在。
- 不启动 REFERENCE、PREPARE、PUBLISH、run-all 或下一批 HISTORY。

## 6. 流程简化

若在用户 24 小时临时授权窗口内执行，本批由主 Agent 直接执行和验证，可使用内部只读 Agent 辅助；不调用
Cursor 外部服务，也不生成虚假的“外部独立初验”结论。窗口结束后重新服从当时有效的协作流程。
