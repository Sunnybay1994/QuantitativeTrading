# Codex 项目迁移交接

### 2026-09-08 R21 trace 合流与 ETF 在途状态（覆盖下文旧快照）

- R21 SinglePassTrace source `3037dee198c383ccd10c8e7b52008fbf92f24468` 已经领域验收及原独立
  reviewer 最终 `REVIEW_PASS / P0=P1=P2=0`，统筹 latest-main merge-tree 通过后 no-ff 合入
  `883aa97d9e3179444741ac2b1efaa311a886b466`。仅三表 trace、原因子兼容及测试/合同/交付/审查文档，
  不包含完整 runner、公共 receipt、残差诊断或经济运行。
- 统筹在根 main 以 `D:\Miniforge3\python.exe`、`PYTHONPATH=F:\AI_Coding\QuantitativeTrading\src`、
  `POLARS_MAX_THREADS=2`、`OMP_NUM_THREADS=1`、`PYTHONDONTWRITEBYTECODE=1` 运行冷导入，确认实际
  module 位于根 src；定向 `pytest -q tests/unit/test_classic_eleventh_batch.py
  tests/unit/test_cross_sectional_rank.py -p no:cacheprovider --basetemp <evidence>/pytest-temp`
  为 `40 passed, 468 warnings`；生产+test Ruff `--no-cache` 通过，生产 mypy 指定隔离 cache 通过。
  四阶段 native exit 均 0，stdout/stderr/exit 留在
  `artifacts/agent_runs/m2-r21-trace-integration-20260908/`。warnings 为 Pandera/Polars concat 弃用告警，
  未修改依赖；这些是 Windows 开发集成证据，不关闭 Linux Gate。
- main 与 source 的 production/test Git blobs 分别同为 `08f9dae5e13fe4240d34db2fafacdcd540f5a9ea`、
  `6f28093ad1bcc655b8e8e4fec481dcb25add89e8`。main checkout 为 CRLF、source 为 mixed，故文件 SHA
  不直接复用：本次 main production SHA256 `d6fe9ae1e060e1eeab4332c7d16d85f98001a25ef8da5c36a2af0e1cfd9176ab`，
  test SHA256 `d45cf11432876119c326a7abf95acd0859439beaae822ef694505da6346dfd55`。
- R21 source tracked clean，但含原失败/成功验证证据，状态 `INTEGRATED / RETAINED_EVIDENCE`，不标 RETIRED，
  不删除 source 或 ignored evidence。原 delivery/review 保留失败、返工和 SHA 勘误历史。
- ETF 最新静态复验仍 `REVIEW_FAIL / P1=1`（测试覆盖不足）；已批准原 Worker 1 的原 subagent
  `01a07e54-d06c-7bf0-b520-5bd1225ce828` 仅 test+delivery 的 `STATIC_REWORK3`。生产冻结 SHA256
  `3d4047c48a2d33610d3cd989ffa42fe4ca2cb8849b9ee3f05b283987c20eb52e`；Python/data/network 仍 0。
  框架经理接原独立 reviewer 复验，通过后另申请 fixture；尚未完成真实补数。
- 投研 residual 数值提案仅为待独立审查基线，`SOLVER_AUTHORITY_UNBOUND`；NumPy 只是在 research optional
  group 显式声明的待审批提案，不安装、不扩 core，不绕过公共 receipt 或经济准入。

### 2026-09-08 ETF 派发状态更正

当前 fresh 读取已返回原 Worker 1 的完整历史：首次派发成功创建唯一隔离实现者
`01a07e54-d06c-7bf0-b520-5bd1225ce828`，第二次消息复用了该实现者。ETF source
`c06b776` 现有获批的 production、unit test、delivery exact3 未跟踪文件；交付报告为
`DELIVERY_READY`，全部运行验证与真实补数仍为 UNRUN。框架经理负责接续原实现链的独立初验。
下文 `DISPATCH_NO_PROGRESS` 是此前工具返回空 items 时的历史误判，现被本条更正；空返回和顶层 idle
不能证明 subagent 不存在。保留历史记录，不替换或重复创建实现者。

