# Codex 项目迁移交接

### 2026-08-16 当前续写摘要（覆盖下文旧停止点）

- 当前隔离集成线为 `codex/m1-m2-integration@本文件所在提交`；业务合流稳定点 `46f8e1d` 已保留原提交身份吸收
  M1 `9004b6d`、S2 `4ac392a`、liquidity `ec506b6`、GUI G1/C4 `a5c63f7`/`18dc006`、M4 RUN-0D2
  `92de0d4`、downside beta `3c8c6c4`、Alpha158 `0f737ac` 与 MAX `0363b0f`。此后 `ba83ad7` 吸收
  R10 证据，`c2c8841` 吸收 MAX daily-basic 控制，`8427c83` 吸收 GUI D1，`086cae9` 吸收 PIT 首跑前置，
  `4745cb4` 吸收 FWD-R1；MAX-control 合流回归为 25 passed，GUI D1 为 19 passed/2 skipped，PIT 前置为
  32 passed，FWD-R1 为 17 passed/1 skipped，四者定向
  Ruff、mypy、cold import 均通过，不把这些定向证据扩大表述为覆盖其它范围。
- 根 checkout 仍停在 `codex/m2-strategy-fastlane@4d569be`，由唯一 Tushare finance writer 使用；writer
  权威终态前禁止切换根分支或并发写源码。根只剩 `docs/quant_factor_research_v2/**` 25 个未跟踪资料文件，
  当前只读、不是 SSOT，未经用户决定不得删除、改写、提交或被运行时代码自动发现。
- S2 admission 已形成 fail-closed 安全点：B8 metrics provenance 尚未绑定到 verified replay/metrics 时，
  完整证据只能是 `RESEARCH_ONLY / ADMISSION_METRICS_PROVENANCE_UNBOUND`，不得生成 `ELIGIBLE` 或
  `PAPER_CANDIDATE`。source binding、人工准入与真实 PAPER Gate 仍开放。
- 六条 M2 因子真实不可变 run 已用 no-clobber、逐文件 set/size/SHA-256 与 `run.json` 输出闭包验真后保留在根
  `artifacts/research/runs/<run_id>/`。Amihud、自由流通换手、downside beta、Alpha158 第四批与 MAX
  daily-basic 控制 `30326191…e2cf` 均为 `REJECTED`；原始 MAX `10dea14f…129bb3` 通过初筛但最高仅
  `RESEARCH_ONLY`。控制实验因 2x 成本收益为负而拒绝，不能把原始 MAX 的结果升级为已排除规模/换手暴露；
  forward、统一回放和人工 admission 仍未闭合。相关短期 worktree 已退出；统一 I/O/compute 分段仍是性能债，
  当前证据不支持先上 GPU、并行或语言重写。
- M2-SOURCE-R10 已发布同逻辑输入、同经济行为的 successor `e43da184…7a96f`，根 canonical 经 public verifier
  复验为 `RESEARCH_ONLY`；source/canonical 6 文件、60,597 bytes、逐文件 SHA-256 差异为 0。R10 证据已由
  `ba83ad7` 合流，重复 worktree 已移除，source branch 已由 `archive/m2-source-r10-successor-20260816` 保存后删除。
  历史混合 EOL 导致旧 code hash 不可由 commit 复算的 provenance 债仍开放，但不再阻塞 M2-FWD-R1。
- finance writer 仍在根 checkout 单实例推进，`data/clean/tushare_financials` 尚未形成；真实 PIT quality run
  继续 fail-closed 等待 writer 终态、全量 bytes audit 与不可覆盖 snapshot。snapshot READY 时，PIT 优先于
  新的非财务研究包。PIT 首跑前置 `3b8857c` 已以 A1 `RECONSTRUCTED_CURRENT_INVENTORY_V1`、coverage gate、
  code-identity 与 `UNFROZEN/[]` pre-artifact STOP 进入 `086cae9`；来源线已 archive-first 退出，但这不等于
  当前 raw、snapshot 或真实 report-type 分布已经 READY。
- M3 retained 两折链仍没有权威 `completion.json`，stderr 为空且 owned 进程仍在运行；detached
  `c9f2f36`、两份 session 配置、owned 解释器与 `codex/m3-g8e-r2-windows-hardlink@71dffa5` 继续冻结，
  不恢复、不重启、不清理，也不以旧 receipt 代替本轮 completion；新 owned child 证明 fold2 h10 仍在自然运行。
- M4 RUN-0D2 已以 `92de0d4` 合流，但没有启动 PAPER、订单或 28 日计时。正常 PAPER 启动仍须关闭
  UA-M4-005 durable approval 与 UA-M4-006 shared barrier，再按顺序完成 cross-day rotation；UA-M4-007 只约束
  正常窗口结束后的 actual fault drill，不冒充首日启动前置。A/B 代码在用户裁定前暂停。
- GUI C4 `18dc006` 已合流：optional 依赖为 `streamlit>=1.49,<2`，12 处 dataframe 参数已迁移；真实 AppTest/browser
  功能 smoke 通过且 console error 为 0。GUI D1 `9f42b3c` 又以只读的 14 字段关系诊断进入 `8427c83`；来源环境
  AppTest 5 passed/0 skipped，integration 最小回归 19 passed/2 skipped，真实 canonical 字节派生的隔离篡改反例
  证明 output digest 失败时不展示 mismatch 面板、metrics 或 NAV。D1 没有增加运行能力，来源 worktree/branch 已在
  archive tag 留档后退出。两类 Vega Infinite extent warning 继续登记为 renderer 债，不宣称 zero-warning；G2
  本地作业编排仍仅有只读设计，当前不为一个运行按钮提前引入 SQLite worker/lease 平台。
