# M1 HK60 R2 Verified Mixed-Source Available-History Gate 独立复验报告

日期：2026-08-15（Asia/Shanghai）  
模型：`cursor-grok-4.6-high`  
角色：未参与 R1/R2 实现的全新外部独立复验 Agent  
结论：**FAIL / 返回返工。** 只解锁返工，不进入主 Agent 主验，不宣布真实 HK60 / W1 / Linux/ext4 Gate。

权威任务单：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate任务单.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate任务单.md) §14  
R1 FAIL：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate独立初验报告.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate独立初验报告.md)  
R2 交付：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate交付报告.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate交付报告.md) §5

生产代码、实现测试、任务单与既有报告保持只读。本文件为本次唯一写入。未 add/commit/push，未联网，未跑真实 HK60 或 Linux。正向 capability 仅经 public `finalize_hk_history` + `load_verified_hk_bar_bundle`；未使用 `object.__new__` / seal / registry / attestation 签发合法 bundle。

---

## 1. 独立性与范围

- 未参与 R1/R2 实现，独立上下文：是
- 模型如实记录为 `cursor-grok-4.6-high`
- 核对：AGENTS.md、`.ai/README.md`、任务单（含 §9/§10/§14）、R1 交付与 FAIL、R2 交付、`query.py` / `query_universe.py`、实现测试与 `tests/support/hk_history_v3.py`
- 对抗反例均为系统临时目录进程，不落盘正式 `data/` / `artifacts/`
- 实现者未覆盖的独立攻击：错 source 未映射 bar、不同开市日、availability 内证券的未映射日、非 09999 成员、event/calendar/physical-bar parquet、DuckDB IO 异常图、`object.__new__` / copy / deepcopy

---

## 2. 标准—证据—结论

| 冻结项 | 独立证据 | 结论 |
|---|---|---|
| §14.1 missing 只由 fresh availability `(symbol,trade_date,source)` exact mapped rows 满足；物理 last-N 只能产生 unexpected | 未映射 `00001.HK@2026-07-08 source=hkex`、`00002.HK@2026-07-09 source=yahoo`、成员 `08888.HK` 均 `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`、`missing_session_total>=1`、无 `--output`；research frame 仍只有 mapped `2026-07-10` | **通过** |
| 豁免日 unexpected、equal-count wrong-date、mapping 外更早 bar 不进 research frame；无 sort/distinct/source priority | 07-08 闭市 equal-count 仍 missing+unexpected；01065 豁免日 bar → unexpected=1；模块源码无 `ORDER BY source` / `DISTINCT ON` / Decimal / UA-M1 硬编码 | **通过** |
| §14.2 / §9 实际损坏 snapshot/parquet/IO 的 API 与 CLI 异常图完全脱敏 | event parquet：API `__cause__ is None` 且 `__context__ is None`，CLI 仅稳定码。calendar parquet 与 physical last-N / mapped DuckDB IO：API `__cause__ is None` 但 `__context__` 仍为 Polars `ComputeError` / DuckDB `InvalidInputException`（含绝对路径） | **不通过（问题 1）** |
| fresh plan 可含 UA-M1-001/004/005；mixed 零读写 `evidence.json` | `query.py` / `query_universe.py` 无 UA 集合硬编码；mixed 完整路径 patch `load_hk_no_trade_evidence` 仍成功，hostile `evidence.json` 字节不变；单源 CLI 仍引用 `evidence.json` | **通过** |
| 双时点、二次 verify、旧单源、route/Instrument、fake/subclass/pickle/copy、失败无 output | naive/`+08:00` verification 拒绝且无 output；`SimpleNamespace` / `object.__new__` / pickle / copy / deepcopy 拒绝；实现者二次 verify 漂移与 STOCK/ETF 测试仍绿 | **通过**（旧单源 02983 tushare missing 以实现者测试为准） |

---

## 3. 问题

### 问题 1 — mixed AH/query 的 calendar 与 DuckDB parquet/IO 翻译未离开 active `except`，`__context__` 仍指向底层异常

