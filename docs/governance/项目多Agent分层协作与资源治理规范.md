# 项目多 Agent 分层协作与资源治理规范

> 状态：项目级操作规范
> 权威关系：本文件是 [`AGENTS.md`](../../AGENTS.md) 的执行细则；发生冲突时以 `AGENTS.md` 和用户最新明确指示为准。

## 1. 目标与适用范围

本规范定义 `QuantitativeTrading` 项目的 Agent 组织结构、任务下发链、资源治理、Git/worktree 生命周期和
交付闭环。目标是同时保证：

1. 各领域独立规划、职责清晰；
2. 具体实现上下文隔离，可安全并行；
3. CPU、内存、I/O、网络、文件和 Git 写入不冲突；
4. integration 与项目目录树长期保持整洁；
5. 任何业务结论、Gate 和不可变产物都有明确 owner 与证据链。

本规范不建立新的调度平台、数据库或常驻服务。当前继续使用任务文档、session、branch/worktree、资源窗口和
提交记录完成轻量治理。

## 2. 组织结构

```text
用户 / 项目负责人
└── 项目架构与统筹 Agent（Architect / Orchestrator）
    ├── 框架开发 Agent（Domain Manager）
    ├── 投研 Agent（Domain Manager）
    ├── GUI 开发 Agent（Domain Manager）
    └── 实现 Worker 池
        ├── 本地 Luna Worker 1 session
        │   └── 多个任务各自使用隔离 subagent
        ├── 本地 Luna Worker 2 session
        │   └── 多个任务各自使用隔离 subagent
        └── 外部 cursor-agent 独立会话
```

### 2.1 用户 / 项目负责人

- 决定业务目标、风险偏好、优先级和不可逆事项；
- 指定特殊 worker、模型、真实网络、真实数据、PAPER/LIVE 等授权；
- 对需要人工裁定的安全、凭据、账户和准入事项作最终决定。

### 2.2 项目架构与统筹 Agent

定位类似项目架构师和总调度，不承担常规业务功能实现。职责包括：

- 维护总体架构、跨领域边界、SSOT 和 integration；
- 审核领域经理的任务拆分是否最小、正确且可合流；
- 冻结 exact base、branch/worktree、路径白名单、共享文件锁和资源窗口；
- 维护全局 CPU、内存、I/O、网络、writer、测试槽和长进程所有权；
- 处理跨领域依赖、冲突、合流、archive tag、worktree/branch 退休和物理残留；
- 执行最终跨模块验收，确保项目树和运行现场可解释、可恢复。

统筹 Agent 不越过领域经理直接改变业务路线，也不把普通实现长期留在 integration 工作树中。

### 2.3 领域经理 Agent

当前固定三个领域经理：框架开发、投研、GUI 开发。每个领域经理负责：

- 维护自己的详细路线图、任务依赖、优先级、基础设施债和性能 backlog；
- 把目标拆成可独立交付的最小任务包；
- 冻结任务包的业务合同、失败语义、反例、路径白名单和验收命令；
- 向统筹申请 exact base、worktree、共享文件锁和资源窗口；
- 选择并向具体 Worker 下发任务，跟踪实现、返工与领域验收；
- 向统筹提交安全 SHA、验证证据、剩余风险和合流申请。

领域经理不直接修改 integration、不自行抢占共享资源、不跨领域派单，也不把计划状态写成完成状态。
任务经统筹冻结后，领域经理与所选 Luna Worker 直接交互，不需要中央 Agent 转发普通派发、ACK、静态进度、
独立初验、合同内返工或交付消息。领域经理仍须把共享资源申请、白名单扩大、身份冲突和合流申请提交统筹。

### 2.4 实现 Worker

Worker 只执行已经冻结的具体任务，不决定业务路线或扩大架构。

当前默认使用由多个本地 Luna Worker session 组成的 Worker 池。除非用户明确指定其他方式：

- 领域经理在统筹冻结任务后，直接选择一个空闲或合适的 Luna Worker，并把完整任务包发给该 Worker；
- Luna Worker 的顶层 session 是事件驱动 dispatcher，只负责任务校验、subagent 创建、路由登记和异常协调；
- Luna Worker 收到每个具体任务后必须创建独立 subagent 执行，不能在顶层 session 直接混做多个实现；
- 每个 Luna Worker 可同时管理多个互相隔离的 subagent；项目不预设固定“四槽”或“每个 Worker 一次只能有
  一个任务”的规则。实际并行度由可用 Agent 容量、任务依赖、文件写集合和统筹分配的共享资源共同限制；
