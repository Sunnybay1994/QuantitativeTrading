# M4 B4-P0B 显式 Route 贯通外部闭环任务单

日期：2026-07-17  
状态：**冻结；仅在 P0A 外部独立初验通过后执行**  
目标：把 P0A 的 `ConnectRoute` / `VerifiedConnectMarketContext` 串行接入 intent、snapshot、B2 和 P3，消除
symbol 级额度与第二套日历事实；不实现 B4 planner，不关闭 B4/M4 Gate。

## 1. 共同设计裁定

- 港股通订单必须显式选择 `ConnectRoute.SH_CONNECT` 或 `ConnectRoute.SZ_CONNECT`；A 股订单 route 必须为
  `None`。禁止裸字符串、`AUTO`、`ANY`、按证券代码猜 route 或把两条 route 做 OR 聚合。
- `buy_quota_available` 是 route/session/as_of 事实，唯一 SSOT 为 `VerifiedConnectMarketContext`；从
  `SymbolMarketState` 删除该字段及 identity payload，调用方和测试同步迁移。
- `OrderIntentSpec`、`OrderIntent` 新增 `connect_route: ConnectRoute | None`，字段进入 intent identity。HK 必须
  非空，SH/SZ 必须 `None`；同一 target/snapshot/account/config 下只改 route，intent id 必须改变。
- `VerifiedMarketSnapshot` 新增 `connect_contexts: tuple[VerifiedConnectMarketContext, ...]`，按 route 排序并进入
  snapshot identity。route 唯一；context session 与 snapshot session 相同，context `as_of <= snapshot.as_of`。
  snapshot 含 HK state 时至少一个 context；不含 HK state 时 contexts 必须为空，避免无关 route 改变 A 股身份。
- B2 直接消费 `VerifiedConnectMarketContext`，不再消费可独立构造的 `ConnectCalendarState`；`connect_open` 只在
  规则层按 `mainland_open and hong_kong_open` 派生。BUY 检查 context quota，SELL 不受 quota 阻断。
- `ConnectRuleConfig.route` 改为精确 `ConnectRoute` 并进入既有 identity；删除本模块 `_CONNECT_ROUTES`/裸字符串
  校验。Schema 中历史 route 列暂保留字符串存储，但新 Python 领域代码只能 import 枚举。
- P3 对每个 HK intent 在 snapshot 中查唯一同 route context，验证 session、as_of、snapshot identity 后再读取
  quota。缺失/重复/mismatch/未来 context fail closed；SH/SZ 不消费 connect context。
- 本迁移处于 M4 未发布阶段，不保留旧构造器兼容重载，不同时维护新旧 identity。所有直接消费者和 fixture 必须
  显式迁移；禁止默认填 route 或 quota。

## 2. P0B1 — D0 intent/state/snapshot 合同迁移

### 白名单

- `src/quant/execution/contracts.py`
- `src/quant/execution/__init__.py`
- `tests/unit/test_execution_contracts.py`
- `tests/unit/test_execution_ports.py`（只改受构造器迁移影响的 fixture）
- `docs/agent/M4_B4-P0B1领域合同迁移交付报告.md`

不得修改 B2、P3、repository、config、数据或其他测试。若现有直接消费者因此暂时失败，只在报告列清单，留给
P0B2/P0B3；不得跨白名单修补。

### 必测反例

1. HK 缺 route、裸 string、错误 enum 失败；A 股携带 route 失败。
2. 同 payload 只改 SH/SZ route，intent id 改变；篡改 route 后 identity builder 拒绝。
3. `SymbolMarketState` 不再接受或散列 quota；不存在静默兼容 kwargs。
4. snapshot contexts 顺序不影响 identity；重复 route、错 session、未来 as_of、forged context id 失败。
5. 有 HK state 无 context、无 HK state 有 context均失败；SH/SZ-only snapshot identity 不受港股通事实影响。
6. intent/snapshot 原有 forged id、bool/type、时间和顺序反例继续通过。

只跑 contracts/ports 中迁移节点、定向 Ruff/mypy，不跑全量。

## 3. P0B2 — B2 消费唯一 RouteContext

前置：P0B1 独立初验通过。

### 白名单

- `src/quant/backtest/connect_execution.py`
- `src/quant/backtest/__init__.py`
- `tests/unit/test_connect_execution.py` 或实际 B2 直接测试文件
- `docs/agent/M4_B4-P0B2港股通规则迁移交付报告.md`

若测试文件实际名称不同，设计 Agent 先用 `rg --files tests/unit` 定位并在调度台账冻结；不得新建第二套重复测试。

### 必测反例

1. context route 与 config route 不同失败；intent route 与二者任一不同失败。
2. context 只有一地开市时拒绝；不得存或信任调用方自报 `connect_open`。
3. BUY quota false 拒绝，SELL quota false 仍按 sellable/lot/price 规则执行。
4. 同 symbol 两 route 一开一闭时只消费 intent 指定 route，不任选、不聚合。
5. forged context/config/intent/state 在读取经济字段前失败；未来 as_of 或错 session 失败。
6. B2 已主验的 lot、mixed-lot、tick、ELO、Decimal 极值和规则有效期回归继续通过。

## 4. P0B3 — P3 route-aware 风控迁移

前置：P0B2 独立初验通过。

### 白名单

- `src/quant/execution/risk.py`
- P3 的唯一现有测试文件（先 `rg --files` 定位并登记）
- `docs/agent/M4_B4-P0B3事前风控迁移交付报告.md`

不得修改 contracts/B2/P0/store/config。

### 必测反例

1. HK BUY 精确匹配 route context 且 quota false 时拒绝；SELL 不因 quota false 被拒。
2. HK intent 缺 context、route mismatch、错 session、context 晚于 market snapshot/as_of 全部 fail closed。
3. 同 symbol 双 route context 存在时按 intent route 精确选择；不能使用第一项或 OR。
4. A 股不需要 context；任何 A 股既有 T+1/sellable/仓位规则不漂移。
5. 篡改 snapshot contexts、intent route 或 context payload 后即使携带旧 id 也失败。
6. P3 已主验的总开关、data gate、冻结、sell-only、批次聚合、gross exposure、时点与 counters 回归继续通过。

## 5. 每个子包的外部闭环

每个 P0B 子包由一个全新 `cursor-grok-4.5-high` 实现会话和另一个全新只读
`cursor-grok-4.5-high` 验收会话完成。初验失败必须返工并再开新复验。独立报告命名为对应交付报告名加
`独立初验报告`/`独立复验报告`。只运行改动节点与直接回归、定向 Ruff/mypy；三个子包合流后运行一次 D0+B2+P3
定向合流，不跑全量 pytest。

三包通过只代表 route 前置外部闭环完成；B4 planner、D1 生产 repository、真实 route 数据和 M4 Gate 仍未完成。

