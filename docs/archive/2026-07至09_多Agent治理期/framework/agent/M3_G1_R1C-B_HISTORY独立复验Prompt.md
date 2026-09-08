# M3 G1 R1C-B HISTORY 独立复验 Prompt

角色：全新外部独立复验 Agent（代码和数据只读）  
模型：`--model auto`（不得指定或推断具体 Grok 型号）
前置：HISTORY 写入 Agent 已完全退出并提交交付报告

## 任务边界

工作目录：`/home/mabw/win/Cursor/quant`（WSL：`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`）。所有项目命令在 WSL Miniforge `base`。

完整阅读：`AGENTS.md`、`docs/framework/agent/M3_G1_R1C分阶段CLI与真实全量运行外部闭环任务单.md`、
`docs/framework/agent/M3_G1_R1C-B真实运行授权与资源清单.md`、`docs/framework/agent/M3_G1_R1C-B_HISTORY外部运行Prompt.md`、
`docs/framework/agent/M3_G1_R1C-B_HISTORY交付报告.md`。

生产代码、测试、配置、token、`data/**` 全部只读。唯一允许写入：

- `docs/framework/agent/M3_G1_R1C-B_HISTORY独立复验报告.md`

不得运行任何联网命令，不得重新调用 `history`/`index`，不得调用 REFERENCE/PREPARE/PUBLISH/run-all，不得删除或
修复数据，不跑全量 pytest。

## 必验项

1. 新进程零网络 `status`：`completed_stages` 须包含 `INDEX` 与 `HISTORY`（精确集合以合同为准，通常为
   `[INDEX, HISTORY]`）；`history_symbols=637`；`history_requests` 与 plan 闭包一致。
2. 核对 HISTORY plan/request/receipt/raw 身份集合：计划数 **2679**；端点仅授权六类；无额外端点；无缺口/重复身份。
3. INDEX 的 127 `index_weight` evidence 仍完整可恢复，未被 HISTORY 破坏。
4. 验证无 REFERENCE/PREPARE/candidate/release/PUBLISH 完成证据；无 BaoStock 写阶段。
5. 只读凭据泄露扫描：只报告命中数量与相对路径，不输出疑似 secret。
6. 至少一个实现者未用的对抗核对（只读）：例如错误 stage prefix、receipt/raw 集合不等、超计划 request、空响应被放行等。

## 通过条件与报告

全部必验项有独立证据且无高优先级问题，才标记“独立复验通过，可交主 Agent 终验”。否则明确不通过。

不要宣称 R1C-B、G1、M3 或 Gate 完成。完成后立即返回。