- 每个 `task_id` 在任一时刻只能绑定一个 Luna Worker、一个实现 subagent 和一个 worktree。未经明确 STOP、
  身份闭包和统筹重分配，不得把同一任务同时派给另一个 Luna Worker；
- 多个任务只有在依赖已满足、写路径互斥且资源窗口允许时才可并行；否则顺序执行；
- dispatch turn 在返回 `task_id → agent_id → manager_thread_id/worktree` 映射后立即结束并恢复 idle，不等待
  subagent 完整结束；新任务到达时再开启一个短 dispatch turn，因此任务可以分时到达、随到随派；
- subagent 自行向领域经理和统筹推送阶段结果；每个 subagent 完成后必须返回精简交付报告并退出，不长期
  保持 `active`。

#### 2.4.1 Luna 事件驱动 Dispatcher 协议

Luna session 的 idle 状态就是“监听态”，不需要用长期 active turn 或高频 heartbeat 模拟常驻进程。每个领域
任务使用以下事件流：

1. `DISPATCH_REQUEST`：领域经理发送冻结任务包，并附 `task_id`、manager/root thread id、exact base、
   worktree、白名单、依赖和资源级别；
2. `DISPATCH_ACK`：Luna 校验边界、创建或复用该任务唯一 subagent，返回 `agent_id` 和当前状态，然后立即
   结束顶层 turn；ACK 必须直接推送给领域经理，并在 `artifacts/agent_dispatch/<task_id>/mapping.json` 建立
   no-clobber durable mapping；任一通道不可用时必须明确 `STOP`，不得默认为成功；
3. `STATIC_DONE`：subagent 完成静态实现与文本检查后直接通知领域经理和统筹；若工具不能跨 task 发送，
   则写入 Luna mailbox，由下一个短 turn 转发；
4. `RESOURCE_REQUEST`：需要 pytest、Ruff、mypy、真实 I/O、browser、端口或其他共享资源时，subagent 先
   停在安全边界并请求资源，不自行占槽；
5. `RESOURCE_GRANT / REWORK`：统筹或领域经理用新消息唤醒 Luna，Luna 将事件路由给原 subagent 后立即
   回到 idle；不得新建第二实现者覆盖同一现场；
6. `DELIVERED / STOP`：subagent 直接发送压缩交付或阻断报告，Luna 只维护映射和异常升级，不等待全部任务
   成批完成。

上述事件默认在“领域经理 ↔ 所选 Luna Worker / 任务 subagent”之间直接流转。中央 Agent 不作为消息代理，
也不需要逐条批准合同内静态实现、初验和返工。只有以下控制面事件必须提交中央：exact base/worktree 或共享
白名单冻结、CPU/真实 I/O/网络/端口等资源授权、跨领域或共享 SSOT 冲突、dispatch 身份无法闭合、任务迁移到
另一 Luna Worker、架构边界变化、integration 合流与来源线退休。中央直接联系具体 subagent 仅是 dispatcher
不可观察、身份损坏或原 owner 无法路由时的异常恢复手段，不是常规工作流。

Dispatcher 不维护新的数据库、队列服务或常驻后台进程。任务书、worktree、agent tree、压缩消息和按 task
隔离的 ignored mapping 构成当前轻量任务账本；只有直接回调与 mapping 都不可靠且用户另行批准时，才增加
低频 watchdog。不得以 UI `items=0` 单独判断任务未启动，须同时核对 durable mapping、agent tree、worktree
diff/mtime、进程和资源租约。

#### 2.4.2 双通道映射与恢复

每个任务使用独立目录 `artifacts/agent_dispatch/<task_id>/`，避免多个 subagent 争写同一 registry：

- `mapping.json` 由 Luna dispatcher 唯一写入且 no-clobber；至少包含 schema version、task id、稳定 logical
  agent id、可用时的 runtime agent reference、manager/root task id、exact worktree、角色、创建时间和初始状态；
- `status.json` 由该任务唯一 subagent 以临时文件加原子替换更新；只允许 `RUNNING / STATIC_DONE /
  RESOURCE_WAIT / DELIVERED / STOP`，并记录最后事件时间与压缩证据定位；
- 两文件均为运行协调状态，命中项目 ignore，不进入 Git，不保存提示全文、思维链、凭据、业务原始数据或长日志；
- 直接消息是低延迟主通道，durable mapping 是恢复通道。领域经理收到 ACK 后必须核对两者 task id、agent id、
  worktree 一致；不一致时按 `DISPATCH_IDENTITY_MISMATCH` 停止；
- 若 turn 完成但消息不可见，只有已存在且身份一致的 mapping 才允许认定已派发；只有 worktree 变脏不足以推断
  agent 身份。映射未证实时冻结现场、禁止重派，由统筹发起一次 status-only 恢复；恢复仍无 mapping/STOP 时标记
  `MAPPING_UNCONFIRMED` 并等待人工或 Worker 通道恢复。

