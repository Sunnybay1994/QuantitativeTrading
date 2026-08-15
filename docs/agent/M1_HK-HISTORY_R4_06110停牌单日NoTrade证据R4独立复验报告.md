# M1 HK-HISTORY R4：06110.HK 2026-06-25 停牌单日 No-Trade 证据 R4 独立复验报告

日期：2026-08-15（Asia/Shanghai）
复验模型：`cursor-grok-4.6-high`（如实记录；非底层模型名猜测）
角色：外部独立复验 Agent（全新会话；未参与 R4 实现）
状态：**PASS（仅解锁主 Agent 主验与真实 evidence/plan/journal 物化）**
任务书：`docs/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据任务单.md` §11
交付报告：`docs/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据交付报告.md` R4 章
R3 独立复验：`docs/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据R3独立复验报告.md`（PASS；残余 UA-M1-001/004 仍可挂 HKEX）
待验提交：`11a71f5`（合同提交 `a75110d`）

本报告**不**宣称 HK60 / M1 / Linux Gate，**不**宣称真实网络恢复或正式 data 已物化。

## 独立性与范围

- 未参与实现，使用独立全新上下文：是
- 模型如实记录为 `cursor-grok-4.6-high`
- 生产代码、实现测试、任务单、交付报告和旧复验报告只读；本会话唯一写入：本报告
- 未联网、未读取 ignored token、未 add/commit/push、未物化正式 `data/` / `artifacts`、未跑全量或 Linux/WSL Gate
- 正向探针只走公共 `load_hk_no_trade_evidence` / `HKNoTradeEvidence` / `HKNoTradeEvidenceSchema.validate` / `build_hk_history_plan_v2` / `recover_existing_hk_history_requests`
- 未使用 `object.__new__`、私有 seal/registry；未把 public `validate` 改成接受器来构造正向。Schema spy 只包装真实 `validate` 计数；另一次注入 `SchemaError` 仅作负向映射探针。hostile 只替换 `_verify_user_approved_no_trade_raw` 以注入异常图。

检查的代码、diff、测试和产物：

- `git log/diff a75110d..HEAD`；工作树干净，HEAD=`11a71f5`
- `HKNoTradeEvidence.__post_init__` 对 `UA-M1-` record 与 `user-approved-consensus/` selector 的命名空间反向 source 绑定
- `HKNoTradeEvidenceSchema.user_approved_identity_namespace_binds_source` 与既有 001/004/005 exact 析取
- `load_hk_no_trade_evidence` → `_verify_evidence_projection` → 真实 `HKNoTradeEvidenceSchema.validate`
- 实现者 §11.4 测试；实现者未使用的临时对抗探针（`%TEMP%\m1_r4_ua_namespace_r4_independent_probe.py`；退出前删除）

## 目标文件 SHA256（开始 / 结束）

审查期间四份实现文件哈希未变，无并发漂移。

| 文件 | 开始 SHA256 | 结束 SHA256 |
| --- | --- | --- |
| `src/quant/data/hk_history_backfill.py` | `78703B07040C5EFA2C984D064CDFE4726862995336FF997D60C5A4F91FC4E646` | 同左 |
| `src/quant/domain/schemas.py` | `C01F721D2508D7771265D78409225A93FE00F51360134D14C6908AF12821D956` | 同左 |
| `tests/unit/test_hk_history_backfill.py` | `44947C7BAAA2513FB64CB9DFCF59449E0235DACA72641CF9A10AECD73B53D2F1` | 同左 |
| `tests/unit/test_schemas.py` | `DF14B9998730CAB31D922ACD5FF31B28A26C77865C4ED6BCBE1F93FB2551DE4B` | 同左 |

`a75110d..HEAD` 生产 diff 仅：把 R3 的 UA-M1-005-only 反向约束提升为 `UA-M1-` / `user-approved-consensus/` 命名空间绑定 + 对应测试/任务文档。Schema 列/dtype/`Config`/001/004/005 exact 析取未改。本 worktree 无 `DailyBasic1dSchema`。

## 标准—证据—结论

