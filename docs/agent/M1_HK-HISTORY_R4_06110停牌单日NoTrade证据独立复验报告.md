# M1 HK-HISTORY R4：06110.HK 2026-06-25 停牌单日 No-Trade 证据独立复验报告

日期：2026-08-15（Asia/Shanghai）
复验模型：`cursor-grok-4.6-high`（如实记录；非底层模型名猜测）
角色：外部独立初验 Agent（全新会话；未参与 R1/R2 实现）
状态：**FAIL（返回返工）**
任务书：`docs/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据任务单.md`
交付报告：`docs/agent/M1_HK-HISTORY_R4_06110停牌单日NoTrade证据交付报告.md`

本报告只解锁主 Agent 对返工范围的复核；**不**宣称独立初验通过，**不**解锁真实 evidence/plan/journal 物化，**不**宣称 HK60 / M1 / Linux Gate。

## 独立性与范围

- 未参与实现，使用独立全新上下文：是
- 模型如实记录为 `cursor-grok-4.6-high`
- 生产代码、实现测试、任务单、交付报告只读；本会话唯一写入：本报告
- 未联网、未读取 ignored token、未 add/commit/push、未物化正式 `data/` / `artifacts`、未跑全量或 Linux/WSL Gate
- 正向探针只走公共 `load_hk_no_trade_evidence` / `build_hk_history_plan_v2` / `recover_existing_hk_history_requests`；未使用 `object.__new__`、私有 seal/registry

检查的代码、diff、测试和产物：

- 工作树未提交 diff：`src/quant/data/hk_history_backfill.py`、`src/quant/domain/schemas.py`、`tests/unit/test_hk_history_backfill.py`、`tests/unit/test_schemas.py`、任务单状态、交付报告 R2 章节
- `HKNoTradeEvidenceSchema` 列/dtype/001/004 析取；`load_hk_no_trade_evidence` → `_verify_evidence_projection` → `HKNoTradeEvidenceSchema.validate`
- 实现者 §6 测试与 Windows 定向命令
- 实现者未使用的临时对抗探针（`%TEMP%\m1_r4_ua_m1_005_independent_probe.py`；退出前删除）

## 目标文件 SHA256（开始 / 结束）

审查期间四份实现文件哈希未变，无并发漂移。

| 文件 | 开始 SHA256 | 结束 SHA256 |
| --- | --- | --- |
| `src/quant/data/hk_history_backfill.py` | `906CA2DDCC0ED55911FE3154B680AB5B9A5558D0A4DFF56A13A726EE71718394` | 同左 |
| `src/quant/domain/schemas.py` | `CD3B340E67DD819ECCE8AAF5B60433502F4E069F541E3C4D634A590B37EAB730` | 同左 |
| `tests/unit/test_hk_history_backfill.py` | `2A3073EB57DE2F7B4DF884C4B2209C9B1397721A2A533F3D32D73E36EFF6AEA8` | 同左 |
| `tests/unit/test_schemas.py` | `30EC10D31A9BAD1C859AD9FA21E1AAB8670BA6EE2841459614219E75581D5F3C` | 同左 |

`schemas.py` 未提交 diff 仅 12 行：docstring「two→three」+ UA-M1-005 exact 或支。列、dtype、`Config`、001/004 析取、其他 Schema 无漂移。本 worktree 无 `DailyBasic1dSchema`。

## 标准—证据—结论

### 1. public loader 真实经过 Schema 并接受唯一 UA-M1-005 exact key

- 证据：`load_hk_no_trade_evidence` 末尾无条件 `_verify_evidence_projection` → `HKNoTradeEvidenceSchema.validate`。独立 spy：canonical 正向调用 1 次，行=`06110.HK` / `2026-06-25` / `UA-M1-005` / 指定 selector / `USER_APPROVED_MULTI_SOURCE_CONSENSUS`。将 `validate` 改为抛 `SchemaError` 后 loader 稳定 `HK_HISTORY_REFERENCE_INVALID`，`cause/context=None`。实现者正向测试走公共 loader，无 `__new__`/seal。
- 结论：该项通过

### 2. Schema 只增加 06110∧06-25∧UA-M1-005∧exact selector；001/004 与其他契约无漂移

- 证据：git diff 只追加第三条或支。独立 Schema 探针：001/004/005 单行与三行并存 PASS；005 的 symbol/06-24/06-26/record/selector 漂移 REJECT。001 identity 公式与 canonical payload 独立加载仍成立。
- 结论：该项通过

### 3. canonical raw 逐字绑定；删除/增加/重排/URL/字段/metadata/byte 漂移拒绝

