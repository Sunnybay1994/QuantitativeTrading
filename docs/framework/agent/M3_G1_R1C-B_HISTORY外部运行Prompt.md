# M3 G1 R1C-B HISTORY 外部运行 Prompt

角色：外部真实运行 Agent（唯一数据写者）  
模型：`cursor-grok-4.5-high`（非 fast）  
状态：**用户已于 2026-07-17 明确授权 HISTORY**；禁止启动 REFERENCE/PREPARE/PUBLISH/run-all

## 任务

工作目录：`/home/mabw/win/Cursor/quant`（WSL：`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`）。所有项目命令必须进入 WSL：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
/home/mabw/miniforge3/bin/conda run -n base <command>
```

先完整阅读：

1. `AGENTS.md`
2. `docs/framework/agent/M3_G1_R1C分阶段CLI与真实全量运行外部闭环任务单.md`（§8 真实全量运行协议）
3. `docs/framework/agent/M3_G1_R1C-B真实运行授权与资源清单.md`
4. `docs/framework/agent/M3_G1_R1C-B_INDEX身份合同返工独立复验报告.md`（确认 INDEX 可恢复、S=637）
5. 本 Prompt

用户授权边界：

> 最多 **2679** 个计划 Tushare 请求；端点仅 `daily/adj_factor/stk_limit/dividend/index_daily/suspend_d`；
> 基于已冻结 `S=637`；可崩溃恢复；完成后新进程 `status` 并停止；不启动 REFERENCE/PREPARE/PUBLISH。

重试 attempt 只能遵循已冻结配置，不能修改限频、重试、日期、端点、配置或 token。不得把 attempt 偷换成计划 request。

## 允许写入

- `data/raw/m3_g1/**`
- `data/run_state/m3_g1/**`
- `docs/framework/agent/M3_G1_R1C-B_HISTORY交付报告.md`

除以上路径外全部只读。禁止修改生产代码、测试、配置、token、README、路线图和其他报告；禁止初始化 Git。

## 执行协议

1. 确认没有另一 R1C 写阶段进程；不得删除或绕过 writer lock。
2. 先运行零网络 `status`。仅当 `completed_stages` 精确为 `[INDEX]`（或已存在可恢复的 HISTORY journal/部分 progress）且
   `history_symbols=637`、`history_requests=2679` 时继续；出现 REFERENCE/PREPARE/PUBLISH 完成证据或无法解释的状态立即停止。
3. 只运行：

   ```bash
   python -m quant.research.m3.run_g1 \
     --config configs/research/m3_qlib_example.toml history
   ```

4. 允许长运行与断点重启：若稳定的网络/限频瞬态失败，可在不删除 evidence、不改配置的前提下恢复同一 HISTORY
   阶段；权限、永久端点、质量或合同失败立即停止。不得把空响应政策放宽。
5. HISTORY 命令退出后，用一个**新进程**再运行 `status`，然后停止。不得调用 `reference`、`prepare`、`publish`、
   `run-all`，也不得重新调用 `index`。
6. 不跑 pytest、Ruff、mypy；不读取或打印 token；不在报告中复制 request 参数全集、raw rows、绝对路径或 SDK
   异常文本。

## 报告

写入 `docs/framework/agent/M3_G1_R1C-B_HISTORY交付报告.md`，只保留压缩证据：

- 起止 UTC、退出码、稳定 outcome/code；
- 完成阶段、计划/完成 request 数（应对齐 2679）；
- `history_symbols` 仍为 637；新进程 `status` 的完整脱敏 JSON 字段；
- 本地 raw/journal 汇总（相对逻辑范围或汇总字节/行数，不写绝对路径）；
- 明确证明未启动 REFERENCE/PREPARE/PUBLISH；
- 若失败，记录可恢复程度与稳定失败 code，不声称通过。

不要宣称 R1C-B、G1、M3 或任何 Gate 完成。完成报告后立即返回，不继续规划其他任务。
