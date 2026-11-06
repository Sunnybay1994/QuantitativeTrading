
- 用户在 24 小时内暂停外部 Cursor Agent，实现/初验由主 Agent 完成；允许内部子 Agent 并行。用户持续
  授权 Tushare API，无需逐次确认，但必须按 2000 积分档、接口独立权限、行数和限频统筹，禁止泄露 token。
- M3 HISTORY raw/receipt 已完成 `3186/3186` identity closure；当前 G1 仍受基准 full-OHLC 选择与分红
  语义阻塞，尚无 `VerifiedG1Release`。旧的“HISTORY-PILOT10 尚未执行”描述已失效。
- M1 HK Instrument：Tushare `hk_basic` 补全股票；`02983.HK` 按 HKEX 最终公告投影
  2026-07-10 至 2026-08-13 临时柜台生命周期。31 个 ETF 曾由 HKEX 网页 JSONP 补入，但后续许可审计
  发现 HKEX 现行条款禁止未经书面许可的脚本化访问/系统性抓取/建库，R2A 通过结论已撤回，默认 connector
  固定 `HKEX_ETP_LICENSE_REQUIRED` 且零网络；ETF 合规来源重新成为完整 Instrument Gate 阻塞。
- available-history Gate 已解耦：优先使用双 Route 官方资格事实的 `security_type` 排除 31 个 ETF；613 只
  官方 STOCK 仍必须有 Instrument 生命周期。双 Route 真实验证均为 11 只结构性短历史、缺 36,374 个
  应有 session，当前只因 60 日行情未回填而失败，不再被待授权的 ETF Instrument 行阻塞。
- `hk_daily(trade_date=20260710)` 恰好一次权限探针成功：613 个目标覆盖 612 个，缺 `02983.HK`；raw
  snapshot `122521.406613Z-f5b205dcd4e7`。`02609.HK` 的 open 超出供应商 high，现仅对港股 open-only
  口径差异扩展 canonical high/low，raw 和跨市场 Schema 不变；双平台定向测试通过。
- P1 在冷却 60 分钟后用恰好一次 `hk_daily` 请求实测 `00005.HK,00700.HK` 的 60 日区间，返回 120 行；
  两代码各 60 个精确开市日、零重复/空值/目标外证券并通过 Schema，raw snapshot
  `132620.624930Z-77c02bc1c1a8`。下一步按保守上限 83 只/批冻结可恢复 manifest；逗号多代码未由港股
  接口文档明确承诺，任何漂移必须 fail closed，HKEX 公共网页/JSONP 不作为候选生产源。
- HK60 strict plan 已生成：SHA `ffbf8f345626b9db834a7b4c31fa8c31a6b60ffe5053ab4953a27bb2c4c50a03`，
  613/36,376 键拆为 P1 seed 120、`02983` 未解决 1、剩余 610/36,255 的 8 批（`80×7+50`）。代码、
  跨平台测试、真实 plan 冷却 smoke 和 8 批 fake finalize 均通过。真实第一批 80 只/4,800 键 PASS，
  raw SHA `26942dee...f7eb`，clean 零写入；剩余 7 批由 WSL 隐藏单写者按 3,610 秒间隔运行，任一失败即停，
  日志位于 `artifacts/hk_history_backfill/<plan_sha>/runner.*.log`。23:29 第二批单请求 PASS；当前 2/8、
  failure=0、无 finalize，禁止提前发布 clean。
- M1-U0C 已为 2026-07-20..24 每日 21:30 注册五个 Windows 一次性任务，实际配置均 Ready、
  IgnoreNew、wake、missed start ASAP、RestartCount=0，XML/hash 已固化。独立初验发现日志 identity 边界
  可被异常 runner 注入绝对路径，已收紧为 64 位小写 hash 和唯一相对 receipt selector并新增反例；修复后
  WSL/Windows 合并定向集均为 27 passed 且 Ruff/mypy 通过，真实 Gate 仍为 0/5。Task Scheduler Operational 历史通道
  仍关闭，需管理员在 7 月 20 日首跑前启用；项目单行日志和 task info 不受影响。