- 证据：生产 `_user_approved_trading_halt_payload` 与任务单 §3 字段、observation 顺序、两 URL、`RETAINED_ZERO_ROW`、五 `false` 一致；`value != expected or payload != canonical bytes`。实现者与独立探针均拒绝：obs 增删换序、HKEX/etnet URL 漂移、URL 对调、Tushare 语义/kind/额外 url、impact 任一 true、`changes_cash=0`、额外字段、pretty-print、001 payload 挂 005、单字节 raw/metadata。失败码均为 `HK_HISTORY_REFERENCE_INVALID`，`cause/context=None`。
- 结论：该项通过

### 4. v2 plan 只减 06110@06-25；4,693 closure 正向且 4,692/额外/重复失败

- 证据：公共 `build_hk_history_plan_v2`：`06110` effective=`2026-06-24,2026-06-26`；`00002.HK` 同三日不减。独立 80 标的 fixture：request expected=4,694、effective=4,693；`recover_existing_hk_history_requests` 对 4,693 行 retained raw PASS（`complete=True`, 0 网络）；4,692 / 额外 06-25 / 重复行 → `HK_HISTORY_RAW_INVALID`。实现者仅用 2 行微型 recover，属测试缺口，生产闭包行为成立。
- 结论：该项通过

### 5. 未知 record、错 selector/source/reason、冒充 HKEX、001/004 identity

- 证据：未知 `UA-M1-006`、错 selector、`TUSHARE_HK_DAILY`、错 reason、004 selector/001 record 挂 005 key：均拒绝。001 identity 独立探针 PASS。
- **冒充 HKEX 不拒绝**：见下方唯一返工项。
- 结论：该项不通过

### 6. hostile 脱敏、cold import、无联网/正式写入

- 证据：实现者 `test_ua_m1_005_hostile_json_stays_sanitized` 随定向 pytest 通过。cold import 模块路径位于本 worktree `src`。未联网、未写正式 data/artifacts。
- 结论：该项通过

## 问题（阻断返工）

### 现象

公共 `load_hk_no_trade_evidence` **接受** `source=HKEX_DAILY_QUOTATIONS` 且 `source_record_id=UA-M1-005`、key=`06110.HK@2026-06-25`、selector 为 UA-M1-005 的证据集。甚至 raw 为 `{"not":"halt"}` 仍 ACCEPTED。同一 garbage raw 在 `source=USER_APPROVED_MULTI_SOURCE_CONSENSUS` 时正确 REJECT。

因此 UA-M1-005 的 audited identity 可挂到 HKEX 通道，**跳过** 三条 observation、两 URL、Tushare zero-row 与五 impact=false 的逐字 verifier，随后仍可被 v2 plan 用来扣除该键。

`HKNoTradeEvidenceSchema.validate` 对该组合亦 ACCEPT（dataframe check 在 `source != USER_APPROVED_MULTI_SOURCE_CONSENSUS` 时短路为真）。这不是「绕过 Schema」，而是 Schema 对 UA-M1-005 record id 没有逆约束。

### 根因

1. `HKNoTradeEvidence.__post_init__` 只在 `source==USER_APPROVED_MULTI_SOURCE_CONSENSUS` 时调用 `_user_approved_no_trade_is_exact`。
2. `_verify_evidence_projection` 只对同一 source 调用 `_verify_user_approved_no_trade_raw`。
3. Schema check 形如 `(source != USER_APPROVED) | exact-001 | exact-004 | exact-005`，不要求 `source_record_id==UA-M1-005` ⇒ source 必须是 user-approved 且命中第三条或支。

通用 HKEX quotations 投影本就不解析 HTML（`synthetic-fixture` + garbage 对任意键同样 ACCEPTED，属既有通道）。本任务新增的是 **UA-M1-005 这一精确 identity**；它现在可以不经 halt payload 绑定而存在。

### 应遵循规则

- 任务单 §2：不得把该记录标作 `HKEX_DAILY_QUOTATIONS`；只允许 exact user-approved 析取。
- 任务单 §5 与初验清单第 5 项：错 source / 冒充 HKEX 必须拒绝。
- 任务单 §3/§4：canonical halt payload 必须由 user-approved verifier 逐字段/逐字节绑定。
- `AGENTS.md` SSOT：`HKNoTradeEvidenceSchema` 是该投影的权威契约。

### 最小复现（Windows；PYTHONPATH=本 worktree `src`；未联网）

构造 evidence JSON：`source=HKEX_DAILY_QUOTATIONS`，`source_record_id=UA-M1-005`，`symbol=06110.HK`，`trade_date=2026-06-25`，selector=`user-approved-consensus/ua-m1-005-06110-2026-06-25.record`，raw=`{"not":"halt"}` 且 metadata/hash 自洽。

```text
load_hk_no_trade_evidence(...)  →  ACCEPTED
```

对照：仅改 `source=USER_APPROVED_MULTI_SOURCE_CONSENSUS` → `HK_HISTORY_REFERENCE_INVALID`。

