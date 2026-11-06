# 结构整理报告（2026-11-06）

分支：`codex/x1-structure-20261106`。Worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\x1-worktree-20261106`。基于当前主线 `5831562d`；不合并、不推送。

## 验收结论

X1 分支验收通过；主线 R8 仍须按原 600 秒门槛另验。

## 文档与配置

- 搬迁 52 份文档；保留 8 个兼容入口，避免现有任务、自动化和配置引用失效。
- 旧清单原文与过程完整保存在 archive/worklists 的执行记录；清单入口仅保留逐项状态。
- 11 份大文档拆为 38 份分卷；保留原入口、原章节导航，并逐份验证分卷拼接等于原文。
- 九月配置归档 57 份，逐个 Git blob 与原主线完全相同；保留 60 份被代码、脚本、测试、legacy 或其他配置引用的候选。注册表核对 4032 条非空 config_path。

代表路径：`docs/data/REALTIME_DATA.md`、`docs/reviews/项目审查_20261101.md`、`docs/worklists/工作清单_20261102.md`、`docs/research/surveys/`、`configs/archive/2026-09/`。

[结构图与完整 CLI 分组](STRUCTURE.md)；[数据索引](DATA.md)；[完整搬迁及保留清单](../artifacts/x1/moves.json)。

## 代码与跳过项

检查 861 个 src 模块，保守闭包触达 683 个模块；根包含统一 CLI 的全部委派项和 run_*.ps1 的模块入口，包含延迟导入字面量和 TYPE_CHECKING 引用。

- m3 冻结代码、data/m3_* 与活跃 formal/store/session_barrier/contracts 均保留。现有 legacy shim 沿用主线，不重复迁移。
- 未从冻结模块或动态装载关系中推断死代码；无法充分证明无用的模块全部跳过。因此本轮新迁移代码 0、迁移测试 0、删除测试 0；默认测试集合保持完整。
- 不移动 paper、nightly 及其引用，不改计划脚本、策略门槛、成本或账户。
- 完整测试揭示两个基线可复现问题：start 日期替换兼容 CRLF；doctor 的测试发布时刻固定在夹具 CLOCK 之前。仅作此两项最小修正，不放松将来产物检查。

[逐模块依赖路径](../artifacts/x1/reachability.json)。

## 数量对照

| 指标 | 整理前 | 整理后 |
|---|---:|---:|
| src_python | 861 | 861 |
| legacy_python | 104 | 104 |
| default_tests | 669 | 669 |
| research_configs_top | 229 | 172 |
| docs_top | 33 | 20 |
| research_docs_top | 32 | 4 |

当前 src 总行数 224201；本轮没有迁移实现文件，唯一源代码行改动是 CRLF 兼容，行数不变。

## 链接检查

全仓包含历史归档：1670 份 Markdown，检查 3925 条内部路径/章节引用；源文件断链 0、失效锚点 0、越界路径 0。

另列 774 条 worktree 未提供的数据/运行产物引用，不将其当作已有证据。历史缺失材料保留名称、原路径及缺失说明；另一个旧路线图锚点明确标注已失效并指回现有路线图，没有伪造目标文件。

命令：`python scripts/check_internal_links.py --output artifacts/x1/links_final.json`。结果见[回执](../artifacts/x1/links_final.json)，历史修复明细见[记录](../artifacts/x1/link_repairs.json)。

## 测试与证据

- 37 项针对配置搜索/换行与 doctor 夹具的测试通过（31.16s）；[JUnit](../artifacts/x1/targeted.xml)。
- 首轮完整测试：12 workers，固定 900s，904.25s 超时、exit=124；收集 7386 项，未生成完整 JUnit，通过/跳过/失败总数未知。即时失败保留，包含误归档配置（已恢复）及上述两个基线问题。
- 第二轮 worksteal 在包含准备的 900s 总预算下仍超时，结果保留，未当作通过。
- 最终完整复验：全量 `pytest -m "not slow"`，plain assertions、无优化、12 workers；按历史计时优先分发长用例，仅改变调度顺序。独立源码快照、断言反例控制、worker 及 JUnit 精确集合核对，固定 900s（本次连准备阶段也在预算内）。
- 复验结果：complete=True，exit=0，897.34s；passed=7302，skipped=84，failed=0，errors=0。
- 与前轮逐 nodeid 的 Counter 完全相同，7386 项无删除/排除；最终源码、测试与配置 2298 个文件逐字节等于实际测试快照。
- [最终完整 JUnit](../artifacts/tests/20261106T132854_134404/tests.xml)。历史计时只用于并行顺序，没有更改测试或主线默认测试策略。

[完整复验回执](../artifacts/x1/final_fast_receipt.json)；[机器核对](../artifacts/x1/verification.json)。本分支 900s 仅适用于 X1，不改主线 600s 源码或生产 latest。

## 提交与旧 worktree

- `907a7236 fix(tests): keep Windows newlines and publication fixtures deterministic`
- `bdbd44fe chore(configs): archive unreferenced September experiments from current main`

本报告所在的文档主题提交可由 `git log 5831562d..HEAD` 查询，避免报告自引用提交哈希。

按用户 11-06 授权，旧 cursor-agent 目录已移除；旧分支 `cleanup/structure-20261101` 和 `64efc4f8` 保留。18 份本地日志/产物共 99953 字节已备份并逐文件 SHA 核对，见[备份清单](../artifacts/x1/old_cursor_backup/manifest.json)。关闭的只有已核实旧目录的 cursor-agent/终端/监听残留，没有结束 Python 或生产任务。

## 保留边界

主工作区其他会话的全部未提交改动保留；不合并、不推送、不重跑业务流水线、不改正式账户或 market raw。主线当前快测与本分支验收各按自己的实际回执，不互相冒用。
