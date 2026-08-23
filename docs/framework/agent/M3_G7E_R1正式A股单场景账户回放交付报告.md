# M3 G7E R1 正式 A 股单场景账户回放交付报告

日期：2026-08-10  
角色：外部实现 Agent  
状态：**实现与双平台自测完成；待全新独立初验。**

## 1. 交付结论

已按任务书实现单个正式 A 股成本场景的纯内存逐 session 账户回放。public API 从 fresh plan、exact F0 facts
capability、actual G7C 与 actual F2 自己构造结果，只返回七张普通内存表；没有接受 caller transition/replay/open
state/裸 frame，没有发布 artifact、receipt 或指标，也没有读取真实数据、账户或网络。

本报告只声明实现者自测完成，不声明独立初验、主验、G7、M3 或 Gate PASS。

## 2. 生产实现

### 2.1 Fresh 与身份闭包

- 新增 `AShareSimulationFreshVerificationContext`、`AShareSimulationError` 与
  `simulate_formal_a_share_scenario`，并作安全 public export；
- exact 校验 public 输入、成本期间、multiplier 与 initial cash；
- 在创建账户/G7C replay 前 exact once 调用模块 import 的 public `verify_backtest_plan_artifact`；
- fresh plan 与 outer plan 的 root、manifest、manifest/receipt hash、scheduled frame 全部 exact；全程只 clone/use
  fresh scheduled targets；
- 访问 exact F0 capability identity，闭合 release、plan manifest/receipt，再取得八表 clone；
- execution window、SH open calendar、benchmark session、schedule batch 与成本期间逐日闭合。

所有 public 失败统一为 `AShareSimulationError("M3_A_SHARE_SIMULATION_INVALID") from None`。hostile verifier 的
路径/token/内部消息、cause 与 context 不向 caller 泄露。

### 2.2 每日账户时序

逐日严格执行：上一日买入 rollover → actual G7C pre-open advance → cash/stock settlement → 盘前 Decimal mark/NAV
→ 完整目标补零 → actual F2 exact once → close mark/NAV → actual G7C record-close capture → 七表快照。

- 初始现金、空持仓、空 entitlement replay；
- G7C settled stock 直接成为 sellable，不记为当日买入 unsettled；
- capture 使用 F2 后实际总持仓；CAPTURED 不计 NAV 应收，RECOGNIZED 才计；
- 结束时要求 entitlement replay phase `COMPLETE`，但允许未双 leg settled 的 entitlement 保留。

### 2.3 独立 mark book 与 Decimal

- mark book 独立于 `PositionBook`，覆盖 active target、正持仓与未双 leg settled entitlement symbol；
- 原股卖到零仍保留最后合法 mark，后续 FULL_DAY stock-list-date 可先估值 recognized receivable，再生成新的
  sellable position；
- raw bar 使用 open/close；普通 FULL_DAY carry previous mark；公司行动 FULL_DAY 只用 reconciliation 的 positive
  actual factor ratio 调 public `mark_full_day_event_from_factor`；缺 mark/非法事实 fail closed；
- 金额、mark、费用、应收、权益与 turnover 全程 Decimal；私有 context 与 F2 同为 precision 80、
  `ROUND_HALF_UP`、扩展指数域且 traps disabled，caller context 调用前后不变；
- turnover 固定为 `sum(abs(fill.notional))/pre_trade_equity`，one-way 为 gross/2，不复制 development max-side 口径。

### 2.4 七张表

返回并逐 Schema 验证：NAV、trades、positions、rejections、corporate-action postings、daily diagnostics、
entitlements。空表保留 exact schema，输出排序稳定，只有表边界执行 Decimal 到 Float64 的单向投影。函数不写
Parquet/JSON、目录、hash、receipt 或 manifest。

## 3. 测试边界与反例

测试遵守任务书 §13 模块化边界：

