# M1 HK60 R1 Mixed-Source Available-History Gate 外部只读设计审计报告

- **角色**：外部只读设计审计 Agent（不参与实现、不宣称 Gate 通过）
- **模型**：`cursor-grok-4.6-high`（按 2026-08-15～2026-08-20 用户指示如实记录；不声称底层模型）
- **工作区**：`F:\AI_Coding\QuantitativeTrading`
- **日期**：2026-08-15
- **范围**：只读现行 `query.py` / `query_universe.py` / `hk_history_backfill.py` 公共边界与直接测试，以及 [`M1_20260815_HK60后续Windows剩余闭环外部只读审计报告.md`](M1_20260815_HK60后续Windows剩余闭环外部只读审计报告.md) §2 包 C/D。本报告是可冻结进任务书的**唯一推荐设计**。
- **平台**：只考虑 Windows 工程闭包；不宣称 Linux/ext4 Gate。
- **写入**：仅本文件。生产代码、测试、配置、既有文档、`data/` / `artifacts/` 业务产物全部只读；未联网、未读 ignored token、未 add/commit/push。

---

## 0. 冻结事实（代码核对后确认）

1. 物理 bar 键仍是 `(symbol, trade_date, source)`（`Bar1dSchema`）。语义研究键是 `(symbol, trade_date)`，**不允许**同一语义键多源并存后靠排序/去重/优先级静默挑选。
2. `BarQuery.recent_for_universe_audited` / CLI `--source` / `BarWindowCoverage` / `AuditedBarWindow` / `AvailableHistoryCoverage` 均为**单源合同**：SQL 为 `bars.source = ?`；`AuditedBarWindow` 拒绝任何 `frame.source != coverage.source` 的行。
3. v3 availability（`HkBarAvailabilityEvidenceSchema`）已是 **one-source-per-effective-key**：键集合精确等于 `plan.effective_expected_dates`；`02983.HK@2026-07-10` 的 `availability_source_kind=HKEX_SUPPLEMENT`，其余有效键为 `SEED_RAW`/`REQUEST_RAW`（bar `source=tushare`）。
4. v2b `HKHistoryPlan` 已内嵌 exact UA-M1-001 ∪ UA-M1-004；`no_trade_evidence_sha256` 是集合身份。no-trade 日**不在** availability 表中。
5. `load_verified_hk_bar_bundle` 的 `_load_seed` **已经**对 plan 内嵌 evidence 跑 `_verify_evidence_projection`（raw/metadata SHA + UA exact 范围）。fresh capability 绑定 `bars + availability + plan_sha256 + publication_sha256 + root identities`。
6. `query_universe --require-available-history` 现读 `data/clean/hk_no_trade_evidence/evidence.json`；该文件**不是** finalize-v3 产物。包 C 的物化是可选投影，不是第二套 SSOT，也不是 mixed Gate 的必要前置。
7. 不得改 `schemas.py`；不得让 caller 自报 supplement 行、source mapping、evidence hash 或 mapping 文件路径；现有单源 public API / JSON / 测试必须保持兼容。

前次审计包 D 列出的三选项中：**选项 1（两次单源 Gate 再组合）与选项 2（caller 显式 supplement 闭包）均淘汰**。唯一可冻结的是：查询层消费 **fresh VerifiedHkBarBundle.availability 派生的映射**，对 `(symbol, date)` 做精确一源选取，再用 plan 内嵌 evidence 做 available-history 豁免。

---

## 1. 推荐的 public API / 值对象 / CLI 参数与兼容策略

### 1.1 兼容不变量（必须保持）

下列签名、失败码、JSON 键与测试行为**一字不改**：