- **现象**：R2 已修复的 snapshot/event 路径（`_load_official_connect_security_types`）在损坏 parquet 后，实际捕获的 `BarWindowQueryError` 满足 `__cause__ is None` 且 `__context__ is None`。但同一 public `audit_available_history_mixed` / `recent_for_universe_mixed_audited` 在损坏 **calendar parquet** 或 **bar_1d parquet** 后：`str`/`repr`/`traceback.format_exception(exc)` 不含 hostile marker，CLI 也只印稳定码，然而 `exc.__context__` 仍为底层异常。calendar 为 Polars `ComputeError('parquet: File out of specification: The file must end with PAR1')`；physical last-N / mapped DuckDB 为 `InvalidInputException`，消息含绝对路径（`...\bar_1d\date=2026-07-10\data.parquet`）。`__suppress_context__` 为 True，故默认 traceback 不展开，但 public 异常图属性并未清空。
- **根因**：任务单 §9 要求翻译**退出** active `except` 后再 `raise ... from None`。R2 只把该模式用在 `_load_official_connect_security_types`（except 内赋值，except 外 `raise failure from None`）。calendar/instrument 读取与 `_physical_last_n` / `_select_mapped_recent_n` 仍在 except **内部** `raise BarWindowQueryError(...) from None`。PEP 409 下这只清空 `__cause__` 并设置 `__suppress_context__`，`__context__` 仍绑定原异常。实现者新增测试只砸 snapshot，未捕获实际 calendar/DuckDB 异常图。
- **应遵循规则**：任务单 §9、§10.18、§14.2：所有 mixed 翻译离开 active `except` 后抛出；public `__cause__`/`__context__` 均为空；不得把路径、单元格、token、hostile marker 留给调用方；必须检查**实际捕获**的异常，不得用新构造异常代替。
- **最小复现**（系统临时目录，public v3 fixture）：
  1. `publish_minimal_v3` + mixed refs + `recent_for_universe_mixed_audited` 成功后，将 `clean/trade_calendar/market=HK/data.parquet` 写成非 parquet 字节（含 hostile marker）。调用 `audit_available_history_mixed` → `BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")`，`__cause__ is None`，**`__context__` 为 `ComputeError`**。
  2. 同样在 mapped query 成功后损坏 `bar_1d/date=2026-07-10/data.parquet`，再调用 `audit_available_history_mixed`（走 `_physical_last_n`）或直接 `recent_for_universe_mixed_audited`（走 `_select_mapped_recent_n`）→ `__context__` 为带绝对路径的 DuckDB `InvalidInputException`。
- **必须新增的测试**：对 **实际捕获** 的 mixed AH calendar/instrument parquet 异常、physical last-N parquet/IO 异常、mapped query parquet/IO 异常，断言 `__cause__ is None` 且 `__context__ is None`，`repr` 与 `traceback.format_exception(exc)` 以及 `repr(exc.__context__)` 均无 marker/路径；禁止用新构造异常代替。CLI 保持稳定码且无 output。实现者原 snapshot/event 测试仍绿。
- **通过条件**：上述三处翻译改为与 snapshot 相同的“except 内只构造、离开 handler 后 `raise ... from None`”；独立 calendar/bar IO 反例 API `__context__ is None`；定向测试全绿。

---

## 4. 独立对抗摘要（实现者未使用）

| 反例 | 结果 |
|---|---|
| 未映射 `00001.HK@2026-07-08 source=hkex`（不同日期 + 错 source） | **通过**：AH incomplete、missing≥1、无 output；research 仅 07-10 |
| 成员 `08888.HK` 不在 availability，clean 有 tushare bar | **通过**：`missing_symbols` 含 08888，AH incomplete，无 output |
| availability 内 `00002.HK` + 未映射 `07-09 source=yahoo` | **通过**：incomplete、无 output；research 仅 mapped as_of |
| 07-08 闭市 equal-count + 01065 豁免日 unexpected | **通过**：仍同时 missing/unexpected；豁免日 unexpected=1 |
| 损坏 **event** parquet（非 snapshot） | **通过**：API cause/context 皆空；CLI 仅 `BAR_WINDOW_REFERENCE_INVALID` |
| 损坏 **calendar** parquet | **FAIL**：API `__context__=ComputeError` |
| 损坏 **physical last-N / mapped** bar parquet | **FAIL**：API `__context__` 含绝对路径；CLI 在写 output 前因 bundle verify 得到 `HK_BAR_VERIFY_FAILED`（稳定码、无 marker、无 output，不单列产品缺陷） |
| mixed 完整路径 forbid `load_hk_no_trade_evidence` + hostile evidence.json | **通过**：成功且文件未变 |
| date-only / `+08:00` verification-as-of | **通过**：拒绝，无 output |
| `SimpleNamespace` / `object.__new__` / pickle / copy / deepcopy | **通过**：均 fail closed |
| 源码无 `ORDER BY source` / `DISTINCT ON` / UA-M1 硬编码 | **通过** |

