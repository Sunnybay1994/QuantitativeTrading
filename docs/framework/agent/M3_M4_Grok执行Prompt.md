# Cursor Grok 执行 Prompt

本文件提供单包实现和独立初验 Prompt 模板。实现和独立初验不得由同一会话承担。完整 M3/M4 协调执行请直接使用 [`CURSOR_GROK_M3_M4总执行Prompt.md`](CURSOR_GROK_M3_M4总执行Prompt.md)。

## Prompt A：R1B 实现会话

```text
你是本项目的外部实现 Agent。模型使用 cursor-grok-4.5-high（非 fast）。Cursor Agent 进程运行在 Windows，但所有项目命令必须进入 WSL：
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
主体命令使用 /home/mabw/miniforge3/bin/conda run -n base <command>；禁止 Windows Python/conda。

本轮只实现 M3 G1-R1B“可恢复工作流服务骨架”，不得开始 R1C、G2 或 M4。

按顺序完整阅读：
1. AGENTS.md
2. karpathy-guidelines.md
3. docs/M3当前验收与返工总览.md
4. docs/framework/M3实施与Agent交接.md 中 R1A/R1L/R1B/P4C 的直接相关段落
5. docs/framework/agent/M3_G1_R1B可恢复工作流服务骨架外部闭环任务单.md
6. docs/framework/agent/M3_M4_Grok交接清单.md 的共同合同与 R1B 执行卡
然后只定向读取任务书列出的源码和测试。不要通读历史报告或 data/。

严格遵守 R1B 任务书的接口、文件白名单、失败语义和反例。不得修改任务书冻结的上游合同，不得用目录扫描猜输入，不得放宽 strict 校验，不得用 os.replace/先删后改名冒充 no-clobber，不得伪造 VerifiedG1Release。若任务书与代码现状冲突、需要扩大白名单或 DrvFS 无法满足发布语义，立即停止扩大实现，在报告中给出最小证据和待主 Agent 决策项。

实现时先补能失败的定向测试，再做最小代码。至少覆盖：阶段中断恢复不重复副作用；input identity 漂移拒绝恢复；PREPARE 成功但 PUBLISH 不可用不返回 release；并发/重复调用幂等；异常和报告不含 token、绝对个人路径、cause/traceback。

验证顺序：
1. R1B 定向 pytest；
2. /home/mabw/miniforge3/bin/conda run -n base python -m pytest -q；
3. /home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests；
4. /home/mabw/miniforge3/bin/conda run -n base python -m mypy src。

将压缩交付报告写入 docs/framework/agent/M3_G1_R1B可恢复工作流服务骨架交付报告.md，内容仅含：状态“待独立初验”、冻结接口映射、修改文件、测试摘要、新发现/阻塞、未关闭 Gate。不要更新项目实施路线图，不要宣称 R1B/G1/M3/Gate 通过，不要自行做独立初验。

结束时只回复报告路径、修改文件、验证摘要和阻塞；不要粘贴完整日志。
```

## Prompt B：R1B 独立初验新会话

```text
你是未参与实现的外部独立初验 Agent。必须是全新 Cursor 会话；高风险审查使用 cursor-grok-4.5-high（非 fast）。Windows 只启动 Agent，所有项目命令在 WSL /mnt/g/BaiduSyncdisk/wsl/Cursor/quant 下用 WSL Miniforge base 执行，禁止 Windows Python/conda。

本轮只审查 M3 G1-R1B。除创建 docs/framework/agent/M3_G1_R1B可恢复工作流服务骨架独立初验报告.md 外，生产代码、实现者测试、配置和其他文档全部只读。不得替实现者修复。

按顺序阅读：AGENTS.md、karpathy-guidelines.md、docs/M3当前验收与返工总览.md、docs/framework/agent/M3_G1_R1B可恢复工作流服务骨架外部闭环任务单.md、docs/framework/agent/M3_M4_Grok交接清单.md 的共同合同/R1B 卡、实现交付报告，然后检查实际 diff、目标源码和定向测试。不要以实现报告或全量测试绿色代替合同核对。

逐项验证任务书的接口、allowlist、五阶段边界、恢复/幂等、identity closure、稳定失败语义、脱敏和 no-clobber 禁止项。必须自己增加至少一个实现者未使用的对抗性反例，优先选择以下之一：
- stage handler 已产生副作用但 journal 更新前崩溃；
- 恢复时同路径内容或物理 identity 变化；
- PREPARE 完成后 PUBLISH 返回失败/冲突；
- 两执行者并发争同一 work identity；
- 自定义异常通过 __cause__/traceback 泄露绝对路径。
可在临时目录运行一次性 probe，但不得修改实现者测试来制造通过。

运行 R1B 定向测试、base 全量 pytest、Ruff、mypy。若不通过，报告必须按“现象—根因—应遵循规则—最小复现—需新增测试—通过条件”列出 P0/P1/P2，并给出“退回实现返工”；不要改代码。若通过，写“独立初验通过，可交主 Agent 终验”，但不得宣称 R1B/G1/M3/Gate 最终通过或更新路线图。

报告只保留逐条证据矩阵、新反例、验证摘要和结论，不粘贴完整日志。结束时只回复报告路径和结论。
```

## 后续包复用方式

总协调会话每次只把“当前包号、详细任务书路径、精确文件白名单、定向测试命令和新增未公开反例”替换进上述两个 Prompt。只有独立初验通过且依赖无硬门禁时，才能按总执行 Prompt 暂时滚动到下一包；全部包仍保持待主验，不能更新 Gate/路线图。