- 2026-07-19 HK60 第 3 批以 `HK_HISTORY_RAW_INVALID` fail-closed 停止，runner 已退出；当前 2 receipt /
  3 intent / 3 attempt / 0 finalize。唯一缺键为 `01065.HK@2026-05-05`。2026-07-22 一次 targeted
  `hk_daily` 仍返回 0 行并 raw-first 留存，证明不是批量偶发漏行；现行 session 全覆盖合同需要显式无行情
  事实语义。禁止重试旧 attempt 或 finalize，见
  [`agent/M1_HK-HISTORY-R1_第三批稳定缺行事故与重试裁定.md`](../framework/agent/M1_HK-HISTORY-R1_第三批稳定缺行事故与重试裁定.md)。
- M1-U0C 的 2026-07-20、21 两次真实 Task Scheduler 运行均 result=0，项目日志均证明首次 SUCCESS、同
  identity 重放 ALREADY_COMPLETE；当前 streak 2/5。Operational 历史通道仍关闭，最终以项目日志、
  verified receipt 和 Task info 共同验真，不把 2/5 写成 Gate 通过。

## 1. 项目目标和当前状态

### 1.1 目标

建设一套个人使用、日频起步、面向 A 股和港股通的轻量量化投研交易系统：

1. 交易所/Tushare/免费校验源进入统一 raw/clean 数据层；
2. 因子、策略和模型只消费经过验证的数据，以统一 `target_weight` 作为研究到交易的边界；
3. 所有候选策略回到同一个中国市场规则、费用和账户模拟层准入；
4. 先完成 PAPER/SHADOW、OMS、风控和对账，再评估 QMT/PTrade 等实盘 Gateway；
5. 数据、配置、代码、身份和实验结果可追溯，任何数据质量或身份门禁失败均 fail closed。

### 1.2 当前停止点

| 里程碑 | 当前状态 | 结论 |
| --- | --- | --- |
| M0 骨架与契约 | 已完成 | 项目结构、Schema、枚举、连接器边界和最小测试已建立 |
| M1 基础数据 | 主链大部完成，Instrument/历史仍有阻塞 | 股票、日历、港股通事实链和查询已贯通；HK ETF 合规来源、港股 60 日行情、复权和连续运行未关闭 |
| M2 基线策略 | 工程闭环完成 | S0/S1、总回报研究价、walk-forward、成本压力、报告及股票/ETF 统一日频事件模拟器均已完成；候选池后见偏差和券商成本校准限制继续披露 |
| M3 Qlib 研究链 | 3190 HISTORY receipt 闭包，正式候选质量失败 | 510300 五响应/mapper 已闭合；full candidate 为 `G1_CANDIDATE_COMPONENT_INVALID`；无正式 `VerifiedG1Release` |
| M4 纸面交易 | 基础领域/存储/OMS/风控子包完成，业务闭环未完成 | 配置、领域合同、端口、SQLite、OMS、事前风控、港股通纯规则与 RouteContext 已有；planner/账本/Paper Gateway/服务/对账/操作尚未闭环 |
| M5 实盘 | 未开始 | 当前没有券商量化权限；不实现或启用 LIVE/无人值守交易 |

2026-07-22 本次交接前的 R5 Cursor 会话已自然结束；HISTORY 已在后续任务中完成 3190/3190 raw/receipt
闭包。不要再按旧 PILOT10 或旧 3186 停止点重做，也不要重复消耗五个 510300 API identity。

### 1.3 最近真实数据终态

- SH clean event：1,212 行，ADD 794、REMOVE 418；reverse audit 为 `current=644,event=1212,reverse=268,PASS`。
- SZ clean event：1,237 行；reverse audit 为 `current=644,event=1237,reverse=417,PASS`。
- SH historical universe：1,062 个区间、919 个历史证券、2014-11-17 基线 268、2026-07-10 成员 644。
- SZ historical universe：1,149 个区间、1,014 个历史证券、2016-12-05 基线 417、2026-07-10 成员 644。
- 两个 universe 的 dry-run preview 与发布文件逐字段一致；基线前一日查询均抛 `EligibilityHistoryError`。
- 终验证据：[`agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md`](../framework/agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md)、
  [`agent/M1_SSE-REAL2双Route历史Universe发布主Agent最终验收报告.md`](../framework/agent/M1_SSE-REAL2双Route历史Universe发布主Agent最终验收报告.md)。

