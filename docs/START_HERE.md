# 接手

先读根目录 [AGENTS.md](../AGENTS.md) 和[当前审查与执行清单](worklists/review-and-worklist-20261115.md)，再按需读 [OPERATIONS.md](OPERATIONS.md) 与路线图 §1.0.3 / §1.0.4 / §1.2。新审查按本机事实选择性采纳；[11-09清单](worklists/工作清单_20261109.md)保留既有交付与自然观测出处。

1. `git status` 与最近提交，保留他人未提交改动。
2. `python -m quant status` 与计划任务；已有挖掘/日更在跑就不要再开一份。
3. 按当前清单的优先级推进，不另开审查建议中的任务。旧清单仅作出处；11-02 清单已关闭，其月底订单观测并入本轮 K2。清单以外建议写入路线图 §5，等待用户裁定。
4. 新实验用版本化 config + 新 run 目录。
5. 数字只来自机器 report 和排行榜。

环境、调度、恢复、证据位置的细节都在 [OPERATIONS.md](OPERATIONS.md)。包、CLI 和运行目录先看 [STRUCTURE.md](STRUCTURE.md)，依赖边界看 [ARCHITECTURE.md](ARCHITECTURE.md)，研究判定看 [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md)。各类资料入口见[文档目录](README.md)。

## 文档维护约定

README 面向用户，只保留项目介绍、主要功能、常用操作和详细指南入口。通知接入放在[通知说明](operations/NOTIFICATIONS.md)，看板口径放在[DASHBOARD.md](DASHBOARD.md)，调度与恢复放在[OPERATIONS.md](OPERATIONS.md)；研究规则、架构和进度分别维护在现有协议、架构文档与路线图。实验结果由流水线报告保存，不把实现记录和阶段性研究结论不断追加到 README。AGENTS.md 保持精简，仅承载必要工作规则。
