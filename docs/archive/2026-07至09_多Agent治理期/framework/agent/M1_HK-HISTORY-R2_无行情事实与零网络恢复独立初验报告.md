# M1 HK-HISTORY-R2：无行情事实与零网络恢复独立初验报告

日期：2026-08-11（Asia/Shanghai）  
角色：未参与实现的全新外部 Cursor 独立初验 Agent（`cursor-grok-4.5-high`）  
结论：**FAIL**

本 PASS/FAIL 仅面向主 Agent 合同复验；**不解锁**正式 HK60 / M1 Gate。

## 1. 范围与只读边界

- 核对：`docs/framework/agent/M1_HK-HISTORY-R2_无行情事实与零网络恢复任务单.md`、`docs/framework/agent/M1_HK-HISTORY-R2开发实现报告.md`、actual `src/quant/data/hk_history_backfill.py`、`tests/unit/test_hk_history_backfill.py`。
- 生产代码、实现者测试、任务单与交付报告：**只读**。
- 唯一写入：本报告。
- 仅用 fixture / 系统临时目录；未访问正式 `data/`、未联网、未消耗供应商额度。
- 未修改代码、未 `git add/commit`、未跑全量 pytest。

## 2. 合同映射（摘要）

| 冻结项 | 独立核对 |
|---|---|
| 精确 no-trade evidence 与 effective expected | v2 plan/receipt 绑定 evidence-set SHA；raw 校验走 `effective_expected_dates` |
| 零网络 recover | `recover_existing_hk_history_requests` / CLI `--recover-existing-only` 在 connector 构造前分支；network=0 |
| 首个 ABSENT → `HK_HISTORY_INCOMPLETE` | 多批 fixture 复现；replay 同码且不写 attempt/intent |
| 无 licensed evidence 的 01065 | 缺 bar 且无豁免 → `HK_HISTORY_RAW_INVALID`（fail-closed） |
| 同 key bar 与 no-trade 冲突 | raw 仍含 evidence 日 bar → `HK_HISTORY_RAW_INVALID`，不写 receipt |
| 合法不同 closure 整体重签 | 新 evidence/plan SHA 对旧 journal → `HK_HISTORY_PLAN_CONFLICT`，旧 binding/receipt 字节不变 |
| 错误脱敏 | **未满足**项目已采用的递归 `__context__` 清空标准（见 §3） |

实现者自测覆盖大量 finalize-v3 / capability 对抗，但对 R2 recover 边界的“递归异常图脱敏”与“bar∩no-trade”等内存/临时目录反例不足；本轮补测。

## 3. FAIL 项（现象—根因—规则—最小复现—通过条件）

### F1. recover / evidence 投影路径未清空敌对异常 `__context__`

- **现象**：对 `_read_anchored_path` 注入带 token 与绝对路径的递归 `ValueError`→`RuntimeError` 后调用 `recover_existing_hk_history_requests`，公开 `str(exc)=="HK_HISTORY_REFERENCE_INVALID"`，但 `exc.__context__` 仍为含 `HOSTILE_VENDOR_TOKEN` 与绝对路径的 `RuntimeError`；按实现者自用 `_assert_sanitized_exception` 递归遍历 `__cause__/__context__` 即判定泄漏。`__cause__ is None`，`__context__ is not None`。
- **根因**：`_verify_evidence_projection` / `_load_seed` 等在 `except Exception:` **块内** `raise HKHistoryBackfillError(...) from None`。Python 仅清除 `__cause__` 并设 `__suppress_context__=True`，**不**清空 `__context__`。同文件 `load_verified_hkex_retained_bundle_for_finalize` 已用“`failed=True` 后在 except 外 raise”模式达到 `__context__ is None`，R2 recover 路径未对齐。
- **应遵循规则**：任务单 §8「错误输出不得包含 token、供应商原文或绝对路径」；同模块 finalize-v3 已冻结的递归异常图脱敏合同（`__cause__`/`__context__` 均为 `None`，格式化回溯无 marker）。
- **最小复现**（仅临时目录；示意）：
  1. 构造最小 v2 plan + synthetic evidence raw；
  2. monkeypatch `_read_anchored_path` 抛出 `RuntimeError(f"{marker} path={path}") from ValueError(marker)`；
  3. 调用 `recover_existing_hk_history_requests(...)`；
  4. 断言公开码为 `HK_HISTORY_REFERENCE_INVALID`，且递归 walk `__context__` **不得**见到 marker/绝对路径；`exc.__context__ is None`。
