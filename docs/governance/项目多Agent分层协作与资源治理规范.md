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

本规范不建立新的调度平台、数据库、强制 ACK 协议或常驻服务。任务书和交付文档是业务协作主通道；session、
agent tree、branch/worktree、资源窗口和提交记录只承担通知、执行和现场核对职责。

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
任务经统筹冻结后，领域经理只需把任务书路径、task id 和 worktree 发给所选 Worker，然后等待交付文档；不需要
维护 ACK/mapping/status 状态机，也不要求 Worker 持续发送静态进度。领域经理仍须把共享资源申请、白名单扩大、
跨领域冲突和合流申请提交统筹。

### 2.4 实现 Worker

Worker 只执行已经冻结的具体任务，不决定业务路线或扩大架构。

当前默认使用由多个本地 Luna Worker session 组成的 Worker 池。除非用户明确指定其他方式：

- 领域经理在统筹冻结任务后，直接选择一个空闲或合适的 Luna Worker，并把任务书路径、task id、worktree 和
  资源级别发给该 Worker；完整合同只在任务书中维护，不在 session 消息中复制；
- Luna Worker 的顶层 session 只负责读取任务书、创建隔离 subagent 和转交任务；不需要建设 dispatcher 状态机；
- Luna Worker 收到每个具体任务后必须创建独立 subagent 执行，不能在顶层 session 直接混做多个实现；
- 每个 Luna Worker 可同时管理多个互相隔离的 subagent；项目不预设固定“四槽”或“每个 Worker 一次只能有
  一个任务”的规则。实际并行度由可用 Agent 容量、任务依赖、文件写集合和统筹分配的共享资源共同限制；
- 每个 `task_id` 在任一时刻只能绑定一个 Luna Worker、一个实现 subagent 和一个 worktree。未经明确 STOP、
  身份闭包和统筹重分配，不得把同一任务同时派给另一个 Luna Worker；
- 多个任务只有在依赖已满足、写路径互斥且资源窗口允许时才可并行；否则顺序执行；
- 顶层 turn 在创建 subagent 并把任务书路径交给它后即可结束并恢复 idle，不等待 subagent 完整结束；
- subagent 在分配的交付报告路径记录实现、验证、STOP、资源请求和剩余风险。完成后只需向领域经理发送
  `DELIVERY_READY <path>` 或等价短提示并退出，不长期保持 `active`。

#### 2.4.1 任务书与交付文档协议

任务合同不再依赖 session 间长消息、ACK 或 ignored JSON 状态。新任务统一使用以下文档位置：

| 领域 | 任务书 | Worker 交付 | 独立审查 |
|---|---|---|---|
| 框架 | `docs/framework/tasks/` | `docs/framework/deliveries/` | `docs/framework/reviews/` |
| 投研 | `docs/research/tasks/` | `docs/research/deliveries/` | `docs/research/reviews/` |
| GUI | `docs/gui/tasks/` | `docs/gui/deliveries/` | `docs/gui/reviews/` |
| 跨领域治理 | `docs/governance/tasks/` | `docs/governance/deliveries/` | `docs/governance/reviews/` |

文件名使用稳定 task id，例如 `M2-EVAL-R16_任务书.md`、`M2-EVAL-R16_交付报告.md` 和
`M2-EVAL-R16_独立初验报告.md`。任务书由领域经理拥有，交付报告由实现 Worker 拥有，审查报告由独立 reviewer
拥有；同一时刻不得交叉改写。已有 `docs/*/agent/` 历史文档和正在执行的任务保持原路径，不进行批量迁移；
新任务开始使用上述目录。

任务书至少包含：目标/非目标、exact base、branch/worktree、写白名单、只读输入、禁止项、合同和失败语义、
反例、资源等级、验证要求、交付报告路径和 STOP 条件。Worker 收到的 session 消息只需包含：

```text
TASK_READY <task_id>
taskbook=<repo-relative path>
worktree=<absolute path>
resource=STATIC_ONLY|RESOURCE_GRANTED
```

Worker 开始后可立即创建交付报告并标记 `IN_PROGRESS`，随后在同一文件更新 `RESOURCE_WAIT / STOP / DELIVERED`、
changed paths、验证结果、真实证据边界和残留。完成时发送 `DELIVERY_READY <path>`；领域经理读取文档验收，不要求
Worker 回传完整日志或维持额外状态心跳。

#### 2.4.2 轻量活性观察与异常处理

业务经理不负责强制调度 Worker，也不维护运行时状态机。需要判断任务是否仍在推进时，仅允许低频只读观察：

1. 分配的 Worker/subagent id 是否仍存在；
2. 批准的代码、测试或交付报告是否出现合理的 diff/mtime 变化；
3. 已授权共享资源是否仍被正确 owner 持有。

