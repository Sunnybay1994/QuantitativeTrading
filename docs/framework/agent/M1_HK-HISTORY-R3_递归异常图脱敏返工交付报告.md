# M1 HK-HISTORY-R3：递归异常图脱敏返工交付报告

日期：2026-08-11（Asia/Shanghai）  
角色：全新外部 Cursor 实现 Agent（`cursor-grok-4.5-high`）  
任务单：[`M1_HK-HISTORY-R3_递归异常图脱敏返工任务单.md`](M1_HK-HISTORY-R3_递归异常图脱敏返工任务单.md)  
前置 FAIL：[`M1_HK-HISTORY-R2_无行情事实与零网络恢复独立初验报告.md`](M1_HK-HISTORY-R2_无行情事实与零网络恢复独立初验报告.md) §3 F1

状态：**实现自测完成；未宣称独立初验 / 主验 / M1 Gate**

## 1. 变更摘要

对齐同模块 finalize-v3 / bar capability 已验收模式：在 R2 recover / evidence / seed / v2 plan·load·recover 可达边界，**先记录稳定错误码，退出 active `except` 后再** `raise HKHistoryBackfillError(code) from None`，使 public 失败的 `__cause__` 与 `__context__` 均为 `None`，递归异常图与 format traceback 不含 token / 供应商原文 / 绝对路径。

保持既有错误分类：`REFERENCE_INVALID` / `PLAN_CONFLICT` / `INCOMPLETE` / `RAW_INVALID` 不互相吞并；不改 bar∩no-trade、evidence identity、v2 journal/receipt、attempt/replay、`network_requests=0`、clean 零写或正式 finalize 语义；未触碰正式 `data/` / journal / clean；未联网；未 add/commit。

## 2. 白名单改动

| 路径 | 作用 |
|---|---|
| `src/quant/data/hk_history_backfill.py` | `load_hk_no_trade_evidence`、`build_hk_history_plan_v2`、`write_or_verify_plan`、`load_hk_history_plan`、`recover_existing_hk_history_requests`，以及 `_verify_evidence_projection` / `_load_seed` / `_validate_seed_raw` / `_bind_v2_journal` / `_write_or_verify_json` / `_verify_receipt` / `_write_receipt` / `_validate_raw` / `_read_and_validate_request` / `_raw_state` 改为 failure-flag 后抛出 |
| `tests/unit/test_hk_history_backfill.py` | 新增 hostile 递归图脱敏与 R2 独立反例正式回归 |
| `docs/framework/agent/M1_HK-HISTORY-R2_无行情事实与零网络恢复任务单.md` | 仅状态/链接 |
| `docs/framework/agent/M1_HK-HISTORY-R3_递归异常图脱敏返工任务单.md` | 仅状态 |
| 本报告 | 唯一交付报告 |

## 3. 新增正式回归（对照任务 §3）

1. `test_recover_sanitizes_hostile_anchored_read_exception_graph`：`_read_anchored_path` 注入 `RuntimeError(token+abs_path) from ValueError(token)` → exact `HK_HISTORY_REFERENCE_INVALID`，cause/context 空，递归图/traceback/repr 无 marker/path。
2. `test_recover_hostile_sites_keep_error_classification`：evidence / seed / binding / receipt / raw 五站点 hostile，错误码不漂移且递归脱敏。
3. `test_load_hk_no_trade_evidence_sanitizes_hostile_sites`：直接 loader 的 read / JSON / projection hostile 同级脱敏。
4. `recover→ABSENT→replay`、bar∩no-trade、01065 无 licensed evidence 缺行、不同 evidence closure 重签、binding hardlink+same-bytes inode replay、attempts 预植脏 journal：均已落正式单测并保持通过。
5. 全部 hostile 断言复用 `_assert_sanitized_exception`（递归 walk `__cause__`/`__context__` + `traceback.format_exception`）。

## 4. 验证摘要

### Windows 原生 Miniforge（`D:\Miniforge3\python.exe`）

```text
PYTHONPATH=<worktree>/src
pytest tests/unit/test_hk_history_backfill.py tests/unit/test_backfill_hk_history.py -q -p no:cacheprovider
→ 147 passed, 2 skipped

ruff check src/quant/data/hk_history_backfill.py tests/unit/test_hk_history_backfill.py
→ All checks passed!

mypy src/quant/data/hk_history_backfill.py
→ Success: no issues found in 1 source file

cold import → worktree src\quant\data\hk_history_backfill.py
git diff --check（白名单源码/测试）→ pass
```

### WSL Miniforge `base`（**DrvFS** `/mnt/f`，**非 ext4**）

```text
findmnt -T <worktree> → FSTYPE=drvfs
pytest 同组 → 149 passed
ruff / mypy / cold import → pass
```

不得将本 DrvFS 绿测表述为 ext4 Gate。

## 5. 边界

- 未宣称独立初验、主验、正式 HK60、licensed `01065`、M1 或 ext4 Gate。
- 本包仅修复 R2 F1 递归异常图脱敏；正式 evidence / v2 生产恢复 / batch 4–8 仍开放。
- 下一步：未参与本轮实现的全新 `cursor-grok-4.5-high` 会话独立复验；PASS 后仍须主 Agent 终验。