```text
BarQuery.recent_for_universe(..., source: str, observations: int = 60) -> pl.DataFrame
BarQuery.recent_for_universe_audited(..., source: str, observations: int = 60) -> AuditedBarWindow
BarQuery.recent_for_universe_available_history_audited(..., source: str, ...) -> AuditedAvailableHistoryBarWindow
BarQuery.audit_available_history(audited: AuditedBarWindow, ..., no_trade_evidence_path: Path | None = None, no_trade_raw_root: Path | None = None) -> AuditedAvailableHistoryBarWindow

python -m quant.data.query_universe --universe {SH_CONNECT,SZ_CONNECT} --as-of DATE --source TEXT --observations N --data-root PATH [--output PATH] [--require-full-window] [--require-available-history]
```

- `BarWindowCoverage.source` / `AuditedBarWindow`「整框单源」不变量保留。
- 单源成功 JSON 仍由 `_coverage_payload` + 可选 `available_history` 构成；不得给单源路径增加必填键。
- `--source tushare --require-available-history` 在 mixed clean 上对 `02983.HK@2026-07-10` 记入 `missing_sessions` 是**既有单源语义**，不是 bug；HK60 子 Gate 不再走这条命令。

### 1.2 新增 CLI（互斥，而不是污染 `--source`）

`argparse` 把现有必填 `--source` 改为互斥组（旧调用线仍合法）：

```text
source_group = mutually_exclusive_group(required=True)
  --source TEXT
  --from-verified-hk-availability

当且仅当 --from-verified-hk-availability：
  --plan PATH                 # 必填；与 backfill CLI 同一 operator-bound plan
  --journal-root PATH         # 必填；必须已是 v2 journal 根（含 binding.json），不得指向 mapping 文件
  --require-available-history # 必填（缺省则 BAR_WINDOW_INPUT_INVALID）
  --data-root PATH            # 已有；派生 raw/clean，禁止再增加 mapping/evidence/hash 参数
  --as-of / --universe / --observations / --output / --require-full-window 同现合同
```

禁止新增的参数（任务书必须写死）：

- `--supplement*`、`--source-map*`、`--availability-json`、`--no-trade-evidence-sha256`、`--bundle-as-of-datetime`
- 任何让 caller 提交 `(symbol, date, source)` 行或 evidence hash 的入口

`--plan` / `--journal-root` / `--data-root` **不是** mapping 输入：它们是与包 B 相同的 operator 绑定；mapping 只能从 fresh capability 的 `availability` 列派生。`journal_root` 必须已含 `binding.json`，且 `binding.journal_id == plan.journal_id`、`binding.plan_sha256 == plan.plan_sha256`、`binding.no_trade_evidence_sha256 == plan.no_trade_evidence_sha256`（复用现有 `_verify_journal_binding`，由 `load_verified_hk_bar_bundle` 执行）。禁止 `journal_root.name == plan.journal_id` 的额外启发式，以免与现行 backfill「journal_root 即 journal 目录」合同分叉。

`--from-verified-hk-availability` 与 `--source` 同时出现 → `BAR_WINDOW_INPUT_INVALID`。  
`--from-verified-hk-availability` 而不带 `--require-available-history` → `BAR_WINDOW_INPUT_INVALID`（mixed 输出必须带 exact session 审计，否则会把 no-trade 日「少一天再补更早一天」）。  
Gate 命令**不得**带 `--require-full-window`（结构性短历史不是 incomplete；full-window 仍可按现优先级先失败，但不作为 HK60 子 Gate）。

冻结 Gate 命令形：

```text
python -m quant.data.query_universe \
  --universe SH_CONNECT \
  --as-of 2026-07-10 \
  --from-verified-hk-availability \
  --plan <v2b-plan> \
  --journal-root <v2b-journal> \
  --observations 60 \
  --data-root data \
  --require-available-history \
  --output <parquet>
# SZ_CONNECT 再跑一次；两 Route 都 complete 才关 W1 HK60 子 Gate
```

`load_verified_hk_bar_bundle(..., as_of: datetime)` 的 cutoff **由 `--as-of` date 派生**，caller 不可另传：

```text
bundle_as_of = datetime.datetime.combine(as_of, datetime.time(23, 59, 59, tzinfo=datetime.timezone.utc))
```

