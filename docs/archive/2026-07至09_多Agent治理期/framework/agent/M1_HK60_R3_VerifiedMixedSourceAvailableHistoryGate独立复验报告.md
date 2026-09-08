# M1 HK60 R3 Verified Mixed-Source Available-History Gate 独立复验报告

日期：2026-08-15（Asia/Shanghai）  
模型：`cursor-grok-4.6-high`  
角色：未参与 R1/R2/R3 实现的全新外部独立复验 Agent  
结论：**PASS。** 只解锁主 Agent 主验与真实 HK60 运行准备；不宣布 M1 / W1 / Linux/ext4 Gate。

权威任务单：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate任务单.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate任务单.md) §15  
R2 FAIL：[`M1_HK60_R2_VerifiedMixedSourceAvailableHistoryGate独立复验报告.md`](M1_HK60_R2_VerifiedMixedSourceAvailableHistoryGate独立复验报告.md)  
R3 交付：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate交付报告.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate交付报告.md) §6  
待验提交：`185c4fe`（R3 合同/旧报告提交 `bff7e8a`）；审查范围 `9dcff42..HEAD`

生产代码、实现测试、任务单、交付报告与旧复验报告保持只读。本文件为本次唯一写入。未 add/commit/push，未联网，未跑真实 finalize/query、全量 pytest 或 Linux。正向 capability 仅经 public `finalize_hk_history` + `load_verified_hk_bar_bundle`；未使用 `object.__new__` / seal / registry / attestation 签发合法 bundle。

---

## 1. 独立性与范围

- 未参与 R1/R2/R3 实现，独立上下文：是
- 模型如实记录为 `cursor-grok-4.6-high`
- 核对：AGENTS.md、`.ai/README.md`、任务单 §9/§10/§15、R1/R2 独立报告、R3 交付、`9dcff42..HEAD`、`query.py` / `query_universe.py`、实现测试与 `tests/support/hk_history_v3.py`
- 对抗反例均为系统临时目录进程，不落盘正式 `data/` / `artifacts/`
- 实现者未覆盖的独立攻击：合法但错误 schema 的 calendar/instrument/snapshot parquet（非 `NOT-A-PARQUET-FILE`）；额外 `date=*` 分区上的截断 parquet / XML 污染（不砸 as_of 文件）；`00001.HK@2026-07-09 source=wind` 与成员 `03690.HK`；闭市日 `2026-07-07` equal-count；event 截断为 `PAR1`+独立 marker

---

## 2. 标准—证据—结论

