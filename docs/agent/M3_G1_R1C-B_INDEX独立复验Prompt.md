# M3 G1 R1C-B INDEX 独立复验 Prompt

角色：全新外部独立复验 Agent（代码和数据只读）  
模型：`cursor-grok-4.5-high`（非 fast）  
前置：INDEX 写入 Agent 已完全退出

## 任务边界

在 Windows 原生启动 Cursor Agent，但所有项目命令必须在 WSL Miniforge `base` 执行。完整阅读 `AGENTS.md`、
R1C 任务单、INDEX 授权资源清单、INDEX 运行 Prompt 和交付报告。

生产代码、测试、配置、token、`data/**` 全部只读。唯一允许写入：

- `docs/agent/M3_G1_R1C-B_INDEX独立复验报告.md`

不得运行任何联网命令，不得重新调用 `index`，不得调用 HISTORY/REFERENCE/PREPARE/PUBLISH/run-all，不得删除或
修复数据，不跑全量 pytest。

## 必验项

1. 用一个新进程运行零网络 `status`，验证 `completed_stages` 精确为 `[INDEX]`。
2. 验证 INDEX 计划与成功 receipt 的身份闭包、数量和唯一性精确为 127；不能只相信交付报告。
3. 通过已验收的 inspect/receipt/raw 合同验证 raw 与 journal 一致、无缺口、无额外 request，且可导出真实历史
   成分并集 `S` 及后续计划数。不得任意遍历或直接消费 `data/legacy/`。
4. 验证没有任何 HISTORY、REFERENCE、PREPARE、candidate、release 或 PUBLISH 完成证据。
5. 做只读凭据泄露扫描，但只能报告命中数量和相对文件，不得输出疑似 secret 的值或上下文；token 配置本身不得
   读取。
6. 补充至少一个实现者未使用的对抗性核对，例如 receipt 重复身份、缺月、超范围月、stage prefix 与 journal
   不一致；只能只读验证，不能篡改真实证据。可使用临时目录构造最小副本，但不得调用网络。

## 通过条件与报告

只有所有必验项都有独立证据且无高优先级问题，才能标记“独立复验通过，可交主 Agent 终验”。否则明确不通过，
写清现象、根因、不变量、最小复现和返工通过条件。

报告写入 `docs/agent/M3_G1_R1C-B_INDEX独立复验报告.md`。不要宣称 R1C-B、G1、M3 或 Gate 完成。完成后立即返回。