### 1. UA-M1-001/004/005 各自 exact identity 改标 HKEX，canonical 与可解析 garbage raw 均拒绝；cause/context=None

- 证据：对三条记录分别构造 `source=HKEX_DAILY_QUOTATIONS`，保留 exact record/selector/key，并把 canonical metadata `source` 同步为 HKEX。raw 分别为各自 canonical JSON 与独立 nested garbage `{"arr":[0,1],"nested":{"ok":true,"n":0},"tag":"r4-indep"}`（实现者只用 `{"not":"halt"}`）。dataclass / Schema / public loader 三边界均为拒绝；loader 稳定 `HK_HISTORY_REFERENCE_INVALID`，`__cause__`/`__context__` 为 `None`。
- 结论：通过

### 2. 每条只保留 `UA-M1-*` record 或只保留 `user-approved-consensus/` selector，配 HKEX 或另一非 USER source，fail closed

- 证据：独立 HKEX selector `hkex/quotations/r4-indep-01065-20260505.html` / `...02402-20260414.html` / `...06110-20260625.html` + 对应 UA record；独立 record `hkex-r4-indep-record-001/004/005` + exact user-approved selector。另用 `TUSHARE_HK_DAILY` 对三条分别做 record-only / selector-only。上述均在 dataclass / Schema / loader 拒绝，loader `cause/context=None`。
- 结论：通过

### 3. 未知 `UA-M1-999` 与未知 `user-approved-consensus/fake.record` 不能挂 HKEX，也不能以 USER 越过 existing exact allowlist

- 证据：`UA-M1-999` + 独立 HKEX selector；`UA-M1-999` + USER + UA-M1-005 exact selector/key；`user-approved-consensus/fake.record` + HKEX + 非 UA record；`fake.record` + USER + `UA-M1-001` exact key。四组均在三边界拒绝。实现者 Schema 只用了 `UA-M1-006` / `ua-m1-006-unknown.record`，且未走 public loader。
- 结论：通过

### 4. canonical USER_APPROVED 001/004/005 经真实 Schema/raw verifier 继续通过，identity 字节不变

- 证据：包装真实 `HKNoTradeEvidenceSchema.validate` 计数 = 3，行分别为 UA-M1-001 / 004 / 005。raw 字节与各自 canonical payload 一致。loader 存储的 `evidence_sha256` 等于由公开字段重算的 identity；二次加载 identity 字节不变。将 `validate` 改为抛 `SchemaError` 后 loader 映射为 `HK_HISTORY_REFERENCE_INVALID`，`cause/context=None`。
- 结论：通过

### 5. 普通 HKEX 使用非 UA record + 非 user-approved selector 继续通过；不要求 HTML 语义 parser

- 证据：独立 HTML `R4-INDEP ordinary quotations; no semantic parser required`，record=`r4-indep-ordinary-01065/02402/06110`，selector=`hkex/quotations/r4-indep-ordinary-*.html`。对 `01065@05-05` / `02402@04-14` / `06110@06-25` 三组，public loader / dataclass / Schema 均 ACCEPTED，且未进入 user-approved raw verifier。
- 结论：通过

### 6. 4,693/4,694 raw closure、hostile 异常图、cold import、Schema 列/dtype 保持

- 证据：独立 80 标的 fixture：request expected=4,694、effective=4,693；`06110` 只去 `2026-06-25` 且保留 `06-24`/`06-26`；`00002.HK` 同三日不被扣。`recover_existing_hk_history_requests` 对 4,693 行 retained raw PASS（`complete=True`，0 网络）。4,692 / 额外 `06-25` / 重复行 → `HK_HISTORY_RAW_INVALID`。hostile 注入 `_verify_user_approved_no_trade_raw` 异常图，公共码脱敏且 `cause/context=None`。cold import 模块路径位于本 worktree `src`。Schema 12 列、`trade_date=pl.Date`、`source_as_of=pl.Datetime`、`Config.strict/coerce` 未变。
- 结论：通过

### 7. 禁止伪正向构造

