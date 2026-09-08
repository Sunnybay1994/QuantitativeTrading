# M1 SSE-REAL1 真实 SH Clean 事件重建 — 独立验证报告

## 结论

- **独立验证：通过**
- 角色：未参与执行的全新独立验证 Agent；代码/配置/测试/`data/` 只读；唯一写入为本报告
- 环境：WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` + Miniforge `base`；验证过程零网络（未调用 SSE/Tushare，未执行 rebuild/update/publish）
- **不宣称**主验 / Gate / 里程碑通过

## 对照材料

- 任务单：`docs/framework/agent/M1_SSE-REAL1真实SHClean事件重建任务单.md`
- 执行报告：`docs/framework/agent/M1_SSE-REAL1真实SHClean事件重建执行报告.md`
- 契约：`ConnectEligibilityEventSchema`（`src/quant/domain/schemas.py`）；`CleanConnectEventStore.read_route` / `replace_route`（`src/quant/data/storage.py`）；`map_sse_events`（`src/quant/data/connect_market.py`）

---

## 1. SH clean 行数 / ADD-REMOVE / Schema / 无重复污染

| 判定 | **通过** |
| --- | --- |

### 命令与退出码

```bash
# 经 CleanConnectEventStore.read_route + ConnectEligibilityEventSchema.validate
/home/mabw/miniforge3/bin/conda run -n base python /tmp/sse_real1_verify_sh.py
# EXIT:0
```

### 证据（脱敏）

| 项 | 值 |
| --- | ---: |
| `SH_rows` | 1212 |
| `ADD` | 794 |
| `REMOVE` | 418 |
| `ADD+REMOVE` | 1212 |
| `routes` | `['SH_CONNECT']` |
| `sources` | `['sse']` |
| Schema validate | ok |
| 主键重复 `(route,effective_date,symbol,action)` | 0 |
| 同日同标的多 action | 0 |
| `action_set` | `['ADD','REMOVE']` |
| 非 SH / 非 sse 行 | 0 / 0 |

---

## 2. SH 零网络 reverse audit

| 判定 | **通过** |
| --- | --- |

### 命令与退出码

```bash
python -m quant.data.audit_connect_eligibility \
  --route SH_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2014-11-17 --expected-baseline-count 268
# EXIT_SH:0
```

### 证据

`current_count=644,event_count=1212,reverse_count=268,status=PASS`
（另：`event_min=2014-12-08`,`event_max=2026-07-10`）

---

## 3. SZ 零网络 reverse audit

| 判定 | **通过** |
| --- | --- |

### 命令与退出码

```bash
python -m quant.data.audit_connect_eligibility \
  --route SZ_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2016-12-05 --expected-baseline-count 417
