# M1 SSE-REAL1 真实 SH Clean 事件重建 — 执行报告

## 结果

- 状态：**已交付（执行完成，待独立验证）**
- 角色：真实执行 Agent（仅执行，未改代码/配置/测试/路线图）
- 唯一写入产物（本报告外）：1 份新 immutable SSE events raw；1 次 `SH_CONNECT` clean event 原子替换
- 明确未修改：SZ clean、snapshot/calendar/universe、代码、测试、配置、legacy
- 不宣称独立验证 / 主验 / Gate / 里程碑通过

## 环境

- 工作目录：WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`
- Python：`/home/mabw/miniforge3/bin/conda run -n base`
- 凭据：未读取/输出 token；仅由既有 ignored 配置供程序使用（本命令走官方 SSE，无 Tushare）

## 1. 零网络 Preflight

### 命令

```bash
python -m quant.data.audit_connect_eligibility \
  --route SH_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2014-11-17 --expected-baseline-count 268
```

### 结果

| 项 | 值 |
| --- | --- |
| 退出码 | 1（审计工具对冲突状态的预期非零） |
| stdout 关键行 | `REVERSE_AUDIT_STATE_CONFLICT` |
| 是否符合继续条件 | **是**（任务书要求必须观察到该状态） |

### Preflight 目标文件 hash/mtime（相对路径）

| 目标 | bytes | mtime (+0800) | sha256 |
| --- | ---: | --- | --- |
| `data/clean/connect_event/route=SH_CONNECT/data.parquet` | 22924 | 2026-07-11 15:10:21 | `198a3633c9c89f88635f2bc71ee2424cf9840a9509f2827cafa0b9c0cbff59fa` |
| `data/clean/connect_event/route=SZ_CONNECT/data.parquet` | 23821 | 2026-07-12 00:47:04 | `30abfb4a03e247669547dabcd3dc1d539d8ba47de4655d7621dee58ebd158bd5` |

Preflight 前既有 SH events raw（未覆盖基线）：
`data/raw/sse/connect_eligibility_event/date=2026-07-11/071021.175558Z-3865e982db01.{json,parquet}`

## 2. 唯一授权网络/写入命令

### 命令

```bash
python -m quant.data.update_connect --route SH_CONNECT --table events --replace-clean
```

### 结果（脱敏摘要）

| 项 | 值 |
| --- | --- |
| 退出码 | **0** |
| JSON 摘要 | `raw_path=data/raw/sse/connect_eligibility_event/date=2026-07-17/141156.141055Z-d9a0dc824c59.parquet`；`clean_rows=1212`；`clean_mode=REPLACE_ROUTE` |
| 重试 | **无**（完成后立即停止） |
| 是否运行 snapshot/calendar/universe | **否** |

## 3. 写入后证据

### Clean 前后对比

| 目标 | 变化 | bytes | mtime (+0800) | sha256 |
| --- | --- | ---: | --- | --- |
| SH clean | **已替换** | 23068（原 22924） | 2026-07-17 22:11:56 | `db685e5675a858f7903fda8e0eebcf0753090ea921e8b48e2a6f869f038d2fbb` |
| SZ clean | **未变** | 23821 | 2026-07-12 00:47:04 | `30abfb4a03e247669547dabcd3dc1d539d8ba47de4655d7621dee58ebd158bd5`（与 preflight 一致） |

### 新 immutable raw 闭包

| 项 | 证据 |
| --- | --- |
| 新快照路径 | `data/raw/sse/connect_eligibility_event/date=2026-07-17/141156.141055Z-d9a0dc824c59.{json,parquet}` |
| metadata 关键字段 | `source=sse`，`table=connect_eligibility_event`，`rows=1212`，`snapshot_id=141156.141055Z-d9a0dc824c59`，`fetched_at=2026-07-17T14:11:56.141055+00:00`，`parameters=[route]` |
| checksum 闭合 | metadata `checksum_sha256` = parquet sha256 = `4c7e666685b35f3fb626dd7c68d964499d01f1187193931878b645ac09c326e1` |
| 既有 raw 未覆盖 | `date=2026-07-11/071021.175558Z-3865e982db01.*` 仍在，mtime 仍为 2026-07-11 15:10；json/parquet sha256 分别为 `f71c9a97…ae9d10` / `4c7e6666…c326e1` |
| raw 目录结构 | `connect_eligibility_event/` 仅 `date=2026-07-11` 与新建 `date=2026-07-17` |

说明：新旧 raw parquet 内容 checksum 相同（官方 events 载荷一致），但为独立新快照路径与新 metadata，符合不可覆盖语义。

### 停止条件核对

| 条件 | 是否满足 |
| --- | --- |
| Preflight 为 `REVERSE_AUDIT_STATE_CONFLICT` | 是 |
| 仅执行一次授权写命令且 exit 0 | 是 |
| 不重试、不扩表、不改代码 | 是 |
| 仅写本执行报告 | 是（本文件） |
| 失败即停并升级 | 不适用（本次成功） |

## 4. 可恢复状态与后续

- 已发生写入：新 SH events raw 快照；SH clean 已原子替换为 `REPLACE_ROUTE`（CLI 报告 1212 行）。
- SZ / universe / snapshot / calendar 未动，可按既有文件继续。
- 建议：交由未参与执行的独立验证 Agent，按任务书第 3 节核对行数/ADD-REMOVE/audit PASS、SZ 不变、raw 闭包；**本报告不代替独立验证**。