### 2026-09-07 新统筹接管摘要（当前权威快照，覆盖下文旧停止点）

- 用户已指定当前“项目统筹调度”任务接替原项目统筹/中央 Agent。框架、投研、GUI 三个领域经理已切换
  协调入口；既有 taskbook、Worker/subagent、worktree、脏文件、证据以及 `STOP/LOCKED` 状态不变。
  Git 管理的 `tasks/deliveries/reviews` 继续是生命周期权威，session/ACK/mapping 只作诊断。
- 当前集成线为根 `main@3ac097f0b361de9e9078b079bae66fff6644a7b0`。投研经理先将既有研究报告与
  R21 runner 任务书 exact2 收口为纯文档提交 `a7091e48d1e1c89a37d719141a173ac8f4b13a9f`；随后统筹把
  GUI G1-D2 source `9144452b39a61212c389e1f0729e9176b2187813` 以 no-ff 合入 `3ac097f`。
  合流后 GUI 定向 pytest 在项目内隔离 basetemp 为 `26 passed, 2 skipped`；两个 skip 分别受当前 Windows
  symlink/只读 base 缺 Streamlit 条件约束，来源线既有受控环境 AppTest 证据仍为 `9 passed, 0 skipped`；
  Ruff 与两生产文件 mypy 均通过。首次 pytest 的 26 个 setup error 全部来自系统 pytest 临时目录访问拒绝，
  改用项目内 ignored basetemp 后闭合，不归类为产品失败。
- GUI G1-D2、`governance-research-specific-tools-boundary` 与 `m2-s2-etf-voltarget-forward1` 三条已合流、
  tracked clean、无正式 ignored evidence/占用进程的短来源线已 archive-first 退休；归档标签分别为
  `archive/gui-g1-d2-run-search-20260907`、
  `archive/governance-research-specific-tools-boundary-20260907` 和
  `archive/m2-s2-etf-voltarget-forward1-20260907`。其他含 `agent_runs`、validation evidence、本地 formal config、
  未合流提交或不明确 owner 的 worktree 全部保留，不为目录数量批量清理。
- 当前投研第一业务队列是用户已明确授权的 exact11 ETF 截至 2026-08-31 价格与分红补齐：既有来源、
  no-clobber 隔离 raw/candidate、完整历史重建与重叠/接缝/集合闭包验证；不得覆盖 canonical clean，
  不运行回测、trial、PAPER 或交易。框架/data 经理负责形成任务包并向统筹申请 exact worktree、网络与数据
  I/O 资源；投研经理负责经济口径与结果验收，不重复创建 writer。
  初始任务书已以 `f8238471809915589d7f5a15378edc579f00acf5` 进入 main；唯一 source worktree 为
  `codex/m2-etf-exact11-isolated-total-return-backfill-r1@c06b77632cf65db90d39d5897c664f372a2d9736`，
  其 Phase1A 已冻结 calendar/clean/static 只读输入、raw 路径二阶段申请和独立 exact6 no-clobber evidence
  合同。当前仍未授 Python/CPU、真实 data read、network 或执行；没有可直接复用的现成 inventory CLI，
  最小 runner/tests exact2 已冻结。framework/data 经理向唯一现有 Luna Worker 1 派发并按中央裁定向同一
  Worker 最短重发一次，两次 turn 都以空 items 结束，未创建可确认的隔离 subagent、diff 或 delivery；当前
  状态为 `DISPATCH_NO_PROGRESS / STOP`，不是实现失败。禁止第三次重发、替换 Worker 或由顶层接管代码；
  验证、真实 Phase1A data read 与 network 仍未授权。
