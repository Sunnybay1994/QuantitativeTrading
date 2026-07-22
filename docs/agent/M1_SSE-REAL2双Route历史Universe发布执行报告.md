# M1 SSE-REAL2 双 Route 历史 Universe 发布 — 执行报告

## 结果

- 状态：**已交付（执行完成，待独立验证）**
- 角色：真实执行 Agent（仅执行，未改代码/配置/测试/路线图）
- 唯一写入产物（本报告外）：`SH_CONNECT` 与 `SZ_CONNECT` 两个 universe membership clean 文件（原子替换）
- 明确未修改：clean event / raw / snapshot / calendar、代码、测试、配置、legacy
- 不宣称独立验证 / 主验 / Gate / 里程碑通过

## 环境与前置

- 工作目录：WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`
- Python：`/home/mabw/miniforge3/bin/conda run -n base`
- 网络：零网络；未读取/输出 token
- 前置：SSE-REAL1 主验通过；用户已明确授权发布两个 universe

## 1. 发布前目标 hash/mtime

| 目标 | bytes | mtime (+0800) | sha256 |
| --- | ---: | --- | --- |
| `data/clean/universe_membership/universe=SH_CONNECT/data.parquet` | 3001 | 2026-07-12 01:12:16 | `0cef2cfd752a1af555d6ccbad85af2870fc259e3737ca038d3a205d9fdb461b2` |
| `data/clean/universe_membership/universe=SZ_CONNECT/data.parquet` | 3001 | 2026-07-12 01:12:24 | `00eb290f2a11b10631a6e46cc48b420189938b2add861717868a2a0ae51b9847` |

## 2. 零写入 dry-run（先 SH 后 SZ）

### SH dry-run

```bash
python -m quant.data.rebuild_connect_universe \
  --route SH_CONNECT --baseline-date 2014-11-17 \
  --mode reverse-audit --snapshot-date 2026-07-10 \
  --expected-baseline-count 268 --dry-run
```

| 项 | 值 |
| --- | --- |
| 退出码 | **0** |
| 摘要 | `rows=1062`；`symbols=919`；`coverage_start=2014-11-17`；`open_intervals=644`；`published=false`；`status=PASS` |
| 合同核对 | 覆盖起点与 open=644 符合任务书；SH rows/symbols 冻结为 **1062/919** |

### SZ dry-run

```bash
python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --baseline-date 2016-12-05 \
  --mode reverse-audit --snapshot-date 2026-07-10 \
  --expected-baseline-count 417 --dry-run
```

| 项 | 值 |
| --- | --- |
| 退出码 | **0** |
| 摘要 | `rows=1149`；`symbols=1014`；`coverage_start=2016-12-05`；`open_intervals=644`；`published=false`；`status=PASS` |
| 合同核对 | 与任务书冻结值 rows/symbols/open/coverage_start 精确一致 |

### dry-run 后文件状态

- 两目标 hash/mtime **与发布前完全一致**（零写入确认）
- `universe_membership/` 下无 temp/残留文件

## 3. 串行发布

### 3.1 SH 发布（先）

```bash
python -m quant.data.rebuild_connect_universe \
  --route SH_CONNECT --baseline-date 2014-11-17 \
  --mode reverse-audit --snapshot-date 2026-07-10 \
  --expected-baseline-count 268
```

| 项 | 值 |
| --- | --- |
| 退出码 | **0** |
| 摘要 | `rows=1062`；`symbols=919`；`coverage_start=2014-11-17`；`open_intervals=644`；`published=true`；`status=PASS` |
| 与 dry-run | rows/symbols/open/coverage_start **完全一致** |
| 重试 | **无** |

SH 发布后即时核对：

| 目标 | 变化 | bytes | mtime (+0800) | sha256 |
| --- | --- | ---: | --- | --- |
| SH universe | **已替换** | 5703 | 2026-07-17 22:22:45 | `cf300a5daba437cebcddfa74ed4b8a497d8c829e556c548add8d1bf9aa42dbe2` |
| SZ universe | **未变** | 3001 | 2026-07-12 01:12:24 | `00eb290f2a11b10631a6e46cc48b420189938b2add861717868a2a0ae51b9847` |
| temp 残留 | **无** | — | — | — |

### 3.2 SZ 发布（仅在 SH exit 0 后）

```bash
python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --baseline-date 2016-12-05 \
  --mode reverse-audit --snapshot-date 2026-07-10 \
  --expected-baseline-count 417
```

| 项 | 值 |
| --- | --- |
| 退出码 | **0** |
| 摘要 | `rows=1149`；`symbols=1014`；`coverage_start=2016-12-05`；`open_intervals=644`；`published=true`；`status=PASS` |
| 与 dry-run | rows/symbols/open/coverage_start **完全一致** |
| 重试 | **无** |

## 4. 发布后终态与隔离

### Universe 终态

| 目标 | bytes | mtime (+0800) | sha256 |
| --- | ---: | --- | --- |
| SH universe | 5703 | 2026-07-17 22:22:45 | `cf300a5daba437cebcddfa74ed4b8a497d8c829e556c548add8d1bf9aa42dbe2` |
| SZ universe | 6152 | 2026-07-17 22:23:06 | `c4501b974ce99c1ea48c3f2eaa18bd9fce0b03b9b1c0b8b27d012b5b634b9e9a` |

### 原子发布 / 临时文件

- 生产路径使用 `_replace_parquet_guarded`（`.tmp.parquet` → `os.replace`）
- 发布后 `universe_membership/` 仅各有一个 `data.parquet`；**无** `.tmp.parquet` / temp / partial 残留
- 部分提交状态：**不适用**（两路均 exit 0；无中断失败）

### 范围隔离（非授权目标未变）

| 目标 | bytes | mtime (+0800) | sha256 | 说明 |
| --- | ---: | --- | --- | --- |
| SH clean event | 23068 | 2026-07-17 22:11:56 | `db685e5675a858f7903fda8e0eebcf0753090ea921e8b48e2a6f869f038d2fbb` | 与 SSE-REAL1 终态一致 |
| SZ clean event | 23821 | 2026-07-12 00:47:04 | `30abfb4a03e247669547dabcd3dc1d539d8ba47de4655d7621dee58ebd158bd5` | 与 SSE-REAL1 终态一致 |

未运行 `update_connect`；未改 raw/snapshot/calendar；未改代码/测试/配置/路线图。

## 5. 停止条件核对

| 条件 | 是否满足 |
| --- | --- |
| 两路 dry-run 均 PASS 且符合冻结合同 | 是 |
| dry-run 零写入 | 是 |
| 严格串行：SH 先、SZ 仅在 SH exit 0 后 | 是 |
| 仅写两个授权 universe + 本报告 | 是 |
| 零网络、无重试、无自行修复 | 是 |
| 不宣称独立验证/主验/Gate/里程碑通过 | 是 |

## 6. 后续

- 已发生写入：两个 universe membership clean 文件已原子替换。
- 建议：交由未参与执行的独立验证 Agent，按任务书第 3 节核对 dry-run 一致性、Schema、`eligible_symbols_on` 与非 universe hash 不变；**本报告不代替独立验证**。
