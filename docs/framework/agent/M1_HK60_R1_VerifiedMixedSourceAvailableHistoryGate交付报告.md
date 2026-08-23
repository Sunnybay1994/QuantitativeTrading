# M1 HK60 R1 Verified Mixed-Source Available-History Gate 交付报告

日期：2026-08-15（Asia/Shanghai）  
模型：`cursor-grok-4.6-high`  
角色：外部实现 Agent（不得宣布 Gate 通过）  
结论：**R3 实现与 Windows 定向自测完成；待全新外部独立复验。** 不关闭真实 HK60 / W1 / Linux/ext4。

权威任务单：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate任务单.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate任务单.md)。设计审计的双时点错误以任务单为准。

---

## 1. 改动

白名单内：

- `src/quant/data/query.py`：mixed 值对象与 `BarQuery.recent_for_universe_mixed_audited` / `audit_available_history_mixed`
- `src/quant/data/query_universe.py`：`--source` 与 `--from-verified-hk-availability` 互斥；mixed 必填 `--plan` / `--journal-root` / `--verification-as-of` / `--require-available-history`
- `tests/unit/test_query.py`、`tests/unit/test_query_universe.py`：§10 反例
- 新增 `tests/support/hk_history_v3.py`：仅 public `finalize_hk_history` + `load_verified_hk_bar_bundle` 最小链
- `README.md`：仅 mixed CLI 入口与双时点说明
- 本报告；任务单状态改为待独立初验

未改 `src/quant/data/__init__.py`、backfill/schemas/配置/正式 data/artifacts/路线图。未 add/commit/push，未联网、未读 token。

---

## 2. 关键设计

- 两个时点分离：`--as-of` = 市场查询日，必须 exact 等于 `plan.as_of`；`--verification-as-of` = 操作员冻结的 aware UTC cutoff，直接传给首次 `load_verified_hk_bar_bundle` 与 output 前第二次 `verify_hk_bar_bundle`。禁止从查询日、wall clock、mtime 或 `max(availability)` 推断。
- mapping 只从 fresh `VerifiedHkBarBundle.availability.select(symbol, trade_date, source)` 派生，键集合必须 exact 等于 `plan.effective_expected_dates`。伪造 bundle / 子类 / pickle → `HK_BAR_VERIFY_FAILED`。
- DuckDB 物理重复或同键多源 → `BAR_WINDOW_DUPLICATE_KEY`；错源 → `BAR_WINDOW_REFERENCE_INVALID`。禁止 caller mapping、source priority、`ORDER BY source`、`DISTINCT ON`。
- 研究 frame = mapping 三列 exact join 后再按 symbol/date 最近 N；mapping 外更早 bar 不补窗。available-history 观察集用物理 last-N，以便豁免日 unexpected 与 equal-count wrong-date。
- mixed 只用 plan 内嵌 no-trade evidence；不读、不写 `evidence.json`。旧单源 API/CLI/JSON 仍读 `evidence.json`。
- public mixed CLI：load → query → AH → 第二次 verify；任一步失败不写 `--output`；稳定码脱敏且 `raise ... from None`。
- 正向 fixture 禁止 `object.__new__` 与 seal/registry/attestation monkeypatch。HKEX 解析器 monkeypatch 仅用于合成 retained raw。

---

## 3. Windows 定向自测

解释器：`D:\Miniforge3\python.exe`；`PYTHONPATH` 绑定本 worktree `src`。

| 命令 | 结果 |
|---|---|
| `python -m pytest -q tests/unit/test_query.py tests/unit/test_query_universe.py tests/unit/test_hk_history_backfill.py::test_v3_minimal_chain_covers_three_days_no_trade_and_hkex_supplement` | **70 passed** |
| `ruff check` 白名单 5 个 py | PASS |
| `ruff format --check` 同上 | 5 files already formatted |
| `mypy src/quant/data/query.py src/quant/data/query_universe.py` | Success: no issues found |
| cold import `quant.data.query` / `query_universe` + `python -m quant.data.query_universe -h` | `COLD_IMPORT_PASS verified-hk-availability-v1` |