# EXIT_SZ:0
```

### 证据

`current_count=644,event_count=1237,reverse_count=417,status=PASS`

---

## 4. SZ clean 未变；SH clean 为替换而非拼接

| 判定 | **通过** |
| --- | --- |

### 只读 hash/mtime（+0800）

| 目标 | bytes | mtime | sha256 |
| --- | ---: | --- | --- |
| SH clean | 23068 | 2026-07-17 22:11:56 | `db685e5675a858f7903fda8e0eebcf0753090ea921e8b48e2a6f869f038d2fbb` |
| SZ clean | 23821 | 2026-07-12 00:47:04 | `30abfb4a03e247669547dabcd3dc1d539d8ba47de4655d7621dee58ebd158bd5` |

### 映射

- SZ：与执行报告 preflight/写后记录的 bytes/mtime/sha256 **完全一致** → 未改。
- SH：与 preflight 旧值 `bytes=22924` / sha256=`198a3633…ff59fa` **不同**；写后值与执行报告一致 → 旧文件已被替换。
- 字节仅 +144，远非“旧+新”量级；且第 7 项证明 clean 与新 raw 映射后全字段相等，排除意外 concat 残留污染。

---

## 5. 新 raw 不可变闭包；旧 raw 未覆盖；无凭据泄露

| 判定 | **通过** |
| --- | --- |

### 新快照

- 路径：`data/raw/sse/connect_eligibility_event/date=2026-07-17/141156.141055Z-d9a0dc824c59.{json,parquet}`
- metadata 关键字段：`source=sse`，`table=connect_eligibility_event`，`rows=1212`，`snapshot_id=141156.141055Z-d9a0dc824c59`，`fetched_at=2026-07-17T14:11:56.141055+00:00`，`parameters={'route':'SH_CONNECT'}`
- `checksum_sha256` == parquet sha256 == `4c7e666685b35f3fb626dd7c68d964499d01f1187193931878b645ac09c326e1` → **闭合**
- metadata 键集合无 token/password/secret 类字段；验证过程未读取/输出凭据

### 旧 raw 未覆盖

- `date=2026-07-11/071021.175558Z-3865e982db01.{json,parquet}` 仍在；mtime 仍为 2026-07-11 15:10:21
- json sha256=`f71c9a97…ae9d10`；parquet sha256 与新快照内容相同（载荷一致）但路径独立
- `connect_eligibility_event/` 仅 `date=2026-07-11` 与 `date=2026-07-17` 两个分区

---

## 6. 未重建 universe / 无额外网络 / 无代码配置测试变更

| 判定 | **通过（含证据边界）** |
| --- | --- |

### 可核实的正向证据

| 检查 | 结果 |
| --- | --- |
| 执行窗口 `2026-07-17 22:00–22:20` 内 `data/` 变更文件 | **仅** SH clean + 新 raw json/parquet（3 个文件，mtime 均 22:11:56） |
| universe_membership SH/SZ | mtime 仍为 2026-07-12 01:12，未落入执行窗口 |
| connect_snapshot / connect_calendar | mtime 仍为 2026-07-11/12，未落入执行窗口 |
| SZ clean | 见第 4 项，未变 |
| 本验证会话 | 仅只读 audit / 本地 Python 读取；未跑 `update_connect` / rebuild / pytest |

### 证据边界（不臆断）

1. **额外网络请求**：离线产物无法绝对证明执行 Agent 当时仅发起一次 SSE 请求；仅能确认授权写命令对应的新 raw 快照已落盘，且验证侧零网络。
2. **代码/配置/测试内容未改**：工作区对 WSL `git` 不可用（`fatal: not a git repository`），无 commit 基线可 diff。Baidu 同步盘上部分 `src/`/`tests/`/`configs/` 文件 mtime 可能被同步触碰（例如 `src/quant/data/repositories.py` mtime≈22:11:03），**mtime≠内容变更证明**。在无 git hash 对照下，不能绝对证明这些路径内容字节未变；但执行窗口内 `data/` 写入集合与任务授权一致，且未见 universe/snapshot/calendar/SZ 被写。

---

## 7. 执行者未使用的对抗性检查

| 判定 | **通过** |
| --- | --- |

### 检查设计

对**新 raw parquet** 调用生产映射 `map_sse_events`，再与 `CleanConnectEventStore.read_route("SH_CONNECT")` 做主键与全字段比对；并核对 raw `ADJUST_TYPE` 与 clean `action` 计数。

### 为何能发现拼接/映射错误

- 若 clean 被旧文件 concat/错误 unique，或 route/source/日期映射串台，则 `map_sse_events(raw)` 与 clean 的 key set 或全字段 equals 会失败。
- 若 action 映射颠倒或混入非法 `ADJUST_TYPE`，则 ADD/REMOVE 与 raw「调进/调出」计数会对不上，或 `map_sse_events` 直接抛 `SSE_EVENT_ADJUST_TYPE_INVALID`。

### 命令与退出码

```bash
/home/mabw/miniforge3/bin/conda run -n base python /tmp/sse_real1_map.py
# EXIT:0
```

### 证据

| 项 | 值 |
| --- | --- |
| mapped_rows / clean_rows | 1212 / 1212 |
| 主键集合相等 | True（only_mapped=0, only_clean=0） |
| 全字段 equals（9 列） | True |
| raw `调进`/`调出` | 794 / 418 |
| clean ADD/REMOVE | 794 / 418 |
| raw `ADJUST_TYPE` 集合 | 仅 `调进`,`调出` |

（附：同日同标的多 action=0；SH/SZ route 隔离成立。执行报告未展示该 raw→`map_sse_events`→clean 全字段 equals。）

---

## 任务书验收标准逐项映射

| # | 任务书要求 | 判定 |
| --- | --- | --- |
| 1 | SH 恰 1212；ADD=794；REMOVE=418；Schema 通过 | **通过** |
| 2 | SH audit `current=644,event_count=1212,reverse=268,status=PASS` | **通过** |
| 3 | SZ audit `current=644,event_count=1237,reverse=417,status=PASS` | **通过** |
| 4 | SZ hash/mtime 不变；旧 SH 替换非 concat | **通过** |
| 5 | 新 immutable raw 闭包；旧 raw 未覆盖 | **通过** |
| 6 | 不重建 universe；不联网（验证侧）；不跑 pytest；不修复 | **通过**（绝对“执行期无额外网络/代码未改”见证据边界） |
| 7 | 至少一个执行者未用的对抗性只读检查 | **通过**（raw `map_sse_events` ↔ clean 全字段） |

## 总评

独立验证范围内各项验收标准均满足，**独立验证通过**。本结论仅覆盖 SSE-REAL1 任务书第 3 节；不等于主验、Gate 或更早 universe 发布状态。