## 2. 已完成的功能

### 2.1 项目治理和目录

- 建立 `AGENTS.md`、`.ai/` 通用工程规则、SSOT 表和“文档随代码更新”规则。
- 按绿地项目处理：生产代码不得 import `archive/legacy_pre_greenfield/`；`data/legacy/` 不参与默认发现。
- 代码、数据和产物分离：`src/`、`data/`、`artifacts/`、`archive/` 各自有明确职责。
- 复杂里程碑采用“主 Agent 冻结任务书 → 外部实现 → 不同外部会话独立初验 → 主 Agent 终验”，初验失败必须返工复验。
- 外部 `cursor-agent` 从 Windows 启动，但项目命令固定进入 WSL Miniforge；所有新会话统一使用
  `--model auto`，不得把旧任务文档中的固定 Grok 型号继续作为当前派发指令，也不得推断 `auto` 的底层模型。
- 外部 Agent 与 Luna Worker、实现 subagent 属于平级执行通道。Worker 及其创建的 subagent 不得自行启动、
  调用、恢复或委派外部 Agent；需要外部能力时必须 STOP 并回报原派发者，只能由用户、统筹或获授权领域经理
  在冻结任务边界后直接派发。
- 用户于 2026-08-30 重申领域边界：compiler/toolchain/parser/wrapper/capability fixture、流式大 JSON 证据工具
  等工具性质开发统一归框架领域；投研经理只负责策略、因子、经济假设、PIT/回测合同与研究结论。此前待批的
  M2 C1B compiler/wrapper 包转框架线重新冻结，投研线不得继续创建或执行；新框架包在另行授权前继续保持
  no-network/install/download、无 C1A fallback、R3/exact9/data 未读且 large-input 未执行。

### 2.2 M1 数据层

- `BaseConnector`、Tushare、BaoStock、AKShare、上交所/深交所官方连接器和独立 mapper。
- raw 不可覆盖快照、JSON 元数据、请求参数、行列信息、抓取时间和 SHA-256 闭包。
- clean Parquet 的 Schema、唯一键、OHLC、缺失观测、异常跳点、连续性和跨源质量门禁。
- A 股/港股行情、复权因子变化事件、三地交易日历、证券主表、研究调整价、ETF 分红总回报链。
- DuckDB 最近 N 个观测查询，以及 `as_of` 时点港股通成员 × 历史行情窗口查询。
- 港股通双 Route 快照、事件、交易日历、reverse audit、membership preview、受控 single-route replace 与
  guarded universe 发布。
- HKEX 2026 年度通告覆盖 14 个工作日全日休市和 3 个半日市；双 Route 2026 日历审计无违规。
- 数据主源为 Tushare Pro 2000 积分，港股通资格和服务日以交易所官方事实为准，BaoStock/AKShare 做校验和降级。

### 2.3 M2 策略和薄回测

- 策略统一输出 `TargetWeightSchema`；策略不下载数据、不下单、不读取账户。
- `ETF_POOL_M2_V1` 共 11 只；20/60/120 日动量、60 日回归斜率×R²、绝对趋势和现金过滤。
- 收盘后信号只安排到下一开市日，不允许同日收盘前视成交。
- S0 买入持有和等权月调仓、S1 两折 walk-forward、0.5×/1×/2× 成本压力、QuantStats 报告。
- 研究收益统一采用“不复权价格 + 现金分红再投资”的总回报序列；账户仍使用不复权成交/估值和现金流。
- A 股 T+1、整手、停牌/涨跌停、费用和拒绝原因等规则原语已接入统一股票/ETF 日频事件回测器。

