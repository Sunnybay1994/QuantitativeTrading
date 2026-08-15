# M1 HK-HISTORY R1：港股 Close 有界包络返工交付报告

日期：2026-08-15（Asia/Shanghai）  
角色：外部实现收尾 Agent  
模型：`cursor-grok-4.6-high`  
合同：[`M1_HK-HISTORY-R1_港股Close有界包络返工任务单.md`](M1_HK-HISTORY-R1_港股Close有界包络返工任务单.md)  
取证：[`M1_01065_20260515_OHLC异常Cursor只读取证报告.md`](M1_01065_20260515_OHLC异常Cursor只读取证报告.md)  
状态：**已交付，待独立初验**（不宣布 M1 / HK60 Gate）

## 结果

- 状态：已交付
- `TushareBarMapper` 仅对 HK canonical 投影新增 close-only 有界包络；A 股/非 HK、`Bar1dSchema.ohlc_valid`、raw 字节均不变。
- 前一实现会话已写入 mapper/测试/README 语义；本收尾保留其合同实现，只把 README 从全文件 LF 噪声恢复为 HEAD 混合换行 + 目标段语义。
- 明确未修改：Schema、连接器、raw/evidence、`publish_tushare_bulk_clean.py`、factors、configs、`docs/quant_factor_research_v2`、data/artifacts；未联网、未读 token、未 `git add/commit/push`。

## 修改文件及目的

| 文件 | 目的 |
| --- | --- |
| `src/quant/data/mappers.py` | HK close-only 包络：open 已在原区间、close 一侧越界、相对最近正边界偏离 ≤5% 时 `high=max(raw_high, raw_close)`、`low=min(raw_low, raw_close)`；保留既有 open-only |
| `tests/unit/test_tushare_connector.py` | 任务单正/负向反例；废止 R0 无条件 `HK close>high` 硬失败，改为小偏离通过 / 大偏离拒绝 |
| `README.md` | 仅同步该 mapper 行为段；恢复 HEAD 混合 EOL，避免全文件 LF/CRLF 噪声 |
| `docs/agent/M1_HK-HISTORY-R1_港股Close有界包络返工交付报告.md` | 本报告 |

## 设计与合同证据

| 冻结规则 / 必测反例 | 实现 / 测试 |
| --- | --- |
| 仅 HK canonical；raw 不改写 | `raw.select(...)`；`test_hk_close_above_vendor_high_expands_canonical_range` 断言 raw high 仍 `4.38` |
| 既有 HK open-only 保持 | `hk_open_only_mismatch` 仍要求 close 在原区间；既有 open 上/下越界测试继续通过 |
| close-only：有限为正、`high>=low`、open 在区间、一侧越界、分母=最近正边界、≤5% | `_HK_CLOSE_ENVELOPE_MAX_RELATIVE_DEVIATION=0.05`；`01065` 例 → clean high=`4.39` 且 Schema 通过；close 略低于 low → clean low 扩展 |
| open+close 同时越界、偏离>5%、`high<low`、零/负/NaN/Inf、SZ close 越界 | `test_mapper_does_not_hide_non_hk_open_only_ohlc_errors` 继续 Schema 拒绝 |
| 5% 只是脏数据上限，不是价位表/CAS 证明 | mapper docstring 与 README 均写明 |

与任务单无偏离。R0「港股 close 越界一律硬失败」按本任务单显式废止，仅在上述 close-only 条件下放行。

## 验证

环境：Windows `D:\Miniforge3\python.exe`（开发反馈环，不替代 WSL Gate）。

| 命令或检查 | 结果 | 证据 |
| --- | --- | --- |
| `python -m pytest tests/unit/test_tushare_connector.py -q` | 通过 | `35 passed`，3.68s |
| `python -m pytest tests/unit/test_hk_history_backfill.py tests/unit/test_backfill_hk_history.py -q` | 通过 | `151 passed, 2 skipped`，102.57s |
| `ruff check src/quant/data/mappers.py tests/unit/test_tushare_connector.py` | 通过 | `All checks passed!` |
| `mypy src/quant/data/mappers.py tests/unit/test_tushare_connector.py` | 通过 | `Success: no issues found in 2 source files` |
| 全量 pytest / 网络 / Tushare / WSL Gate | 未运行 | 任务书禁止 |

## 清理与范围审查

- 无临时代码；未在 mapper 复制港交所价位表。
- README `git diff --stat`：`8` 行语义，不再是全文件 700+ 行换行噪声。
- 工作区另有并行会话改动（`publish_tushare_bulk_clean.py`、factors、configs、`docs/quant_factor_research_v2` 等）；本会话未触碰。
- 范围外改动：无。

## 风险与交接

- **已知限制**：官方 HKEX 2026-05-15 Daily Quotations 仍 `INSUFFICIENT`；本包络是供应商口径 fail-closed 投影，不证明该 close 来自 CAS 撮合。
- **未验证**：独立初验对抗性反例；WSL base Gate；真实 retained raw 重跑 / clean 再发布。
- **回滚**：还原白名单三文件即可；不改 raw。
- **下一步**：未参与实现的外部初验 Agent 只读核对；主 Agent 终验前不得宣称 M1 / HK60 Gate 通过。
