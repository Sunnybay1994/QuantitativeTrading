# M1 SSE-E2 单 Route Clean 事件原子重建独立初验报告

日期：2026-07-17  
角色：外部独立初验 Agent（全新会话，未参与实现）  
任务单：[M1_SSE-E2单RouteClean事件原子重建任务单.md](M1_SSE-E2单RouteClean事件原子重建任务单.md)  
交付报告：[M1_SSE-E2单RouteClean事件原子重建交付报告.md](M1_SSE-E2单RouteClean事件原子重建交付报告.md)  
前置主验：[M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md](M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md)

**结论：初验通过（exit 0）。** 生产代码/实现测试/README/配置/data 只读核对；未联网、未访问项目 `data/`、未跑全量 pytest、未做 Git。不宣称真实 clean 已修复，不宣称 Gate 通过。

## 1. 范围与纪律

| 项 | 状态 |
|---|---|
| 唯一写入 | 本报告 |
| 生产代码/实现测试/README/配置 | 只读 |
| 项目 `data/` / 网络 / 全量 pytest / Git | 未触碰 |
| 环境 | WSL Miniforge `base`（`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`） |

## 2. 合同逐项核对

| # | 冻结合同点 | 证据 | 结论 |
|---|---|---|---|
| 1 | 单 route replace：Schema 严格校验 → 非空且单 route → 拒绝在目标变化前发生 | `CleanConnectEventStore.replace_route`：先 `ConnectEligibilityEventSchema.validate`，再非空/`len(routes)==1`，最后 `_replace_parquet_guarded`；`test_connect_event_replace_rejects_empty_multi_route_and_schema_before_mutation` | 通过 |
| 2 | 不 concat 旧文件；按 `effective_date,symbol,action` 排序 | `replace_route` 仅 `sort` + guarded 写；无 `pl.concat`/`read_parquet` 旧文件；upsert 仍保留 concat（预期） | 通过 |
| 3 | 另一 route / raw 零变化 | `test_connect_event_replace_leaves_other_route_bytes_and_mtime`（SZ 字节+mtime）；pipeline mapper 失败保留 raw、clean 字节不变 | 通过 |
| 4 | 严格 bool：`True` 合法、`1` 非法 | `update_events`：`type(replace_clean) is not bool` → `TypeError`；`test_update_events_replace_clean_type_boundary` | 通过 |
| 5 | CLI 非法组合在 connector/网络/FS 前拒绝 | `main` 在构造 connector/`stores` 前检查 `--replace-clean` 仅 events；`test_replace_clean_rejects_non_events_before_connector_or_fs`（monkeypatch boom + `tmp_path` 空） | 通过 |
| 6 | 顺序 fetch→raw→mapper→replace；mapper 失败 raw 可留、原 clean 不变 | `update_events` 顺序与 `test_update_events_mapper_failure_keeps_raw_and_old_clean` | 通过 |
| 7 | JSON `clean_mode` 严格 `UPSERT`/`REPLACE_ROUTE` | `update_connect.main`；默认 CLI/`--replace-clean` 两测；无 token | 通过 |
| 8 | 默认 upsert 兼容；显式 flag 只走 `replace_route` | `replace_clean=False`→`upsert`；`True`→`replace_route`；默认无 flag 旧 REMOVE 与新 ADD 并存（upsert 语义） | 通过 |
| 9 | 写后重读 Schema + 行数/业务键；失败不宣称成功 | `replace_route` 写后校验；对抗 A7 强制 reread 清空 → `ValueError("replace_route 写后校验失败")` 且 `returned is None` | 通过 |
| 10 | 路径 fail-closed（任务单强制） | `_assert_safe_clean_replace_target` + `_replace_parquet_guarded`；实现单测 + 本报告 `/tmp` 对抗 8 项全过 | 通过 |
| 11 | README 仅安全用法与警告 | README 显式 `--replace-clean`、不 concat、不自动 universe、未经授权勿碰真实 data | 通过 |

## 3. 定向验证（任务单命令）

```text
python -m pytest tests/unit/test_storage.py -q -k 'connect and (event or replace)'
  → 7 passed, 13 deselected   exit 0

python -m pytest tests/unit/test_connect_market.py -q
  → 21 passed                 exit 0

python -m pytest tests/unit/test_update_connect.py -q
  → 5 passed                  exit 0

ruff check <白名单六文件>
  → All checks passed!        exit 0

mypy src/quant/data/storage.py src/quant/data/connect_market.py src/quant/data/update_connect.py
  → Success: no issues found  exit 0
```

合计定向：`EXITS storage=0 connect=0 update=0 ruff=0 mypy=0`。

## 4. 实现者未公开对抗（WSL `/tmp`）

脚本：`/tmp/sse_e2_adversarial_verify.py`（工作区 `/tmp/sse_e2_adv_indep`）。  
相对交付报告/实现单测，本初验新增或独立复现：

| ID | 反例（实现者未作为初验证据公开/未覆盖变体） | 期望 | 结果 |
|---|---|---|---|
| A1 | `store.root` 本身为 symlink | fail-closed；外部/真实路径字节不变 | PASS（`受控 raw root 祖先不得是 symlink`） |
| A2 | root 祖先目录为 symlink | 同上 | PASS |
| A3 | 目标 `data.parquet` 为指向外部的 symlink | fail-closed；外部字节不变；仍为 symlink | PASS |
| A4 | 目标为 FIFO | fail-closed（须普通文件）；外部不变 | PASS |
| A5 | 目标为**目录**（实现单测仅 FIFO） | fail-closed；目录内 nested 字节不变 | PASS |
| A6 | 预置 `data.tmp.parquet` 为指向外部的 symlink | 拒绝写跟随时；外部与旧 clean 不变 | PASS（`clean 临时文件路径非法`） |
| A7 | monkeypatch 写后 reread 清空，模拟校验失败 | 抛错且不返回成功行数 | PASS（`replace_route 写后校验失败`，`returned=None`） |
| A8 | `route=<R>` 目录 symlink 到外部 | fail-closed；外部 `data.parquet` 字节不变 | PASS |

```text
TOTAL=8 PASS=8 FAIL=0   adv exit 0
```

## 5. 已知非阻塞备注（不构成初验失败）

- `_validate_controlled_root` 错误文案仍写“受控 raw root”，clean 路径复用该检查时文案略偏，但 fail-closed 行为正确。
- 交付报告已声明：upsert 路径未加同等 symlink 防护；TOCTOU 理论竞态；真实 `data/clean` 未重建——均属范围外/待主验与授权，不降级本包代码合同。

## 6. 初验判定

- **初验：通过**
- **综合退出码：0**
- 返工项：无
- 下一步：交主 Agent 终验；真实 clean 重建须另获授权，不得由本包自动执行。
