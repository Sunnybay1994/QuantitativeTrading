# M4 Route 前置与 M3 HISTORY 主 Agent 集中验收报告

日期：2026-07-17  
范围：M4 B4-P0A/P0B1–P0B3、P0B 合流、M3 G1 R1C-B HISTORY 失败态  
结论：**P0A/P0B 领域链及 D1-R Route repository 闭包通过主验；HISTORY 零网络合同返工通过主验，真实 HISTORY 仍须另行授权**

本报告不关闭 B4、M4、R1C-B、G1、M3 或任何 Gate。

## 0. 增量终验结论（2026-07-17）

### Route/D1-R

- 外部实现与独立初验通过后，主 Agent 重跑 contracts、ports、connect execution、risk：`113 passed`；
- `contracts.py`、`ports.py`、`connect_execution.py`、`risk.py`、`repositories.py` 定向 mypy 通过；
- 原合流结果 `104 passed / 2 failed` 的两个缺失 `connect_contexts` 公共入口已闭合；A 股显式零 context，
  港股通按精确 route 集合加载 verified context。

因此本报告原 §1.2 缺口已关闭，P0A/P0B 与 D1-R Route repository 前置通过主 Agent 最终验收；这仍不关闭
B4、M4 或任何 Gate。

### HISTORY-H1/H2/H3

- H1 将 `suspend_d` 冻结为每个历史成员证券一个完整历史窗口请求，保留 `row_limit=5000` 与空结果
  `ALLOW`；独立初验唯一一次零网络 status 得到 `S=637`、计划 `3186`、可复用 `114`、缺失 `3072`，旧
  月窗证据 `5` 完整加 `1` 不完整原样保留；
- H2 修正 candidate 测试夹具遗漏 `ts_code` 后，暴露生产 candidate 仍按自然月验收停牌请求；实现 Agent
  遵守白名单停止，没有越权修改生产代码；
- H3 删除旧自然月闭包，改为每个 `history_symbol` 恰一个全历史窗口 `suspend_d`，并严格闭合
  `ts_code/start_date/end_date/suspend_type=S`。独立初验的集合外证券、重复证券、子窗口和非法类型反例均
  fail-closed；
- 主 Agent 最终定向回归：`197 passed / 1 deselected`，Ruff 通过，三个相关生产模块 mypy 通过；生产闭包
  中已无 `expected_months/actual_months` 旧分支。

因此 HISTORY 的**零网络代码、恢复规划与 candidate 合流合同**通过主 Agent 最终验收。该结论不代表真实
HISTORY 已抓取、R1C-B/G1/M3 Gate 已通过；当前仍禁止网络，下一步必须由用户按新的 3072 个缺失请求预算
重新授权真实 HISTORY。

### HISTORY-H4 有界恢复

为避免一次 `history` 调用放出全部 3072 个缺失请求，H4 新增 `--max-new-requests N`：只统计本轮新提交的
request identity，已有 receipt 不占额度；预算耗尽后返回 `INCOMPLETE`/0，恰好完成返回 `SUCCESS`/0，未提供
上限时保持既有 fail-closed 语义。独立初验确认预算耗尽后的非法尾部 journal 仍被全局 preflight 拒绝，且
`True` 等伪整数在 FS/API 前失败。主 Agent 复跑 8 个核心预算/CLI 测试、定向 Ruff 和三模块 mypy，全部通过。

H4 通过主 Agent 最终验收，不代表任何真实网络请求已获授权。下一步建议先授权 `N=10` 的 pilot；当前配置
`max_attempts=5`，因此授权边界应同时写明“最多 10 个新 request identity、最多 50 次含重试 API attempt”，
完成后停止并报告，再决定后续批量大小。

## 1. M4 Route 前置裁定

### 1.1 已通过的领域闭包

源码审查与定向验证确认以下链路成立：

