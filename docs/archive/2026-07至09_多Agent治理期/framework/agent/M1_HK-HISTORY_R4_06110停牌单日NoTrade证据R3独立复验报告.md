# M1 HK-HISTORY R4：06110.HK 2026-06-25 停牌单日 No-Trade 证据 R3 独立复验报告

日期：2026-08-15（Asia/Shanghai）
复验模型：`cursor-grok-4.6-high`（如实记录；非底层模型名猜测）
角色：外部独立复验 Agent（全新会话；未参与 R1/R2/R3 实现）
状态：**PASS（仅解锁主 Agent 主验与真实 evidence/plan/journal 物化）**
任务书：`docs/framework/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据任务单.md` §10
交付报告：`docs/framework/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据交付报告.md` R3 章
R2 独立复验：`docs/framework/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据独立复验报告.md`（FAIL，反向来源绑定缺口）
待验提交：`90f8d20`（此前合同/报告提交 `2ba1e80`）

本报告**不**宣称 HK60 / M1 / Linux Gate，**不**宣称真实网络恢复或正式 data 已物化。

## 独立性与范围

- 未参与实现，使用独立全新上下文：是
- 模型如实记录为 `cursor-grok-4.6-high`
- 生产代码、实现测试、任务单、交付报告和旧复验报告只读；本会话唯一写入：本报告
- 未联网、未读取 ignored token、未 add/commit/push、未物化正式 `data/` / `artifacts`、未跑全量或 Linux/WSL Gate
- 正向探针只走公共 `load_hk_no_trade_evidence` / `HKNoTradeEvidence` / `HKNoTradeEvidenceSchema.validate` / `build_hk_history_plan_v2` / `recover_existing_hk_history_requests`
- 未使用 `object.__new__`、私有 seal/registry；未把 public `validate` monkeypatch 成接受器来构造正向。Schema spy 只包装真实 `validate` 计数；另一次注入 `SchemaError` 仅作负向映射探针。

检查的代码、diff、测试和产物：

- `git log/diff 9fc08ba..HEAD` 与 `2ba1e80..90f8d20`；工作树干净，HEAD=`90f8d20`
- `HKNoTradeEvidence.__post_init__` 对 UA-M1-005 record/selector 的反向 source 绑定
- `HKNoTradeEvidenceSchema.ua_m1_005_identity_binds_user_approved_source` 与既有 exact 析取
- `load_hk_no_trade_evidence` → `_verify_evidence_projection` → 真实 `HKNoTradeEvidenceSchema.validate`
- 实现者 §6 / §10.4 测试；实现者未使用的临时对抗探针（`%TEMP%\m1_r4_ua_m1_005_r3_independent_probe.py`；退出前删除）

## 目标文件 SHA256（开始 / 结束）

审查期间四份实现文件哈希未变，无并发漂移。

| 文件 | 开始 SHA256 | 结束 SHA256 |
| --- | --- | --- |
| `src/quant/data/hk_history_backfill.py` | `14BC351BED66154ECCDF8255CE18B448839D510E116C51ABA615AEAA3EA46FF2` | 同左 |
| `src/quant/domain/schemas.py` | `9633E11FB631EB491717DC7648A7A57A2B4878CB0DB08DF9BB22D1EA7211D691` | 同左 |
| `tests/unit/test_hk_history_backfill.py` | `826CF3467978DA6AA5C9A856F290DF4A64AED6EB37F3FF5A20C752740B3128F2` | 同左 |
| `tests/unit/test_schemas.py` | `EE98BAFE067C94ABAA5E00AE50B43018446518B11C29B5D9B3BB60DF8F643839` | 同左 |

`9fc08ba..HEAD` 生产 diff 仅：第三条 exact 或支 + UA-M1-005 反向来源绑定 + 对应测试/任务文档。Schema 列/dtype/`Config`/001/004 析取未改。本 worktree 无 `DailyBasic1dSchema`。

## 标准—证据—结论

### 1. HKEX + UA-M1-005 canonical identity + canonical/garbage raw 必须拒绝；cause/context=None