若真实 `bar_available_at` 晚于该 cutoff，保持现有 `HK_BAR_PUBLICATION_INVALID` 失败，**停止并交主 Agent**，不得擅自改成次日或 `max(bar_available_at)`。

### 1.3 新增 Python 值对象（不修改现有三类）

冻结 token：`VERIFIED_HK_AVAILABILITY_SOURCE = "verified-hk-availability-v1"`  
（对齐 availability payload `schema_version=hk-bar-availability-v1`；**不是** bar 行上的 `source` 列值。）

```python
@dataclass(frozen=True, slots=True)
class MixedSourceBarWindowCoverage:
    universe: str
    as_of: dt.date
    source: str  # 必须恰好为 VERIFIED_HK_AVAILABILITY_SOURCE
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
    source_row_counts: tuple[tuple[str, int], ...]  # 按 source 名排序的返回行计数

@dataclass(frozen=True, slots=True)
class AuditedMixedSourceBarWindow:
    frame: pl.DataFrame
    coverage: MixedSourceBarWindowCoverage
    # 不变量：不得构造 AuditedBarWindow(frame, fake_single_source_coverage)
    # frame.source 只允许出现在 mapping 的 source 集合中
    # 每个 (symbol, trade_date) 至多一行
    # 每个出现的 (symbol, trade_date, source) 必须等于 mapping[(symbol, date)]

@dataclass(frozen=True, slots=True)
class AuditedMixedSourceAvailableHistoryBarWindow:
    frame: pl.DataFrame
    coverage: MixedSourceBarWindowCoverage
    available_history: AvailableHistoryCoverage  # .source == VERIFIED_HK_AVAILABILITY_SOURCE
```

`AvailableHistoryCoverage` **复用、不改字段**。mixed 路径把 `.source` 设为冻结 token，使 session 审计仍走现有日期差集；**按源的正确性在 JOIN 阶段已经 fail-closed**，不把 `unexpected_sessions` 改成按源拆分。

`MixedSourceBarWindowCoverage` 的计数不变量与 `BarWindowCoverage` 相同（missing/short/min/max 交叉约束），另加：

- 三个 sha256 均为 `[0-9a-f]{64}`，且必须等于传入的 `VerifiedHkBarBundle` 身份（`availability_content_sha256` 用现有 `_availability_payload` 同类规则对 `bundle.availability` 求内容哈希，**禁止** caller 传入）。
- `source_row_counts` 排序、正计数、合计等于 `frame.height`；HK60 真值期望含 `("hkex", 1)` 当且仅当该 Route 成员含 `02983.HK` 且窗口包含 `2026-07-10`。

### 1.4 新增 BarQuery 方法（精确签名）

```python
def recent_for_universe_mixed_audited(
    self,
    *,
    membership_path: Path,
    universe: str,
    as_of: dt.date,
    observations: int,
    bundle: VerifiedHkBarBundle,
    plan: HKHistoryPlan,
) -> AuditedMixedSourceBarWindow: ...

def audit_available_history_mixed(
    self,
    *,
    audited: AuditedMixedSourceBarWindow,
    calendar_path: Path,
    instrument_path: Path,
    eligibility_snapshot_root: Path,
    eligibility_event_root: Path,
    no_trade_evidences: tuple[HKNoTradeEvidence, ...],
    no_trade_evidence_sha256: str,
) -> AuditedMixedSourceAvailableHistoryBarWindow: ...
```

禁止：

- 接受 `mapping: DataFrame` / `list[tuple]` / `dict` 作为 public 参数（那是 caller 自报 mapping）。
- 接受非 `VerifiedHkBarBundle` 实例（`__new__` 已拒绝伪造；`type(bundle) is not VerifiedHkBarBundle` → `HK_BAR_VERIFY_FAILED`）。
- 把 mixed frame 塞进现有 `AuditedBarWindow`。
- 为 `load_verified_hk_bar_bundle` 增加写盘 CLI。