未跑全量 pytest、真实 HK60、Linux/WSL Gate。既有 Pandera deprecation warning 不影响断言。

§10 反例均有对应测试：旧单源兼容；互斥/缺参；naive/非 UTC/`as_of≠plan`；双源/物理重复/错源/缺 mapped；mapping 外不补 N；UA 豁免 + 05-04 missing + 豁免日 unexpected；UA-001 plan 配 v2b journal；no-trade 篡改；STOCK 缺 Instrument / ETF 无 Instrument；equal-count wrong-date；伪造 bundle；二次 verify 漂移不写 output；hostile OSError 脱敏；模块源码不出现 Decimal / `ORDER BY source` / `DISTINCT ON`。正向 complete 路径不读 `evidence.json`。

---

## 4. 残余风险

- fixture 绿测 ≠ 真实双 Route Gate。真实关闭仍需主分支 v2b 8/8 零网络 recover、唯一 `--finalize-v3`、fresh bundle，以及 SH/SZ 各一次 mixed CLI（`as_of=2026-07-10`、`observations=60`、同一 operator-bound `verification_as_of`）。
- argparse 层 `--source` 与 mixed flag 均为可选，互斥在解析后以 `BAR_WINDOW_INPUT_INVALID` 失败，避免 argparse exit 2。
- 未改 `__init__.py`；mixed API 需从 `quant.data.query` 直接导入。
- Windows 定向自测不是 Linux/ext4 Gate。

下一步：未参与本实现的全新外部独立初验会话（`--model cursor-grok-4.6-high`）只读核对并补实现者未使用的对抗性反例。

---

## 5. R2 返工

日期：2026-08-15（Asia/Shanghai）  
模型：`cursor-grok-4.6-high`  
角色：外部返工实现 Agent（不得宣布 Gate 通过）  
结论：**R2 实现与 Windows 定向自测完成；待全新外部独立复验。**

权威返工项：任务单 §14；初验报告问题 1/2。未重写整体设计，未改 backfill/schema/`__init__.py`，未联网，未 add/commit/push。

### 5.1 关闭项

1. **mapping 外 bar 不得补 missing**  
   `audit_available_history_mixed` 将观察集显式拆开：missing 只看 fresh availability 三列 exact join 后的 mapped research frame；unexpected 仍用物理 last-N。availability 外成员或 required 日仅有未映射 bar 时 AH incomplete、不写 `--output`。豁免日 unexpected 与 equal-count wrong-date 回归保持。

2. **mixed AH 实际 Polars/IO 异常图**  
   `_load_official_connect_security_types` 在 active `except` 内只构造稳定异常，离开 handler 后 `raise ... from None`。测试捕获 **实际** `audit_available_history_mixed` 异常，断言 `__cause__ is None` 且 `__context__ is None`，repr/traceback 不含 hostile marker；不用新构造异常代替。

mixed 仍只消费 public backfill loader 已验真的 plan 内嵌 evidence，不硬编码 UA-M1-001/004/005 集合，不读写 `evidence.json`。

### 5.2 改动文件

- `src/quant/data/query.py`：拆分 missing/unexpected 观察集；官方 Route parquet 翻译退出 except 后再抛
- `tests/unit/test_query_universe.py`：§14 两反例 + 实际异常图测试
- 本报告 R2 章节；任务单状态改为待独立复验
- 未改 `README.md`、`query_universe.py`、`hk_history_v3.py`、`test_query.py`

### 5.3 Windows 定向自测

解释器：`D:\Miniforge3\python.exe`；`PYTHONPATH` 绑定本 worktree `src`。

| 命令 | 结果 |
|---|---|
| `python -m pytest -q tests/unit/test_query.py tests/unit/test_query_universe.py tests/unit/test_hk_history_backfill.py::test_v3_minimal_chain_covers_three_days_no_trade_and_hkex_supplement` | **73 passed**（原 70 + §14 新增 3） |
| `ruff check` 白名单 5 个 py | PASS |
| `ruff format --check` 同上 | 5 files already formatted |
| `mypy src/quant/data/query.py src/quant/data/query_universe.py` | Success: no issues found |
| cold import `quant.data.query` / `query_universe` + `-h` | `COLD_IMPORT_PASS verified-hk-availability-v1 heavy=[]` |