- R21 因子计算已经合流，但 runner 接入任务仍为 `DESIGN_PENDING_REVIEW_AND_PUBLIC_RECEIPT_API`；公共
  attempt receipt、pre-label schedule、诊断 schema 与运行身份未闭合前，不读取未来收益 label、不执行经济
  evaluation/publish。公共 receipt Windows successor 的唯一 Parser 门禁为 `PARSER_ERRORS=10 / exit 2`，
  保持 `PRODUCT_NOT_EVALUATED`，旧链不得 patch、重试或另建 carrier。
  投研经理先在 `216c1977` 补充内部全市场 eligibility 缺日反例；中央随后采纳“R21 新 strict
  canonical-session identity、旧 batch 不迁移”的设计，并由 `73a1bb01767435d401bf671f0d939b2a84bfc54b`
  写回任务书。该裁定只关闭 schedule 设计歧义，不构成公共 receipt、实现或经济运行授权。
- M3 旧 retained 仍是 `terminal FAILED / LOCKED`，不恢复、不重跑、不清理；M4 真实 bootstrap、PAPER、
  28 日 soak 与 Linux/ext4 Gate 均未被本次接管或 GUI 合流推进。当前没有 Python/pytest/data writer 长进程；
  后续资源仍逐任务 fresh 核验与发锁。

### 2026-08-16 当前续写摘要（覆盖下文旧停止点）

- 当前项目集成线为 `codex/project-integration@本文件所在提交`；物理 worktree 目录仍沿用历史名称
  `artifacts/dev_worktrees/m1-hk60-integration`。2026-08-23 已确认 ACL 与同级目录改名能力正常，当前改名阻断
  是受保护的 Tushare finance writer 进程把该目录作为 CWD 持有。不得为目录整洁中断或重启 writer；收到
  `[TUSHARE_FINANCE_TERMINAL_NOTIFIED]` 且再次核对进程、Git 与目录状态后，才由统筹执行
  `git worktree move` 到 `artifacts/dev_worktrees/project-integration`；
  业务合流稳定点 `46f8e1d` 已保留原提交身份吸收
  M1 `9004b6d`、S2 `4ac392a`、liquidity `ec506b6`、GUI G1/C4 `a5c63f7`/`18dc006`、M4 RUN-0D2
  `92de0d4`、downside beta `3c8c6c4`、Alpha158 `0f737ac` 与 MAX `0363b0f`。此后 `ba83ad7` 吸收
  R10 证据，`c2c8841` 吸收 MAX daily-basic 控制，`8427c83` 吸收 GUI D1，`086cae9` 吸收 PIT 首跑前置，
  `4745cb4` 吸收 FWD-R1，`936ffee` 吸收 PIT R2 维度审计，`7b377db` 吸收框架 owner 的 M3/M4 状态收口，
  `9151d3f` 吸收 M3 root-topology 修复，`8991b0e` 吸收 Windows Conda Python hardlink forward-port，
  `864d254` 吸收 TARGET R11 未来标签前视修复；
  MAX-control 合流回归为 25 passed，GUI D1 为
  19 passed/2 skipped，PIT 前置为 32 passed，FWD-R1 为 17 passed/1 skipped，PIT R2 为 18 passed，五者定向
  Ruff、mypy、cold import 均通过，不把这些定向证据扩大表述为覆盖其它范围。
- 根 checkout 仍由受保护的 Tushare finance writer 使用；writer 继续自然采集，writer 权威终态前禁止切换
  根分支、结束进程或并发写源码。投研 session 以 30 分钟 heartbeat 只读监测；只有
  `COMPLETE=177184`、其他请求状态为 0、active lease 为 0 且 writer 自然退出时，才向统筹发送一次性终态
  通知并暂停自动化。
  用户提供的 `quant_factor_research_v2` 资料包已按批示迁入
  `docs/research/references/quant_factor_research_v2/`：共 25 个文件、1,562,345 bytes，迁移前后相对路径、
  长度与 SHA-256 全量一致，根目录原未跟踪副本已移除。该资料包是版本化知识输入，不是项目 SSOT，
  运行时代码仍不得自动发现或消费。
- S2 admission 已形成 fail-closed 安全点：B8 metrics provenance 尚未绑定到 verified replay/metrics 时，
  完整证据只能是 `RESEARCH_ONLY / ADMISSION_METRICS_PROVENANCE_UNBOUND`，不得生成 `ELIGIBLE` 或
  `PAPER_CANDIDATE`。source binding、人工准入与真实 PAPER Gate 仍开放。