Agent 仍存在时，短期无文件变化不等于失活；禁止因此连续 resume、status-only、STOP、重派或创建第二实现者。
只有 Agent 明确退出/报错/STOP，或长时间不再存在且交付文档没有形成时，领域经理才把现场提交统筹裁定。

`artifacts/agent_dispatch/`、ACK、mapping/status 可由 Worker 自愿保留作诊断，但不是派发、身份或交付 Gate，
不要求修复历史缺字段，也不得因为这些可选文件不一致而中断已有唯一 Worker。唯一所有权优先由任务书、分配消息、
worktree 和 agent id 判断。发现真正的双写、两个实现者、白名单越界或共享资源冲突时，才立即停止并升级统筹。

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

领域经理先把冻结任务包写成任务书，再向选定 Worker 发送 task id、任务书路径和 worktree。Worker 必须：

- 核对 branch、HEAD、worktree 和白名单；
- 只修改批准路径；
- 发现合同矛盾、真实数据反例或依赖缺失时立即停止扩大并回报；
- 执行与风险相称的定向测试、Ruff、mypy、cold import 或真实探针；
- 不自行合流、rebase、修改 integration 或宣布项目 Gate 通过。

Luna Worker 收到任务后创建隔离 subagent，把任务书路径交给它，然后顶层 turn 即可恢复 idle。实际实现、
资源等待和交付文档都由对应隔离 subagent 承担；不要求额外 ACK 或 durable mapping。

任务冻结后的普通通信由领域经理通过任务书和交付报告完成；session 只传文档指针、资源批准或明确阻断。中央
只接收需要控制面裁决的事件和最终合流申请，不承担日常消息中继。若某 Luna Worker 繁忙，可将新的、尚未派发
任务分配给另一 Luna Worker；已派发任务不得仅为提高吞吐而迁移或复制。

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

这些状态是文档里的里程碑，不是要求 Worker 高频更新的 heartbeat：`PROPOSED/FROZEN` 由任务书记录，
`IMPLEMENTING/SELF_VERIFIED/BLOCKED` 由交付报告记录，其余由领域经理或统筹在验收、合流时更新。判断实时活性
仍以 agent id 是否存在、批准路径是否有变化、进程和资源 owner 为低频旁证；短期无变化不自动触发 STOP。

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

## 7. 任务与交付文档格式

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

### 7.2 领域经理 → Worker：任务书

任务书存放于 `docs/<domain>/tasks/`，除准入信息外，还必须写明交付报告路径、允许创建的临时目录、是否允许
网络/真实数据、提交策略和停止条件。派发消息只发送 task id、任务书路径、worktree 和资源等级。

### 7.3 Worker → 领域经理：交付文档

交付报告存放于 `docs/<domain>/deliveries/`，由 Worker 唯一写入。最低结构为：

```text
source SHA / parent / branch / worktree：
exact changed paths：
实现语义：
验证结果：
真实依赖证据边界：
资源与临时现场终态：
剩余风险 / STOP：
```

Worker 可以先创建报告并写 `IN_PROGRESS`，需要资源时更新为 `RESOURCE_WAIT`，完成后更新为 `DELIVERED`；不要求
另行维护 status.json。独立 reviewer 的报告写入 `docs/<domain>/reviews/`，不得修改实现交付报告。

### 7.4 领域经理 → 统筹：合流申请

必须附 source SHA、路径核对、验证摘要、审查结论、产物 retained 状态、资源释放和来源线退出条件。

## 8. 当前默认执行策略

1. 当前三个领域经理分别负责框架开发、投研和 GUI 开发；
2. 当前默认实现通道为本地 Luna Worker 池；每个 Worker 均可并行管理多个隔离 subagent，每个具体任务仍只能
   绑定一个 Worker 和一个实现 subagent；任务身份和合同以 Git 中的任务书为准，实时活性只参考 Codex agent id
   与批准路径变化，不维护强制 dispatch registry；
3. 只有用户或统筹明确指定时才改用外部 `cursor-agent`；未指定模型时使用 `auto`；
4. 领域经理在统筹冻结后通过任务书下发、通过交付/审查文档收件；中央只管理控制面、资源、合流和真正的双写
   或所有权异常，不介入普通 Worker 心跳；
5. 不为提高表面并行度拆分共享文件或强耦合任务，也不设置脱离实际资源的固定并发槽数；
6. 不因 worker 类型改变 PIT、不可变发布、统一回放、OMS/风控/对账、人工准入和凭据安全 Gate；
7. 新 Worker 类型加入前，先由统筹补充身份、权限、资源、交付和退出合同。