- 证据：独立探针 `hkex-canonical-raw`、`hkex-nested-garbage`（`{"nested":{"ok":[1,2,3]},"n":0}`）、`hkex-partial-halt-garbage`（仅 approval/decision）。dataclass / Schema / public loader 三边界均为拒绝；loader 稳定 `HK_HISTORY_REFERENCE_INVALID`，`__cause__`/`__context__` 为 `None`。实现者只用了 `{"not":"halt"}`。
- 结论：通过

### 2. 只放 UA-M1-005 record 或只放 exact selector，配任意非 USER_APPROVED source，fail closed

- 证据：独立 selector `hkex/daily/r3-indep-d260625e.html` + record=`UA-M1-005` + HKEX；独立 record `hkex-r3-indep-record` + exact selector + HKEX；另用 `TUSHARE_HK_DAILY` 分别只放 record / 只放 selector。再加 HKEX + 完整 identity 但 symbol=`00002.HK` 或 date=`2026-06-24`，以及 HKEX + UA-M1-005 record + UA-M1-004 selector。上述均在 dataclass / Schema / loader 拒绝，loader `cause/context=None`。
- 结论：通过

### 3. canonical USER_APPROVED UA-M1-005 经真实 Schema 与 raw verifier；symbol/date/record/selector 漂移拒绝

- 证据：包装真实 `HKNoTradeEvidenceSchema.validate` 计数 = 1，行=`06110.HK` / `2026-06-25` / `UA-M1-005` / exact selector / `USER_APPROVED_MULTI_SOURCE_CONSENSUS`。raw 字节与任务单 §3 canonical JSON 一致；observations 顺序、HKEX/etnet URL、`RETAINED_ZERO_ROW`、五 impact=`false` 一致。将 `validate` 改为抛 `SchemaError` 后 loader 映射为 `HK_HISTORY_REFERENCE_INVALID`。漂移 `06111.HK` / `06-24` / `06-26` / `UA-M1-006` / 001 selector 均拒绝。独立还拒绝 URL 对调、Tushare 加 url、Tushare `source_kind=HKEX_DAILY_QUOTATIONS`、`changes_cash=0`、pretty-print、001 payload 挂 005。
- 结论：通过

### 4. 普通 HKEX quotation 未被误收紧；UA-M1-001/004 正向与 identity 保持

- 证据：同 `06110.HK@2026-06-25` 但不携 UA-M1-005 身份（独立 HTML raw + record=`r3-indep-ordinary-06110`）loader/Schema 均 ACCEPTED。001 单独加载 identity=`UA-M1-001@01065.HK@2026-05-05`；004 单独加载 13 行。同 key 的普通 HKEX 行与 UA-M1-005 并存被 Schema 唯一键拒绝。
- 结论：通过

### 5. 4,693 retained raw + exact evidence 闭包；canonical 观察；hostile / cold import

- 证据：独立 80 标的 fixture：request expected=4,694、effective=4,693；`06110` 只去 `2026-06-25` 且保留 `06-24`/`06-26`；`00002.HK` 同三日不被扣。`recover_existing_hk_history_requests` 对 4,693 行 retained raw PASS（`complete=True`，0 网络）。4,692 / 额外 `06-25` / 重复行 → `HK_HISTORY_RAW_INVALID`。hostile 注入 `_verify_user_approved_no_trade_raw` 异常图，公共码脱敏且 `cause/context=None`。cold import 模块路径位于本 worktree `src`。
- 结论：通过

### 6. 禁止伪正向构造

- 证据：实现者 UA-M1-005 测试与本探针均未用 `object.__new__`、私有 seal/registry，也未把 public validator 改成接受器来构造正向。canonical 正向经公共 loader 与真实 Schema。
- 结论：通过

## 新增的对抗性反例（实现者未使用）

临时探针已删除。实现者覆盖了 HKEX+canonical/`{"not":"halt"}`、HKEX record-only（`hkex/daily/d260625e.html`）、HKEX selector-only（`synthetic-fixture-record`）、USER_APPROVED record/selector 漂移、普通 HKEX `_evidence` 夹具、obs 增删换序、URL `/drift`、Tushare 观察文本、impact true、raw/metadata 换行、001/004 mix、hostile `_strict_json`、2 行微型 recover。下列条目不在实现者用例中：

