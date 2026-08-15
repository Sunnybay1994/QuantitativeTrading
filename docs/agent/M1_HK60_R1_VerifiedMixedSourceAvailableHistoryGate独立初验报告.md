# M1 HK60 R1 Verified Mixed-Source Available-History Gate 独立初验报告

日期：2026-08-15（Asia/Shanghai）  
模型：`cursor-grok-4.6-high`  
角色：未参与实现的全新外部独立初验 Agent  
结论：**FAIL / 返回返工。** 只解锁返工任务，不进入主 Agent 主验，不宣布真实 HK60 / W1 / Linux/ext4 Gate。

权威任务单：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate任务单.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate任务单.md)  
实现交付报告：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate交付报告.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate交付报告.md)

生产代码与实现测试保持只读。本文件为本次唯一写入。未 add/commit/push，未联网，未跑真实 HK60 或 Linux。

---

## 1. 独立性与范围

- 未参与实现，独立上下文：是
- 模型如实记录为 `cursor-grok-4.6-high`
- 核对：任务单、交付报告、白名单 diff、`src/quant/data/query.py`、`src/quant/data/query_universe.py`、`tests/unit/test_query.py`、`tests/unit/test_query_universe.py`、`tests/support/hk_history_v3.py`
- 正向 fixture 经 public `finalize_hk_history` + `load_verified_hk_bar_bundle`；未使用 `object.__new__` / seal / registry / attestation monkeypatch 构造合法 capability
- 对抗反例均为临时进程，不落盘正式 `data/` / `artifacts/`

---

## 2. 标准—证据—结论

| 冻结项 | 独立证据 | 结论 |
|---|---|---|
| 双时点分离；naive / 非 UTC / 日期-only 在写 output 前拒绝 | `--verification-as-of 2026-08-16`、`+08:00` → `BAR_WINDOW_INPUT_INVALID` 且无 parquet；`Z` / `-00:00` 接受为 UTC，成功 JSON 为 `+00:00`，`as_of` 仍为 `2026-07-10`；显式 `2026-07-10T23:59:59+00:00` 作为验真 cutoff → `HK_BAR_PUBLICATION_INVALID`、无 output（代码未从查询日派生 cutoff） | 通过 |
| mapping 只来自 fresh exact availability；伪造 / 子类 / pickle / 额外键 | `type is not VerifiedHkBarBundle`、`VerifiedHkBarBundle()`、pickle、子类在实现测试中拒绝；独立 `object.__new__` 附加 availability 超集键 → `HK_BAR_VERIFY_FAILED`；原 bundle 对 copied journal 二次 `verify_hk_bar_bundle` → `HK_BAR_VERIFY_FAILED` | 通过（Python API 不重验 attestation，见残余） |
| 同键双源 / 重复 / 错源 / mapping 外补窗 / equal-count | 实现测试覆盖双源、物理重复、错源、closed-day equal-count、mapping 外更早 bar 不进入 **research frame**。独立反例证明 mapping 外 bar 仍可补 **available-history required sessions** 并写 `--output` | **不通过（问题 1）** |
| mixed 零读写 `evidence.json`；UA 篡改 | 完整路径 monkeypatch `load_hk_no_trade_evidence` 仍成功；hostile `evidence.json` 字节不变。UA-M1-001 raw 追加 → `HK_BAR_VERIFY_FAILED`、无 output | 通过 |
| STOCK/ETF、SH/SZ、旧单源兼容 | 实现测试覆盖缺 Instrument / 官方 ETF 无 Instrument；独立 SZ 查询不泄漏 SH 成员 `00001.HK`；旧单源 02983 tushare missing 保持 | 通过 |
| hostile cause/context/repr；失败无 output；cold import | CLI 损坏 snapshot：stderr 仅稳定码、无 marker、无 output。mixed AH **API** 翻译保留 `__cause__`/`__context__`。cold import 未加载 qlib/lightgbm/mlflow/tushare | **不通过（问题 2）**；cold import 通过 |
| 正向 capability 仅 public finalize/load | `tests/support/hk_history_v3.py` 仅 HKEX retained 解析器 monkeypatch，无 seal/registry/attestation/`object.__new__` 签发 | 通过 |