### 2.4 M3 研究基础

已经通过主 Agent 最终验收的主要子包包括：

- C0 严格 TOML、未知键/跨字段校验及九类分层 identity；
- G0 Python 子项：`py312` + Python 3.12.13 + `pyqlib==0.9.7` 兼容探针；
- E3 严格 Receipt、路径脱敏、no-clobber 发布语义；
- B2A 请求/raw journal、P1 readiness/schema、P2-0 信号边界、B3 PIT 成员状态、B2C 执行事实；
- P4A/P4B/P4C candidate、来源闭包与不可变发布合同；
- R0 权威日历、R1A 运行身份/计划、R1L 崩溃安全 journal 锁、R1B 可恢复 workflow、R1C-A 分阶段 CLI；
- INDEX 真实阶段：127 份 evidence 完整，`S=637`，workflow 为 `completed_stages=[INDEX]`；
- HISTORY-H1–H3：把 `suspend_d` 从错误月窗改为每个历史成员一个完整窗口；
- HISTORY-H4：`history --max-new-requests N`，预算只计算本轮新 committed identity，预算耗尽返回
  `INCOMPLETE`/0。

HISTORY 计划 `5*S+1 = 3186` 个 identity 已全部形成 raw/receipt 闭包。旧失败证据仍保留为历史
evidence，禁止删除或覆盖；后续只处理 G1 契约/发布阻塞，不重复 HISTORY 获取。

### 2.5 M4 交易基础

- `TradingConfig`、安全默认值、identity；拒绝 LIVE 和 `auto_trade=true`。
- 领域枚举和值对象、严格 identity、订单/事件/快照合同。
- Market/Account repository Protocol 与 route-aware production/fake repository。
- SQLite migration/store、trusted root、symlink containment、订单与事件幂等冲突。
- SQLite v2 transactional outbox delivery：deterministic claim、lease attempt fencing、`SENT/UNKNOWN` 终态、
  `TX_BUSY` fail-fast 与方法级 SAVEPOINT 全有或全无；只关闭 P4 存储前置，不代表 service/P4 Gate 完成。
- OMS `reduce_order` 纯状态机：重复、乱序、部分成交、拒单/撤单等合同。
- `evaluate_pretrade` 事前风控：输入自证优先、批次汇总、资格/现金/限制检查。
- 港股通纯规则：双日历、route context、额度、board lot/碎股、tick 精确整除；BUY 和 SELL 额度语义分离。
- `ConnectRoute → VerifiedConnectMarketContext → intent/snapshot → connect execution → risk` 链已贯通。
- Route 参数加入后遗留的 OMS 测试 helper 漂移已修复；当前 execution 六文件合流为 WSL `331 passed`，
  Windows `326 passed, 5 skipped`，不再保留原 41 项 TypeError。

## 3. 关键架构决策及原因

