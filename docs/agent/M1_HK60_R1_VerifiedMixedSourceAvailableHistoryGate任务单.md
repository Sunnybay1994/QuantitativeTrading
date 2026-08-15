# M1 HK60 R1 Verified Mixed-Source Available-History Gate 任务单

状态：**R2 返工已冻结；R1 独立初验 FAIL。** 必须关闭 mapping 外 bar 补足 required session 与 API 异常图泄漏后，再由全新外部会话复验。真实双 Route Gate 必须等待包含最新 exact no-trade 集合的 HK60 v2c 8/8、唯一 `--finalize-v3` 与 fresh bundle 验真完成。

日期：2026-08-15（Asia/Shanghai）  
平台边界：Windows 工程闭环；不声明 Linux/ext4 Gate。  
外部会话：实现与独立初验必须使用两个全新 Cursor 会话，均显式 `--model cursor-grok-4.6-high`。  
设计依据：[`M1_HK60_R1_MixedSourceAvailableHistoryGate外部只读设计审计报告.md`](M1_HK60_R1_MixedSourceAvailableHistoryGate外部只读设计审计报告.md)。本任务单修正该报告中把研究查询日当作发布验真 cutoff 的时间语义错误；冲突时以本任务单为准。

---

## 1. 目标与非目标

### 1.1 目标

在不改变现有单源查询合同的前提下，为 HK60 v3 增加一个来源可证明的 mixed-source 查询与 available-history Gate：

- 绝大多数有效键的 bar `source=tushare`；
- `02983.HK@2026-07-10` 的正式补充 bar `source=hkex`；
- 每个 `(symbol, trade_date)` 的唯一允许来源只从 fresh `VerifiedHkBarBundle.availability` 派生；
- v2 plan 内嵌且已由 backfill loader 验真的 exact no-trade evidence 直接用于豁免，不发布第二份 evidence SSOT；当前真实恢复计划将包含 UA-M1-001/004/005；
- 查询同时输出最近 N 行和 exact coverage；只有 source、session、instrument、route membership 和 fresh publication 全部闭合才允许写 `--output`。

### 1.2 非目标

- 不改变现有 `--source`、`BarWindowCoverage`、`AuditedBarWindow`、`AvailableHistoryCoverage` 的单源语义。
- 不修改 `hk_history_backfill.py`、`backfill_hk_history.py`、`schemas.py`、正式 data/artifacts。
- 不物化 `data/clean/hk_no_trade_evidence/evidence.json`；mixed 路径不得读取它。旧单源路径继续维持现状。
- 不实现港股复权、公司行动 formal P1C、ETF licensed Instrument 或 Linux/ext4。
- fixture 绿测不关闭真实 HK60/W1/M1 Gate。

---

## 2. 必须保持的旧合同

以下 public API、返回类型、单源 JSON 与失败行为保持兼容：

```python
BarQuery.recent_for_universe(..., source: str, observations: int = 60) -> pl.DataFrame
BarQuery.recent_for_universe_audited(..., source: str, observations: int = 60) -> AuditedBarWindow
BarQuery.recent_for_universe_available_history_audited(..., source: str, ...) -> AuditedAvailableHistoryBarWindow
BarQuery.audit_available_history(audited: AuditedBarWindow, ...) -> AuditedAvailableHistoryBarWindow
```

现有 CLI `python -m quant.data.query_universe ... --source TEXT` 继续合法。单源 Tushare 查询在 mixed clean 中把 02983 当日记为 missing 是旧合同，不允许为通过 Gate 而偷偷改变。

---

## 3. 时间语义（主 Agent 修正项）

必须区分两个时点：

1. `--as-of DATE`：市场查询日/窗口终点；本 Gate 为 `2026-07-10`，必须 exact 等于 `plan.as_of`。
2. `--verification-as-of DATETIME`：发布及 retained source 在何时已经可知的 aware UTC cutoff，直接传给 `load_verified_hk_bar_bundle` 与第二次 `verify_hk_bar_bundle`。

禁止把 `--as-of 2026-07-10` 派生为 `2026-07-10T23:59:59Z` 作为 bundle cutoff。正式 retained raw、receipt 和 HKEX metadata 是 2026-08 才取得，使用查询日作 cutoff 会让真实发布必然自拒绝。

`--verification-as-of` 必须由操作员绑定记录显式冻结；不得使用进程 wall clock、文件 mtime、`max(availability)` 后读自适应，亦不得回流成策略的 PIT `as_of`。本 Gate 是事后完整性验收，不证明这些数据在 2026-07-10 当时可知。