---

## 3. 问题

### 问题 1 — mapping 外 bar 把 available-history 补成 complete 并写出 output

- **现象**：合法 v3 发布后，向 clean 追加 **不在** `VerifiedHkBarBundle.availability` 中的 bar。mixed CLI 的 research frame 仍按三列 exact join（短窗 / missing），但 `available_history.is_available_history_complete=true`、`missing_session_total=0`，并且 **写入 `--output`**。成功 JSON 可以同时出现 `missing_symbols=["09999.HK"]` 与 `is_available_history_complete=true`。
- **根因**：`audit_available_history_mixed` 把 `_physical_last_n`（不 join mapping、不要求 mapped source）整份当作 `observed_frame`。`_available_history_from_references` 用同一观察集计算 missing 与 unexpected。物理 last-N 里的未映射行被当成 required session 已到齐。CLI 只以 AH complete 决定写盘，不要求 mapped frame 覆盖那些 session。
- **应遵循规则**：任务单 §6.4 mapping 外 bar 不得补窗；§6.5 mapped source 缺行必须进入 `missing_sessions`；§8 只有 complete 才写 `--output`。物理 last-N 只应用于 unexpected（豁免日出现 bar、equal-count wrong-date），不得满足 missing。
- **最小复现**（临时 fixture，不落盘正式数据）：
  1. `publish_minimal_v3`；成员仅 `00001.HK`；日历 `2026-07-09`/`2026-07-10` 开市；`list_date=2026-07-09`；`--observations 2`。plan/mapping 仅有 `00001.HK@2026-07-10`。追加未映射 `00001.HK@2026-07-09` tushare bar。mixed CLI → **code=0，output 存在，AH complete，research 仅 1 行（07-10）**。
  2. 合法 v3 后把 `09999.HK` 写入 SH 成员与 Instrument/snapshot，并追加其 as_of tushare bar（该键不在 availability）。mixed CLI → **code=0，`missing_symbols=['09999.HK']`，AH complete=true，output 存在**。
- **必须新增的测试**：
  1. 未映射 bar 落在 required 且不在 mapping 的开市日：`BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`，`missing_session_total>=1`，不写 output；research frame 仍不得含该行。
  2. 成员中存在 availability 以外的 STOCK，即使 clean 有未映射 bar：不得 AH complete，不得写 output；禁止 `missing_symbols` 非空同时 `is_available_history_complete=true`。
  3. 回归：豁免日 unexpected 与 closed-day equal-count 仍依赖物理 last-N，不得被“missing 改回 mapped frame”破坏。
- **通过条件**：missing 只由 **mapped 三列 exact 出现** 判定；unexpected 可由物理 last-N 产生；未映射行永远不能把 AH 补成 complete；上述两反例 CLI 非零且 `--output` 不存在；实现者原 70 项定向测试仍绿。

### 问题 2 — mixed AH 翻译未切断 `__cause__` / `__context__`

- **现象**：损坏 `connect_snapshot` parquet 后调用 `audit_available_history_mixed`，抛出 `BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")`，但 `__cause__` 与 `__context__` 均为 Polars `ComputeError('parquet: File out of specification: The file must end with PAR1')`。CLI stderr 只有稳定码，无 hostile marker，也无 output。
- **根因**：`_load_official_connect_security_types` 使用 `raise BarWindowQueryError(...) from exc`。mixed AH 经 `_available_history_from_references` 直接暴露该翻译。实现者 hostile 测试对 **新构造** 的 `HKHistoryBackfillError` 做 `traceback.format_exception`，未检查实际捕获异常的 cause 图。
- **应遵循规则**：任务单 §9 所有翻译退出 active `except` 后 `raise ... from None`，`__cause__` / `__context__` 必须为空；不得把底层单元格/路径类异常图留给调用方。
- **最小复现**：public v3 + mixed audited window 后，把 snapshot parquet 写成非 parquet 字节，调用 `audit_available_history_mixed`，断言 `exc.__cause__ is None and exc.__context__ is None`。
- **必须新增的测试**：对 **实际捕获** 的 mixed AH / CLI 翻译异常检查 `__cause__`、`__context__`、`repr` 不含 marker；禁止用新构造异常代替。
- **通过条件**：将该 `from exc` 改为 `from None`（或在 mixed 边界再包一层 `from None`）；新测试绿；CLI 行为保持稳定码。

