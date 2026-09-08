# M1 SSE-E2 单 Route Clean 事件原子重建交付报告

日期：2026-07-17  
角色：外部实现 Agent（全新会话）  
任务单：[M1_SSE-E2单RouteClean事件原子重建任务单.md](M1_SSE-E2单RouteClean事件原子重建任务单.md)  
前置：[M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md](M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md)

结论：**代码与 fake 测试已按任务单实现并通过五项定向验证；未触碰项目真实 data，不宣称真实 clean 已修复，不宣称 Gate 通过。**

## 1. 完成内容

1. `CleanConnectEventStore.replace_route(frame)`：Schema 严格校验 → 非空且单 route → 受控原子替换
   `root/route=<route>/data.parquet`（按 `effective_date,symbol,action` 排序，不 concat 旧文件）→ 写后重读
   Schema + 行数/业务键集合校验。
2. 路径 fail-closed：目标或祖先为 symlink、目标非普通文件、临时路径非法时拒绝写入，不跟随到外部文件。
3. `ConnectMarketPipeline.update_events(*, replace_clean: bool = False)`：严格 `bool`（`True` 合法、`1` 非法）；
   `False` 仍 upsert，`True` 只走 `replace_route`；执行顺序 fetch → raw write → mapper → clean；mapper 失败时
   raw 可保留、原 clean 不变。
4. CLI `--replace-clean`：仅允许与 `--table events`；非法组合在 connector/网络/FS 前拒绝；JSON 增加
   `clean_mode`=`UPSERT`|`REPLACE_ROUTE`。
5. README 仅补充显式 replace 用法与警告。

## 2. 白名单改动文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/storage.py` | `replace_route` + `_assert_safe_clean_replace_target` / `_replace_parquet_guarded` |
| `src/quant/data/connect_market.py` | `update_events(replace_clean=...)` |
| `src/quant/data/update_connect.py` | `--replace-clean`、早拒绝、`clean_mode` |
| `tests/unit/test_storage.py` | replace 行为、跨 route 不变、非法输入、symlink/fifo fail-closed |
| `tests/unit/test_connect_market.py` | upsert/replace 分流、类型边界、mapper 失败 raw 保留 |
| `tests/unit/test_update_connect.py` | CLI 契约与无副作用（新建） |
| `README.md` | 安全用法与警告 |
| `docs/framework/agent/M1_SSE-E2单RouteClean事件原子重建交付报告.md` | 本报告 |

未改其他生产模块；未联网；未访问项目 `data/`；未跑全量 pytest；未做 Git。

## 3. 验证（WSL Miniforge base）

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

## 4. 风险与未验证

- **真实 clean 未重建**：本包只交付受控工具；既有 `data/clean/connect_event` 仍可能含旧 mapper 错误行，须另获授权后再执行真实 replace。
- **upsert 路径未加同样 symlink 防护**：仅 `replace_route` 走 guarded 写入；普通 upsert 仍用原 `_replace_parquet`（任务范围外）。
- **TOCTOU**：检查与 `os.replace` 之间仍有理论竞态，与项目其他受控路径一致。
- 独立初验须另会话只读核对，并补 `/tmp` 对抗性 symlink/非普通文件反例；实现者自测不能代替初验。

## 5. 下一步

交未参与实现的外部初验 Agent → 主 Agent 终验 → 再请求真实数据重建授权。
