# M4 P8 RUN-0D0 R1：Formal Daily Inputs 与只读 Runner 交付报告

日期：2026-08-14

## 结论

UA-M4-004 的工程部分已完成。正式执行面现在可以从版本化 source selector 派生唯一的
`PAPER_CANDIDATE` 研究产物与当日开盘事实包，构造 CLI 所需 target、market、account 和 planner config；
公开 daily runner 只接受 `inspect`、`plan`，没有 approve、submit、cancel 或 reconcile 入口。

本轮没有创建或伪造首个 `PAPER_CANDIDATE`，没有采集真实开盘数据，没有注册任务，也没有启动 PAPER。
策略会话仍负责候选，数据流程仍负责 clean opening facts；真实启动继续由 UA-M4-002 控制。

## 变更

- 新增 `quant.execution.paper_formal_daily`：
  - strict source selector loader；
  - lightweight research run 全树与 run identity 复验；
  - `PAPER_CANDIDATE` target loader，并将完整候选域补齐为显式零权重；
  - opening instrument/price/limit/suspension/calendar receipt publisher 与 loader；
  - formal broker account、policy 和 service composition 组合；
  - 仅 `inspect` / `plan` 的 runner。
- 增加 lazy package exports 与 source 配置示例。
- 增加 focused tests，覆盖 candidate 正向、缺失候选零权重、`RESEARCH_ONLY` 拒绝、opening bundle
  重放/篡改和 dispatch action 前置拒绝。

## 正常开发检查

- focused pytest：`4 passed`；
- Ruff：生产模块、package export、focused test 全绿；
- mypy：两个生产文件全绿；
- lazy cold import：`FORMAL_DAILY_LAZY_IMPORT_PASS`。

另执行既有 execution CLI 邻接时得到 `13 passed, 1 failed`。唯一失败位于未修改的既有 cancel 二次恢复节点，
表现为 `LOCAL_RECOVERY_BLOCKED`；本轮未修改 CLI/reconcile/store，未将该结果记为本功能通过证据，也未越界修补。

## 尚未关闭

- 首个真实 `PAPER_CANDIDATE` 的 run id 尚未产生；
- 当日 clean opening facts 尚未发布；
- source selector 尚未从 example 物化为正式版本；
- UA-M4-002 尚未授权真实启动、计划任务注册和 28 日 soak；
- 本轮是主 Agent 暂停外部 Agent 期间的串行开发，不是外部独立初验或最终 Gate。