---

## 4. 新 CLI 合同

将 `--source` 与新 flag 放入 required mutually-exclusive group：

```text
--source TEXT
--from-verified-hk-availability
```

当且仅当选择 mixed 路径，以下参数必填：

```text
--plan PATH
--journal-root PATH
--verification-as-of AWARE_UTC_ISO8601
--require-available-history
```

已有 `--universe`、`--as-of`、`--observations`、`--data-root`、`--output` 保持。HK60 Gate 禁止同时带 `--require-full-window`，因为 11 只结构性短历史不是缺失。

禁止增加 `--supplement*`、`--source-map*`、`--availability-json`、evidence hash/path、bundle cutoff 推断参数。caller 不得提交任何 `(symbol,date,source)` mapping。

参数冲突、mixed 缺任一必填项、naive/non-UTC verification datetime、query date 与 plan 不等、mixed 携 `--require-full-window`，统一 `BAR_WINDOW_INPUT_INVALID`。

---

## 5. 新值对象与 Python API

在 `quant.data.query` 新增冻结 token：

```python
VERIFIED_HK_AVAILABILITY_SOURCE = "verified-hk-availability-v1"
```

新增普通审计值对象，不冒充 formal capability：

```python
@dataclass(frozen=True, slots=True)
class MixedSourceBarWindowCoverage:
    universe: str
    as_of: dt.date
    source: str  # exact VERIFIED_HK_AVAILABILITY_SOURCE
    requested_observations: int
    eligible_symbol_count: int
    returned_symbol_count: int
    missing_symbols: tuple[str, ...]
    short_symbol_counts: tuple[tuple[str, int], ...]
    min_observations: int
    max_observations: int
    plan_sha256: str
    publication_sha256: str
    availability_content_sha256: str
    source_row_counts: tuple[tuple[str, int], ...]

@dataclass(frozen=True, slots=True)
class AuditedMixedSourceBarWindow:
    frame: pl.DataFrame
    coverage: MixedSourceBarWindowCoverage

@dataclass(frozen=True, slots=True)
class AuditedMixedSourceAvailableHistoryBarWindow:
    frame: pl.DataFrame
    coverage: MixedSourceBarWindowCoverage
    available_history: AvailableHistoryCoverage
```

计数、排序、唯一性、SHA 和 frame 交叉约束必须与旧值对象同等严格；mixed frame 的语义键 `(symbol,trade_date)` 必须唯一，逐行物理键必须与 availability mapping exact。`source_row_counts` 按 source 排序、正计数且合计等于 frame.height。

新增：

```python
BarQuery.recent_for_universe_mixed_audited(
    *, membership_path: Path, universe: str, as_of: dt.date,
    observations: int, bundle: VerifiedHkBarBundle, plan: HKHistoryPlan,
) -> AuditedMixedSourceBarWindow

BarQuery.audit_available_history_mixed(
    *, audited: AuditedMixedSourceBarWindow,
    calendar_path: Path, instrument_path: Path,
    eligibility_snapshot_root: Path, eligibility_event_root: Path,
    no_trade_evidences: tuple[HKNoTradeEvidence, ...],
    no_trade_evidence_sha256: str,
) -> AuditedMixedSourceAvailableHistoryBarWindow
```

这两个 API 是查询原语，不自行声称 bundle fresh；formal operator 闭环由 CLI 的前后两次 public bundle verifier 保证。不得接受裸 mapping、裸 availability、普通 DataFrame 代替 bundle，或把 mixed frame 塞入旧 `AuditedBarWindow`。

---

## 6. 唯一 source mapping 与 DuckDB 规则

mapping 只从 exact `VerifiedHkBarBundle.availability.select(symbol,trade_date,source)` 派生：

- `(symbol,trade_date)` 唯一；
- 键集合 exact 等于 `plan.effective_expected_dates`；
- 不按 `availability_source_kind` 猜 source；
- 不读 mapping artifact，不接受 caller mapping。

DuckDB 对 eligible、`trade_date <= as_of`、mapping 域执行：

1. `(symbol,trade_date,source)` 物理重复 → `BAR_WINDOW_DUPLICATE_KEY`。
2. 同一 `(symbol,trade_date)` 多 source → `BAR_WINDOW_DUPLICATE_KEY`；禁止 source priority、sort、distinct 修复。
3. mapping 键存在 bar 但 source 不等 → `BAR_WINDOW_REFERENCE_INVALID`；禁止仅 INNER JOIN 后静默吞掉错源。
4. 选取只允许三列 exact join，再按 symbol/date 最近 N；mapping 外 bar 不得用于补足窗口。
5. mapped source 缺行进入 `missing_sessions`；required 外行进入 `unexpected_sessions`；两者均使 `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`。