- M2-FWD-R1 `76b55cf` 已进入 `4745cb4`，R10 来源绑定与标准 LightweightResearchRun 发布路径的开发检查通过；
  没有执行真实 2026-08-31 发布或生成真实 forward artifact，来源线已 archive-first 退出。
- `data/clean/tushare_financials` 仍不存在。CPU8–11 当前交给
  `codex/m2-pit-r2-dimension-audit@086cae9` 做 report-type/comp-type 分布证据的定向开发检查；仍不选
  allowed values、不读 partial raw、不运行 integrated bytes audit 或发布 snapshot。所有短任务保持 BelowNormal、
  CPU8–11、数值线程不超过 2。
  完整 branch/worktree 所有权、退出条件、artifact 保留条件和基础设施债
  见 [`项目结构与合流治理路线图`](roadmaps/项目结构与合流治理路线图.md)。项目初期继续以最小正确业务闭环
  为先；PIT、fail-closed、统一回放、OMS/风控/对账、人工准入和凭据安全不得作为“基础设施瑕疵”延期。

### 2026-08-14 当前续写摘要（覆盖下文旧停止点）

- 前台策略审查已诚实收口：固定 60 观测、12% 不加杠杆波动率目标在两折和三档成本下均为正，但 2026-08-31 前没有冻结后的首个前向信号，历史 ETF 池 PIT 与统一市场事件重放仍未闭合，因此保持 `RESEARCH_ONLY`，不生成 `PAPER_CANDIDATE`。Tushare 核心历史 raw 已完成 24,343/24,343 个请求和全量摘要复核，但需先隔离 21 条 OHLC 异常、特殊代码与 `600018.SH` 复权缺口，不能整批直升 clean。
- M3 honest 300 public CLI 曾在资源受限的唯一 Windows 进程中通过首发、completed resume、零写边界与 teardown（`1 passed in 9716.55s`），但该产物使用了已由 SSOT 从 `summary` 修正为 `research-summary` 的旧 stage，不能继续用于 tracking。修正 revision `c9f2f36` 的 retained root 已完成 h5/h10 三场景 backtest；其 fold manifest 只有 `fold_001`，正式跨折 `research-summary` 按最小 two-fold 合同 fail-closed，因此 `UA-M3-003` 旧目标已撤回。旧 G1 的 eligible domain 也只覆盖 23 个 session，无法派生第二折；当前唯一受限 Windows 进程正在通过 public 链新建 24-session G1 与 two-fold × two-horizon retained root，已完成 G1 阶段，新 root 完成前不做 tracking 写入。
- M4 已完成 formal gateway、broker/OMS store、fresh G1 calendar ledger provider、ExecutionService composition、VerifiedSoakSchedule 与只读 daily runner。`UA-M4-004` 已批准：首个 PAPER target 由策略会话产出的真实 `PAPER_CANDIDATE` 提供，开盘事实由 receipt-backed clean source 提供；fixture、历史回测、空 target 与 `RESEARCH_ONLY` 均不得冒充正式输入。真实任务注册和启动仍受 `UA-M4-002` 控制。
- M1 U0C-R3 已在 2026-08-14 自然完成第五个一次性任务：最终 live `LastTaskResult=0`，WSL base 五日 `audit_daily_streak` 返回 exact `PASS/sessions=5`，连续调度子 Gate 关闭。Operational 历史通道仍关闭且已披露；HK60、正式许可/复权/公司行动与 M1 整体 Gate 仍开放。
- Linux/ext4、真实 PAPER、28 日 soak 和 LIVE 均未完成。外部 Agent 当前暂停，由主 Agent 串行开发；内部 subagent 不用于模拟独立实现/初验。
- 已完成 worktree 与临时目录清理：统一集成、活动 M1、活动 M2 三个附加工作树因分别承载 M3 续跑、M1 第五次自然任务和策略候选开发而保留；旧 M3 run 已移入 `artifacts/archive/agent_runs/20260814/`，活动/归档树中的测试与字节码缓存已清理。未挂载的旧 `m3-g4-formal` 与 `pre-m2-main-dirty-20260802` 分支已先建立 `archive/*` 标签再删除活动分支引用，可完整恢复历史。

### 2026-08-10 当前续写摘要（覆盖下文旧 G1/M3/M4 停止点）

- 正式 G1 Windows轨已完成并从磁盘fresh验真：release `08eb9b31...7359`、manifest
  `d3923fa1...f99c4`、17个exact artifact paths、quality 0 error/0 warning；见
  [`20260809_M3_G1_Windows正式发布物磁盘复验报告.md`](agent/20260809_M3_G1_Windows正式发布物磁盘复验报告.md)。
  WSL仍为WSL1/DrvFS，Linux/ext4 Gate开放。