- **通过条件**：recover / evidence / seed 公共失败边界与 finalize loader 同级脱敏；新增实现者未覆盖的定向单测覆盖上述 monkeypatch；Windows 与 WSL base 定向 pytest 绿。

## 4. 独立对抗反例结果（实现者未用）

| 反例 | 结果 |
|---|---|
| 同 symbol/date raw bar ∩ no-trade evidence | **PASS** → `HK_HISTORY_RAW_INVALID`，无 receipt，无 clean |
| `01065` 无 licensed evidence 且 raw 缺行 | **PASS** → `HK_HISTORY_RAW_INVALID` |
| 合法不同 evidence closure 整体重签后 replay 旧 journal | **PASS** → `HK_HISTORY_PLAN_CONFLICT`，binding/receipt 字节不变 |
| journal `binding.json` hardlink 别名 + same-bytes 换 inode 后 replay | **PASS**（字节幂等 replay；inode 非合同主键；DrvFS/NTFS 非 ext4） |
| 预植 `attempts/` 脏 journal；以及正常 recover→ABSENT→replay 顺序 | **PASS**：预植 → `PLAN_CONFLICT`；正常路径 incomplete/replay 均 `INCOMPLETE`，仅 receipt、无 attempt/intent/clean |
| CLI `--recover-existing-only` 零 connector 构造、零 clean 写 | **PASS**：`constructs=0`，`clean`/`clean/bar_1d` 不存在（exit 1 因第二批 ABSENT，符合 incomplete） |
| hostile 递归异常脱敏 | **FAIL**（§3 F1） |

## 5. 验证证据

### Windows 原生 Miniforge（`D:\Miniforge3\python.exe`，3.13.13）

```text
PYTHONPATH=<worktree>/src
ruff check hk_history_backfill.py test_hk_history_backfill.py → All checks passed!
mypy src/quant/data/hk_history_backfill.py → Success: no issues found in 1 source file
cold import → worktree src\quant\data\hk_history_backfill.py
pytest tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider
→ 106 passed, 2 skipped（Windows symlink/特权相关）
```

### WSL Miniforge `base`（**DrvFS** `/mnt/f`，**非 ext4**）

```text
findmnt -T <worktree> → FSTYPE=drvfs
cold import → worktree 路径
ruff / mypy → pass
pytest tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider
→ 108 passed
```

平台特有终验不得将本 DrvFS 绿测表述为 ext4 Gate 已通过。

### 独立对抗脚本

- 宿主临时目录执行（非仓库白名单文件）；7 项中 6 PASS / 1 FAIL（F1）。

## 6. 边界与剩余风险

- 正式 `01065.HK@2026-05-05` licensed evidence、正式 v2 plan/journal 零网络恢复、batch 4–8、02983 合规来源与 HK60 Gate：**均未**在本轮声称关闭（与实现报告一致）。
- binding 合同按字节而非 inode；same-bytes 换 inode 可幂等 replay——记为已观察行为，非本轮否决点。
- CLI stderr 只打印稳定错误码，可掩盖库层 `__context__` 泄漏；库 API 与日志/调试 walk 仍暴露敌对上下文，故不能因 CLI 表象降级为非缺陷。

## 7. 结论

**FAIL** — 阻断进入主验关闭本子项。须先按 §3 F1 返工并对齐 finalize-v3 级递归异常脱敏，再交未参与该轮实现的外部初验复验。本报告不授权正式 HK60/M1 Gate 推进。