CLI 编排（`query_universe.main` mixed 分支）只调用上述方法；`raw_store` / `seed_raw_root` / `clean_root` 仅由 `--data-root` 派生，与 `backfill_hk_history` 一致：`raw = data_root/raw`，`clean = data_root/clean/bar_1d`。

Mixed 成功 JSON：在现有 `_coverage_payload` 同名键之上**仅 mixed 分支**附加：

```text
source = "verified-hk-availability-v1"
plan_sha256, publication_sha256, availability_content_sha256
source_row_counts: [[source, n], ...]
available_history: <现有 _available_history_payload 形状不变>
rows / symbols / first_trade_date / last_trade_date / output 同现字段
```

`--output` 仍只在 available-history complete 时写 parquet；失败不写。这就是「Gate + 最近 N 行研究消费」的同一调用。

---

## 2. Source mapping 的派生源：v3 availability capability

**唯一推荐：从 fresh `VerifiedHkBarBundle.availability` 派生 `(symbol, trade_date) → source`。**

| 候选 | 裁决 | 理由 |
|---|---|---|
| v3 availability capability | **采用** | 已是发布后、fresh 验证过的 one-source-per-effective-key 表；含 `source`、`availability_source_kind`、raw/receipt 身份；与 `bundle.bars` / `publication_sha256` / roots 绑定。 |
| plan.unresolved / expected_dates | 拒绝 | `unresolved` 只表示 tushare 未取到的**缺口**，不是「该键必须是 hkex」的发布证明；plan 不给每键 `source` 字符串。用它当 mapping 会在错误发布上静默猜源。 |
| 新 artifact / mapping.json / evidence.json 扩列 | 拒绝 | 第二套 SSOT；caller 路径；与「不得改 schemas / 不得自报 mapping」冲突。 |

派生规则（实现必须写成纯函数，输入只能是已验证的 `bundle.availability` 与 `plan`）：

1. `mapping = availability.select(symbol, trade_date, source)`，按 `(symbol, trade_date)` 排序。
2. `(symbol, trade_date)` 必须唯一；`len(mapping) == plan.effective_expected_dates` 键数且集合相等，否则 `HK_BAR_VERIFY_FAILED`（capability 已坏，不是 query 去「修」）。
3. Query **不得**再按 `availability_source_kind` 猜 `source`；只用 `source` 列。
4. Mapping 只覆盖 HK60 有效键。最近 N 行的 JOIN 以 mapping 为权威：窗口内未映射的 bar 不得靠 `UNION ALL` 混入。

No-trade 豁免**不**从 availability 派生（那些日根本不在表里），见 §4。

---

## 3. DuckDB SQL / 物理键规则

物理层继续承认 `(symbol, trade_date, source)` 可多源共存于 parquet；**语义层对 mapping 内每个键要求恰好一行且源等于 mapping**。禁止 `QUALIFY`、`ORDER BY source`、`COALESCE`、`priority`、`DISTINCT ON (symbol, trade_date)`。

推荐四步（全部参数化；mapping 以 DuckDB 注册表传入，内容只来自 bundle）：

**A. 物理重复** — 现键 `(symbol, trade_date, source)` 在 eligible ∩ `trade_date <= as_of` ∩ mapping 键上 `COUNT(*) > 1`  
→ `BAR_WINDOW_DUPLICATE_KEY`

**B. 语义多源** — 同一 `(symbol, trade_date)` 出现 `COUNT(DISTINCT source) > 1`（无论是否包含 mapped source）  
→ `BAR_WINDOW_DUPLICATE_KEY`  
（这是 02983 同时有 tushare 与 hkex 的反例；不得留下 hkex。）

**C. 错源** — 存在 bar 使 `(symbol, trade_date) ∈ mapping` 且 `bars.source != mapping.source`（此时若只有错源，B 不会触发）  
→ `BAR_WINDOW_REFERENCE_INVALID`  
（clean 与 availability 不一致；fresh bundle 已通过则只可能 TOCTOU 或分区混入，必须停，不得改 JOIN 吞掉。）