---

## 4. 独立对抗摘要（实现者未使用）

| 反例 | 结果 |
|---|---|
| date-only / `+08:00` verification-as-of | 拒绝，无 output |
| `Z` / `-00:00` UTC | 接受；JSON cutoff 与 `as_of` 分离 |
| 查询日 `23:59:59+00:00` 作 verification cutoff | 发布验真失败，无 output；代码未自动派生 |
| mixed 完整路径 forbid `load_hk_no_trade_evidence` + hostile evidence.json | 成功且文件未变 |
| **mapping 外 required-date bar** | **FAIL：AH complete 并写 output** |
| **availability 外成员 + 未映射 bar** | **FAIL：missing_symbols 与 AH complete 并存并写 output** |
| 原 bundle + copied journal 二次 verify | `HK_BAR_VERIFY_FAILED` |
| copied journal 作为 CLI 新 root 新鲜 load | 通过（残余：fresh load 绑定新 inode，不是 capability 换根） |
| `object.__new__` availability 超集键 | `HK_BAR_VERIFY_FAILED` |
| UA-M1-001 raw 篡改 | `HK_BAR_VERIFY_FAILED`，无 output |
| SZ 查询不泄漏 SH 成员 | 通过 |
| 损坏 snapshot mixed AH cause 图 | **FAIL：cause/context 非空**；CLI 输出脱敏通过 |

---

## 5. 验证

解释器：`D:\Miniforge3\python.exe`；`PYTHONPATH` 绑定本 worktree `src`。未联网。

| 命令 | 结果 |
|---|---|
| `pytest -q tests/unit/test_query.py tests/unit/test_query_universe.py tests/unit/test_hk_history_backfill.py::test_v3_minimal_chain_covers_three_days_no_trade_and_hkex_supplement` | **70 passed**（实现者测试未覆盖问题 1/2） |
| `ruff check` 白名单 5 个 py | PASS |
| `ruff format --check` | 5 files already formatted |
| `mypy src/quant/data/query.py src/quant/data/query_universe.py` | Success: no issues found |
| cold import `quant.data.query` / `query_universe` + `-h` | `COLD_IMPORT_PASS verified-hk-availability-v1 heavy=[]` |
| 独立临时对抗（不落盘） | 问题 1、2 FAIL |

Windows 定向绿测 ≠ 真实双 Route Gate，也不覆盖本次独立反例。

---

## 6. 已核对且本轮不阻塞的项

- `--source` 与 `--from-verified-hk-availability` 互斥；mixed 缺 plan/journal/verification-as-of/available-history 或夹带 `--require-full-window` → `BAR_WINDOW_INPUT_INVALID`
- 无 `ORDER BY source` / `DISTINCT ON` / Decimal / caller mapping 参数
- 二次 verify 在写 output 前；clean 漂移不写盘（实现测试）
- 正向 fixture 未走 capability 内部绕过
- `__init__.py`、backfill、schema、正式 data/artifacts 未被本实现修改

---

## 7. 残余风险（即使返工通过后仍存在）

- fixture 绿测不关闭真实 HK60 / W1 / Linux/ext4。真实关闭仍需主分支 v2b 8/8、唯一 `--finalize-v3`、fresh bundle、SH/SZ 各一次 mixed CLI。
- mixed Python 查询原语只做 `type is VerifiedHkBarBundle`，不重放 attestation；formal 闭环仍依赖 CLI 两次 public verifier。
- 对 caller 提供的 journal 做 **新鲜** load（copied tree、新 inode）可以自成一条 capability；拒绝的是“旧 bundle 换 copied root”的二次 verify。
- 问题 2 的 CLI 面已脱敏；未修 API cause 图前不得宣称异常图合同满足。

---

## 8. 结论

**返回外部实现 Agent 返工。** 初验不通过，主 Agent 不得进入第 4 步主验，也不得自行改代码跳过独立初验。

返工后必须再由未参与该轮实现的全新外部初验会话复验问题 1 与问题 2 的新增测试及独立反例。
