# M4-B4 港股通 Route 与日历接口前置裁定

日期：2026-07-17  
状态：**设计缺口已识别；B4 编码前必须冻结，尚未授权实现**  
边界：不改变已通过主验的 B2 纯规则合同，不宣称 B4/M4 Gate 完成

## 1. 当前合同断点

已验收的 B2 需要同时消费：

- `ConnectCalendarState.route`，且 route 只能是 `SH_CONNECT` / `SZ_CONNECT`；
- route 对应的内地与香港双日历开市状态；
- route 对应的额度可用性；
- per-symbol market state、board lot、tick/ELO 可申报价格带。

但 D0/D1 当前只提供：

- `OrderIntent`：没有 route 字段；
- `SymbolMarketState` / `VerifiedMarketSnapshot`：只有单一 quota 状态，没有 route 身份；
- `MarketDataRepository.load_verified_market_snapshot(...)`：没有返回 `ConnectCalendarState` 的端口；
- `TradingConfig`：没有把证券或订单确定性映射到南向 route 的版本化 selector。

因此 B4 的 `build_order_plan(..., market, account, config)` 目前无法证明它传给 B2 的 route、双日历与额度来自
哪个受信输入。由 planner 默认为 SH/SZ、按证券上市地猜 route，或把两条 route 静默聚合，都会改变可交易日、
额度和订单 identity。

## 2. 两种可行模型

### A. 显式 Route（推荐）

- 在生成/计划边界为每个港股通 intent 明确携带 `SH_CONNECT` 或 `SZ_CONNECT`；
- verified market context 以 `(session_date, route, symbols)` 为身份范围，包含该 route 的双日历与额度；
- config 只负责版本化允许 route/路由策略，不按证券代码偷偷猜；
- 同一证券若两条 route 均可用，上游必须显式选择，选择结果进入 plan/intent identity。

优点：审计、额度和恢复语义最清楚。代价：需要 D0 identity/构造器和 D1 port 的受控增量迁移，不能只改 B4。

### B. 经证明的聚合 Route

- broker/gateway 明确承诺路由对调用方不可见且能在两条 route 间原子选择；
- repository 返回新的 verified aggregate context，证明至少一条 route 同时满足双日历、额度与证券准入；
- identity 必须包含候选 route 集、聚合算法版本和所用事实，不能沿用单 route B2 对象伪装聚合。

优点：上层 intent 较简。风险：真实券商能力未验真前无法采用；任何“OR 两条额度/日历”的本地推断都可能与
券商实际路由不一致。

## 3. 冻结结论

当前选择 **A：显式 Route** 作为默认设计方向，但在 B4 编码前必须先做一个小型 `B4-P0` 合同包：

1. 冻结 route 位于 target→plan 的哪一层，以及是否进入 `OrderIntent`；
2. 为 D1 增加窄的 verified Connect market context port，禁止 planner 直接读 `data/`；
3. 冻结 route-aware snapshot/plan identity 与同一港股证券双 route 的冲突语义；
4. 用 fake broker capability 证明显式 route；真实 MiniQMT 能力以后只影响 Gateway adapter，不反向污染纯合同；
5. 迁移 D0/D1/B2/P3 消费方的文件白名单和兼容期，避免一次大包修改共享生产文件。

在 B4-P0 通过主验前，不实现 B4，不在 `OrderIntent` 外另挂未验真的 route 字符串，也不扩展 B2 接受
`AUTO`/`ANY`。这不影响 B2 作为显式 route 纯函数继续被回测和测试调用。

## 4. B4-P0 必备反例

- 同一港股证券 SH_CONNECT 开市、SZ_CONNECT 休市，缺 route 的计划必须失败而不是任选一条；
- 两条 route 日历均开但只有一条额度可用，BUY 的 identity 必须绑定实际 route；SELL 不因 quota 被拒；
- target/market/account 相同但 route 不同，plan/intent identity 必须不同；
- route-aware context 与 intent route 不一致 fail closed；
- repository 缺 route 日历、过期或重复 route facts fail closed；
- 输入顺序变化不改变结果，同一 route id 配不同 payload 必须身份冲突。
