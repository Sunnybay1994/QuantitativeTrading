# M3/M4 Cursor Grok 交接清单

更新日期：2026-07-15  
目标模型：Windows 原生 `cursor-agent` 的非 fast `cursor-grok-4.5-high`；简单、只读初验可由用户决定使用 `auto`。项目命令必须切换到 WSL 路径并使用 WSL Miniforge 环境。

## 1. 开工前必读顺序

1. [`../../AGENTS.md`](../../AGENTS.md)
2. [`../../karpathy-guidelines.md`](../../karpathy-guidelines.md)
3. [`../M3当前验收与返工总览.md`](../M3当前验收与返工总览.md)
4. [`../M3实施与Agent交接.md`](../M3实施与Agent交接.md) 中当前包章节
5. 本清单
6. 当前包的详细任务书和直接目标源码/测试

禁止为了“熟悉项目”一次读取全部历史报告。先用 `rg` 定位，仅在冲突或验收追溯时读取直接前序报告。

## 2. 所有包共同合同

### 环境

- Windows 只负责启动 `cursor-agent`；项目命令在 WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 执行。
- 主体：`/home/mabw/miniforge3/bin/conda run -n base <command>`。
- Qlib 兼容任务：`/home/mabw/miniforge3/bin/conda run -n py312 <command>`；不得修改 base，也不得用 py312 替代 base 回归。
- 禁止 Windows Python/conda，禁止跨环境拼接 `PYTHONPATH`。

### 交付流程

1. 实现会话严格按白名单修改，运行改动相关 pytest 和定向 Ruff/mypy，写压缩交付报告；全量质量命令仅留给
   跨模块合流、关键发布/迁移、里程碑/Gate 或任务书明确要求的阶段。
2. 关闭实现会话；新建未参与实现的会话做独立初验。除固定验收报告外只读；逐条映射合同并增加至少一个新反例。
3. 初验失败时，回实现会话按“现象—根因—规则—最小复现—新增测试—通过条件”返工，再开新的独立复验。
4. 独立初验通过后停止，报告“可交主 Agent 终验”，不得勾选路线图或宣称 Gate/里程碑完成。

开发和合同测试使用最小确定性 fixture；真实数据 smoke 只取必要证券、交易日和字段并限制请求次数。除明确的
数据覆盖、性能或 Gate 验证外，不用大范围历史数据跑开发测试，优先复用已留存 raw。

### 禁止项

- 不读取、import 或复制 `archive/legacy_pre_greenfield/` 的旧实现。
- 不直接遍历或打开 `data/`；只有明确的数据迁移/采集任务可通过 `quant.data` 工具或 repository 访问。
- 不扫描目录猜产物，不把路径存在当作 verified 类型，不放宽 strict Schema/JSON。
- 不以 `os.replace`、先删后改名、检查后重命名冒充 no-clobber 原子发布。
- 不泄露 token、绝对个人路径、异常 cause/traceback 或账号信息。
- 不接实盘、不生成真实 broker 命令、不把 `auto_trade` 改为 true。

## 3. M3 逐包执行卡

现行详细任务书是精确接口 SSOT；以下执行卡只规定颗粒度和交接点，不重复完整字段表。

### R1B — 可恢复工作流服务骨架（下一包）

- **目标**：将已验收的 R1A plan、R1L journal lock 和 P4C candidate/release 合成为 `INDEX → HISTORY → REFERENCE → PREPARE → PUBLISH` 五阶段可恢复服务。
- **允许修改**：详细任务书指定的 `src/quant/research/m3/g1_workflow.py`、包导出、对应新测试及本包两份报告；发现任务书与实际 allowlist 不一致时先停止回报。
- **输入**：verified config/plan/journal/candidate/release readers；不得重算各 stage 业务事实。
- **输出**：确定性 stage result、稳定失败语义、可续跑状态；只有 PUBLISH 成功才能返回 verified release。
- **关键反例**：中途崩溃后重复调用不重复已完成 API；输入 identity 改变拒绝续跑；PREPARE 成功但 FS 不支持发布时不伪造 release；两个并发调用不得重复副作用。
- **通过条件**：详细任务书全部定向测试 + base 全量质量命令；报告明确哪些是真实、哪些是 fake。
- **详细任务书**：[`M3_G1_R1B可恢复工作流服务骨架外部闭环任务单.md`](M3_G1_R1B可恢复工作流服务骨架外部闭环任务单.md)。

### R1C-A — CLI 与 fake continuation

