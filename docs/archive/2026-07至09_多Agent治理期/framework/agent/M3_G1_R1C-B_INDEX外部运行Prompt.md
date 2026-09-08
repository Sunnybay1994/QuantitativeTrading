# M3 G1 R1C-B INDEX 外部运行 Prompt

角色：外部真实运行 Agent（唯一数据写者）  
模型：`--model auto`（不得指定或推断具体 Grok 型号）
状态：用户已明确授权 INDEX；禁止启动 HISTORY

## 任务

在 Windows 原生启动 Cursor Agent，但所有项目命令必须进入 WSL，并使用：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
/home/mabw/miniforge3/bin/conda run -n base <command>
```

先完整阅读：

1. `AGENTS.md`
2. `docs/framework/agent/M3_G1_R1C分阶段CLI与真实全量运行外部闭环任务单.md`
3. `docs/framework/agent/M3_G1_R1C-B真实运行授权与资源清单.md`

用户授权边界是：最多 127 个 Tushare `index_weight` **计划请求**，INDEX 完成后停止并报告，绝不启动
HISTORY。重试 attempt 只能遵循已冻结配置，不能修改限频、重试、日期、端点、配置或 token。

## 允许写入

- `data/raw/m3_g1/**`
- `data/run_state/m3_g1/**`
- `docs/framework/agent/M3_G1_R1C-B_INDEX交付报告.md`

除以上路径外全部只读。禁止修改生产代码、测试、配置、token、README、路线图和其他报告；禁止初始化 Git。

## 执行协议

1. 确认没有另一 R1C 写阶段进程；不得删除或绕过 writer lock。
2. 先运行零网络 `status`。仅当状态为 fresh（`completed_stages=[]`，计划 `index_requests=127`）或已存在可恢复
   的 INDEX journal 时继续；出现 HISTORY/REFERENCE/PREPARE/PUBLISH 或无法解释的状态立即停止。
3. 只运行：

   ```bash
   python -m quant.research.m3.run_g1 \
     --config configs/research/m3_qlib_example.toml index
   ```

4. 若稳定的网络/限频瞬态失败，可在不删除 evidence、不改配置的前提下恢复同一 INDEX 阶段；权限、永久端点、
   质量或合同失败立即停止。不得把空响应政策放宽。
5. INDEX 命令退出后，用一个新进程再运行 `status`，然后停止。不得调用 `history`、`reference`、`prepare`、
   `publish` 或 `run-all`。
6. 不跑 pytest、Ruff、mypy；不读取或打印 token；不在报告中复制 request 参数全集、raw rows、绝对路径或 SDK
   异常文本。

## 报告

写入 `docs/framework/agent/M3_G1_R1C-B_INDEX交付报告.md`，只保留压缩证据：

- 起止 UTC、退出码、稳定 outcome/code；
- 完成阶段、计划/完成 request 数；
- INDEX 后真实历史成分并集 `S`、由 CLI/工作流给出的 `history_requests` 和 `reference_requests`；
- 基于 60 requests/minute 的 HISTORY 纯限频理论下限；
- INDEX 本地数据与 journal 的汇总行数/字节数（只写相对逻辑范围或汇总，不写绝对路径）；
- 明确证明未启动 HISTORY；
- 若失败，记录可恢复程度与稳定失败 code，不声称通过。

不要宣称 R1C-B、G1、M3 或任何 Gate 完成。完成报告后立即返回，不继续规划其他任务。