SQL 必须参数化；不得拼接 caller source/path 文本。

---

## 7. no-trade evidence

Mixed Gate 只使用 fresh v2 plan 的 `no_trade_evidence` / `no_trade_evidence_sha256`。`load_verified_hk_bar_bundle` 已在同次 fresh 链验证对应 raw/metadata SHA 与 exact UA 范围。

- mixed 路径不得读、写或比较 `clean/hk_no_trade_evidence/evidence.json`；避免同一事实出现可选第二来源。
- 旧单源路径保持对现文件的旧行为，不迁移、不删除。
- 只允许 01065@2026-05-05 与 02402 的冻结 13 日；2026-05-04 仍必须有 bar。

---

## 8. public fresh 顺序与输出

CLI mixed 分支唯一顺序：

1. 轻量参数与路径类型检查，尚不写 output。
2. `load_hk_history_plan`，要求 v2、query date exact 等于 plan.as_of。
3. 由 data-root 派生 raw、clean/bar_1d；调用 `load_verified_hk_bar_bundle(..., as_of=verification_as_of)`。
4. 从 capability availability 派生 mapping，构造 mixed recent-N frame。
5. 用 plan 内嵌 evidence 做 calendar/instrument/route available-history audit。
6. 调用 `verify_hk_bar_bundle` 第二次 fresh rebuild，仍使用同一 verification_as_of 和 exact roots。
7. 只有 complete 才写 `--output`，随后打印成功 JSON。

mixed 成功 JSON 沿用旧 coverage/rows/symbols/date/output 语义，并增加：

```text
source="verified-hk-availability-v1"
plan_sha256
publication_sha256
availability_content_sha256
source_row_counts=[[source,count],...]
available_history=<旧 payload 形状>
verification_as_of=<canonical aware UTC>
```

`verification_as_of` 只说明验真 cutoff，不是市场/信号 as_of。

---

## 9. 稳定失败与脱敏

沿用：

- `BAR_WINDOW_INPUT_INVALID`
- `BAR_WINDOW_DUPLICATE_KEY`
- `BAR_WINDOW_REFERENCE_INVALID`
- `BAR_WINDOW_INCOMPLETE`
- `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`
- public `HK_HISTORY_*` / `HK_BAR_*` 稳定码

新逻辑不得把路径、raw 单元格、token、hostile marker 写入异常。所有翻译退出 active `except` 后 `raise ... from None`，确保 `__cause__` / `__context__` 均为空。失败不写 output。

---

## 10. 必测反例

至少覆盖：

1. 旧单源 API/CLI/JSON 完全兼容。
2. mixed 与 `--source` 同时出现。
3. mixed 缺 plan/journal/verification-as-of/available-history。
4. naive、非 UTC、错误日期的 verification-as-of；query as-of 与 plan 不等。
5. 同语义键双源、同物理键重复。
6. mapping 要 hkex 但只有 tushare（错源）；mapping 要 hkex 但两者皆无（missing）。
7. mapping 外更早 bar 不得补足最近 N；mapping 外但落在 required session 的 bar 也不得满足 available-history missing。
8. 01065/02402 exact 豁免；05-04 缺行仍 missing；豁免日出现 bar 为 unexpected。
9. UA-M1-001-only plan 与 v2b journal 混配。
10. no-trade raw/metadata 篡改。
11. STOCK 缺 Instrument 失败；官方 ETF 无 Instrument 仍排除。
12. equal-count wrong-date 仍 missing+unexpected。
13. bundle 伪造、子类、pickle、旧 capability。
14. 第二次 verifier 期间 root/clean/availability 漂移，output 必须不存在。
15. hostile OSError/ValueError 递归异常图完全脱敏。
16. caller ambient Decimal/row physical input order 不影响结果（若实现无 Decimal，至少证明不访问）。
17. required session 只有未映射 bar：必须 missing、AH incomplete、无 output；成员证券完全不在 availability 时，即使 clean 有 bar 亦同。
18. 实际捕获 mixed AH 底层 Polars/IO 异常，`__cause__`/`__context__` 必须为空；不得用新构造异常代替被测异常。

正向 fixture 必须通过 public `finalize_hk_history` + `load_verified_hk_bar_bundle` 的最小 v3 链签发 capability；禁止 `object.__new__`、seal/registry/attestation monkeypatch。

---