- **前置**：R1B 主 Agent 终验。
- **目标**：薄 CLI 只解析参数并调用 workflow；fake handlers 证明停止点、恢复、稳定 exit code/summary。
- **边界**：不联网、不读取真实数据、不发布正式 G1；CLI 不复制 workflow 状态机。
- **反例**：非法 stage、重复启动、handler 失败、summary 写入失败、敏感路径异常。

### R1C-B — 真实全量 PREPARE

- **前置**：R1C-A 主验、用户授权真实数据调用。
- **目标**：运行真实 INDEX/HISTORY/REFERENCE/PREPARE，冻结请求、receipt、审计和候选 identity。
- **边界**：允许 Tushare connector 读取 ignored token；报告仅记录脱敏摘要。此包不 PUBLISH。
- **反例**：API 缺页/重复/空表、积分不支持接口、日历/成员/公司行动不守恒、重跑结果 identity 漂移。

### R1C-C — 正式 PUBLISH

- **前置**：R1C-B 主验，且目标 FS 经独立探针证明支持任务书要求的原子 no-clobber。
- **目标**：正式发布并从发布目录重新验真 `VerifiedG1Release`。
- **硬停止**：DrvFS 探针失败时只报告阻塞，不实现降级协议。
- **反例**：已存在同 identity 同内容、同 identity 异内容、发布后 cleanup/fsync 失败、并发发布。

### G2A / G2B / G2C

- **G2A**：verified G1 release → strict snapshot；不得复制 provider 逻辑。
- **G2B**：pinned dump tool → provider materialization；父进程 import 隔离，工具子进程可用 py312。
- **G2C**：fresh process 通过 Qlib public API 做确定性 3×20×7 回读。
- **共同反例**：tree 多/缺文件、calendar/instrument 漂移、bin 截断、NaN gap、Float32 staging 与源 Float64 口径混用。
- **任务书**：[`M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md`](M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md)。每次只实现一个子包。

### G3A / G3B

- **G3A**：从 verified snapshot 独立构建 label/eligible/benchmark artifacts；只消费冻结数据。
- **G3B**：Qlib expression/direct 与独立 benchmark 双路径对账，四类误差序列按配置容差决策。
- **反例**：信号/成交日错位、eligible key 超集/缺集、benchmark 重复或缺日、末端 horizon、NaN 被静默丢弃。

### G4A / G4B / G4C

- **G4A**：交易日 folds、embargo 与尾部覆盖。
- **G4B**：fold-shared Alpha158 feature artifact；禁止每 horizon 重算。
- **G4C**：features/labels/eligible/scorable 监督对齐。
- **反例**：train/valid/test overlap、embargo 少一天、尾部样本错误进入训练、行序改变 identity、非 scorable 被填值。
- **任务书**：[`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](M3_G4_G6研究链分包骨架与外部闭环任务单.md)。

### G5A / G5B

- **G5A**：固定配置的原生 LightGBM 训练，模型 identity 绑定 fold-shared features 和 horizon labels。
- **G5B**：预测、稳定排序和无状态 Top-k；相同输入两次 score 最大差满足冻结容差。
- **反例**：线程/seed 漂移、同分排序不稳定、训练数据泄露 test、模型缓存跨 horizon 误用。

### G6A / G6B

- **G6A**：只在 test 段计算 IC/RankIC/ICIR/覆盖率。
- **G6B**：按 experiment/work identity 汇总，不重算指标。
- **反例**：valid 混入 test、空截面、常数 score、coverage 分母漂移、NaN 被当 0。

### G7P0 / G7A–G7F

- **G7P0**：只扩充 scientific config；不写回测。
- **G7A**：prediction → target artifact。
- **G7B**：调度、窗口、成本日程 → backtest plan。
- **G7C**：公司行动 entitlement 纯状态转移。
- **G7D**：订单差量、A 股 T+1、申报数量和费用纯函数。
- **G7E**：单场景逐 session 账户循环。
- **G7F**：0.5×/1×/2× 独立回放、指标和不可变发布。
- **共同反例**：同收盘成交前视、T+1 误卖、停牌估值丢失、分红 entitlement 错日、法定费用被缩放、三个场景共享可变账户。
- **任务书**：[`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](M3_G7目标到账户回测分包骨架与外部闭环任务单.md)。高风险 G7C/D/E 必须分别交付。

### G8A–G8F

- registry → StageRunner → CLI → tracking journal → fresh-process reproducibility → fake DAG，严格按 A 到 F。
- 暂不提前实现 fake 框架；先完成真实 critical path，避免接口在真实 handler 落地前漂移。
- 反例：目录扫描发现 stage、相同 work 重复 MLflow run、final 目录半发布、恢复时输入 identity 改变、fake 通过被误报真实 Gate。
- **任务书**：[`M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md`](M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md)。