- M2工程闭环已完成。M3正式研究链已推进至G6B主验PASS；G5A/G5B输出事务与root lease、G6A/G6B评估汇总
  均已闭合工程合同。G7A正式TargetArtifact的R1 Decimal尾差已由R2固定Decimal50/ROUND_DOWN闭包关闭，
  实现、独立复验和主验均PASS；G7B formal BacktestPlanArtifact亦已完成实现、独立初验和主验PASS，主验正式
  文件Windows/WSL各4 passed且实现扩大回归各109 passed。G7D-F0唯一formal八表MarketFacts经R1/R2来源闭包
  返工后已于R3完成独立复验和主验PASS；G7C亦已完成R1/R2运行时来源闭包和R3 tests-only证据返工，生产文件
  在R3前后SHA保持不变，独立复验与主验均PASS。G7D remaining已拆为串行F1/F2；F1正式A股开盘执行事实已
  完成实现、全新独立初验和主验PASS。F2 formal session订单执行状态转移的R1 rejection notional缺口已由R2
  `reference_opens` + canonical self-digest及逐项 `open*quantity` 复算关闭；实现、全新独立复验与主验均PASS，
  Windows/WSL最终formal各20 passed，允许进入G7E。self-digest仅为普通值内部一致性，不是来源证明；G7E必须
  在自己的调用栈内调用F2。随后G7E审计发现F0遗留旧`H00300.CSI`与正式config/SSOT的`510300.SH`冲突；
  F0 R4已改为只从fresh config派生exact `510300.SH`，并移除F1 date guard的平行旧常量。R4实现、全新独立
  复验与主验均PASS，主验Windows/WSL F0+F1+F2各68 passed。随后G7E hostile Decimal联调发现F2
  null-gap的ambient `abs`与F1 half-tick环境算术缺口；F2 R3已改用`copy_abs()`，F1 R2已改用exact
  `0.005`及私有80位add/sub，两包均完成实现、全新独立复验和主验PASS。G7E现已恢复实现；其formal
  simulator的R1 Float64 NAV独立投影导致合法Decimal账户被Schema自拒绝；R2已改为四个已投影Float64分量
  按Schema同序生成输出equity，同时保留Decimal收益与后续状态链。R2实现、全新独立复验和主验均PASS，
  G7E单场景账户回放工程合同完成。G7F因正式三场景嵌套目录发布而新增P0共享NestedArtifactPublication
  前置；P0实现、全新独立初验与主验均PASS，受限两层nested publication及全部flat客户端兼容闭合，现已
  解锁G7F。G7F R1三场景29-file/21-input artifact本体与独立Decimal/whole-bundle/tree对抗通过，但邻接发现
  corporate-actions cold test在父pytest内reload导致G7E identity顺序污染；R2仅把reload隔离到fresh子进程，
  production与G7F tests哈希不变。R2全新独立复验与主验PASS，G7F工程合同完成并解锁G8。G8 R1已闭合
  formal backtest单WORK wave：exact 21 inputs/29 outputs、StageRunner首次/恢复/orphan逐次fresh及receipt前后
  G7F验真均完成实现、全新外部Cursor独立初验和主验PASS。Windows actual exclusive commit通过；本机WSL1
  不支持`RENAME_NOREPLACE`，仅91 passed/1窄skip，Linux ext4 Gate仍开放。随后G8D-F1 formal Tracking
  StageRunner单WORK wave完成：exact 34 inputs/11 uploads/22 params/2 request tags、显式client、外置lock、
  request→remote→marker及首次/resume/orphan闭包均通过。R1独立初验发现FINISHED run未比较两个request tags；
  R2已将request tags与五个protected tags共同纳入逐键复用校验，并经另一全新外部Cursor独立复验及主验PASS。
  当前只声明G8D-F1工程合同完成；真实MLflow/网络与ext4仍未验。G7C不得另建corporate-action facts capability。
  G8 CLI/fresh-process/fake full DAG、正式全work性能、G9与M3 Gate仍开放；下一工程包应先冻结G8C CLI增量。
- M4 P4-P8工程合同、RUN-0A环境合同、RUN-0B1独立durable PAPER broker均已通过相应主验；P8正式状态仍为
  `WAITING_FOR_SOAK_EVIDENCE`。RUN-0B2A1 R2 durable ORDER/CANCEL risk receipt/recovery已于2026-08-09
  主验PASS；B2A2已完成移除P7 caller risk、接入recovery retained receipts并于同日主验PASS。正式runner、
  WSL2/ext4、注册和真实28日soak尚未开始；RUN-0B2B A股formal PAPER policy/config loader已于同日完成
  独立复验与主验；RUN-0B2C formal broker policy binding亦已完成实现、独立初验与主验，自身不创建
  root/DB/gateway。下一包B2D formal PAPER账户Genesis任务已冻结为停止状态，仍等待用户批准account selector、
  非秘密label、genesis UTC与初始CNY现金四项业务SSOT；批准前不创建正式account TOML或实现loader。
- M1 PRE-B v3 availability capability已于R4主验PASS；fixture-only显式v3 finalize CLI外壳R2已关闭单文件
  held-instance内容漂移，但独立复验确认无锁双文件顺序扫描无法证明共同返回瞬间不可变；§12 R3已诚实重冻为
  write-once retained输入与caller quiescence信任边界，禁止用增加扫描轮数伪造强保证；R3已于同日完成独立
  复验与主验。P1A HK总回报应用日程来源无关工程合同亦已完成实现、独立初验和主验；下一步先只读冻结
  P1B gross total-return研究价格数值与development四文件发布合同已完成实现、独立初验和主验。正式P1C
  必须等待真实HK60 v3与licensed HK公司行动provenance，不再扩张fixture wrapper。正式HK60仍受02983可信observed
  metadata与licensed `01065.HK@2026-05-05`完整HKEX issue/spec阻塞；U0C-R3五个自然交易日任务已在
  2026-08-09只读回查为Ready且从未运行；同日preflight发现正式WSL路径缺少runner，已用注册时冻结的exact
  bytes（SHA `bdedb953...02c`）恢复并通过WSL SHA/bash-n/冷导入，任务本身未修改或触发。窗口仍冻结在
  2026-08-10至08-14自然触发，禁止手动提前触发。