- 六条 M2 因子真实不可变 run 已用 no-clobber、逐文件 set/size/SHA-256 与 `run.json` 输出闭包验真后保留在根
  `artifacts/research/runs/<run_id>/`。Amihud、自由流通换手、downside beta、Alpha158 第四批与 MAX
  daily-basic 控制 `30326191…e2cf` 均为 `REJECTED`；原始 MAX `10dea14f…129bb3` 通过初筛但最高仅
  `RESEARCH_ONLY`。控制实验的历史产物因 2x 成本收益为负而记录为 `REJECTED`，不能把原始 MAX 的结果
  升级为已排除规模/换手暴露；
  但 TARGET R11 后该历史成本腿不是有效经济证伪；控制 run 的 immutable `REJECTED` 状态保持不变，原始
  MAX 与控制 run 均不得推进。forward、统一回放和人工 admission 仍未闭合。相关短期 worktree 已退出；
  统一 I/O/compute 分段仍是性能债，
  当前证据不支持先上 GPU、并行或语言重写。
- M2-SOURCE-R10 已发布同逻辑输入、同经济行为的 successor `e43da184…7a96f`，根 canonical 经 public verifier
  复验为 `RESEARCH_ONLY`；source/canonical 6 文件、60,597 bytes、逐文件 SHA-256 差异为 0。R10 证据已由
  `ba83ad7` 合流，重复 worktree 已移除，source branch 已由 `archive/m2-source-r10-successor-20260816` 保存后删除。
  历史混合 EOL 导致旧 code hash 不可由 commit 复算的 provenance 债仍开放，但不再阻塞 M2-FWD-R1。
- finance writer 已自然耗尽当前可领取请求并退出，`data/clean/tushare_financials` 尚未形成。用户已裁定投研主线
  不因采集等待而整体暂停，但恢复期间只能消费既有、已验证、冻结且不可变的 clean snapshot；禁止读取或使用
  partial financial raw、采集中 ledger 或未发布的 financial clean。财务接入顺序保持
  `writer terminal → audit-v4 → R3 → publisher/不可覆盖 snapshot → PIT`，任何前置未闭合都不得启动真实 PIT
  quality run。
  2026-08-28 四财务 dataset 的只读一致性事务为 `COMPLETE=175,819 / RETRYABLE=1,365`，
  `PENDING/RUNNING/FAILED/SPLIT_REQUIRED=0`，lease 行数与 active lease 均为 0，writer absent，最新 finance
  stderr 为 0 bytes。1,365 条全部为 `cashflow / RETRYABLE / attempts=3 / TRANSIENT`；full canonical request-set
  schema `m2-tushare-finance-retry-request-set-v1` 的 527,133 bytes SHA-256 为
  `45523530323690e8ecf9f1a7649e0efbdac9ce9c99de3e5fef0f572e0f4ec966`，辅助 IDs-only SHA-256 为
  `f22b930b1bde003a63ca66d4a086ffa4ee8d6af2d9c517904fbc5eb23a209992`。[`UA-M2-001`](用户待批示与参与事项.md)
  用户已逐字批准仅该 full digest 集合每 request 增加 1 次机会，attempt ceiling `3 → 4`、single writer/single pass。
  首次 PID `40212` 在零写边界因 `RECOVERY_PRIORITY_SET_FAILED` 停止；显式 64-bit Windows `ctypes` ABI 的独立
  AUDIT1 随后 PASS。新的 recovery2 preflight/manifest 再次闭合原 exact 1,365/digest/lease0/writer absent，manifest
  SHA-256=`a2500992bebb88bcc9b737ff1551997d2030ca268bb8fc68168f587a28687db9`；唯一 writer PID `8676` 以
  `BelowNormal/0x3` 完成 exact 1,365，terminal SHA-256=
  `33655f1f15144551cd536610cac033534047341f39419452c84e325df4a1691b`，failure null、stderr 0 bytes。
  唯一 post-terminal 只读复核确认四财务 dataset 各 `COMPLETE=44,296`、合计 `177,184`，所有 noncomplete 状态为
  0、lease0、writer absent；exact 1,365 当前均 attempts4/COMPLETE，重建冻结 prestate full digest仍精确匹配；
  post-terminal result SHA-256=`7757a3c40526121cb26b2d087a81b14885968c37f96f2db89fd5ddae1c079386`。
  UA-M2-001 恢复已关闭，但 audit-v4、snapshot、R3 与真实 PIT仍未运行，下一步必须先冻结独立 audit-v4 包。
  snapshot READY 时，PIT 优先于新的非财务研究包。PIT 首跑前置 `3b8857c` 已以 A1
  `RECONSTRUCTED_CURRENT_INVENTORY_V1`、coverage gate、
  code-identity 与 `UNFROZEN/[]` pre-artifact STOP 进入 `086cae9`；来源线已 archive-first 退出，但这不等于
  当前 raw、snapshot 或真实 report-type 分布已经 READY。PIT R2 `cadff72` 的 audit schema v3、维度计数闭包和
  publisher 严格结构校验已进入 `936ffee`，来源线也已 archive-first 退出；本次只完成代码与 fixture 回归，未读取
  partial raw、未执行 integrated `--verify-bytes`、未选择 allowed values，也未发布 snapshot。v3 只能证明
  report-type/comp-type 分布，不能证明 `report_type=1` 是 PIT 单季差分所需的累计流量；writer 终态后必须先
  完成 audit-v4 type1/type2 对账。只有 terminal + `verify_bytes=true` + 基础 quality 可用时才执行 flow CTE；
  否则 v4=`NOT_EVALUATED`，不得用 partial evidence 下结论。publisher 只接受 terminal bytes-verified `PASS`，
  其余状态不得进入 R3 或发布 snapshot。