### G9A–G9G

- quality → evidence plan → upstream checker → work checker → tracking checker → decision/publish/CLI → fake integration。
- G9 只验身份、覆盖和证据合取，不重新计算上游业务公式。
- 反例：glob 猜证据、旧 tracking target、quality 身份与 current code 不一致、一个 work 缺证据仍 PASS、报告含凭据/绝对路径。
- **任务书**：[`M3_G9最终准入分包骨架与外部闭环任务单.md`](M3_G9最终准入分包骨架与外部闭环任务单.md)。

## 4. M4 逐包任务卡

M4 所有 public 字段最终以 `src/quant/domain/schemas.py`/`enums.py` 为 SSOT；以下是快速执行卡，精确签名、白名单、依赖和失败语义已经冻结在 [`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md)，不得另造接口。

### M4-C0 — 交易配置与身份

- **建议文件**：`src/quant/execution/config.py`、`configs/trading/example.toml`、`tests/unit/test_trading_config.py`。
- **输出**：strict `TradingConfig`，包含 mode、安全开关、规则版本选择器、费率/FX/风险限制有效期和 canonical identity。
- **失败语义**：未知字段、bool 冒充数值、有效期重叠/缺口、`LIVE`、`auto_trade=true` 全部 fail closed。
- **反例**：TOML 字段重排 identity 不变；任一风险阈值改变 identity 必变；配置不得含 token/account id。

### M4-D0 — 领域合同

- **建议文件**：增量修改 `domain/enums.py`、`domain/schemas.py`，新建 `execution/contracts.py` 与定向测试。
- **输出**：immutable `OrderIntent`、`OrderCommand`、`ExecutionEvent`、`BrokerSnapshot`、`LedgerEntry`、`ReconciliationIssue`；明确 market/currency/units/timestamps/idempotency keys。
- **失败语义**：非法状态/币种/方向/数量/时间关系在边界拒绝，不在 engine 内猜测修复。
- **反例**：相同 broker event id 内容不同；fill 累计量超过 order；HKD quote 与 RMB settlement 被合并成一个金额。

### M4-D1 — 数据访问端口

- **建议文件**：`src/quant/data/repositories.py`（实现端）、`src/quant/execution/ports.py`（Protocol）、对应 contract tests。
- **输出**：按明确 key/as_of 返回 validated frames/domain snapshots 的窄接口；无任意目录参数。
- **失败语义**：缺日、缺证券、质量 Gate 失败、PIT 不满足必须 typed error/fail closed。
- **反例**：策略/execution 传入 `data/legacy` 路径；repository 返回超集/重复 key；as_of 后数据渗入。

### M4-B1 — A 股规则

- **建议文件**：`backtest/market_rules_a.py` 及测试；重用领域枚举，不扩展 IO。
- **输出**：纯函数 `evaluate_a_share_order(...) -> RuleDecision`；处理 T+1 sellable、停牌、涨跌停和分板块申报数量。
- **反例**：主板/创业板与科创板数量规则混为 board_lot；全部持仓零股卖出；价格恰在上下限；上市首日/无涨跌幅限制由版本化状态表达。

### M4-B2 — 港股通规则

- **建议文件**：`backtest/market_rules_connect.py` 及测试。
- **输出**：双日历、T+0 sellable、per-symbol board lot、碎股只卖、tick/price limit、quota state 的纯规则决策。
- **反例**：A 股开市但港股休市；board lot 在 effective date 改变；碎股买入；增强限价超允许档位；额度不足只阻止新买不阻止卖。

### M4-B3 — 费用、FX 与有效期

- **建议文件**：重构 `backtest/costs.py`，新增 `backtest/fx.py` 与测试；费率只来自 config。
- **输出**：逐项费用 breakdown、quote/settlement 金额、所用规则和 FX snapshot identity。
- **反例**：最低佣金、卖方印花税、不同市场费用、零/缺失 FX、有效期边界、法定费用与 slippage 混缩放。

### M4-B4 — 目标到订单计划

- **建议文件**：`portfolio/order_planner.py`、测试。
- **输入**：verified target、positions/cash/sellable、market facts、config；不做 IO。
- **输出**：确定性 `OrderPlan`，包含 accepted/rejected intents、残差现金和 diagnostics 守恒。
- **反例**：先买后卖导致虚假现金；rounding 超权重；停牌目标；最小费用使小单不经济；相同目标与快照必须同 identity。

### M4-B5 — 多币种结算与公司行动账本

- **建议文件**：`backtest/ledger.py`、`backtest/corporate_actions.py`、测试。
- **输出**：不可变账户状态转移，区分 trade date、settlement date、receivable/payable、HKD quote 与 RMB cash。
- **反例**：部分成交、T+2 未结算资金重复可用、除权日与登记日混用、重复公司行动、FX rounding 不守恒。

### M4-B6/B7/B8 — 统一回测与策略准入

- **B6**：事件引擎只编排 B4/B5，不复制规则；同一输入多次运行 bytes/identity 稳定。
- **B7**：净值、换手、成本、回撤、容量/滑点压力；明确缺失值和年化 session。
- **B8**：M2/M3 在同 snapshot、成本、规则和窗口比较，输出 decision，不静默选择冠军。
- **反例**：同收盘前视成交、三场景共享账户、幸存者偏差、不同数据版本被拿来比较。

### M4-P0 — SQLite 持久化

- **建议文件**：`execution/store.py`、`execution/migrations/`、测试。
- **输出**：显式 schema version、事务 repository、唯一约束和 migration；数据库在 tests 临时目录。
- **反例**：重复 client order/event/outbox key、进程在 commit 前后崩溃、未知新 schema version、迁移中断。

### M4-P1 — OMS 纯状态机

- **建议文件**：`execution/oms.py`、测试。
- **输出**：合法状态转移和幂等 reduce；不得做网络或数据库 IO。
- **反例**：ACK 后又收到旧 NEW、重复 fill、乱序 partial/final fill、cancel 与 fill 竞态、累计成交超量。

### M4-P2 — Paper Gateway

- **建议文件**：`execution/gateways/paper.py`、测试。
- **输出**：同规则/费用下的确定性 ack/fill/reject/cancel 事件；支持故障注入。
- **反例**：断线重连、重复回调、部分成交、延迟 ACK、撤单后晚到 fill、进程重启。

### M4-P3 — 事前风控

- **建议文件**：`execution/risk.py`、测试。
- **输出**：逐规则 decision 与完整 audit trail；总开关/人工确认/仅卖出/冻结证券优先级冻结。
- **反例**：数据 Gate 失败仍买入、卖出被买入限额误拒、同一批订单分别通过但合计超限、撤单计数跨重启丢失。

### M4-P4 — 执行服务与 outbox

- **建议文件**：`execution/service.py`、测试。
- **输出**：plan/risk/OMS/store/gateway 的窄编排；订单状态与 outbox 同事务提交，发送后可幂等恢复。
- **反例**：提交 DB 后发送前崩溃、发送成功回写前崩溃、重复 worker、相同 plan 重提、不同 payload 复用 id。

### M4-P5 — 恢复与对账

- **建议文件**：`execution/reconcile.py`、测试。
- **输出**：local OMS/ledger 与 broker snapshot 的差异分类、自动安全动作建议；不自动篡改账本。
- **反例**：broker 多/少订单、未知持仓、现金差、重复成交、盘中 snapshot、无法解释差异必须人工介入。

### M4-P6/P7/P8 — 操作、报告与稳定性 Gate

- **P6**：CLI 仅提供 inspect/plan/approve/paper-submit/cancel/reconcile；危险操作二次确认且 M4 无 live。
- **P7**：EOD 订单/成交/持仓/现金/差异/风险事件报告，日志脱敏。
- **P8**：至少四周 PAPER/SHADOW；重启、断线、重复/乱序回报、时钟/数据缺失、磁盘错误故障演练。
- **通过条件**：零未解释资金/持仓差、零重复经济影响、所有阻断有可操作告警；否则不进入 M5。

## 5. 报告模板

实现报告只保留：包号与状态、冻结输入/输出、修改文件、测试命令与摘要、新发现、已知阻塞、声明未通过的更高 Gate。独立初验报告保留：逐条证据矩阵、新增反例、发现问题、是否进入主验。禁止粘贴完整日志。

## 6. 当前交接动作

总协调任务从 **R1B 实现会话**开始，按依赖队列逐包执行。每个包必须先结束实现上下文，再由未参与实现的全新上下文独立初验；通过后才可把下一包作为“基于待主验接口的预实现”继续，所有状态保持待主验。禁止在同一会话改换角色，禁止并行写 M4 公共领域文件。正式 G1 发布、真实 Provider/训练、真实 PAPER soak 等硬门禁不满足时必须停止对应分支，但可推进依赖已经满足且白名单互斥的另一分支。全部可行包完成或只剩硬阻塞后，生成外部执行总报告并通知用户唤醒主 Agent 集中终验。