- 证据：实现者 R4 测试与本探针均未用 `object.__new__`、私有 seal/registry，也未把 public validator 改成接受器来构造正向。canonical 正向经公共 loader 与真实 Schema。
- 结论：通过

## 新增的对抗性反例（实现者未使用）

临时探针已删除。实现者覆盖了 HKEX+canonical/`{"not":"halt"}`、HKEX record-only（`hkex/daily/d260505e.html` 等）、HKEX selector-only（`synthetic-fixture-record`）、Schema 层 `UA-M1-006` / `ua-m1-006-unknown.record`、普通 `_evidence` 夹具、001/004/005 canonical 正向。下列条目不在实现者用例中：

| 探针 | 期望 | 结果 |
| --- | --- | --- |
| spy：public loader 三次调用真实 `HKNoTradeEvidenceSchema.validate`，行=001/004/005 | 3 次调用 | PASS |
| Schema.validate 改为抛错 | loader `HK_HISTORY_REFERENCE_INVALID`，cause/context=None | PASS |
| 001/004/005 各挂 HKEX + 同步 metadata + nested garbage | 三边界拒绝 | PASS |
| 独立 `hkex/quotations/r4-indep-*.html` record-only；独立 `hkex-r4-indep-record-*` selector-only | 三边界拒绝 | PASS |
| `TUSHARE_HK_DAILY` 对 001/004/005 只放 record / 只放 selector | 三边界拒绝 | PASS |
| `UA-M1-999` 挂 HKEX；`UA-M1-999` + USER 挂 005 selector | 三边界拒绝 | PASS |
| `user-approved-consensus/fake.record` 挂 HKEX；同 selector + USER + UA-M1-001 | 三边界拒绝 | PASS |
| 独立 HTML 的普通 HKEX 01065/02402/06110（非 UA 身份） | 接受 | PASS |
| 4,694 expected / 4,693 effective；recover 4,693 行 | 正向闭合 | PASS |
| 4,692 / 额外 06-25 / 重复行 | `HK_HISTORY_RAW_INVALID` | PASS |
| `00002.HK` 同三日不被 plan 扣除 | 不减 | PASS |
| hostile verifier 异常图 | 脱敏 + cause/context=None | PASS |

## Windows 定向验证

`PYTHONPATH` 指向本 worktree `src`。解释器：`D:\Miniforge3\python.exe`。

| 命令 | 结果 | 摘要 |
| --- | --- | --- |
| pytest `test_hk_history_backfill.py` + Schema 两 HKNoTrade 节点 | 通过 | 137 passed, 2 skipped，115.68s |
| `ruff check` 四白名单文件 | 通过 | All checks passed |
| `mypy` 两生产文件 | 通过 | no issues found in 2 source files |
| cold import loader/plan/Schema | 通过 | 路径位于本 worktree |
| 独立对抗探针 | 通过 | 111 passed, 0 failed |

未运行 Linux/WSL、全量 pytest、真实回填或联网。实现者自测绿不能代替本独立复验。

## 结论

- **PASS。** R3 阻断的 user-approved 命名空间换源缺口已在 dataclass、Schema 与 public loader 三边界关闭：UA-M1-001/004/005 及未知 `UA-M1-*` / `user-approved-consensus/` 身份不能挂 HKEX 或其他非 USER source；canonical USER_APPROVED 正向仍经真实 Schema 与逐字节 raw verifier，identity 字节不变。
- 本结论只解锁主 Agent 主验与任务单 §9 的真实 raw/metadata/新 v2 plan/journal 物化。
- **不**宣称 HK60 / M1 / Linux Gate，**不**宣称正式 data 已写入。

## 残余风险（非本轮阻断）

- `source_as_of` 仍按字符串计入 identity；物化时须由主 Agent 显式冻结 `+00:00`，不得用 mtime/now 推断。
- 通用 `HKEX_DAILY_QUOTATIONS` + 非 UA / 非 `user-approved-consensus/` 身份仍不解析 quotations HTML；关闭该通道超出本轮合同。
- 命名空间规则是前缀合同（`UA-M1-`、`user-approved-consensus/`），不是对任意相似字符串的模糊匹配；这与任务书 §11.3 一致。