- F0 来源闭包复用已主验 formal test 的窄 `_issued_capability`，不运行完整 G1；
- 只 monkeypatch G7E 模块 import 的 public plan verifier，覆盖 exact once、hostile、nonexact 与 stale outer；
- G7C/F2 始终调用 actual public API，不 monkeypatch账户数学、prepare/seal/registry 或 capability；
- nested plan context 复用既有 target formal helper 的 exact普通值；另用 public dataclass constructors 建立约60行
  exact release test value，只作为 mocked verifier 参数，不作来源证明且不传给未 mock upstream；
- 无 `object.__new__`、`SimpleNamespace`、development manifest 冒充、临时 support 文件、debug print 或失败草稿。

五 session / 三证券 golden 显式核对七表，覆盖：

- record-close 当日买入计入 capture；CAPTURED 当日不进入 NAV；
- cash 与 stock 不同结算日；原股卖到零后 recognized stock receivable 仍按独立 mark 估值；
- FULL_DAY factor mark，stock-list-date 从保留 mark 生成 sellable 红股并按目标卖出；
- 合法正目标但无 open 时保留 F2 nullable target/rejection quantity，不用 close 反推；
- 涨停买拒绝、blocked sell、lot residual、最低佣金、先卖后买与 asymmetric gross/2；
- terminal lower-limit blocked exit 保留 position、`target_quantity=0` 与 `pending_exit=True`，不强平；
- schedule row reverse 后七表逻辑内容与排序不变；facts capability 只提供 F0 已签发的 canonical frames，G7E 无裸
  frame 输入，因此不伪造非canonical capability来制造“facts frame shuffle”。F0 canonical/order由其主验套件负责；
- caller precision 4 + `Inexact` trap 下七表与标准调用相同，caller precision/rounding/traps/flags 不变；
- fake facts 在 property access 前拒绝，API 不暴露 caller F2/G7C/open-state/frame 参数。

F2 邻接正式测试继续覆盖 T+1 partial、主板/科创板 lot、Fraction allocation、五类 ordinary rejection、§14
special 与 reference digest；G7E 不复制或二次撮合这些语义。

## 4. 文件清单

- `src/quant/backtest/a_share_simulator.py`；
- `src/quant/backtest/__init__.py`；
- `tests/unit/test_m3_g7e_formal_a_share_simulator.py`；
- `tests/integration/test_m3_g7e_formal_a_share_simulator_golden.py`；
- `docs/framework/agent/M3_G7E_R1正式A股单场景账户回放任务单.md`（只更新状态）；
- 本报告。

## 5. 验证证据

Windows Miniforge，工作树自身 `src`：

- G7E unit + golden：`6 passed`；
- F0/G7B/G7C/F1/F2 + development simulator 邻接：`88 passed`；
- Ruff：通过；
- mypy `a_share_simulator.py`：通过；
- cold import：通过。

WSL Miniforge `base`，同一工作树：

- G7E unit/golden 与上述邻接合并：`94 passed`；
- Ruff：通过；
- mypy `a_share_simulator.py`：通过；
- cold import：通过。

测试仅有 Pandera deprecation 与受限 `.pytest_cache` warning，无失败。WSL 路径落在 DrvFS 映射，以上只算
双平台兼容证据，不声称 Linux/ext4 Gate。

## 6. 剩余风险与交接

- 七表是普通可变 DataFrame 值，不是 authority；后续 G7F 必须 fresh 重跑并逐表 Schema/经济复算与
  whole-rehash，不能信任 caller result；
- §13 的模块化 fixture 不重新证明 F0/G7B 来源闭包，该证明继续由其已主验正式套件负责；
- 未实现 0.5×/1×/2× orchestration、benchmark return、metrics、writer、manifest、receipt 或 publication；
- shared worktree 有其他里程碑既有改动；本轮只对上述白名单文件负责；
- 下一步必须由未参与实现的全新外部 Agent 独立初验并增加实现者未用反例，之后才可进入主 Agent 最终验收。