- 当前按用户最新指示继续由主Agent推进，但后续减少内部subagent，优先使用不同全新外部`cursor-agent`
  会话承担实现与独立初验；主Agent负责冻结任务、裁决与最终验收。各worktree包含大量用户与既有里程碑脏文件，
  禁止add/commit或清理无关内容。
### 2026-08-02 G6A 续写摘要（覆盖下文旧停止点）

- G7P0 已完成：四个回测舍入/年化字段进入 scientific identity；当前严格闭包为 148 shapes / 161 leaves，
  Windows 与 WSL base 配置集合均 `89 passed`。早期任务单的 138→142 已被后续 C0 增量超越，不得回退。
- development example G6B 也已完成：同 horizon 跨折 summary、严格 fold metrics、跨日重算和 experiment
  receipt 闭包在 Windows/WSL base 均为 `8 passed`；开发研究链 G4A→G6B 的工程合同至此闭合，但正式
  production G4–G6 与真实绩效 Gate 仍保持开放。详见
  [`docs/agent/M3_G6B开发示例跨折研究汇总Artifact主Agent阶段验收报告.md`](agent/M3_G6B开发示例跨折研究汇总Artifact主Agent阶段验收报告.md)。
- development example 研究链已推进到 G6A：逐 work evaluation artifact、八状态 IC、五层 key 闭包、
  四类 coverage、canonical manifest 与 fresh receipt verifier 已完成；Windows 与 WSL base 定向集合均为
  `19 passed`。详见
  [`docs/agent/M3_G6A开发示例逐Work评价Artifact主Agent阶段验收报告.md`](agent/M3_G6A开发示例逐Work评价Artifact主Agent阶段验收报告.md)。
- 正式 G2A 已完成 Windows 独立发布与 fresh verify；正式 G2B 当前在独立工作树执行，G1 fresh verify 已
  PASS，正在 fresh 验证 G2A snapshot，尚未进入 provider materialize。development 结果仍不得关闭正式 Gate。

### 2026-08-02 最新续写摘要（覆盖下文旧停止点）

- 正式 G1 Windows release 已完成磁盘验真：release id
  `08eb9b31ab4d8c8473c0a7bb612df83009a68b761b8a35816653b2ce07807359`，manifest SHA-256
  `d3923fa1143fbc5c4ff352f7b4d0cf5baeb197d2bb161ead34255bd7375f99c4`，17 个 artifact。该事实不等于
  Linux/ext4 Gate；正式 release、journal 和候选目录继续只读。
- 正式 G2A 在独立 `artifacts/formal_g2a_windows/` 根并行执行：snapshot 物理构建、request 与约 630 个
  output 的 receipt 已 no-clobber 发布，当前在最终 fresh G1 + snapshot 全链 verifier；未取得
  `VerifiedSnapshotArtifact` 前不得启动正式 G2B。
- development example 路径严格隔离，身份固定 `development_example`、`formal_gate_eligible=false`。
  G4A/G4B/G4C、G5A 和 G5B 的开发合同已完成；G5A 双平台 fixture 为 14 项且 Windows 真实
  LightGBM 4.6.0 native train/save/load/predict 冷启动通过；G5B Windows prediction 对抗集 17 项、
  WSL base 合并受影响回归 44 项通过。它们不能关闭 production G4/G5 或正式 Gate。
- M2 统一股票/ETF 日频模拟器已合入 main 并双平台通过 118 项定向测试。M4 P3-RC1 日风险计数器 SQLite
  CAS 持久化已合入 main；Windows 197 passed/5 skipped，WSL base 202 passed，并补齐 v2→v3 migration
  回归。M4 仍待 cancel 接入、PaperGateway、服务编排、恢复对账、运维报告和连续 28 天 PAPER。
- 当前执行方式：主 Agent 自行实现与验证；正式 G1/G2 长时 I/O 低频异步推进，不能阻塞 development
  G2–G9 与 M4 工程。内部 subagent 仅用于文件互斥的只读审查或独立后台工作，不调用外部 Cursor Agent。

### 2026-07-31 最新续写摘要（覆盖下文旧停止点与执行模式）

- 当前分支为 `main`；P0K-A-REAL1 闭包提交 `dec16c8`，P0K-B 主实现提交 `3ba098d`。本摘要之后
  的文档提交以实际新 HEAD 为准。现有多份旧 `docs/agent/*.md` 工作树改动属于用户内容，禁止混入提交。
- G1 正式数据闭包现为：3190 个既有 Tushare/基金 HISTORY receipt、13 个 CNINFO rights 批次、
  CNINFO `stock_dividend` 与 `stock_share_change` 各 637（共 1274）个正式 request。
- P0K-B 已证明 600733 raw `0.5`、basis `3.5`、effective `0.5/3.5`。顶层 Windows 零网络
  `status` 首轮仍在旧 market-reference 分支失败；最小返工后，Windows/WSL P0E/P0I/P0K-B 相邻
  合同均 `42 passed`，正式 receipt 单次候选重放已越过 600733。