| 冻结项 | 独立证据 | 结论 |
|---|---|---|
| §15 实际损坏 calendar parquet，public mixed AH 捕获稳定 `BarWindowQueryError`，cause/context 均 None；绝对路径、底层类型、hostile marker 不出现在 str/repr/格式化 traceback | 成功 mixed query 后，把 calendar 写成 **合法但错误 schema** 的 parquet（列 `hostile_col`，marker `\\?\C:\r3-ind-cal-schema-9f3a\hostile.parquet`）。`audit_available_history_mixed` → `BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")`，`__cause__ is None` 且 `__context__ is None`；`str`/`repr`/`traceback.format_exception`/`repr(__context__)` 不含路径、`ComputeError`/`SchemaError`/`PAR1` 或 marker | **通过** |
| 实际损坏 DuckDB 读取的 bar parquet；分别覆盖 physical-last-N 与 mapped selection；不能用新构造异常替代实际底层失败 | **不砸 as_of 文件**。physical：额外 `date=2026-07-02` 截断 parquet + `R3IND_DUCKDB_PHYS_...`；mapped：额外 `date=2026-07-01` 写入 XML + `R3IND_MAPPED_SEL_...`。两条 public API 均捕获实际 IO 失败翻译后的稳定码，cause/context 皆空，无绝对路径/底层类型/marker | **通过** |
| CLI 在这些失败或前置 fresh verifier 更早拒绝时均无 output；不要求绕过正式 v3 verifier 强行抵达 DuckDB | calendar 错 schema CLI：`err=BAR_WINDOW_REFERENCE_INVALID`，stdout 空，output 不存在。额外损坏分区 CLI **自然抵达 DuckDB 翻译**（`BAR_WINDOW_REFERENCE_INVALID`，非必须 `HK_BAR_VERIFY_FAILED`），无 marker/路径，无 output | **通过** |
| R2 已关闭的 mapping 外 required-date bar、availability 外成员 bar、不同 source bar 仍不能补 missing；豁免日 unexpected 与 equal-count wrong-date 保持 | 未映射 `00001.HK@2026-07-09 source=wind` + 成员 `03690.HK@2026-07-10 source=hkex`：research 仅 mapped `2026-07-10/tushare`，AH incomplete，`missing_symbols` 含 `03690.HK`，missing_n=3，无 output。闭市 `2026-07-07` equal-count：missing=1 且 unexpected=1。`01065` 豁免日 bar → unexpected=1 | **通过** |
| snapshot/event 异常图、旧单源 API、双时点、fresh capability、无 evidence.json IO、row physical order 控制组 | snapshot 错 schema 与 event 截断 `PAR1`：cause/context 皆空。旧单源 CLI 仍把 `02983.HK` 记 tushare missing。naive / `+08:00` verification 拒绝且无 output。hostile `evidence.json` 字节不变且 patch `load_hk_no_trade_evidence` 仍成功。`object.__new__` / deepcopy / pickle 拒绝。as_of parquet 行反序后 source_row_counts 仍为 `(('hkex', 1), ('tushare', 2))` | **通过** |
| 正向 capability 必须走 public finalize/load/verify 最小链，不得 `object.__new__`、seal/registry monkeypatch | `publish_minimal_v3` 仅 public `finalize_hk_history` + `load_verified_hk_bar_bundle`；返回 `type is VerifiedHkBarBundle`。HKEX retained 解析器 monkeypatch 仅用于合成 raw，不签发 mixed capability | **通过** |

---

## 3. 问题

无。§15 calendar / DuckDB 实际异常图已关闭；R2 §14.1 mapping 外 missing 与豁免/equal-count 回归保持。

---

## 4. 独立对抗摘要（实现者未使用）

| 反例 | 结果 |
|---|---|
| calendar 写成合法错误 schema parquet（非 `NOT-A-PARQUET-FILE`） | **通过**：API cause/context 皆空；CLI 仅稳定码、无 output |
| 同 handler 的 instrument 错 schema parquet | **通过**：API 异常图完全脱敏 |
| 额外 `date=2026-07-02` 截断 parquet → `_physical_last_n` | **通过**：实际 DuckDB IO，cause/context 皆空 |
| 额外 `date=2026-07-01` XML 污染 → `_select_mapped_recent_n` | **通过**：实际 DuckDB IO，cause/context 皆空 |
| 上述两条 CLI（不绕过 v3 verifier） | **通过**：`BAR_WINDOW_REFERENCE_INVALID`，无 output、无路径/marker |
| 未映射 `00001.HK@2026-07-09 source=wind` + 成员 `03690.HK` | **通过**：research 仅 07-10 tushare；AH incomplete；无 output |
| 闭市 `2026-07-07` equal-count（非实现者 07-08） | **通过**：missing=1 且 unexpected=1，无 output |
| `01065` 豁免日 unexpected | **通过**：unexpected=1 |
| snapshot 错 schema；event 截断 `PAR1` | **通过**：cause/context 皆空 |
| 旧单源 02983 tushare missing；naive/`+08:00` cutoff | **通过** |
| forbid `load_hk_no_trade_evidence` + hostile evidence.json | **通过**：成功且文件未变 |
| `object.__new__` / deepcopy / pickle；行物理反序 | **通过**：伪造拒绝；counts 不变 |
| 源码无 `ORDER BY source` / `DISTINCT ON` / Decimal / UA-M1 硬编码；mixed CLI 不读 `evidence.json` | **通过** |

---

## 5. 验证

解释器：`D:\Miniforge3\python.exe`；`PYTHONPATH` 绑定本 worktree `src`。未联网。未设 PYTHONPATH 时会导入 site-packages 旧 `quant`（无 mixed API）；本轮证据均在绑定 worktree 后采集。