**D. 选取与最近 N** — 仅：

```sql
INNER JOIN mapping
  ON bars.symbol = mapping.symbol
 AND bars.trade_date = mapping.trade_date
 AND bars.source = mapping.source
WHERE bars.trade_date <= ?
-- 然后 PARTITION BY bars.symbol ORDER BY bars.trade_date DESC
-- observation_number <= N
ORDER BY symbol, trade_date
```

缺失 mapped 行：**不**在 SQL 阶段升格为异常；进入 available-history 的 `missing_sessions` → `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`（与现合同一致）。  
额外日期（frame 有、required 无）→ `unexpected_sessions` → 同一 incomplete 码。  
额外且未映射、但出现在 last-N 的 bar：因为 D 是 INNER JOIN mapping，根本不会进入 frame；若它落在 required 日，则表现为 missing（mapped 源缺）+ 若同时触犯 C 则先 C。不得为了「凑满 N」去 mapping 外取更早的 tushare 行替代 02983 当日。

`AuditedMixedSourceBarWindow` 必须再断言：`frame.select(symbol, trade_date).n_unique() == frame.height`，且每行 `(symbol, trade_date, source)` 等于 mapping。

---

## 4. No-trade evidence：从 fresh v2 plan 派生（不另物化）

**唯一推荐：直接使用 fresh 加载的 v2 plan 内嵌 `no_trade_evidence` / `no_trade_evidence_sha256`。不发布、不依赖 `data/clean/hk_no_trade_evidence/evidence.json` 来关闭 mixed Gate。**

理由：

- Plan 已是 UA-M1-001/004 的权威闭包；再写 evidence.json 是字节投影副本，增加 no-clobber/漂移面，且前次包 C 与「不得第二套 SSOT」张力未解。
- `load_verified_hk_bar_bundle` → `_load_seed` 已对同一集合做 raw 投影校验。mixed Gate 以 bundle load 为第一件事，因此 **不必**为 query 再写一份 clean JSON。
- finalize-v3 本来就不写该路径（包 B 已记录）。

### 4.1 旧 CLI 迁移（兼容，不强制迁移）

| 调用 | 行为 |
|---|---|
| `--source S --require-available-history`（旧） | **不变**：若 `clean/hk_no_trade_evidence/evidence.json` 存在则 `load_hk_no_trade_evidence`；不存在则零豁免。单源测试与 JSON 保持。 |
| `--from-verified-hk-availability`（新） | **忽略** evidence.json 作为输入。豁免只来自 `plan.no_trade_evidence`。 |
| 两路径同时存在 evidence.json | mixed 启动后若该 canonical 路径**存在**，则必须 `load_hk_no_trade_evidence` 并要求 `evidence_set_sha256 == plan.no_trade_evidence_sha256` 且 evidences 精确相等；否则 `BAR_WINDOW_REFERENCE_INVALID`。文件**不存在**则继续（不把包 C 当前置）。 |

包 C 从 HK60 子 Gate 关键路径上**降级为可选防漂移检查**，不再是包 D 的硬依赖。本报告覆盖前次审计「包 D 依赖包 C」的裁决。

`audit_available_history_mixed` 把 plan 的 tuple 注入现有 `_available_history_from_references` 的 evidence 循环（01065@2026-05-05 与 02402 的 13 个 ISO 日从 required 中扣除；05-04 仍要求有 bar）。不要新 reason、不要通配停牌。

---

## 5. Fresh verification 顺序、稳定失败码、异常脱敏

### 5.1 唯一合法顺序（Windows quiescence 由 operator 保证，与 V3M-P0 R3 相同）