- 当前正式首败为 `601016.SH@2022-11-28` no-event factor jump
  (`actual=1.1272352132049517`)。下一动作是 P0K-C 只读真实证据诊断；HISTORY 成功前禁止
  REFERENCE/PREPARE/PUBLISH。
- 当前无有效 `VerifiedG1Release`；旧 Windows release 的 source-tree identity 已失效，G2A 未启动。
- 用户当前要求主 Agent 自行串行实现、自行验证，不调用外部 Agent；必要时可用内部 subagent 做互斥、
  只读并行工作。Windows 原生 Miniforge 用于开发与 Windows 正式轨，WSL Miniforge base 仍是
  Linux/平台特有 Gate 权威；Windows 绿测不等于 Linux Gate。

> 生成时间：2026-07-17；最近续写：2026-07-22（Asia/Shanghai）
> 当前工作路径：Windows `F:\AI_Coding\QuantitativeTrading`；WSL
> `/home/mabw/AI_Coding_win/QuantitativeTrading` 解析到同一目录。Git 已有 `master` 与初始提交
> `ed77978`；当前工作树含本轮未提交文档/实现变更，必须用 `git status` 逐项保护。
> 本文是迁移快照，不取代 SSOT。里程碑以 [`../项目实施路线图.md`](../项目实施路线图.md) 为准，当前验收以
> 截至2026-07-31的旧状态见 [`M3当前验收与返工总览`](archive/agent-history/M3当前验收与返工总览_截至2026-07-31.md)，当前状态以本文件顶部最新摘要、代码和路线图为准，架构理由以
> [`../A股港股通个人量化投研交易系统调研.md`](../A股港股通个人量化投研交易系统调研.md) 为准。

### 2026-07-22 最新续写摘要（覆盖下文旧流程与停止点）

- 用户最终明确交接方式：Codex 只提供交接文档和 prompt，由用户在外部自行执行全部后续任务；结果返回后
  再由 Codex 最终验收。此前误启动的 Cursor 协调会话及其 WSL 定向 pytest 已停止；其部分诊断产物仅作
  只读证据，不构成正式交付或独立初验，R5 仍待全新外部会话初验。
- 22:xx 最新停止点：BENCH-B1B 已完成外部实现、R1/R3/R4 返工闭环和不同全新 Cursor 会话的独立
  复验；主 Agent 的 WSL base 静态 Gate 通过，四组单测为 `214 + 250 + 31 + 24 = 519 passed`。
  R5 又把两个 HISTORY resume 测试从正式规模缩到最小真实 fixture，外部实现自测为 `2 passed in
  42.02s`，但**尚未进行全新会话独立初验和主 Agent 验收**，不得把 R5 写成关闭。
- 正式 G1 HISTORY 已按预算新增且仅新增 510300.SH 五个身份，当前闭包为 `637 symbols / 3190
  requests`。三段 `fund_adj` 分别 791/972/851 行，`fund_div` 22 行，`fund_daily` 2614 行；五个
  `intent/candidate/receipt` 均已原子提交，禁止重复请求。基金五响应严格重读并独立映射成功，产生 2614
  个 2015-10-09..2026-07-10 benchmark bars，source snapshot
  `a4cd3f23aab767e4f1af090cc3a283df8570ebd59af8a402e4173653fa28582c`。
- 正式全候选仍 fail closed：WSL `status` 在 1993.4 秒后返回
  `INSPECT:G1_WORKFLOW_QUALITY_FAILED`；后续零网络组件诊断已把首个失败定位为
  `corporate_action_selection` 的 `G1_CORPORATE_ACTION_RESULT_INVALID`，触发于
  `m3_execution_facts.py::_assert_ledger_evidence_closure`，表现为 ledger `event_id` 与根据所选 evidence
  重算的 `_event_id_sha256(...)` 不一致。在此之前 daily/adj_factor、stk_limit、suspend、benchmark 均已
  通过。下一步复核最小复现并冻结最小返工，不能重做五个 API 请求，也不能进入
  REFERENCE/PREPARE/PUBLISH。
- 环境事实已纠正：当前 Ubuntu 是 **WSL1**（内核 `4.4.0-22621-Microsoft`，根为 `wslfs`），`/tmp`
  的 `RENAME_NOREPLACE` 探针为 False；机器固件虚拟化当前为 False。现机没有可用 WSL ext4 release
  root，正式 PUBLISH 仍被环境 Gate 阻塞。启用 VT-x/虚拟化并迁移或新建 WSL2 属于需用户配合的主机变更，
  不得用 Windows/DrvFS 或降级原子合同绕过。
- 用户恢复“外部 Cursor 实现 → 另一全新外部 Cursor 独立初验 → 主 Agent 终验”，暂停内部 subagent；
  Windows 反馈环可使用最新 PowerShell 7（当前探测为 7.6.4）与 Miniforge，WSL Miniforge `base` 仍是
  Gate 权威。调整 Codex 本机权限/人工审批后，外部 Cursor CLI 已恢复；B1A 实现、完整独立初验及 R1/R2
  两轮“返工实现→独立复验”均使用互相独立的全新会话完成。后续继续保持角色与白名单隔离。