| 命令 | 结果 |
|---|---|
| focused：calendar / DuckDB bar IO / 既有 snapshot 异常图 3 项 | **3 passed** |
| `pytest -q tests/unit/test_query.py tests/unit/test_query_universe.py tests/unit/test_hk_history_backfill.py::test_v3_minimal_chain_covers_three_days_no_trade_and_hkex_supplement` | **75 passed** |
| `ruff check` 白名单 5 个 py | PASS |
| `ruff format --check` | 5 files already formatted |
| `mypy src/quant/data/query.py src/quant/data/query_universe.py` | Success: no issues found |
| cold import `quant.data.query` / `query_universe` + `-h` | `COLD_IMPORT_PASS verified-hk-availability-v1 heavy=[]`；help 含 `--from-verified-hk-availability` |
| 独立临时对抗（不落盘，25 项） | **25 passed / 0 failed** |

Windows 定向绿测 ≠ 真实双 Route Gate。Pandera deprecation warning 不影响断言。`9dcff42..HEAD` 文件集合未超出任务单白名单（生产 `query.py` / `query_universe.py`、实现测试、`hk_history_v3.py`、README mixed CLI、任务单/交付/R1·R2 报告）。

---

## 6. 已核对且本轮不阻塞的项

- calendar/instrument parquet 与 `_physical_last_n` / `_select_mapped_recent_n` 均已改为 except 内只构造稳定异常、离开 handler 后 `raise failure from None`
- snapshot/event 既有 leave-except 模式保持
- mapping 外 required-date / availability 外成员 / 不同 source 不能把 AH 补成 complete；禁止 `missing_symbols` 非空同时 AH complete
- mixed CLI `_run_mixed` 不读 `evidence.json`；旧单源路径仍引用该文件
- 二次 verify 在写 output 前（实现者漂移测试仍绿）
- `__init__.py`、backfill、schema、正式 data/artifacts 未被本实现修改

---

## 7. 残余风险

- fixture 绿测不关闭真实 HK60 / W1 / Linux/ext4。真实关闭仍需最新 v2c（UA-M1-001/004/005 exact）8/8、唯一 `--finalize-v3`、fresh bundle，以及 SH/SZ 各一次 mixed CLI（`as_of=2026-07-10`、`observations=60`、同一 operator-bound `verification_as_of`）。
- mixed Python 查询原语只做 `type is VerifiedHkBarBundle`，不重放 attestation；formal 闭环仍依赖 CLI 两次 public verifier。
- 对 caller 提供的 journal 做新鲜 load（copied tree、新 inode）可以自成一条 capability；拒绝的是“旧 bundle 换 copied root”的二次 verify。
- `query_universe._parse_verification_as_of` 对非法 ISO 字符串仍在 active `except ValueError` 内 `raise ... from None`。CLI 只打印稳定码且本轮 naive/`+08:00` 无 output；该路径不是 §15 的 Polars/DuckDB/IO 公共 mixed AH 边界，不构成本轮 FAIL。若后续把 CLI 解析异常图也纳入 §9 全闭包，需同样改为离开 handler 后再抛。
- 实现者砸 as_of bar 后 CLI 可能先被 fresh verifier 以 `HK_BAR_VERIFY_FAILED` 拒绝；本轮独立反例用 **额外分区** 在不绕过 verifier 的情况下实际打到 DuckDB 翻译，两条失败语义均无 output。

---

## 8. 结论

**进入主 Agent 第 4 步主验。** 复验通过，但不宣布 M1 / W1 / Linux/ext4 Gate，也不代替真实 HK60 双 Route 运行。

§15 calendar parquet 与 DuckDB physical-last-N / mapped selection 的实际异常图已关闭：public `__cause__` / `__context__` 均为 `None`，str/repr/traceback 不含绝对路径、底层类型或 hostile marker；CLI 失败不写 `--output`。R2 已关闭的 mapping 外 missing 与豁免/equal-count 经不同证券、不同 source、不同闭市日独立反例保持。主验仍须在真实依赖上完成 v2c 8/8、唯一 `--finalize-v3`、fresh bundle 与 SH/SZ mixed CLI。