1. 解析 CLI；mixed 互斥与 `--require-available-history` 强制；`--as-of` 必须等于 `plan.as_of` 的 date（真 Gate 为 `2026-07-10`），否则 `BAR_WINDOW_INPUT_INVALID`。
2. `plan = load_hk_history_plan(--plan)`；`schema_version == hk-history-plan-v2`。
3. `bundle = load_verified_hk_bar_bundle(plan, journal_root, seed_raw_root=data/raw, raw_store, clean_root=data/clean/bar_1d, as_of=bundle_as_of)`。此步已：binding、8 份 receipt、hkex retained、availability 字节、clean 内容、**no-trade raw 投影**。
4. 从 `bundle.availability` 派生 mapping（§2）；身份字段拷入 coverage。
5. 可选：canonical evidence.json 存在则与 plan 集合对账（§4.1）。
6. `recent_for_universe_mixed_audited`（§3 SQL）。不得在此之前写 `--output`。
7. 若 `--require-full-window`：`is_full_window` 失败则 stdout incomplete JSON、exit 1（现优先级）。Gate 不使用该旗标。
8. `audit_available_history_mixed`（calendar / instrument / connect snapshot+event 路径仍由 `--data-root` 派生，与现 CLI 相同，**不是** caller 自报 evidence 路径）。
9. `verify_hk_bar_bundle(bundle, ...)` **第二次 fresh rebuild**。漂移 → `HK_BAR_VERIFY_FAILED`，**不写 output**。
10. complete 才写 parquet 并打印成功 JSON。

禁止在 3 失败后继续用「裸 parquet UNION」凑窗口。

### 5.2 稳定失败码（stderr 单行 = `str(exc)`；stdout 仅 incomplete 两种 JSON）

沿用现码，**不新增** `BAR_WINDOW_SOURCE_*`：

| 条件 | 码 | 通道 |
|---|---|---|
| 互斥参数 / 缺 plan / as_of≠plan.as_of / mixed 无 available-history / observations 非法 | `BAR_WINDOW_INPUT_INVALID` | stderr |
| 物理或语义重复键 | `BAR_WINDOW_DUPLICATE_KEY` | stderr |
| 错源、引用缺失、evidence.json 漂移、instrument/calendar 非法、STOCK 无 Instrument | `BAR_WINDOW_REFERENCE_INVALID` | stderr |
| 缺会话 / 意外会话 | `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE` | stdout JSON + exit 1 |
| full-window 不足 | `BAR_WINDOW_INCOMPLETE` | stdout JSON + exit 1 |
| bundle/availability/finalize/锚点/伪造 capability | `HK_BAR_VERIFY_FAILED` 或 `_public_hk_bar_error_code` 已允许的 `HK_HISTORY_FINALIZE_V3_INVALID` / `HK_HISTORY_AVAILABILITY_UNSUPPORTED` / `HK_BAR_PUBLICATION_INVALID` | stderr |
| plan/journal binding 冲突 | `HK_HISTORY_PLAN_CONFLICT` | stderr |
| evidence raw 投影失败（经 bundle load） | `HK_HISTORY_REFERENCE_INVALID` → CLI 可保持该码，**不要**一律改写成 `BAR_WINDOW_REFERENCE_INVALID`（与单源 path-load 的映射区分：单源 `load_hk_no_trade_evidence` 失败仍映射为 `BAR_WINDOW_REFERENCE_INVALID`） | stderr |

`query_universe` mixed 分支必须 `except HKHistoryBackfillError`：只打印 `str(exc)`；未知码折叠为 `HK_HISTORY_REFERENCE_INVALID`（对齐 `backfill_hk_history` 白名单策略，query 侧白名单 = 上表 HK_* 集合 ∪ 现有 BAR_WINDOW_*）。

### 5.3 异常脱敏

- 所有新路径 `raise ... from None`；禁止把路径、token、parquet 单元格、hostile `__cause__` 放进 `str(exc)`。
- `BarWindowQueryError.__str__` 已等于 `code`；不得改。
- 测试必须覆盖：在 mapping JOIN / plan load / bundle verify 边界注入带路径的 `OSError`/`ValueError`，公共码仍为上表之一且消息无路径。

---

## 6. 最小文件白名单与 ≥12 个关键反例

### 6.1 实现白名单（互斥；不改 schemas / 不改 backfill 生产逻辑）