- A 股闭环优先。用户确认 G1 benchmark 路线 B：`510300.SH` ETF 总回报代理。B0/R1 以三次总计、各
  endpoint 恰好一次的 raw-first 小窗探针证明 `fund_daily/fund_div/fund_adj` 当前账号均可用：分别返回
  8/22/8 行；所有 raw pair 均可重读且不含 token。`fund_div` 有供应商重复/投影冲突，必须按经济事件键
  去重并对核心字段冲突 fail closed；`fund_adj` 正常返回唯一正因子。R2 又以 2026-01-19 除息窗口证明
  `pre_close=previous_close-div_cash` 与复权因子比关系在既有 `rtol=0.001` 内成立。B1A 基础设施已完成外部
  实现、独立初验、两轮返工复验与主验；最终 WSL 为 282 passed，Ruff/mypy/whitespace Gate 通过。B1B
  510300 总回报映射/全链身份重基线任务书已解冻，尚未进入外部实现。
- M4-P2A Gateway dispatch 边界已完成外部独立初验与主验。双平台定向 pytest 均为 `17 passed`，Ruff
  与无增量 mypy 通过；P2A 合同子包关闭，但 PaperGateway、service、OMS/store、对账和四周 PAPER Gate
  仍未完成，不标记 P2/M4 Gate 通过。
- M1-U0C 截至 2026-07-22 12:34 仍为真实 `2/5`；当日任务将在 21:30 执行。HK60 旧 plan 仍停在第 3 批
  稳定缺行事故，禁止重试旧 attempt 或 finalize，A 股优先期间只保留诊断证据。

### 2026-07-18 续写摘要（覆盖下文旧停止点）

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
  [`agent/M1_HK-HISTORY-R1_第三批稳定缺行事故与重试裁定.md`](agent/M1_HK-HISTORY-R1_第三批稳定缺行事故与重试裁定.md)。
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
- 终验证据：[`agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md`](agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md)、
  [`agent/M1_SSE-REAL2双Route历史Universe发布主Agent最终验收报告.md`](agent/M1_SSE-REAL2双Route历史Universe发布主Agent最终验收报告.md)。

## 2. 已完成的功能

### 2.1 项目治理和目录

- 建立 `AGENTS.md`、`.ai/` 通用工程规则、SSOT 表和“文档随代码更新”规则。
- 按绿地项目处理：生产代码不得 import `archive/legacy_pre_greenfield/`；`data/legacy/` 不参与默认发现。
- 代码、数据和产物分离：`src/`、`data/`、`artifacts/`、`archive/` 各自有明确职责。
- 复杂里程碑采用“主 Agent 冻结任务书 → 外部实现 → 不同外部会话独立初验 → 主 Agent 终验”，初验失败必须返工复验。
- 外部 `cursor-agent` 从 Windows 启动，但项目命令固定进入 WSL Miniforge；高风险任务使用非 fast
  `cursor-grok-4.5-high`。

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

- [`../AGENTS.md`](../AGENTS.md)、[`../.ai/README.md`](../.ai/README.md)：Agent、SSOT、验证、环境和交易安全规则。
- [`../A股港股通个人量化投研交易系统调研.md`](../A股港股通个人量化投研交易系统调研.md)：完整技术选型和 pipeline 定位。
- [`../项目实施路线图.md`](../项目实施路线图.md)：M0–M5 状态与 Gate。
- [`M3实施与Agent交接.md`](M3实施与Agent交接.md)、[`M3_M4实施总规划.md`](M3_M4实施总规划.md)：M3/M4 契约与依赖；当前状态以本文件顶部摘要和路线图为准。
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

`docs/agent/` 保存任务书、实现报告、独立初验和主验报告。优先读取：

- [`agent/M4_P0Route与M3_HISTORY主Agent集中验收报告.md`](agent/M4_P0Route与M3_HISTORY主Agent集中验收报告.md)
- [`agent/M3_HISTORY-PILOT10真实有界恢复执行任务单.md`](agent/M3_HISTORY-PILOT10真实有界恢复执行任务单.md)
- [`agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md`](agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md)
- [`agent/M1_SSE-REAL2双Route历史Universe发布主Agent最终验收报告.md`](agent/M1_SSE-REAL2双Route历史Universe发布主Agent最终验收报告.md)
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

- Git 已存在有效 HEAD：`master@ed77978`。后续不得再执行 `git init`；当前未提交改动属于正在进行的
  里程碑工作，提交前须按白名单核对，不得覆盖用户或其他 Agent 改动。
- README 链接了根目录 `karpathy-guidelines.md`，但当前文件实际缺失；现行代码规则在
  [`.ai/coding_rules.md`](../.ai/coding_rules.md)。迁移后应决定恢复该文件或修正引用，避免断链。
- 当前约有 94 个生产 Python 文件、63 个测试文件。`data/` 约 15MB，`artifacts/` 约 2MB。
- `archive/legacy_pre_greenfield/` 约 11GB，其中几乎全部是
  `archive/legacy_pre_greenfield/data/qlib_dataset`。生产代码明确不使用该目录，`data/qlib/` 当前为空；迁移时
  可将该 11GB 目录继续压缩/单独冷存或不随工作目录复制，但不要在未备份时删除。
- 移动目录可能改变真实路径、inode、symlink 祖先和 trusted-root 检查。复制完成后不要直接继续写 run state，
  先执行第 6.3 节零网络检查；失败时保留旧目录，禁止修改 receipt 绕过门禁。

## 6. 测试命令及当前结果

### 6.1 验证原则

日常只跑改动相关测试、定向 Ruff/mypy 和最小真实样本。全量 pytest 只在跨模块合流、关键发布、里程碑或
Gate 主验运行。本停止点没有为纯数据发布机械重跑全量测试。

### 6.2 最近已确认结果

