# M3 G1 R1C-B 真实运行授权与资源清单

日期：2026-07-17（INDEX 外部独立复验通过后由总协调更新；同日用户授权 HISTORY）  
状态：**INDEX 已完成并可恢复；HISTORY 已授权但外部确认未通过（截断硬阻塞，待主 Agent 裁定）；REFERENCE/PREPARE/PUBLISH 均未授权**  
边界：本清单本身不调用网络；不宣称 R1C-B、G1、M3 或 Gate 通过；外部只写「待主 Agent 整体验收」

**HISTORY 用户授权（原文，2026-07-17）**：

> 授权执行 R1C-B HISTORY 阶段：允许最多 2679 个计划 Tushare 请求（端点仅 daily/adj_factor/stk_limit/dividend/index_daily/suspend_d），基于已冻结 S=637；可崩溃恢复；完成后新进程 status 并停止；不启动 REFERENCE/PREPARE/PUBLISH。

权威证据：
- 独立复验：[`M3_G1_R1C-B_INDEX身份合同返工独立复验报告.md`](M3_G1_R1C-B_INDEX身份合同返工独立复验报告.md)（通过）
- 总协调零网络 `status`（2026-07-17，exit 0）与复验一致

## 1. 当前可恢复状态（已冻结）

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
/home/mabw/miniforge3/bin/conda run -n base python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status
```

```json
{
  "outcome": "INCOMPLETE",
  "completed_stages": ["INDEX"],
  "index_requests": 127,
  "history_symbols": 637,
  "history_requests": 2679,
  "reference_requests": 0,
  "primary_candidate_key": null,
  "release_id": null,
  "manifest_sha256": null
}
```

冻结解读：

| 字段 | 值 | 含义 |
|---|---:|---|
| `S` = `history_symbols` | **637** | INDEX 后真实历史成员并集 |
| HISTORY Tushare 计划请求 | **2679** = `4×637+131` | 下一阶段若授权的上限 |
| INDEX 已用请求 | **127** | 仅 `index_weight`；raw/journal 可恢复 |
| CLI `reference_requests` | **0** | 当前 workflow 计数；**理论**未来 BaoStock = `S=637` |
| 后续阶段完成证据 | **无** | 未跑 HISTORY/REFERENCE/PREPARE/PUBLISH |

按配置 60 requests/minute、忽略重试与写盘：HISTORY 纯限频理论下限 ≈ `2679/60 ≈ 44.7` 分钟。

## 2. 请求规模公式（不变）

```text
INDEX Tushare             = 127          （已完成）
HISTORY per-symbol        = 4 × S
HISTORY index_daily       = 1
HISTORY suspend_d monthly = 130
HISTORY Tushare total     = 4 × S + 131  （现 S=637 → 2679）
REFERENCE BaoStock        = S            （现 637；尚未启动）
```

计划 request ≠ attempt 上限；配置每请求最多 5 attempts。

## 3. 推荐下一步授权（仅建议，未自动执行）

### A. INDEX — 已完成

用户已授权并完成；身份合同返工独立复验通过。**不再需要**重复 INDEX 授权。

### B. HISTORY — **已授权，按外部运行 Prompt 执行**

执行 Prompt：[`M3_G1_R1C-B_HISTORY外部运行Prompt.md`](M3_G1_R1C-B_HISTORY外部运行Prompt.md)  
复验 Prompt（写入退出后）：[`M3_G1_R1C-B_HISTORY独立复验Prompt.md`](M3_G1_R1C-B_HISTORY独立复验Prompt.md)

约束摘要：
- 网络：仅上列七端点中的六个 HISTORY 端点（无 `index_weight`）；
- 上限：必须等于已验真 plan 的 **2679**；重试不计为新计划 request；
- 写入：`data/raw/m3_g1/**`、`data/run_state/m3_g1/**`；同一时刻仅一个数据写者；
- 与任何 `src/**` 写会话互斥（G1 identity 冻结窗口）；
- 禁止缩短区间、降低质量门禁、并行第二 workflow。

### C. 再后：REFERENCE + PREPARE / PUBLISH

- REFERENCE：BaoStock，数量 `S=637`；须另授权。
- PUBLISH：仍受 `RENAME_NOREPLACE` 环境门禁（见 §4）；须另授权。

## 4. 正式 PUBLISH 外部门禁

主 Agent 探针结果仍为：

```text
DEFAULT_TMP_RENAME_NOREPLACE False
```

即使后续 PREPARE 成功，也不得在当前环境调用 PUBLISH 或降级发布协议。

## 5. 安全与停止条件

- token 只从 ignored `configs/tushare.local.toml` 间接加载；报告不得出现 token；
- permanent/permission/quality failure 立即停止并保留 evidence；
- 不修改配置、token、日期、端点集合、限频或 retries；
- `.git` 仍为空目录；真实数据不进入 Git；
- **本清单更新 ≠ 授权 HISTORY**。

## 6. 用户授权语句（HISTORY）

用户已于 2026-07-17 给出 HISTORY 授权（见文首）。本授权**不延伸**至 REFERENCE/PREPARE/PUBLISH。