| 探针 | 期望 | 结果 |
| --- | --- | --- |
| spy：public loader 调用真实 `HKNoTradeEvidenceSchema.validate` 且行为含 UA-M1-005 | 1 次调用 | PASS |
| Schema.validate 改为抛错 | loader `HK_HISTORY_REFERENCE_INVALID`，cause/context=None | PASS |
| HKEX + 完整 identity + nested/partial garbage raw | 三边界拒绝 | PASS |
| HKEX + 只 record + 独立 selector；HKEX + 只 selector + 独立 record | 三边界拒绝 | PASS |
| `TUSHARE_HK_DAILY` + 只 record / 只 selector | 三边界拒绝 | PASS |
| HKEX + 完整 identity 但 symbol/date 漂移；HKEX + 005 record + 004 selector | 三边界拒绝 | PASS |
| URL 对调、Tushare 加 url、kind=`HKEX_DAILY_QUOTATIONS`、pretty JSON、`changes_cash=0`、001 payload 挂 005、`UA-M1-006` | 拒绝 | PASS |
| 独立 HTML 的普通 HKEX `06110@06-25`（非 UA-M1-005 身份） | 接受 | PASS |
| 4,694 expected / 4,693 effective；recover 4,693 行 | 正向闭合 | PASS |
| 4,692 / 额外 06-25 / 重复行 | `HK_HISTORY_RAW_INVALID` | PASS |
| `00002.HK` 同三日不被 plan 扣除 | 不减 | PASS |
| hostile verifier 异常图 | 脱敏 + cause/context=None | PASS |
| `source_as_of=+08:00` 等价瞬时 | 任务未冻结字面量 | 接受（非阻断；见残余） |
| HKEX + UA-M1-001 identity | 本轮未要求泛化 | 仍接受（残余） |

## Windows 定向验证

`PYTHONPATH` 指向本 worktree `src`。解释器：`D:\Miniforge3\python.exe`。

| 命令 | 结果 | 摘要 |
| --- | --- | --- |
| pytest `test_hk_history_backfill.py` + Schema 两 HKNoTrade 节点 | 通过 | 136 passed, 2 skipped，109.80s |
| `ruff check` 四白名单文件 | 通过 | All checks passed |
| `mypy` 两生产文件 | 通过 | no issues found in 2 source files |
| cold import loader/plan/Schema | 通过 | 路径位于本 worktree |
| 独立对抗探针 | 通过 | 合同项全绿；仅观测项见残余 |

未运行 Linux/WSL、全量 pytest、真实回填或联网。实现者自测绿不能代替本独立复验。

## 结论

- **PASS。** R2 阻断的 UA-M1-005 record/selector 反向来源绑定已在 dataclass、Schema 与 public loader 三边界关闭；canonical USER_APPROVED 正向仍经真实 Schema 与逐字节 raw verifier。
- 本结论只解锁主 Agent 主验与任务单 §9 的真实 raw/metadata/新 v2 plan/journal 物化。
- **不**宣称 HK60 / M1 / Linux Gate，**不**宣称正式 data 已写入。

## 残余风险（非本轮阻断）

- `source_as_of` 仍接受 `2026-08-15T08:00:00+08:00`：该字段不在 halt raw 内，identity 按字符串计入；物化时须由主 Agent 显式冻结 `+00:00`。
- UA-M1-001（及同类 004）record/selector 仍可挂 `HKEX_DAILY_QUOTATIONS` 并被公共 loader 接受。任务书 §10 明确只绑定 UA-M1-005、不得泛化 001/004；若主 Agent 要关闭同一类洞，需另冻任务。
- 通用 `HKEX_DAILY_QUOTATIONS` + 非 UA-M1-005 身份仍不解析 quotations HTML；关闭该通道超出 R4。
- 实现者仍缺少 4,693 行 recover 用例；生产闭包已由本轮独立 fixture 证实，不阻塞主验。