| 范围 | 最近结果 |
| --- | --- |
| SSE-REAL1 主验 | SH/SZ reverse audit 两条命令均 exit 0，分别 `644/1212/268/PASS`、`644/1237/417/PASS` |
| SSE-REAL2 主验 | 双 Route `--dry-run` exit 0；SH `1062/919/644/PASS`，SZ `1149/1014/644/PASS`，`published=false` |
| M4 Route/D1-R | 113 passed；五个相关模块 mypy 通过 |
| M3 HISTORY H1–H3 | 197 passed / 1 deselected；Ruff/mypy 通过 |
| M3 HISTORY H4 | 8 个核心预算/CLI 测试通过；定向 Ruff/mypy 通过 |
| M3 G1-P4C 当时全量基线 | 798 passed；Ruff；79 个 source files mypy 通过 |
| Qlib 环境探针 | py312 41 passed / 1 deselected；base 42 passed；Qlib 0.9.7 关键 import/readiness 通过 |

`798 passed` 是 P4C 当时的全量基线，之后还有 Route、HISTORY、SSE 等增量，因此**不能表述为当前 HEAD 的
最新全量回归**。迁移后先跑定向 smoke；在恢复大规模 HISTORY 前通常不必跑全量，在正式 G1 release 或跨
Gate 验收前再跑。

### 6.3 迁移后的零网络 smoke

在新目录中进入 WSL Miniforge base，先运行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python --version
/home/mabw/miniforge3/bin/conda run -n base python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status

/home/mabw/miniforge3/bin/conda run -n base python -m quant.data.audit_connect_eligibility \
  --route SH_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2014-11-17 --expected-baseline-count 268
/home/mabw/miniforge3/bin/conda run -n base python -m quant.data.audit_connect_eligibility \
  --route SZ_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2016-12-05 --expected-baseline-count 417

/home/mabw/miniforge3/bin/conda run -n base python -m quant.data.rebuild_connect_universe \
  --route SH_CONNECT --baseline-date 2014-11-17 --mode reverse-audit \
  --snapshot-date 2026-07-10 --expected-baseline-count 268 --dry-run
/home/mabw/miniforge3/bin/conda run -n base python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --baseline-date 2016-12-05 --mode reverse-audit \
  --snapshot-date 2026-07-10 --expected-baseline-count 417 --dry-run
```

这些命令不得联网或写 data。任何 identity、path、receipt、Schema 或计数差异都先停止调查。

推荐定向测试：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_audit_connect_eligibility.py \
  tests/unit/test_rebuild_connect_universe.py \
  tests/unit/test_eligibility.py \
  tests/unit/test_update_connect.py -q

/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_g1_planning.py \
  tests/unit/test_m3_backfill_requests.py \
  tests/unit/test_m3_g1_candidate.py \
  tests/unit/test_m3_g1_workflow.py \
  tests/unit/test_m3_run_g1.py -q

/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_execution_contracts.py \
  tests/unit/test_execution_ports.py \
  tests/unit/test_execution_store.py \
  tests/unit/test_execution_oms.py \
  tests/unit/test_connect_execution.py \
  tests/unit/test_pretrade_risk.py -q
```

需要全量 Gate 时才使用：

```bash
/home/mabw/miniforge3/bin/conda run -n base ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base mypy src
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
```

## 7. 环境变量和启动方式

### 7.1 运行环境

- 只支持 WSL，不要求兼容 Windows 原生 Python。
- 主体环境：WSL Miniforge `base`；最后验收记录为 Python 3.13.13。
- Qlib 环境：WSL Miniforge `py312`；Python 3.12.13，`pyqlib==0.9.7`。
- 非交互固定前缀：`/home/mabw/miniforge3/bin/conda run -n <env> <command>`。
- 外部 `cursor-agent` 只能从 Windows 启动，但 Prompt 必须要求其在 WSL 新项目路径执行所有 Python、测试和工具。

安装/恢复：

```bash
cd /新的/WSL/项目路径
/home/mabw/miniforge3/bin/conda run -n base python -m pip install -e '.[dev]'
/home/mabw/miniforge3/bin/conda run -n base python -m pip install -e '.[data]'
/home/mabw/miniforge3/bin/conda run -n base python -m pip install -e '.[research]'
```

不要在 base 安装 `.[qlib]`；`py312` 已有已验收 Qlib 环境，迁移代码后只需从新目录调用。

### 7.2 凭据和环境变量

- Tushare token 只在 `configs/tushare.local.toml`。该文件不入 Git，迁移时用私密方式单独复制。
- 可选环境变量 `QUANT_TUSHARE_CONFIG=/安全路径/tushare.local.toml` 用于改变本地配置路径。
- 不支持 `--token` 命令行参数，不把 token 写入 `.env`、MCP URL、日志、报告或聊天。
- 当前不需要其他强制环境变量。交易配置来自 `configs/trading/example.toml`；`auto_trade=false`，无 LIVE。

### 7.3 常用入口

```bash
# M3 状态/分阶段工作流
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status

# 数据更新（真实网络；必须有单独授权和小范围预算）
python -m quant.data.update --source tushare --date YYYY-MM-DD --symbols 000001.SZ

# Tushare 脱敏权限检查
python -m quant.data.check_tushare --date 2026-07-10
```

迁移需保留 `data/raw`、`data/clean`、`data/run_state` 和必要 `artifacts` 的相对结构。不要只复制源码后重建
run state；这会丢失 INDEX/HISTORY receipt 和真实数据血缘。`configs/tushare.local.toml` 因被忽略，普通源码
复制工具可能漏掉，必须单独确认。

