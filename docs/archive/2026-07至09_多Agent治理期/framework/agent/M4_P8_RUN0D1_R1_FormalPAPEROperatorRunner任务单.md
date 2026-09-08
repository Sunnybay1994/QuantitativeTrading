# M4 P8 RUN-0D1 R1：Formal PAPER Operator Runner 任务单

日期：2026-08-15  
状态：R3 返工、外部独立复验与主 Agent Windows 工程验收均已完成；未启动 PAPER/soak  
实现模型：`cursor-grok-4.6-high`

## 1. 目标

现有 `paper_formal_daily.py` 已能从正式 source selector、`PAPER_CANDIDATE`、opening facts、
broker snapshot 和 formal service composition 构造 `CliDependencies`，但公开 runner 只接受
`inspect`、`plan`。底层 `quant.execution.cli` 已实现带 challenge 的 `approve`、`paper-submit`、
`cancel` 以及 `reconcile`。

本包只补一个 PAPER-only operator wrapper，使 2026-09 首个候选出现后，人工可以在批准窗口内沿用同一
fresh formal 输入执行完整 CLI 动作。不得自动确认、自动重试、连接真实券商、注册系统任务或启动 soak。

## 2. 公共接口

在 `quant.execution.paper_formal_daily` 新增并安全导出：

```python
def run_formal_paper_daily_operator(
    *,
    action: Literal[
        "inspect", "plan", "approve", "paper-submit", "cancel", "reconcile"
    ],
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    composition: VerifiedFormalPaperServiceComposition,
    session_date: date,
    now: datetime,
    confirm_sha256: str | None = None,
    command_id: str | None = None,
) -> int: ...
```

既有 `run_formal_paper_daily_read_only` 保持兼容，仍只允许 `inspect/plan`。

## 3. 冻结行为

1. 每次调用只通过现有 `build_formal_paper_daily_dependencies` 构造一次 fresh PAPER capability 链；
   不复制 runtime/policy/store/gateway/service 验真。
2. 参数矩阵：
   - `inspect/plan/reconcile`：禁止 `confirm_sha256` 和 `command_id`；
   - `approve/paper-submit`：禁止 `command_id`，允许 `confirm_sha256=None` 先打印 challenge，也允许传入
     用户刚确认的 exact digest；
   - `cancel`：要求非空 `command_id`，允许同样的两步 challenge，禁止其他参数组合。
3. wrapper 只拼接 canonical argv 并调用现有 `quant.execution.cli.main`；CLI 的 exit code、stdout/stderr、
   confirmation 与幂等语义保持 SSOT，不在 wrapper 复制。
4. 无 confirm 的确认型动作必须只输出 challenge、返回既有 exit `20`，不得写订单/发送 gateway。
5. 有 confirm 仍只能消费 exact formal PAPER composition 和 deterministic PAPER gateway；任何 LIVE、
   未知 selector、输入 identity 漂移或 fresh 失败在到达 CLI action 前 fail closed。
6. `UNKNOWN` 不自动重发；wrapper 不循环、不等待、不跨日补发、不把 `auto_trade` 改为 true。
7. 稳定异常继续使用 `FormalPaperDailyRunnerError`，异常 cause/context 清空且不泄露路径、账号或输入内容。

## 4. 文件白名单

- `src/quant/execution/paper_formal_daily.py`
- `src/quant/execution/__init__.py`
- `tests/unit/test_paper_formal_daily.py`
- `tests/unit/test_execution_cli.py`（只有确需补 operator 邻接时）
- `docs/framework/agent/M4_P8_RUN0D1_R1_FormalPAPEROperatorRunner交付报告.md`

不得修改 CLI/store/gateway/service/policy/runtime/config Schema，不得注册 Task Scheduler，不得创建真实
source selector、候选、opening facts、订单、成交或 soak 证据。

## 5. 必测反例

- `inspect/plan/reconcile` 携 confirm 或 command id，在 dependencies/CLI 调用前拒绝。
- `approve/paper-submit` 携 command id 前置拒绝；首次无 confirm 返回 20 且零 staged/sent command。
- `cancel` 缺 command id 前置拒绝。
- 正确 challenge digest 的 approve 只 stage；paper-submit 只发送已 stage 的 PAPER command；重复调用保持
  既有幂等结果，不产生第二份命令。
- 错误 confirm 不 stage/不发送；UNKNOWN 不自动重发。
- hostile fresh/dependency exception 被脱敏且零 CLI 调用。
- 既有 read-only runner 仍拒绝所有 dispatch/reconcile action。

## 6. 开发检查与边界

只运行 formal daily 与 execution CLI 定向测试、Ruff、mypy、cold import；Windows 结果属于工程反馈。
本包不依赖真实候选或真实开盘数据，也不启动 PAPER。完成后仍需独立外部初验和主 Agent 验收；通过仅表示
operator wrapper 可用，UA-M4-002 的真实 28 日计时仍要等首个正式输入。