- `ConnectRoute` 是唯一 Python route 枚举；
- `VerifiedConnectMarketContext` 是双日历和 route 买入额度的唯一领域事实；
- `OrderIntent.connect_route` 与 `VerifiedMarketSnapshot.connect_contexts` 均进入 canonical identity；
- `SymbolMarketState` 已移除 symbol 级 `buy_quota_available`；
- B2 直接消费 context，`connect_open` 只由两个开市 bool 派生；
- P3 按 intent route 精确选择 context，BUY 检查 quota，SELL 不受 quota 阻断；
- 生产代码中无 `ConnectCalendarState`、`_CONNECT_ROUTES` 或 `state.buy_quota_available` 残留。

因此 P0A、P0B1、P0B2、P0B3 的领域实现可保留，不要求回滚。

### 1.2 P0 集成缺口

主 Agent 复跑：

```text
pytest contracts + ports + connect_execution + pretrade_risk
104 passed / 2 failed
```

两个失败均为 `src/quant/data/repositories.py` 调用新版 `build_verified_market_snapshot` 时未传必需的
`connect_contexts`。定向 mypy 同样报两处 `Missing named argument "connect_contexts"`。

这不是可忽略的小问题：A 股 `ValidatedCleanMarketDataRepository` 与 `InMemoryMarketDataRepository.from_states`
公共入口已经不可用，HK repository 更无法装配 route context。故不接受“合流有条件通过”作为最终通过；Route
前置整体状态为 **主验不通过，进入 D1-R 返工**。

## 2. HISTORY 失败态裁定

外部执行与独立复验一致证明：

- INDEX 127 份 evidence 完整；`S=637`；
- HISTORY 已提交 119 份 receipt，其中 5 份为旧月窗 `suspend_d`；
- `201603` 月窗返回达到冻结 5000 行边界，按 `height >= row_limit` 正确触发
  `TUSHARE_RESPONSE_MAY_BE_TRUNCATED`；
- workflow 保持 `completed_stages=[INDEX]`，未启动 BaoStock、PREPARE 或 PUBLISH。

停止是正确的。禁止把判断改成 `height > row_limit`、提高 row_limit 或盲目重试同一月窗。

官方 `suspend_d` 文档说明接口支持 `ts_code/start_date/end_date/suspend_type`，且定位为每日停复牌信息：
<https://tushare.pro/document/2?doc_id=214>。本项目只需要历史成员并集的停牌事实，因此主 Agent 冻结下一版为：

- 每个历史成员 symbol 一个 `suspend_d` 请求；
- 请求覆盖完整 verified history window，固定 `suspend_type=S`；
- 保留 5000 行硬截断门禁和 empty=ALLOW；
- HISTORY 计划数从 `4*S+131` 改为 `5*S+1`；`S=637` 时总计划为 3186；
- 旧 5 个完成月窗和 1 个失败月窗不删除、不覆盖，只作为不再属于新 plan 的历史 evidence；
- 未变的 daily/adj_factor/stk_limit/dividend 114 个 receipt 按原 request id 零网络复用。

新计划理论缺失 request identity 为 `3186 - 114 = 3072`。该数值必须由代码返工后的零网络 status/plan 再验真；
在外部实现和独立复验完成前，不授权任何新网络请求。

## 3. 主验验证

```text
P0A/P0B 四测试文件：104 passed, 2 failed
定向 mypy 五模块：2 errors，均位于 repositories.py
静态旧 SSOT 扫描：无 ConnectCalendarState/_CONNECT_ROUTES/state.buy_quota_available
HISTORY 新进程 status（外部复验）：completed_stages=[INDEX]，history_requests=2679（旧计划）
```

未运行全量 pytest；未调用 Tushare/BaoStock；未修改 data。

## 4. 下一步

严格按 [`M4_D1Route闭包与M3_HISTORY截断返工任务单.md`](M4_D1Route闭包与M3_HISTORY截断返工任务单.md)
执行：先 D1-R，再 HISTORY-H1；两包都完成外部实现—独立初验闭环后停止，由主 Agent确认新资源并向用户请求
HISTORY 的新授权。