| 决策 | 原因 |
| --- | --- |
| Parquet + Polars + Pandera + DuckDB 为轻量数据主干 | 无需常驻服务，列式读写和本地查询足够；Schema/质量门禁明确 |
| raw 不可覆盖，clean 可重建但必须受控发布 | 保留供应商原始事实、支持复现与纠错，避免错误派生数据静默污染 |
| 交易所官方事实 + Tushare 主源 + BaoStock/AKShare 校验 | Tushare 接口统一但权限/限频存在；港股通规则和资格必须以官方源为准 |
| 当前不接 Tushare MCP | 正式管道需要确定参数、raw 留档、限频、重试和可复现；MCP URL 携带 token，增加日志/配置泄露面。正式数据继续走 connector |
| Qlib 只处在 clean 之后的研究路径 | 它擅长 Alpha158/模型/实验，不负责原始数据治理、OMS、对账或实盘状态 |
| vectorbt 仅是可选规则实验台 | 适合 ETF/参数扫描，但复杂中国市场成交必须回到统一回测层；不进入交易运行时依赖 |
| QMT/PTrade/MiniQMT 只作为外部 Gateway | 券商政策和 Windows 环境不稳定；策略、组合、OMS 必须与具体通道解耦。新用户优先评估 QMT/PTrade，MiniQMT 仅存量候选 |
| `target_weight` 是策略统一输出 | 让 Qlib、规则策略、回测和交易共享边界，同时禁止策略直接触碰订单/账户 |
| 研究价与账户价分离 | 复权价用于收益研究；不复权成交价、现金分红和公司行动用于账户守恒 |
| PIT 和显式 `as_of` | 成分、财务、停复牌和规则必须按当时可知信息，禁止未来信息回填 |
| Qlib 使用 `py312`，主体仍在 base | Qlib 0.9.7 官方 wheel 只到 Python 3.12；不降级或污染 base，不做不受支持的源码硬装 |
| clean Parquet → staging Parquet → 官方 `dump_bin.py` → Qlib bin | Qlib 的 Parquet 支持是导入源能力，不等于 LocalProvider 可直接挂载项目 clean 分区 |
| G1 正式 release 要求目录级原子 no-clobber | verified release 不能被并发覆盖或 TOCTOU 篡改；普通 DrvFS 的 `os.replace` 不能伪装成 `RENAME_NOREPLACE` |
| 先 PAPER/SHADOW，后实盘 | 先证明状态恢复、幂等、风控和对账；实盘还需券商权限与程序化交易报备 |

## 4. 修改过的重要文件

以下为重要入口，不是逐文件变更清单；当前工作区没有有效 Git HEAD，无法生成可靠历史 diff。

### 4.1 治理、规划和配置

- [`../AGENTS.md`](../../../../AGENTS.md)、[`../.ai/README.md`]（历史路径 `../../.ai/README.md`，当前仓库未收录）：Agent、SSOT、验证、环境和交易安全规则。
- [`../A股港股通个人量化投研交易系统调研.md`](../../../research/surveys/A股港股通个人量化投研交易系统调研.md)：完整技术选型和 pipeline 定位。
- [`../项目实施路线图.md`](../../../../项目实施路线图.md)：M0–M5 状态与 Gate。
- [`M3实施与Agent交接.md`](../framework/M3实施与Agent交接.md)、[`M3_M4实施总规划.md`](../framework/M3_M4实施总规划.md)：M3/M4 契约与依赖；当前状态以本文件顶部摘要和路线图为准。
- `configs/research/m3_qlib_example.toml`、`configs/trading/example.toml`、`configs/calendars/*.toml`。
- `configs/tushare.local.toml`：本地秘密文件，必须安全手工迁移且继续忽略。

### 4.2 领域和数据

- `src/quant/domain/enums.py`、`src/quant/domain/schemas.py`：枚举与数据合同 SSOT。
- `src/quant/data/connectors/`：Tushare、BaoStock、AKShare、官方港股通源。
- `src/quant/data/storage.py`、`repositories.py`、`quality.py`、`pipeline.py`：存储、repository 和质量门禁。
- `src/quant/data/connect_market.py`、`eligibility.py`、`audit_connect_eligibility.py`、
  `rebuild_connect_universe.py`、`update_connect.py`：港股通事件、审计、区间和发布链。
- `src/quant/data/m3_*.py`、`backfill.py`：M3 请求、mapper、事实、candidate、release 和回补。

### 4.3 研究、回测和执行

- `src/quant/factors/trend.py`、`src/quant/strategies/`、`src/quant/research/run_s*.py`：M2 因子和策略运行。
- `src/quant/backtest/`：时间语义、规则、费用、薄模拟器和港股通规则。
- `src/quant/research/m3/`：配置、合同、标签、readiness、workflow、CLI、receipt、snapshot、tracking。
- `src/quant/execution/config.py`、`contracts.py`、`ports.py`、`store.py`、`oms.py`、`risk.py`：M4 基础。
- 对应测试位于 `tests/unit/test_m3_*.py`、`test_execution_*.py`、`test_connect_*.py`、
  `test_rebuild_connect_universe.py`、`test_pretrade_risk.py` 等。

### 4.4 过程证据