**生产（仅此）**

- `src/quant/data/query.py` — 新值对象与 mixed 查询/审计
- `src/quant/data/query_universe.py` — CLI 互斥组与编排
- `src/quant/data/__init__.py` — 仅当需要导出新类型；否则不要碰

**测试（仅此）**

- `tests/unit/test_query.py`
- `tests/unit/test_query_universe.py`

**明确不写入**

- `src/quant/domain/schemas.py`
- `src/quant/data/hk_history_backfill.py`（fresh verify / evidence 投影已够用；勿为「方便」再包一层写盘 CLI 或新 SSOT）
- `src/quant/data/backfill_hk_history.py`
- `configs/**`、`data/**`、`artifacts/**`
- 既有审计/路线图文档（任务书由主 Agent 另写；README CLI 说明若改公共入口，由**同一实现变更**按 AGENTS.md §3 补一句并链接本设计，不得复制字段表）

不需要新测试文件去复制 `test_hk_history_backfill.py` 的锚点矩阵；mixed 测试用**最小** tmp v3 fixture 或 mock 不了的真实 `load_verified` 小链（可复用现有 backfill 测试的 helper **只读 import**，不要改那份测试文件以免与包 B 操作冲突）。若 fixture 构建成本过高：在 `test_query.py` 用进程内 `object.__new__(VerifiedHkBarBundle)` **禁止**——`__new__` 被设计为失败。测试必须走 `load_verified_hk_bar_bundle` 的最小 finalize-v3 链（现 `test_v3_minimal_chain_covers_three_days_no_trade_and_hkex_supplement` 已证明三天+no-trade+hkex 可在 tmp 闭合）。把该最小链抽到 query 测试内复制一份夹具，**不要修改** `test_hk_history_backfill.py`。

### 6.2 关键反例（任务书至少冻结这些；实现者自测不得删）

1. **单源兼容**：`--source tushare --require-available-history` 在含 `02983.HK@2026-07-10 source=hkex` 的盘上将该日记入 missing；JSON `source` 仍为 `tushare`。
2. **无 mapping 参数**：CLI/API 不存在 supplement 行输入；对 `recent_for_universe_mixed_audited` 传入普通 DataFrame 充当 bundle 失败。
3. **语义双源**：同一 `(02983.HK, 2026-07-10)` 同时有 tushare 与 hkex → `BAR_WINDOW_DUPLICATE_KEY`，frame 不产出、不按 hkex 优先。
4. **错源**：mapping 要 hkex，盘上只有 tushare → `BAR_WINDOW_REFERENCE_INVALID`（不是 incomplete 凑数）。
5. **缺 mapped 源**：mapping 要 hkex，两源皆无 → `missing_sessions` → `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`。
6. **豁免日有 bar**：`01065.HK@2026-05-05` 有行 → unexpected → incomplete。
7. **豁免日无 bar 且 SHA 正确**：01065 该日与 02402 十三日豁免；`2026-05-04` 仍缺则 missing。
8. **UA-M1-001-only 证据/plan** 配 v2b journal → binding/plan 冲突或 reference invalid；不得部分豁免。
9. **raw 篡改**：UA-M1-001/004 raw 字节改动 → bundle load `HK_HISTORY_REFERENCE_INVALID`。
10. **`--source` + `--from-verified-hk-availability`** → `BAR_WINDOW_INPUT_INVALID`。
11. **equal count wrong date**（现有）：用相邻休市日凑满 N → unexpected/missing，不得 complete。
12. **STOCK 无 Instrument** → `BAR_WINDOW_REFERENCE_INVALID`；**官方 ETF 无 Instrument** 仍可排除。
13. **第二次 `verify_hk_bar_bundle` 漂移**（替换 clean 或 availability）→ `HK_BAR_VERIFY_FAILED` 且 `--output` 不存在。
14. **`as_of != 2026-07-10`（plan.as_of）** 的 mixed Gate → `BAR_WINDOW_INPUT_INVALID`。
15. **伪造 capability / 子类 / pickle** → `HK_BAR_VERIFY_FAILED`。
16. **hostile 异常图**（路径型 `OSError`）→ 公共码单行，无路径泄漏。