未跑全量 pytest、真实 HK60、Linux/WSL Gate。

### 5.4 残余风险

- fixture 绿测仍不等于真实双 Route Gate。真实关闭仍需最新 v2c（UA-M1-001/004/005 exact）8/8、唯一 `--finalize-v3`、fresh bundle，以及 SH/SZ 各一次 mixed CLI。
- 本轮不宣布独立复验或主验通过。下一步必须由未参与本 R2 实现的全新外部会话（`--model cursor-grok-4.6-high`）复验问题 1/2 的新增测试与独立反例。

---

## 6. R3 返工

日期：2026-08-15（Asia/Shanghai）  
模型：`cursor-grok-4.6-high`  
角色：外部返工实现 Agent（不得宣布 Gate 通过）  
结论：**R3 实现与 Windows 定向自测完成；待全新外部独立复验。**

权威返工项：任务单 §15；R2 独立复验问题 1。未改数据选择、物理顺序、来源、双时点、mapping 外 missing 语义、snapshot/event 已绿路径、旧单源 API/CLI。未改 backfill/schema/`__init__.py`/`README.md`，未联网，未 add/commit/push。

### 6.1 关闭项

calendar parquet 读取与 DuckDB `_physical_last_n` / `_select_mapped_recent_n` 底层失败改为 snapshot/event 同模式：active `except` 内只构造稳定 `BarWindowQueryError`，离开 handler 后 `raise ... from None`。实际损坏 calendar parquet 与实际 DuckDB bar IO 捕获的公共异常满足 `__cause__ is None` 且 `__context__ is None`；`repr`/`traceback`/`repr(__context__)` 不含 hostile marker、绝对路径或底层异常类型。CLI 失败不写 `--output`。

### 6.2 改动文件

- `src/quant/data/query.py`：calendar/instrument parquet 与两条 DuckDB 翻译退出 except 后再抛
- `tests/unit/test_query_universe.py`：实际损坏 calendar parquet 与实际 DuckDB physical last-N / mapped bar IO 异常图测试
- 本报告 R3 章节；任务单状态改为待独立复验
- 未改 `README.md`、`query_universe.py`、`hk_history_v3.py`、`test_query.py`

### 6.3 Windows 定向自测

解释器：`D:\Miniforge3\python.exe`；`PYTHONPATH` 绑定本 worktree `src`。

| 命令 | 结果 |
|---|---|
| focused：calendar / DuckDB bar IO / 既有 snapshot 异常图 | **3 passed** |
| `python -m pytest -q tests/unit/test_query.py tests/unit/test_query_universe.py tests/unit/test_hk_history_backfill.py::test_v3_minimal_chain_covers_three_days_no_trade_and_hkex_supplement` | **75 passed**（原 73 + §15 新增 2） |
| `ruff check` 白名单 5 个 py | PASS |
| `ruff format --check` 同上 | 5 files already formatted |
| `mypy src/quant/data/query.py src/quant/data/query_universe.py` | Success: no issues found |
| cold import `quant.data.query` / `query_universe` + `-h` | `COLD_IMPORT_PASS verified-hk-availability-v1 heavy=[]`；help 含 `--from-verified-hk-availability` |

未跑全量 pytest、真实 HK60、Linux/WSL Gate。既有 Pandera deprecation warning 不影响断言。

### 6.4 残余风险

- fixture 绿测仍不等于真实双 Route Gate。真实关闭仍需最新 v2c（UA-M1-001/004/005 exact）8/8、唯一 `--finalize-v3`、fresh bundle，以及 SH/SZ 各一次 mixed CLI。
- 损坏 clean bar 后从 CLI 入口重跑，可能先被 `load_verified_hk_bar_bundle`/`verify_hk_bar_bundle` 以 `HK_BAR_VERIFY_FAILED` 拒绝且不写 output；API 路径才覆盖实际 DuckDB IO 翻译。
- 本轮不宣布独立复验或主验通过。下一步必须由未参与本 R3 实现的全新外部会话（`--model cursor-grok-4.6-high`）复验 §15 实际 calendar/DuckDB 异常图与独立反例。
