# 通用 AI 软件工程操作系统

本目录定义一套可复制到任何软件工程项目的 AI 协作系统。它关注的是“如何工作”：目标、假设、范围、
验证、审查、交接、安全和人的最终判断；具体项目的架构、命令、领域契约与部署约束应放在项目级
`AGENTS.md`、`CONTRIBUTING.md` 或其他权威文档中。

## 使用顺序

1. 阅读本文件、[`philosophy.md`](philosophy.md) 和
   [`coding_rules.md`](coding_rules.md)。
2. 阅读项目级规则与任务直接相关的代码、测试、配置和文档。更具体、更安全的项目规则优先。
3. 中大型任务使用 [`task_template.md`](task_template.md) 冻结目标、范围和验收标准。
4. 完成实现后使用 [`review_checklist.md`](review_checklist.md) 做简化、范围和证据审查。
5. 多 Agent 或高风险任务分别使用
   [`workflows/multi_agent_delivery.md`](workflows/multi_agent_delivery.md) 与
   [`workflows/high_risk_change.md`](workflows/high_risk_change.md)。
6. 人类定期使用 [`human_capability.md`](human_capability.md) 检查接管与判断能力是否退化。

## 文件职责

- `philosophy.md`：为什么这样工作，以及人、Agent、工具和治理之间的关系。
- `coding_rules.md`：所有 Coding Agent 应遵循的通用执行规则和完成定义。
- `task_template.md`：任务书、交付报告、独立审查和最终验收模板。
- `review_checklist.md`：人工或主 Agent 接受改动前的检查清单。
- `human_capability.md`：防止长期使用 Agent 导致生成、调试和接管能力退化。
- `workflows/multi_agent_delivery.md`：何时使用多 Agent、如何分工、返工和合流。
- `workflows/high_risk_change.md`：不可逆、生产、数据、安全和外部状态变更的增强流程。

## 规则边界

- 本目录不复制项目的 API、Schema、命令、依赖版本或业务规则，避免形成第二事实来源。
- 静态指令不能证明正确性。测试、编译、类型检查、日志、浏览器、基准、真实依赖探针、权限边界和
  可回滚状态共同构成控制系统。
- 风险越低，流程越轻；风险越高，契约、证据、独立审查和回滚要求越完整。
- 任何 Agent 的自我报告都只是待核验证据，不是最终事实。