- TARGET R11 已以 source `7705898`、integration merge `864d254` 和
  `archive/m2-target-label-leakage-fix-20260816` 完成 archive-first 退出。修复强制先按当期 finite factor
  冻结 Top-K，再验证 chosen execution/exit/return；不得用未来 label 可得性删除高分证券并由下一名递补。
  13 个历史 immutable run 保持原字节与状态，`REJECTED` 不升级；四个原 `RESEARCH_ONLY` 经济腿为 HOLD，
  其 targets/NAV/收益/换手/成本字段不得用于 forward、S2/admission 或 PAPER。完整清单与边界见
  [`M2 策略与因子库并行建设路线图`](../research/roadmaps/M2_策略与因子库并行建设路线图.md)。
- TARGET R11 只关闭 Top-K 替补。后续只读审计确认 shared outcome cohort、持有期后漂移换手、pair 两侧
  redundancy coverage、主 config/cost same-bytes identity、分组单调否证和 PIT version/comp-type 链仍未闭合，
  统一登记为 `M2-EVAL-STOP-001`。同一 13 个 run 的 IC/group/direction/fold 与经济字段均不得作为 promotion
  证据；当前无修复 worktree。audit-v4 或纯数据 snapshot READY 都不能代替该方法门禁。
- M3 retained 两折链已进入显式失败终态，而不是运行中或成功 completion：四个 backtest 与 h5/h10 两份 summary
  已完成，但首个 reproducibility 组合 `fold_001/h5` 以 `M3_REPRODUCIBILITY_INVALID` fail closed，wrapper 随后
  `RETAINED_RESUME_FAILED`；evidence 为 `child_returncode=1 / outcome=FAILED / cleanup=REMOVED`，`completion.json`、
  reproducibility artifact/receipt 与 readiness evidence 均不存在，相关进程已退出。根因是 StageRunner 同时收到
  `PROJECT` 与其下三个专业 root；最小修复 `020a04d` 已通过 `9151d3f` 合流，focused `32 passed, 1 skipped`，
  Ruff、mypy 与 cold import 通过，来源线已由 `archive/m3-g8e-r2-root-topology-20260816` 留档后退出。
  历史 `71dffa5` 的 Windows Conda 当前解释器 hardlink 语义又由 `4d0be62` forward-port 到当前代码，并通过
  `8991b0e` 合流：只放行 exact current interpreter 在 Windows 上的预期多链接身份，其他解释器、额外 hardlink
  路径、symlink/reparse 与普通 artifact hardlink 继续拒绝。R3 focused `10 passed, 2 skipped`，关键 nlink>=2
  与额外 hardlink 路径节点实际通过，mypy/cold import 通过；R2/R3 分别由
  `archive/m3-g8e-r2-windows-hardlink-20260816` 与
  `archive/m3-g8e-r3-windows-hardlink-forward-port-20260816` 留档后退出。上述两项只关闭确定性代码阻断，
  actual worker/successor 仍未运行；detached `c9f2f36`、失败证据和两份 session 配置继续冻结，retained
  worktree 已置为 `LOCKED`。除 owner 明确解除 lock 外，禁止写入、自动恢复、重跑、切换 revision、启动
  successor 或清理现场。