对采用本协议前已经启动、无法取得 runtime agent reference 的现场，可由原 Luna 在确认其内部唯一实现者后写入
`adopted=true` 的 mapping；不得由领域经理或统筹仅凭文件时间代写或猜测 agent id。

外部 `cursor-agent` 是可选 Worker。未特别指定模型时使用 `auto`；用户或统筹可针对高风险、复杂实现或能力
需求显式指定其他模型。实现与独立审查必须使用不同的新会话或隔离上下文。

## 3. 权限与责任矩阵

| 活动 | 用户 | 统筹 Agent | 领域经理 | Worker / subagent |
|---|---|---|---|---|
| 业务优先级与高风险授权 | 决策 | 提案/执行 | 提案 | 无权决定 |
| 总体架构和跨域边界 | 确认重大变化 | 负责 | 参与 | 遵守 |
| 领域路线图和任务拆分 | 可调整 | 审核跨域影响 | 负责 | 不修改 |
| exact base/worktree/资源锁 | 可覆盖 | 负责 | 申请 | 使用已批准范围 |
| 业务实现和自测 | 不执行 | 非常规情况下才接管 | 管理 | 负责 |
| 独立初验 | 可要求 | 冻结角色与范围 | 组织 | 不同 Worker/上下文执行 |
| integration 合流与来源线退休 | 不执行 | 负责 | 提交证据 | 无权执行 |
| PAPER/LIVE、凭据、不可逆外部操作 | 决策 | Gate 管理 | 提案 | 禁止自行执行 |

## 4. 标准任务生命周期

### 4.1 领域规划

领域经理先在自己的路线图中明确目标、依赖、业务价值、STOP 条件和完成标准。尚未冻结的想法不得派给 Worker
边做边猜。

### 4.2 统筹准入

领域经理向统筹提交最小准入单，至少包含：

- 任务 ID、目标和非目标；
- 依赖和 exact base；
- 建议 branch/worktree；
- exact 写路径与只读输入；
- 共享文件、数据、端口和外部状态；
- CPU/内存/I/O/网络需求和预计窗口；
- 失败语义、停止条件、验收命令和至少一个反例；
- 期望 Worker 类型。

统筹确认无结构、资源和所有权冲突后，返回冻结任务包。未获准前不得创建 worktree、写文件或启动真实运行。

### 4.3 Worker 下发与实现

领域经理把冻结任务包原样下发给选定 Worker。Worker 必须：

- 核对 branch、HEAD、worktree 和白名单；
- 只修改批准路径；
- 发现合同矛盾、真实数据反例或依赖缺失时立即停止扩大并回报；
- 执行与风险相称的定向测试、Ruff、mypy、cold import 或真实探针；
- 不自行合流、rebase、修改 integration 或宣布项目 Gate 通过。

Luna dispatcher 收到任务后不得把顶层 turn 变成长时间实现或等待循环。它必须返回 `DISPATCH_ACK` 后恢复
idle，让后续分时到达的任务继续触发短 turn；ACK 同时要求直接消息与 durable mapping 身份一致。实际实现、
阶段回报和资源等待都由对应隔离 subagent 承担。

任务冻结后的普通通信由领域经理直接发送给该任务已绑定的 Luna Worker 或 subagent。中央只接收需要控制面
裁决的事件和最终合流申请，不承担日常消息中继。若某 Luna Worker 繁忙，可将新的、尚未派发的互斥任务分配给
另一 Luna Worker；已派发任务不得仅为提高吞吐而迁移或复制。

### 4.4 审查、返工和领域验收

高风险合同、复杂里程碑和用户指定任务必须由未参与实现的独立上下文审查。审查者只读核对实现并增加新的
对抗性反例；不得顺手修改生产代码。审查失败后，领域经理形成最小返工任务，回到原实现链，再由独立上下文
复验。

普通低风险窄包是否需要独立初验由任务书和 `AGENTS.md` 决定；实现者自测始终不能替代统筹最终验收。

### 4.5 统筹合流与退休

领域经理只在以下条件满足后申请合流：

- exact path 与禁止集核对通过；
- 任务文档和验证证据完整；
- worktree tracked 状态 clean；
- 真实产物已按 no-clobber 规则 canonical retained；
- 无测试、端口、锁、临时目录或资源残留。

统筹执行 merge-tree/no-ff、必要的 integration 回归、路线图终态同步、archive tag、worktree remove 和 branch
删除。遇到 Windows ACL 残留时不得假装已清理；必须保留准确路径、影响和所需权限。