## 8. 不应重复尝试的失败方案

1. **不要在 base/Python 3.13 源码硬装 Qlib，也不要降级 base。** 使用已验收 `py312`。
2. **不要让 Qlib LocalProvider 直接挂项目 clean Parquet。** 走 staging + 官方 `dump_bin.py`。
3. **不要把当前港股通名单回填过去。** 必须用 verified snapshot/event 和历史有效区间。
4. **不要恢复 SSE 旧 `ADJUST_TYPE == "01"` 映射。** 官方值是“调进/调出”；错误版本曾把 1,212 行全部变成 REMOVE。
5. **不要用普通 upsert 修复错误 SH clean。** 错误旧行不会被删除；本次已用显式 single-route replace 正确修复。
6. **不要重跑旧 HISTORY 月窗 `suspend_d` 计划。** 它在 5,000 行边界正确 fail closed；不要改成 `>5000`、
   提高上限、盲目 resume、删除旧 evidence 或把不完整 receipt 当成功。
7. **不要在 `/mnt/g` DrvFS 用 `os.replace`/hardlink 假装正式 G1 no-clobber publish。** 正式 release 要在支持并经
   探针验证的 WSL ext4 路径执行。
8. **不要在没有正式 `VerifiedG1Release` 时启动真实 G2–G9。** fake/contract 测试不能关闭 Gate。
9. **不要把空复权因子静默当作 1。** 明确不复权时使用显式参数；研究收益不能混用不同供应商 HFQ 与现金分红总回报。
10. **不要把网页可访问等同于数据许可。** HKEX 公共网页/JSONP 禁止脚本化生产采集；Tushare ETF/API
    权限以当前官方权限表和有界探针为准，不沿用旧积分数字猜测，也不循环重试。
11. **不要把 AKShare 网页端点当唯一生产源。** 已出现上游拒绝/无效响应；保留 raw、换 BaoStock，并继续质量门禁。
12. **默认运行时仍是 WSL Miniforge base。** 本轮用户明确允许 Windows Miniforge 做兼容性定向验证；
    不得因此把生产运行时、路径或依赖合同改成 Windows-only。
13. **不要让因子/策略/执行层直接扫描 `data/` 或 `archive/`。** 只通过 `quant.data` repository/显式工具消费验证对象。
14. **不要重新初始化 Git、删除 11GB legacy 数据或改 receipt 来适应新路径，除非用户明确授权。** 先保留旧目录和哈希证据。
15. **不要在普通开发返工中机械跑全量 pytest、使用大数据样本或高频轮询长任务。** 当前约束是 usage/效率，不是时间。

## 9. 下一步建议

### 9.1 已完成目录定位

1. Windows `F:\AI_Coding\QuantitativeTrading` 与 WSL
   `/home/mabw/AI_Coding_win/QuantitativeTrading` 已确认解析到同一目录；后续不再按旧 `/mnt/g` 路径执行。
2. `configs/tushare.local.toml` 继续保持本地 ignored 且不得输出 token。
3. Git 已有 `master@ed77978`；继续用 `git status`、diff、hash 和测试报告审计变更，不执行第二次初始化。
4. `archive/legacy_pre_greenfield/` 不参与生产或普通测试，未经单独授权不删除。

### 9.2 恢复 M3 主线

HISTORY receipts 已完成，但 HISTORY stage 尚未通过：

1. 先由全新外部只读会话独立初验 R5 最小 fixture；通过后主验两个 resume 测试和定向静态检查。
2. 对正式 `G1_CANDIDATE_COMPONENT_INVALID` 做零网络组件级定位。基金 mapper 已排除，优先逐层验证股票
   daily/adj_factor、严格复权覆盖、stk_limit/suspend、公司行动选择/对账和最终 Schema；避免每次只重复
   20–35 分钟 full build 而无细分证据。
3. 若发现实现缺陷，先冻结返工任务书，再走全新 Cursor 实现、另一全新 Cursor 独立初验、主 Agent 终验；
   若是正式数据缺陷，保留 raw 并按既有 fail-closed 合同裁定，禁止改 receipt 或静默填充。
4. full candidate/HISTORY 真正通过后才运行 REFERENCE 和 PREPARE。正式 PUBLISH 还需用户启用主机虚拟化
   并提供经探针验证的 WSL2 ext4 root，取得 `VerifiedG1Release` 后方可启动真实 G2A。
5. 再按 `G2A→G2B→G2C→G3A→G3B→G4…→G9` 的任务书顺序推进 Qlib provider、标签、模型、回测、追踪和 Gate。

### 9.3 M4 与其他补项

- M3 G7 前置满足后推进 M4 B1/B3，再完成 B4/B5、统一回测 B6–B8。
- 完成 P2 Paper Gateway、P4 outbox 服务、P5 对账恢复、P6–P8 操作和四周稳定性 Gate。
- P1 两代码 60 日有界探针已通过；实现并验证 HK60 raw-first 可恢复 manifest 后，按最多 83 只/批、至少
  60 分钟冷却逐批执行。不得调用 HKEX 公共网页/JSONP；`02983.HK` 缺行必须使用合规来源或明确契约
  处理，不能伪造。
- 券商权限和程序化交易报备明确前不实现 LIVE Gateway；最终实盘前轮换 Tushare token。

路径定位已完成；后续任何 path/trusted-root smoke 差异仍应保留证据并 fail closed，不通过修改合同迁就。