---

## 5. 验证

解释器：`D:\Miniforge3\python.exe`；`PYTHONPATH` 绑定本 worktree `src`。未联网。

| 命令 | 结果 |
|---|---|
| `pytest -q tests/unit/test_query.py tests/unit/test_query_universe.py tests/unit/test_hk_history_backfill.py::test_v3_minimal_chain_covers_three_days_no_trade_and_hkex_supplement` | **73 passed**（含 §14 新增 3；未覆盖本报告 calendar/DuckDB `__context__`） |
| `ruff check` 白名单 5 个 py | PASS |
| `ruff format --check` | 5 files already formatted |
| `mypy src/quant/data/query.py src/quant/data/query_universe.py` | Success: no issues found |
| cold import `quant.data.query` / `query_universe` + `-h` | `COLD_IMPORT_PASS verified-hk-availability-v1 heavy=[]`；help 含 `--from-verified-hk-availability` |
| 独立临时对抗（不落盘） | §14.1 通过；§14.2 snapshot/event 通过；calendar/DuckDB IO 异常图 FAIL |

Windows 定向绿测 ≠ 真实双 Route Gate。Pandera deprecation warning 不影响断言。

---

## 6. 已核对且本轮不阻塞的项

- §14.1 观察集拆分：`audit_available_history_mixed` 以 `audited.frame`（mapped exact join）算 missing，以 `_physical_last_n` 算 unexpected；未映射行不能把 AH 补成 complete
- 禁止 `missing_symbols` 非空同时 `is_available_history_complete=true`（08888 反例）
- `--source` 与 mixed 互斥；mixed 缺参 / `--require-full-window` → `BAR_WINDOW_INPUT_INVALID`
- 二次 verify 在写 output 前（实现者漂移测试仍绿）
- 正向 fixture 未走 capability 内部绕过；`hk_history_v3.py` 仅 HKEX retained 解析器 monkeypatch
- `__init__.py`、backfill、schema、正式 data/artifacts 未被本实现修改
- 损坏 clean bar 后从 CLI 入口重跑，先被 `load_verified_hk_bar_bundle`/`verify_hk_bar_bundle` 以 `HK_BAR_VERIFY_FAILED` 拒绝且不写 output，属 fail-closed，不是本问题的 CLI 泄漏

---

## 7. 残余风险（即使本问题返工通过后仍存在）

- fixture 绿测不关闭真实 HK60 / W1 / Linux/ext4。真实关闭仍需最新 v2c（UA-M1-001/004/005 exact）8/8、唯一 `--finalize-v3`、fresh bundle、SH/SZ 各一次 mixed CLI。
- mixed Python 查询原语只做 `type is VerifiedHkBarBundle`，不重放 attestation；formal 闭环仍依赖 CLI 两次 public verifier。
- 对 caller 提供的 journal 做新鲜 load（copied tree、新 inode）可以自成一条 capability；拒绝的是“旧 bundle 换 copied root”的二次 verify。

---

## 8. 结论

**返回外部实现 Agent 返工。** 复验不通过，主 Agent 不得进入第 4 步主验，也不得自行改代码跳过独立复验。

§14.1 mapping 外 bar 补 missing 已关闭，且经不同日期 / 不同证券 / 错 source 独立反例确认。§14.2 仅关闭了 snapshot/event 的 `from exc`；calendar 与 DuckDB parquet/IO 仍违反 §9 的 `__context__` 空图合同。返工后必须再由未参与该轮实现的全新外部会话复验本报告问题 1 的新增测试及独立反例。