- M4 RUN-0D2 已以 `92de0d4` 合流，但没有启动 PAPER、订单或 28 日计时。正常 PAPER 启动仍须关闭
  UA-M4-005 durable approval 与 UA-M4-006 shared barrier，再按顺序完成 cross-day rotation；UA-M4-007 只约束
  正常窗口结束后的 actual fault drill，不冒充首日启动前置。框架 owner 的单文件状态提交 `c2b4829` 已通过
  `7b377db` 合流，并由 `archive/m4-windows-soak-runtime-20260816` 留档；来源 worktree/branch 已 clean 退休。
  A/B 代码在用户裁定前暂停，未来 UA 包必须从当时最新 integration 新建，不能复用旧 M4 base。
- GUI C4 `18dc006` 已合流：optional 依赖为 `streamlit>=1.49,<2`，12 处 dataframe 参数已迁移；真实 AppTest/browser
  功能 smoke 通过且 console error 为 0。GUI D1 `9f42b3c` 又以只读的 14 字段关系诊断进入 `8427c83`；来源环境
  AppTest 5 passed/0 skipped，integration 最小回归 19 passed/2 skipped，真实 canonical 字节派生的隔离篡改反例
  证明 output digest 失败时不展示 mismatch 面板、metrics 或 NAV。D1 没有增加运行能力，来源 worktree/branch 已在
  archive tag 留档后退出。两类 Vega Infinite extent warning 继续登记为 renderer 债，不宣称 zero-warning；G2
  本地作业编排仍仅有只读设计，当前不为一个运行按钮提前引入 SQLite worker/lease 平台。
- M2-FWD-R1 `76b55cf` 已进入 `4745cb4`，R10 来源绑定与标准 LightweightResearchRun 发布路径的开发检查通过；
  没有执行真实 2026-08-31 发布或生成真实 forward artifact，来源线已 archive-first 退出。
- `data/clean/tushare_financials` 仍不存在。TARGET R11 与 PIT R2 均已合流并退出，CPU8–11 当前未分配新的
  短任务。PIT 有两条必须汇合的前置：writer 终态后的 integrated bytes audit/audit-v4 数据链，以及不依赖
  partial raw 的 `M2-EVAL-STOP-001` 方法链；二者均关闭后才可封板 R3 singleton/trial/fixed-direction/
  outcome-grid/monotonicity/version-chain/performance-sidecar，再进入 publisher/snapshot 与真实 PIT run。
  不得从 partial raw 提前选择 allowed values，
  也不得用 v3 的维度计数冒充累计口径证据。后续短任务仍保持
  BelowNormal、CPU8–11、数值线程不超过 2。
  完整 branch/worktree 所有权、退出条件、artifact 保留条件和基础设施债
  见 [`项目结构与合流治理路线图`](roadmaps/项目结构与合流治理路线图.md)。项目初期继续以最小正确业务闭环
  为先；PIT、fail-closed、统一回放、OMS/风控/对账、人工准入和凭据安全不得作为“基础设施瑕疵”延期。

### 2026-08-14 当前续写摘要（覆盖下文旧停止点）