## 5. 任务状态

统一使用下列状态，避免把“已有卡片”误读为“正在运行”：

| 状态 | 含义 |
|---|---|
| `PROPOSED` | 领域经理已提出，尚未获准 |
| `FROZEN` | 统筹已冻结边界，尚未派发 |
| `DISPATCHED` | 已发给 Worker，尚未开始写入 |
| `IMPLEMENTING` | Worker/subagent 正在执行 |
| `SELF_VERIFIED` | 实现完成且开发检查通过 |
| `REVIEW_REQUIRED` | 等待独立初验 |
| `REWORK` | 初验或主验发现问题，返回实现链 |
| `READY_FOR_INTEGRATION` | 领域验收完成，等待统筹合流 |
| `INTEGRATED` | 已进入 integration |
| `RETIRED` | 来源 branch/worktree、资源和临时现场均已退出 |
| `BLOCKED` | 明确外部条件阻塞，且已记录恢复条件 |

只有 `IMPLEMENTING` 才表示真正活跃执行。UI 历史卡片不构成运行证据；当前进程、agent tree、worktree、锁和
任务状态共同决定真实状态。

## 6. 资源与冲突治理

### 6.1 全局资源租约

所有高 CPU、内存、I/O、网络、数据库 writer、端口和真实运行由统筹分配唯一 owner 与时间窗口。领域经理
不得仅凭“当前看起来空闲”自行抢占。长进程自然运行期间，其他任务必须避开其文件、数据库、端口和资源边界。

每个资源申请至少说明：owner、进程类型、affinity/线程上限、输入输出路径、预计时长、终态证据和清理方式。

### 6.2 文件与 SSOT 锁

- 同一文件同一时刻只有一个 writer；
- 共享 Schema、配置、facade、README、路线图索引、用户批示文档和 integration 由统筹显式发锁；
- 只读审查不得在目标文件仍被写入时开始；
- 跨领域共享修改必须串行，不以 Git 自动合并能力代替所有权治理。

### 6.3 Git/worktree 规则

- 默认一个任务包对应一个 branch/worktree；
- branch 使用 `codex/` 前缀，base 必须为 full SHA；
- Worker 不得自行改 base、rebase 或把别的任务提交混入；
- integration 只由统筹写入；
- 合流后采用 archive-first 退休，先保留 source SHA/tag，再移除 worktree 和 branch；
- worktree 退休前必须检查 ignored 正式产物、缓存、进程 cwd、Git lock 和进行中操作；
- 项目根、integration、`data/`、`artifacts/` 和用户资料不得作为模糊递归删除目标。

## 7. 交付消息格式

### 7.1 领域经理 → 统筹：准入申请

```text
任务 / 目标：
依赖 / exact base：
branch / worktree：
exact 写白名单：
只读输入与禁止项：
资源需求：
失败语义与反例：
验收命令：
建议 Worker：
```

### 7.2 领域经理 → Worker：冻结任务包

除准入信息外，还必须写明任务文档路径、允许创建的临时目录、是否允许网络/真实数据、提交策略和停止条件。

### 7.3 Worker → 领域经理：交付报告

```text
source SHA / parent / branch / worktree：
exact changed paths：
实现语义：
验证结果：
真实依赖证据边界：
资源与临时现场终态：
剩余风险 / STOP：
```

### 7.4 领域经理 → 统筹：合流申请

必须附 source SHA、路径核对、验证摘要、审查结论、产物 retained 状态、资源释放和来源线退出条件。

## 8. 当前默认执行策略

1. 当前三个领域经理分别负责框架开发、投研和 GUI 开发；
2. 当前默认实现通道为本地 Luna Worker 池，现有 `Luna worker 1` 与 `Luna worker 2`；两者均可并行管理多个
   隔离 subagent，每个具体任务仍只能绑定一个 Worker 和一个实现 subagent；运行时 task id 与实时负载以
   Codex 任务列表和 ignored dispatch mapping 为准，不写入 Git 文档；
3. 只有用户或统筹明确指定时才改用外部 `cursor-agent`；未指定模型时使用 `auto`；
4. 领域经理在统筹冻结后直接与所选 Luna Worker 完成派发、初验、返工和交付；中央只管理控制面与异常恢复；
5. 不为提高表面并行度拆分共享文件或强耦合任务，也不设置脱离实际资源的固定并发槽数；
6. 不因 worker 类型改变 PIT、不可变发布、统一回放、OMS/风控/对账、人工准入和凭据安全 Gate；
7. 新 Worker 类型加入前，先由统筹补充身份、权限、资源、交付和退出合同。
