# M1 SSE-REAL1 真实 SH Clean 事件重建任务单

## 1. 授权边界

本任务默认未授权。需用户明确允许：**一次上交所公开 events 请求、一次 immutable raw 新快照写入、一次
`SH_CONNECT` clean event 原子替换**。禁止修改 SZ、snapshot/calendar/universe、代码和配置。

## 2. 外部执行 Agent

全新 `cursor-grok-4.5-high`，Windows 启动但命令只在 WSL Miniforge base。

前置只读：

```bash
python -m quant.data.audit_connect_eligibility \
  --route SH_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2014-11-17 --expected-baseline-count 268
```

必须得到 `REVERSE_AUDIT_STATE_CONFLICT`；若不是，停止。然后记录 SH/SZ clean 目标文件的 bytes hash/mtime，
不得读取 legacy。

唯一授权写命令：

```bash
python -m quant.data.update_connect \
  --route SH_CONNECT --table events --replace-clean
```

完成或失败后立即停止，不重试、不运行 snapshot/calendar/universe、不手工修 Parquet。唯一执行报告：
`docs/framework/agent/M1_SSE-REAL1真实SHClean事件重建执行报告.md`。禁止长响应、绝对敏感路径和任何凭据。

## 3. 外部独立验证 Agent

另一全新 `cursor-grok-4.5-high`；代码、配置、raw、clean 全只读，唯一写：
`docs/framework/agent/M1_SSE-REAL1真实SHClean事件重建独立验证报告.md`。

验证：

1. 用 `CleanConnectEventStore.read_route` 核对 SH 恰 1212 行、ADD=794、REMOVE=418；Schema 通过；
2. SH audit 必须 `current=644,event_count=1212,reverse=268,status=PASS`；
3. SZ audit 必须仍为 `current=644,event_count=1237,reverse=417,status=PASS`；
4. SZ clean bytes hash/mtime 不变；旧 SH clean 被替换而非 concat；
5. 新 immutable raw 快照存在且 metadata/checksum 闭合；既有 raw 未覆盖；
6. 不重建 universe、不联网、不运行 pytest、不修复。

验证通过后交主 Agent 终验；该状态仍不等于更早 universe 已发布。
