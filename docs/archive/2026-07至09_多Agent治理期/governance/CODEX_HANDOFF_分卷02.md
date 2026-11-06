
- 前台策略审查已诚实收口：固定 60 观测、12% 不加杠杆波动率目标在两折和三档成本下均为正，但 2026-08-31 前没有冻结后的首个前向信号，历史 ETF 池 PIT 与统一市场事件重放仍未闭合，因此保持 `RESEARCH_ONLY`，不生成 `PAPER_CANDIDATE`。Tushare 核心历史 raw 已完成 24,343/24,343 个请求和全量摘要复核，但需先隔离 21 条 OHLC 异常、特殊代码与 `600018.SH` 复权缺口，不能整批直升 clean。
- M3 honest 300 public CLI 曾在资源受限的唯一 Windows 进程中通过首发、completed resume、零写边界与 teardown（`1 passed in 9716.55s`），但该产物使用了已由 SSOT 从 `summary` 修正为 `research-summary` 的旧 stage，不能继续用于 tracking。修正 revision `c9f2f36` 的 retained root 已完成 h5/h10 三场景 backtest；其 fold manifest 只有 `fold_001`，正式跨折 `research-summary` 按最小 two-fold 合同 fail-closed，因此 `UA-M3-003` 旧目标已撤回。旧 G1 的 eligible domain 也只覆盖 23 个 session，无法派生第二折；当前唯一受限 Windows 进程正在通过 public 链新建 24-session G1 与 two-fold × two-horizon retained root，已完成 G1 阶段，新 root 完成前不做 tracking 写入。
- M4 已完成 formal gateway、broker/OMS store、fresh G1 calendar ledger provider、ExecutionService composition、VerifiedSoakSchedule 与只读 daily runner。`UA-M4-004` 已批准：首个 PAPER target 由策略会话产出的真实 `PAPER_CANDIDATE` 提供，开盘事实由 receipt-backed clean source 提供；fixture、历史回测、空 target 与 `RESEARCH_ONLY` 均不得冒充正式输入。真实任务注册和启动仍受 `UA-M4-002` 控制。
- M1 U0C-R3 已在 2026-08-14 自然完成第五个一次性任务：最终 live `LastTaskResult=0`，WSL base 五日 `audit_daily_streak` 返回 exact `PASS/sessions=5`，连续调度子 Gate 关闭。Operational 历史通道仍关闭且已披露；HK60、正式许可/复权/公司行动与 M1 整体 Gate 仍开放。
- Linux/ext4、真实 PAPER、28 日 soak 和 LIVE 均未完成。外部 Agent 当前暂停，由主 Agent 串行开发；内部 subagent 不用于模拟独立实现/初验。
- 已完成 worktree 与临时目录清理：统一集成、活动 M1、活动 M2 三个附加工作树因分别承载 M3 续跑、M1 第五次自然任务和策略候选开发而保留；旧 M3 run 已移入 `artifacts/archive/agent_runs/20260814/`，活动/归档树中的测试与字节码缓存已清理。未挂载的旧 `m3-g4-formal` 与 `pre-m2-main-dirty-20260802` 分支已先建立 `archive/*` 标签再删除活动分支引用，可完整恢复历史。

### 2026-08-10 当前续写摘要（覆盖下文旧 G1/M3/M4 停止点）

- 正式 G1 Windows轨已完成并从磁盘fresh验真：release `08eb9b31...7359`、manifest
  `d3923fa1...f99c4`、17个exact artifact paths、quality 0 error/0 warning；见
  [`20260809_M3_G1_Windows正式发布物磁盘复验报告.md`](../framework/agent/20260809_M3_G1_Windows正式发布物磁盘复验报告.md)。
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
  [`docs/framework/agent/M3_G6B开发示例跨折研究汇总Artifact主Agent阶段验收报告.md`](../framework/agent/M3_G6B开发示例跨折研究汇总Artifact主Agent阶段验收报告.md)。
- development example 研究链已推进到 G6A：逐 work evaluation artifact、八状态 IC、五层 key 闭包、
  四类 coverage、canonical manifest 与 fresh receipt verifier 已完成；Windows 与 WSL base 定向集合均为
  `19 passed`。详见
  [`docs/framework/agent/M3_G6A开发示例逐Work评价Artifact主Agent阶段验收报告.md`](../framework/agent/M3_G6A开发示例逐Work评价Artifact主Agent阶段验收报告.md)。
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
> 本文是迁移快照，不取代 SSOT。里程碑以 [`../项目实施路线图.md`](../../../../项目实施路线图.md) 为准，当前验收以
> 截至2026-07-31的旧状态见 [`M3当前验收与返工总览`](../../agent-history/M3当前验收与返工总览_截至2026-07-31.md)，当前状态以本文件顶部最新摘要、代码和路线图为准，架构理由以
> [`../A股港股通个人量化投研交易系统调研.md`](../../../research/surveys/A股港股通个人量化投研交易系统调研.md) 为准。

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