## 11. 文件白名单

实现会话只可修改：

- `src/quant/data/query.py`
- `src/quant/data/query_universe.py`
- `tests/unit/test_query.py`
- `tests/unit/test_query_universe.py`
- 可选新增 `tests/support/hk_history_v3.py`（仅公共最小 fixture；禁止 capability 内部绕过）
- `README.md` 仅补 mixed CLI 入口及双时点说明
- 本任务单状态与唯一交付报告

不得修改 `src/quant/data/__init__.py`，除非现有导出测试明确要求；若需要，先停下回报。不得修改 backfill、Schema、配置、正式数据、路线图或用户待批示文档。

独立初验只读上述生产/实现测试，唯一可写其独立初验报告。

---

## 12. 验证与真实 Gate

实现阶段：Windows 定向 pytest（query/query_universe）、Ruff、mypy、cold import；必要的 backfill 邻接只跑直接节点。不得为了等待真实 8/8 阻塞 fixture 工程实现。

真实 Gate 必须在主分支完成：

1. 最新 v2c（UA-M1-001/004/005 exact）8/8 零网络 recover PASS；
2. 唯一 `--finalize-v3` PASS；
3. fresh bundle load PASS；
4. SH_CONNECT、SZ_CONNECT 各运行一次 mixed CLI，`as_of=2026-07-10`、`observations=60`，显式同一 operator-bound verification_as_of；
5. 两 Route 均 `is_available_history_complete=true`、`unexpected_session_total=0`，source row counts 与 capability 一致。

这只关闭 Windows W1 HK60 不复权 bar/query 子项；不关闭 UA-M1-002、formal P1C、M1 W2 或 Linux/ext4。

---

## 13. 停止条件

实现或真实运行遇到以下任一项立即停止：

- 必须修改 backfill/schema 或接受 caller mapping 才能工作；
- availability 与 effective keys 不同，或 clean 与 mapping 错源/双源；
- verification cutoff 需要从 query date、wall clock、mtime 或读后 max 自适应；
- 正向 fixture 只能伪造 capability；
- plan/evidence 未通过 fresh backfill loader，或其 evidence 与 `effective_expected_dates` 不一致；
- required STOCK Instrument 缺失；
- 8/8/finalize 未完成却尝试真实 Gate；
- 任何联网、采购、credential、正式 data/artifact 写入；
- 需要弱化单源 API 或静默去重才能通过。

---

## 14. R1 独立初验 FAIL 与 R2 精确返工

R1 报告：[`M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate独立初验报告.md`](M1_HK60_R1_VerifiedMixedSourceAvailableHistoryGate独立初验报告.md)。

### 14.1 mapping 外 bar 错误补齐 missing

- **现象**：research frame 已按 mapping exact join，但 available-history 用未 join mapping 的物理 last-N 同时计算 missing 与 unexpected；追加未映射 required-date bar 后，AH 可变成 complete 并写 output。
- **根因**：同一 `observed_frame` 被用于两种不同证明。物理观察适合发现 unexpected，却不能证明 mapped source 的 required key 已存在。
- **规则**：missing 只由 `(symbol, trade_date, source)` 与 fresh availability exact join 后的观察集满足；unexpected 仍由物理 last-N 观察集计算。两集合必须显式分离，不能以 sort/distinct/source priority 修复。
- **最小复现**：availability 只有 07-10，required 还含 07-09；clean 追加未映射 07-09 bar。结果必须 missing≥1、incomplete、无 output。成员 `09999.HK` 完全不在 availability 但 clean 有 bar时亦同。
- **新增测试**：上述两例，以及豁免日 unexpected/equal-count wrong-date 回归。
- **通过条件**：禁止出现 `missing_symbols` 非空但 AH complete；未映射行永远不能满足 missing。

### 14.2 mixed AH API 异常图未脱敏

- **现象**：损坏 snapshot 后 `audit_available_history_mixed` 的稳定异常仍保留底层 Polars `ComputeError` 为 cause/context。
- **根因**：`_load_official_connect_security_types` 使用 `raise ... from exc`，实现测试只检查了新构造异常。
- **规则**：实际翻译必须在离开 active `except` 后以 `from None` 抛出，public `__cause__`/`__context__` 均为空。
- **最小复现**：public v3 fixture 后损坏 snapshot parquet，捕获实际 mixed AH 异常并检查异常图。
- **新增测试**：实际异常、repr/traceback hostile marker、CLI 无 output。
- **通过条件**：API 与 CLI 均只暴露稳定码；实现者原定向测试全绿。