三个业务域分别在 `docs/framework/agent/`、`docs/research/agent/`、`docs/gui/agent/` 保存任务书、实现报告、
独立初验和主验报告；跨域协作规则与总控记录位于 `docs/governance/`。优先读取：

- [`agent/M4_P0Route与M3_HISTORY主Agent集中验收报告.md`](../framework/agent/M4_P0Route与M3_HISTORY主Agent集中验收报告.md)
- [`agent/M3_HISTORY-PILOT10真实有界恢复执行任务单.md`](../framework/agent/M3_HISTORY-PILOT10真实有界恢复执行任务单.md)
- [`agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md`](../framework/agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md)
- [`agent/M1_SSE-REAL2双Route历史Universe发布主Agent最终验收报告.md`](../framework/agent/M1_SSE-REAL2双Route历史Universe发布主Agent最终验收报告.md)
- M3/M4 各已验收子包的 `*主Agent最终验收报告.md`。

## 5. 未完成事项和已知问题

### 5.1 M1/M2

- 港股正式多日行情连续性和复权收益链未完成：`hk_daily` 权限已由一次探针确认，但约 1 次/小时；账号无
  `hk_adjfactor`。单日全市场探针覆盖 612/613，缺 `02983.HK`；两代码 60 日 P1 已完整通过，但全 613
  股票的可恢复 raw/clean 回填尚未执行。
- 31 个 HK ETF 的网页抓取来源已因 HKEX 许可条款撤回；默认 ETP connector 已零网络 fail closed。合规
  instrument 来源重建前，不能把当前暂存 clean 当作完整 HK Instrument/M1 Gate 通过证据；但行情
  available-history Gate 已用官方资格类型解耦，不需要这些暂存行来排除 ETF。
- M1 的连续 5 个交易日无人干预增量运营验收、正式大范围 60 日查询和换源演练仍需按路线图复核。
- M2 U1 已合流 main；合流后 Windows/WSL base 同组 118 项、Ruff、mypy 复验通过，S0/S1 六个核心产物
  与既有基线 byte-identical。工程项已关闭，策略有效性限制仍以路线图链接的主 Agent 报告为准。
- S1 候选池在 2026-07-12 才冻结，已有 2023–2026 历史结果存在候选池后见偏差，只能作为探索证据。

### 5.2 M3

- HISTORY 3190/3190 request/raw/receipt 已闭合；不得重做旧 PILOT10、旧 H00300 或五个 510300 请求。
- 510300 ETF full-OHLC、三段复权、分红语义和 source snapshot mapper 已由正式数据证明通过；full candidate
  仍以 `G1_CANDIDATE_COMPONENT_INVALID` fail closed。先做组件级零网络诊断并走“外部实现→独立初验→
  主验”返工，REFERENCE、PREPARE、PUBLISH 均不得提前执行。
- 当前 Ubuntu 是 WSL1/wslfs，host 和文件系统均不支持正式 release 要求的原子
  `RENAME_NOREPLACE`；固件虚拟化关闭。正式 PUBLISH 必须等用户完成主机虚拟化/WSL2 条件并在真实 ext4
  root 复验，不能降低合同。
- 无正式 `VerifiedG1Release` 时禁止启动真实 G2A；G2–G9 必须按总规划依赖顺序推进。
- base 不安装 Qlib；所有真 Qlib provider/readback 只在 `py312` 执行，核心回归仍回到 base。

### 5.3 M4/M5

- B1/B3 仍等待 M3 G7 相应前置；B4 planner、B5 账本、B6–B8 统一回测与准入未完成。
- P2 Paper Gateway、P4 transactional outbox 服务、P5 恢复/对账、P6–P8 操作/报告/稳定性未完成。
- 没有四周 PAPER/SHADOW 稳定证据，没有券商 Gateway，没有程序化交易报备，不得启用 LIVE。
- Tushare token 在早期已泄露但获准继续用于研究；启用任何实盘通道前必须撤销并轮换，并扫描配置、日志、
  manifest、receipt 和报告。

### 5.4 仓库与迁移问题
