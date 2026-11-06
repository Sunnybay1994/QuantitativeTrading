# 接手

先读根目录 [AGENTS.md](../AGENTS.md)，再读 [OPERATIONS.md](OPERATIONS.md) 和路线图 §1.0.3 / §1.0.4 / §1.2。

1. `git status` 与最近提交，保留他人未提交改动。
2. `python -m quant status` 与计划任务；已有挖掘/日更在跑就不要再开一份。
3. 按路线图做下一件未完成的事，不要重复已完成的 R 任务；[优化工作清单_20261009](archive/worklists/优化工作清单_20261009.md) 四周总验收已于 2026-10-13 闭合，勿重做其已验收项。
4. 新实验用版本化 config + 新 run 目录。
5. 数字只来自机器 report 和排行榜。

环境、调度、恢复、证据位置的细节都在 [OPERATIONS.md](OPERATIONS.md)。架构在 [ARCHITECTURE.md](ARCHITECTURE.md)。判定在 [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md)。

## 文档维护约定

README 面向用户，只保留项目介绍、主要功能、常用操作和详细指南入口。通知接入放在 NOTIFICATIONS.md，看板口径放在 DASHBOARD.md，调度与恢复放在 OPERATIONS.md；研究规则、架构和进度分别维护在现有协议、架构文档与路线图。实验结果由流水线报告保存，不把实现记录和阶段性研究结论不断追加到 README。AGENTS.md 保持精简，仅承载必要工作规则。