### 必须新增的测试

`tests/unit/test_hk_history_backfill.py`：`source=HKEX_DAILY_QUOTATIONS` + `UA-M1-005` identity（canonical halt raw 与 garbage raw 各一）必须拒绝。
`tests/unit/test_schemas.py`：同一行 Schema 必须 `SchemaError`。

### 通过条件

1. `source_record_id=UA-M1-005` 或 UA-M1-005 selector ⇒ `source` 必须是 `USER_APPROVED_MULTI_SOURCE_CONSENSUS` 且命中 `06110.HK ∧ 2026-06-25 ∧ 指定 selector`；否则 dataclass、Schema、public loader 均 `HK_HISTORY_REFERENCE_INVALID`，`cause/context=None`。
2. 不得改 Schema 列/dtype，不得放宽 001/004，不得把 06110@06-25 做成通配停牌规则。
3. 既有 HKEX quotations 通道（非 UA-M1-005 record/selector）不在本返工范围，除非主 Agent 另行重冻。
4. USER_APPROVED 正向仍必须经过 `HKNoTradeEvidenceSchema.validate`。
5. 定向 pytest / Ruff / mypy 再跑绿后，交未参与该返工实现的全新外部初验。

## 新增的对抗性反例（实现者未使用）

临时探针已删除。实现者覆盖了 2 行 recover、symbol/前后日/selector/001 record、obs 增删换序、URL `/drift`、Tushare 观察文本、impact true、raw/metadata 换行、001/004 mix identity、hostile。下列条目不在实现者用例中：

| 探针 | 期望 | 结果 |
| --- | --- | --- |
| spy：public loader 调用 `HKNoTradeEvidenceSchema.validate` 且行为含 UA-M1-005 | 调用 | PASS |
| Schema.validate 改为抛错 | loader 拒绝 | PASS |
| 4,694 expected / 4,693 effective；recover 4,693 行 | 正向闭合 | PASS |
| 4,692 / 额外 06-25 / 重复行 | `HK_HISTORY_RAW_INVALID` | PASS |
| 未知 `UA-M1-006`、错 reason、URL 对调、Tushare 加 url、kind=`HKEX_DAILY_QUOTATIONS`、pretty JSON、`changes_cash=0`、001 payload 挂 005 | 拒绝 | PASS |
| `00002.HK` 同三日不被 plan 扣除 | 不减 | PASS |
| **`source=HKEX_DAILY_QUOTATIONS` + UA-M1-005 identity（halt raw 或 garbage raw）** | **拒绝** | **FAIL（ACCEPTED）** |
| `source_as_of=+08:00` 等价瞬时 | 任务未冻结该证据字段字面量 | 接受（非阻断；见残余） |

## Windows 定向验证

`PYTHONPATH` 指向本 worktree `src`。解释器：`D:\Miniforge3\python.exe`。

| 命令 | 结果 | 摘要 |
| --- | --- | --- |
| pytest `test_hk_history_backfill.py` + Schema 两 HKNoTrade 节点 | 通过 | 135 passed, 2 skipped，139.13s |
| `ruff check` 四白名单文件 | 通过 | All checks passed |
| `mypy` 两生产文件 | 通过 | no issues found in 2 source files |
| cold import loader/plan/Schema | 通过 | 路径位于本 worktree |
| 独立对抗探针 | 阻断 | 36 项中 2 项红；仅 HKEX 冒充为合同失败 |

未运行 Linux/WSL、全量 pytest、真实回填或联网。实现者自测绿不能覆盖本 FAIL。

## 结论

- **返回返工**。USER_APPROVED exact 正向、Schema 析取、canonical 字节绑定、4,693 closure、001/004 identity、hostile/cold import 已独立证实。
- 阻断点：UA-M1-005 identity 可经 HKEX source 绕过 halt payload verifier。
- PASS 条件满足前，主 Agent **不得**物化正式 raw/metadata/新 v2 plan/journal，**不得**进入 HK60 恢复。
- 下一步：主 Agent 确认契约（建议按「UA-M1-005 record/selector 必须绑定 USER_APPROVED exact 或支」最小修补）→ 外部实现返工 → 另一全新外部初验。

## 残余风险（非本轮阻断）

- `source_as_of` 接受 `2026-08-15T08:00:00+08:00`：该字段不在 halt raw 内，identity 按字符串计入；物化时须由主 Agent 显式冻结 `+00:00`，不必在本返工扩成 loader 字面量锁。
- 通用 `HKEX_DAILY_QUOTATIONS` + 非 UA-M1-005 record 仍不解析 quotations HTML；关闭该通道超出 R4 任务单。
- 实现者缺少 4,693 行与 HKEX 冒充用例；前者行为已独立证实，后者必须随返工补测。