真 Gate 验收（非 fixture）：`SH_CONNECT` 与 `SZ_CONNECT` 分别 fresh，`as_of=2026-07-10`，`observations=60`，`unexpected=0`，豁免键与 `plan.no_trade_evidence_sha256` 一致，`source_row_counts` 含 hkex 当且仅当该 Route 含 02983 窗口行；两 Route 都 complete 才关 **W1 HK60 子 Gate**。不关 W2，不宣称 M1 全 Gate。

---

## 7. 与 HK60 8/8 / finalize 的依赖；独立 worktree

| 工作 | 依赖 | 独立 worktree？ |
|---|---|---|
| 本设计的代码 + fixture 反例 | **不**依赖真实 8/8 | **可以**。白名单与包 A（零代码）/包 B（操作现有 backfill CLI，不改 `query.py`）无生产文件冲突。 |
| 真实双 Route mixed Gate | **硬依赖**包 A 的 8/8 定义（v2b、8 receipt、unresolved 仅 02983@2026-07-10）**以及**包 B 的一次 `--finalize-v3` + 进程内 `load_verified_hk_bar_bundle` 成功 | 不可用 fixture 关 Gate；不可与包 B 抢同一 journal/clean 写入。 |
| 包 C evidence.json 物化 | **不再是**包 D 前置 | 不要为 mixed Gate 单开实现会话。 |
| Linux/ext4 | 不在本任务 | 禁止把 Windows 绿测写成 Linux Gate。 |

8/8 精确定义仍以前次审计为准，本报告不把当时 6/8 进度改写成已完成。实现 worktree 不得指向真实 R1 journal 或仅含 UA-M1-001 的旧 v2 journal。

---

## 8. 停止条件

立即停止、保留磁盘证据、交主 Agent 改契约（实现者不得猜测）：

- 真实 `bar_available_at` 晚于派生的 `2026-07-10T23:59:59+00:00`。
- finalize-v3 后 availability 键 ≠ `effective_expected_dates`，或 02983 当日 `source` 不是 `hkex`，或出现第二只 hkex 窗口行。
- clean 与 availability 对同一 `(symbol, date)` 源不一致（错源/双源）。
- v2b plan 的 no-trade 集合不是 UA-M1-001 ∪ UA-M1-004 exact。
- 任一 Route 的 HK STOCK Instrument 对 required 成员缺失（先做前次包 D0，不在 query 里填默认上市日）。
- 发现必须改 `schemas.py`、必须让 caller 提交 mapping、或必须静默 `DISTINCT ON` 才能「通过」。
- 实现中需要修改 `hk_history_backfill.py` 才能让 mixed Gate 工作（说明本设计的「零 backfill 改动」假设被打破）。
- 任务书与真实 SDK/磁盘冲突。
- 任何试图用两次单源 Gate 的进程外拼接、或宣布 Linux/M1 全量 Gate/formal P1C。

非停止但禁止声称完成：fixture 全绿 ≠ HK60 子 Gate；缺真实双 Route stdout complete ≠ W1 关闭。

---

## 9. 覆盖前次包 C/D 的冻结裁决（给任务书的一句话）

**不要做两次单源组合，不要做 caller supplement 参数，不要为 mixed Gate 物化 evidence.json。**  
在 `query.py` / `query_universe.py` 增加与 `--source` 互斥的 `--from-verified-hk-availability`：fresh `VerifiedHkBarBundle` → availability 一键一源 JOIN → plan 内嵌 no-trade 做 exact available-history → 第二次 bundle verify → 写最近 N 行。单源 API 保持原样。Windows only。

主 Agent 可将本节 + §1–§8 直接冻结为任务书正文；实现 Agent 不得在上列停机点上自行发明第三套 mapping。
