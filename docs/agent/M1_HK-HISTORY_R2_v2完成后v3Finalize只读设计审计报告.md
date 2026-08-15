# M1 HK-HISTORY R2：v2 完成后 v3 Finalize 只读设计审计报告

日期：2026-08-15（Asia/Shanghai）  
角色：外部只读设计审计 Agent（M1 HK60 post-8/8 finalize；未参与实现）  
模型：`cursor-grok-4.6-high`（如实记录；不得声称其他底层模型）  
约束：已读根 `AGENTS.md`、`.ai/README.md`；只读现行代码/测试与 `docs/agent` 相关任务/验收；**未读取** `data/`、`artifacts/`、ignored 配置或秘密；**未联网**；**未运行**真实数据命令；生产代码、测试与既有文档只读；本文件为唯一写入；未 `git add/commit/push`。

前提声明：本审计**不核验**当前工作树是否已经 `8/8`。`8/8` 只能由 v2 plan 的 `len(requests)` 与 journal 内 8 份 fresh 可验 receipt 共同证明。下列顺序仅在该前提已成立时唯一合法。

---

## 0. 压缩结论

| 项 | 裁决 |
|---|---|
| 8/8 之后到 Windows clean 正式发布的**唯一调用顺序** | ① 零网络 `--recover-existing-only` 证明 `completed_requests=total_requests` 且 `is_complete=true` → ② **一次** `--finalize-v3`（显式 raw+metadata）写入 `data/clean/bar_1d` 与 journal 四文件 → ③ 进程内 `load_verified_hk_bar_bundle` fresh 验真。禁止 `--finalize`、禁止默认联网 execute、禁止混模式 |
| 唯一 public CLI | `python -m quant.data.backfill_hk_history`；Windows 解释器 `D:\Miniforge3\python.exe` |
| required retained inputs | v2 plan + 已绑定 v2 journal（8 receipt）+ seed raw；HKEX `02983.HK@2026-07-10` **raw+canonical metadata 成对文件**；plan 内精确 `01065.HK@2026-05-05` 的 `USER_APPROVED_MULTI_SOURCE_CONSENSUS` evidence 及其 raw/metadata sidecar；调用方 quiescence |
| 已有工程前置 | V3M-P0 R3 `--finalize-v3` 外壳主验 PASS；PRE-B R4 v3 availability/`VerifiedHkBarBundle` 主验 PASS；02983 parser SHA 已对齐 R2 留存；用户例外已写入 evidence 合同 |
| 缺失工程前置 | **formal V3M-P1 execution manifest 不存在**（治理缺口，不是第二套 finalize 实现）；无 public CLI 封装 `load_verified_hk_bar_bundle`；`query_universe` 消费的 `clean/hk_no_trade_evidence/evidence.json` **不由 finalize 发布** |
| 用户参与点 | 确认 8/8 journal 路径；确认 Windows `data/clean/bar_1d` 为正式发布根；在 loader→finalize 窗口对 retained 双文件与 journal/clean **无并发 writer**；接受 clean 与四文件**非全局原子** |
| 停止条件 | recover 非 8/8；路径隔离失败；bundle/identity 漂移；缺 receipt；key 闭包失败；clean 同键异值；四文件 partial；任何联网/`--finalize`/改写 R1 |
| 仍阻止 **M1 Gate** | 双 Route available-history complete（含 `source=tushare` vs `hkex` 分裂与 evidence.json 未物化）；31 只 HK ETF licensed Instrument；licensed CA / 真实复权 / formal P1C；路线图「港股连续性」未勾；主树未合流 |
| 只阻止 **Linux/ext4** | WSL1/DrvFS；`CleanBarStore.upsert` 使用 `Path.replace` 而非 `RENAME_NOREPLACE`；Windows 绿测/DrvFS ≠ ext4 Gate。**不阻止**本轮 Windows clean 正式发布 |

**一句话：** v2 `8/8` 之后不得再联网、不得走 legacy `--finalize`；Windows clean 正式发布的唯一入口是现有 `--finalize-v3`。它关闭的是 HK60 bar 的 Windows 轨发布，**不能**宣称 HK60 子 Gate、M1 Gate 或 Linux/ext4 Gate。

---

## 1. 审计范围与权威来源

### 1.1 已读契约（现行，不以过期页眉为准）

- 协作/环境：根 `AGENTS.md` §1.1/§4/§5/§8/§11；`.ai/README.md`、`.ai/coding_rules.md`、`.ai/review_checklist.md`
- v2：`M1_HK-HISTORY-R2_无行情事实与零网络恢复任务单.md`（工程合同由 R4 主验吸收脱敏缺口）
- 02983：P0/P1 主验；`M1_HKEX-02983-R2_20260815官方Raw重留存报告.md`
- availability / v3：PRE-B 任务单与 R4 主验；V3M-P0 任务单与 R3 主验
- P1A/P1B 主验（development）；P1C **无任务实现链**
- 用户裁决：`docs/用户待批示与参与事项.md` UA-M1-001（2026-08-15）、UA-M1-002
- 代码 SSOT：`backfill_hk_history.py`、`hk_history_backfill.py`、`hkex_daily_quotations.py`、`query_universe.py`、`storage.CleanBarStore`

### 1.2 本审计明确不关闭的表述

未读磁盘 plan/journal/raw/clean，因此**不宣称**当前已 8/8、不宣称 Windows clean 已发布、不宣称任何 Gate 通过。

---

## 2. 8/8 的精确定义（进入本顺序的门闩）

代码事实：v2 plan 对非 seed、非 unresolved 证券按 `HK_HISTORY_MAX_BATCH_SYMBOLS=80` 切批；HK60 合同冻结为 **8 个 request**。`8/8` 不是「又跑了一次 CLI」，而是同时成立：

1. `plan.schema_version == "hk-history-plan-v2"`
2. `len(plan.requests) == 8`
3. journal `binding.json` 与 `plan.journal_id` / `plan.plan_sha256` / `no_trade_evidence_sha256` exact 绑定
4. 每个 request 均有 `_verify_receipt` 可接受的 COMPLETE receipt（finalize 遇缺 receipt → `HK_HISTORY_INCOMPLETE`）
5. unresolved **精确**为 `(("02983.HK", ("2026-07-10",)),)`；`01065.HK@2026-05-05` 已从 `effective_expected_dates` 扣除，且不得回流为 bar

旧 R1 plan SHA `ffbf8f345626…50a03` 及其 journal **永久只读**，不得作为本顺序的 `--plan` / `--journal-root`。

默认 execute 模式在分流前就会 `TushareConnector(config_path=...)`。8/8 之后再跑默认模式会触碰 ignored 配置语义，即使 `execute_next` 在无 pending 时不再发网。**8/8 后禁止默认 execute。**

---

## 3. 唯一调用顺序（v2 8/8 → Windows clean 正式发布）

解释器：Windows 轨 `D:\Miniforge3\python.exe`（`PYTHONPATH=src` 若未 editable install）。不得用该结果宣称 WSL/ext4 Gate。

### 步骤 0 — 操作员冻结（无新代码；V3M-P1 的最小诚实替代）

在调用 CLI 前，由用户/主 Agent 写下不可变运行绑定（现有代码**没有** execution manifest 文件格式；不得发明第二套 finalize）。至少绑定：

- v2 `--plan` 绝对路径与 `plan_sha256`
- 已绑定 `--journal-root`（含 `binding.json`，**不是** R1 `ffbf8f34…`，也不是未绑定的 CLI 默认根，除非该默认根就是本 plan 的 journal）
- `--data-root`（正式 Windows 根；派生 `raw` 与 `clean/bar_1d`）
- HKEX retained raw/metadata 绝对路径、size/SHA、metadata identity、bundle identity（权威数值见 §5，来自 R2 **文档**而非本审计读盘）
- 声明：自 loader 打开双文件起，至 `finalize_hk_history` 消费 returned bundle 止，retained 双文件、journal、clean **无并发 writer**

无此绑定仍**能**调用现有 CLI（功能已在），但违反 V3M-P0 R3「formal 运行前须绑定 write-once 来源与执行期 quiescence」。本审计裁定：步骤 0 是正式 Windows 发布的治理前置，不是新 parser/新 CLI。

### 步骤 1 — 零网络完整性探针（不写 clean）

```text
python -m quant.data.backfill_hk_history
  --plan <v2-plan.json>
  --data-root data
  --journal-root <v2-journal-root>
  --recover-existing-only
```

禁止同时出现 `--finalize` / `--finalize-v3` / `--confirm-uncertain-retry` / `--hkex-retained-*` / `--config`。

通过 stdout（单行 JSON）：`status=PASS`，`recover_existing_only=true`，`network_requests=0`，`completed_requests` 等于 `total_requests`，`is_complete=true`。  
失败：`HK_HISTORY_INCOMPLETE`（首个 ABSENT raw）或 `HK_HISTORY_RAW_INVALID` / `HK_HISTORY_PLAN_CONFLICT` / `HK_HISTORY_REFERENCE_INVALID` → **立即停止**，不得进入步骤 2。

本步不写 intent/attempt/failure/clean/finalize。若 8 份 receipt 已存在，行为是只读复验。它是 8/8 的**唯一零网络、零 connector 构造**公共证明。

### 步骤 2 — 唯一 Windows clean 正式发布（v3）

```text
python -m quant.data.backfill_hk_history
  --plan <v2-plan.json>
  --data-root data
  --journal-root <v2-journal-root>
  --finalize-v3
  --hkex-retained-raw <02983-raw>
  --hkex-retained-metadata <02983-canonical-metadata>
```

**必须同时有** `--finalize-v3`、`--hkex-retained-raw`、`--hkex-retained-metadata`。  
**必须省略** `--finalize`、`--recover-existing-only`、`--confirm-uncertain-retry`、`--config`。

CLI 合同（`backfill_hk_history.py`）：

1. `_validate_modes`：缺 raw/metadata、或与 legacy/recover/retry 混用 → `HK_HISTORY_PLAN_CONFLICT`（在读 plan 之前）
2. `_validate_finalize_paths`：resolved journal、`data-root/raw`、`data-root/clean/bar_1d` pairwise disjoint、互不为祖先、无 symlink/reparse/physical alias；plan 文件不得位于任一可写 root 内。`data-root` 作为共同父目录合法
3. `load_verified_hkex_retained_bundle_for_finalize(raw, metadata)`：same-window anchored 首读 → `verify_hkex_daily_quotation_retained(..., source_url=SOURCE_URL, expected_raw_sha256=EXPECTED_RAW_SHA256)` → held-instance 复读；**只**把 exact bundle 传给 `finalize_hk_history(..., hkex_retained_bundle=bundle)`，不传 `hkex_retained_raw`
4. 成功 stdout 必须含 `finalize_schema_version="hk-history-finalize-v3"`、`published_rows`、`retained_bundle_id`、`retained_metadata_identity`；stderr 无 payload
5. 信任边界（V3M-P0 R3）：不证明双路径共同瞬间不可变；违反 quiescence 时返回的仍是 verifier 首读 bundle

finalize 内部顺序（不可改、不可拆成两次 CLI）：

1. v2 plan + unresolved exact + fresh re-verify bundle → HKEX 一行 `source=hkex`、`adj_factor=1.0`
2. 锁 journal；验 seed；绑 v2 journal；8 个 receipt 全过
3. concat seed+requests+hkex；`Bar1dSchema`；**effective** expected keys 闭包（无 01065 回流）
4. 为每个 effective key 建 availability（`SEED_RAW` / `REQUEST_RAW` / `HKEX_SUPPLEMENT`），`bar_available_at` 来自 retained `fetched_at` / `source_observed_at`，禁止用时钟/mtime
5. `_preflight_clean`：同键异值 fail closed（`HK_HISTORY_PUBLISH_CONFLICT`）；同键同值可幂等
6. `CleanBarStore(clean/bar_1d).upsert` 然后 `_verify_published`
7. 再写 journal 四文件：`hkex-retained.raw`、`hkex-retained.metadata.json`、`availability.json`、`finalize.json`（schema `hk-history-finalize-v3`）；exact-set no-clobber；异 bytes / partial → `HK_HISTORY_FINALIZE_V3_INVALID`

**诚实非原子边界：** upsert 在四文件之前。四文件失败**不回滚 clean**。同键同值允许重放四文件；同键异值在 preflight 即停。不得手工删竞争/partial 文件来「修好」。

### 步骤 3 — fresh 发布验真（无 public CLI）

`load_verified_hk_bar_bundle(plan, journal_root, seed_raw_root, raw_store, clean_root, as_of)` 只接受 v3 finalize+availability；v1/v2 → `HK_HISTORY_AVAILABILITY_UNSUPPORTED`。  
**没有**对应 `python -m` 入口。Windows 正式发布的最小验真是主 Agent 在隔离进程调用该函数；不得用 stdout JSON 代替 capability。

### 本顺序在此结束

`query_universe --require-available-history`、formal P1C、复权/CA **不是** Windows clean 发布的一部分。它们是发布**之后**的 Gate，见 §8。

---

## 4. Public CLI 参数表

模块：`quant.data.backfill_hk_history`（`argparse`；无 extras console script 依赖）。

| 参数 | 8/8 后步骤 1 | 8/8 后步骤 2 | 禁止 |
|---|---|---|---|
| `--plan PATH` | 必填，v2 | 必填，同一 v2 | R1 plan |
| `--data-root PATH` | 正式根，默认 `data` | 同左 | 把 fixture 写入正式根 |
| `--journal-root PATH` | 已绑定 v2 journal | 同左 | R1 journal；未绑定默认根 |
| `--config PATH` | 省略 | 省略 | 8/8 后任何模式 |
| `--recover-existing-only` | 是 | 否 | 与 finalize 同时 |
| `--finalize-v3` | 否 | 是 | 与 `--finalize` 同时 |
| `--finalize` | 否 | **否** | 本顺序任何一步 |
| `--hkex-retained-raw PATH` | 否 | 必填 | 无 metadata 的 v3；非 finalize 使用 |
| `--hkex-retained-metadata PATH` | 否 | 必填 | legacy `--finalize` |
| `--confirm-uncertain-retry` | 否 | 否 | 8/8 后无 uncertain pending |

稳定失败码（stderr 单行，exit 1）：`HK_HISTORY_PLAN_CONFLICT`、`HK_HISTORY_REFERENCE_INVALID`、`HK_HISTORY_INCOMPLETE`、`HK_HISTORY_RAW_INVALID`、`HK_HISTORY_AVAILABILITY_INVALID`、`HK_HISTORY_FINALIZE_V3_INVALID`、`HK_HISTORY_PUBLISH_CONFLICT`、`HK_HISTORY_PUBLISH_FAILED` 等白名单；未知异常映射 `HK_HISTORY_REFERENCE_INVALID`，`cause/context=None`。

---

## 5. Required retained inputs

### 5.1 HKEX 02983 成对文件（v3 不可缺一）

权威（`M1_HKEX-02983-R2_20260815官方Raw重留存报告.md` + `hkex_daily_quotations.py` 冻结常量，本审计未读盘）：

- URL：`https://www.hkex.com.hk/eng/stat/smstat/dayquot/d260710e.htm`
- raw size：`32_792_625`；SHA-256：`88a45f28aceaf2775153e7a06f26f9b05ed8c5113cfb1c65f5ffccd19bcdb4d2`
- metadata schema：`hkex-daily-quotation-retained-metadata-v1`；`source=HKEX_DAILY_QUOTATIONS`；aware UTC `source_observed_at`；`raw_file_sha256` 与 raw exact；`metadata_identity` R2 记录 `f3a2c5e2…8b02`
- verified bundle id R2 记录：`8c6fae2f…b1426`
- 报告记载路径形态：`data/raw/hkex/daily_quotations/2026-07-10/d260710e.htm` 与同目录 `retained.metadata.json`（位于 `--data-root/raw` 下合法；finalize 会再硬链拷入 journal）

旧 P0 字节 `32,792,632` / `67d1109f…` **已作废**；现行 `EXPECTED_RAW_SHA256` 已改为 R2 值。传入旧字节会 `HK_HISTORY_REFERENCE_INVALID`。

禁止：mtime/当前时间猜 `source_observed_at`；只传 raw 走 v3；规范化/拼接动态 HTML 尾。

### 5.2 v2 no-trade 例外（plan 已绑定；finalize 不另读 HKEX 01065）

精确一键：`01065.HK@2026-05-05`，`source=USER_APPROVED_MULTI_SOURCE_CONSENSUS`，`source_record_id=UA-M1-001`，`raw_selector=user-approved-consensus/ua-m1-001-01065-2026-05-05.record`。  
raw 必须是 canonical JSON `hk-no-trade-user-approved-consensus-v1`（approval_id/approved_on=2026-08-15/双源观察/五项 impact=false）。不得标成 `HKEX_DAILY_QUOTATIONS`。  
`load_hk_no_trade_evidence` / plan bind / schema check 均把该例外锁死为这一键；扩散到其他缺口必须 fail closed。

### 5.3 8/8 Tushare 闭包

seed raw+metadata（plan 绑定 SHA）+ 8 个 request 的 COMPLETE raw 与 journal receipt。finalize 会 fresh 投影每个 key 的 availability；缺 metadata `fetched_at` 则 v3 失败。

---

## 6. 已有 / 缺失工程前置

### 已有（足以支撑步骤 1–2 的代码路径）

| 包 | 状态 | 本顺序中的角色 |
|---|---|---|
| HISTORY-R2/R4 | 工程合同主验（脱敏由 R4 吸收） | v2 plan、evidence、`--recover-existing-only` |
| 02983-P0/P1 | parser + v2 supplement 工程主验 | raw verifier；P1 的 raw-only 路径**不得**用于本发布 |
| PRE-B R4 | v3 availability / `VerifiedHkBarBundle` 开发合同主验 | 步骤 2 四文件 + 步骤 3 loader |
| V3M-P0 R3 | fixture-only `--finalize-v3` 外壳主验 | **就是**步骤 2 的 public CLI |
| 02983-R2 | 官方 raw+metadata 留存（文档） | 关闭「无可信 observed metadata」来源缺口 |
| UA-M1-001 | 用户 2026-08-15 例外 | 关闭本键 licensed 01065 业务前置 |
| U0C-R3 | 5/5 自然窗口已终审 | 不在本顺序内；不再挡 Windows clean |

### 缺失（发布前 vs 发布后）

**发布前（步骤 0）：** formal V3M-P1 execution manifest / 运行绑定。现有 CLI 已能执行；缺的是把 R2 materializer 身份与 quiescence 写成正式运行合同。**不要**再实现一套 finalize。

**不阻塞 Windows clean 写入、但阻塞后续 HK60 子 Gate：**

1. finalize **不写** `data/clean/hk_no_trade_evidence/evidence.json`；`query_universe --require-available-history` 仅当该路径存在才 `load_hk_no_trade_evidence`。缺文件则 01065 不会从 required sessions 豁免。无 public 物化 CLI。
2. 02983 发布为 `source=hkex`，Gate 常用 `--source tushare`。单源查询不会把 hkex 行算进 tushare 窗口。`02983` 若 list_date 使 2026-07-10 仍为 required session，则 `--source tushare` 会 INCOMPLETE。这是发布后 Gate 设计裂口，不是 upsert 失败。
3. 无 `load_verified_hk_bar_bundle` CLI。

**明确未开工且不得并入本发布：** formal P1C；`hkex_no_trade_evidence.py`（对本键已被用户例外替代；对任何其他无交易键仍停止）；licensed ETF adapter；`hk_adjfactor` 真实权限。

---

## 7. 用户参与点

1. **确认 8/8 与路径：** 指出真实 v2 plan 与 journal 根（本审计未读 `artifacts/`）。错误 journal 会在 `_bind_v2_journal` 冲突。
2. **确认发布根：** Windows 正式 `data/clean/bar_1d`（与 A 股共用 store）。预检拒绝同键异值；接受后即 Windows 轨正式 HK bar。隔离 fixture root 不是正式发布。
3. **Quiescence：** 步骤 2 全程不得改 retained 双文件、不得第二进程写同一 journal/clean。代码不提供锁/watcher。
4. **接受非全局原子：** clean 可能在四文件失败后已有 HK 行；只允许 exact 重放，禁止手工删补。
5. **零凭据：** 本顺序不需要 Tushare token；不要为 finalize 提供 `--config`。
6. **不要**把本发布表述为 Linux/ext4 或 M1 Gate。UA-ENV-001、UA-M1-002（ETF/CA/复权）、UA-REPO-001 仍按原清单。

---

## 8. 停止条件

立即停止、保留证据、不补写 R1、不合成 OHLC、不删 partial：

| 现象 | 码 / 动作 |
|---|---|
| 步骤 1 非 8/8 或 ABSENT raw | `HK_HISTORY_INCOMPLETE`；回到余批（每进程 1 请求、≥3600s），**不是** finalize |
| 模式/路径/plan 混用或隔离失败 | `HK_HISTORY_PLAN_CONFLICT` |
| retained 读/symlink/identity/SHA/metadata 失败 | `HK_HISTORY_REFERENCE_INVALID`；零 finalize 调用 |
| 缺 receipt | `HK_HISTORY_INCOMPLETE` |
| effective keys 不闭合或 01065 回流 | v3：`HK_HISTORY_AVAILABILITY_INVALID` |
| clean 同键异值 | `HK_HISTORY_PUBLISH_CONFLICT` |
| 四文件 partial / 异 bytes / 竞争 | `HK_HISTORY_FINALIZE_V3_INVALID`；不删除竞争文件 |
| 任何联网、默认 execute、`--finalize`、猜 metadata | 合同禁止 |
| 需要全局 rollback、自动 quarantine、或抵抗违反 quiescence 的 writer | 超出当前信任模型；另立合同 |

---

## 9. 最小验证矩阵（本顺序；非全量 pytest）

本审计**未执行**下列命令；它们是发布时的最小诚实矩阵。

| # | 检查 | 通过 | 不等于 |
|---|---|---|---|
| V0 | 步骤 0 绑定 SHA/路径/quiescence 与 R2 文档、plan `journal_id` 一致 | 人工核对 | Gate |
| V1 | 步骤 1 recover stdout `is_complete=true` 且 `network_requests=0` | 8/8 | clean 已写 |
| V2 | 步骤 2 前：无 `finalize.json` 或已是 exact v3 四件套 | 可写/可幂等 | 可跑 `--finalize` |
| V3 | 步骤 2 stdout 含 `hk-history-finalize-v3` 与 bundle/metadata identity | Windows 发布 CLI 成功 | M1 |
| V4 | journal 四文件 exact-set；`finalize.json` 绑定 plan/clean/availability/HKEX identities | v3 receipt | 全局原子 |
| V5 | `load_verified_hk_bar_bundle` 对 `as_of >= max(bar_available_at)` PASS；v1/v2 unsupported | 发布可被 P1A 消费 | P1C/formal CA |
| V6 | 定向回归（不跑真实 plan）：`tests/unit/test_backfill_hk_history.py` + `tests/unit/test_hk_history_backfill.py`；Ruff/mypy 两生产文件；cold-import 无网络 | 外壳未漂 | 真实 8/8 |
| V7 | `git diff --check` 白名单；无 add/commit | 卫生 | 合流 |

**禁止**用 fixture 绿测关闭本发布；禁止把 V3 写成 HK60/M1/ext4。

发布**之后**才允许的独立矩阵（非本顺序）：双 Route `--require-available-history`（须先物化 evidence.json 并裁定 `tushare`/`hkex` 源）；P1A/P1B 仅 development；formal P1C 仍等 licensed CA。

---

## 10. 仍阻止 M1 Gate vs 只阻止 Linux/ext4

### 10.1 Windows clean 正式发布本身

**不要求** WSL2/ext4。`CleanBarStore.upsert` 对 `bar_1d` 使用临时 parquet + `Path.replace`；journal 四文件使用 `os.link` no-clobber。这与已存在的 Windows 正式数据轨一致。V3M-P0 在 Windows 定向测试已通过（含 skip 的 POSIX-only 项）。**本发布可在 Windows 完成。**

### 10.2 完成后仍阻止 M1 Gate（不是 ext4 问题）

1. **HK60 子 Gate 未关：** 双 Route `query_universe --universe SH_CONNECT|SZ_CONNECT --as-of 2026-07-10 --source tushare --observations 60 --require-available-history` 必须同时 complete、unexpected=0。阻塞点包括：evidence.json 未由 finalize 写出；`02983` 为 `source=hkex` 与 `--source tushare` 分裂；31 ETF 已可按官方资格排除，但 613 STOCK 仍要 Instrument 生命周期。
2. **完整 HK Instrument：** ETF licensed 来源仍开放（UA-M1-002）；不阻塞 613 STOCK 的 HK60 计算，但阻塞完整 M1。
3. **复权 / PIT CA / formal P1C：** P1A/P1B 仅为 development；P1C 明文等待正式 HK60 v3 **且** licensed CA provenance。Windows clean 只满足「v3 bar 可能存在」，不满足 CA。
4. **SSOT 文档未同步：** `项目实施路线图.md` 仍写 01065 licensed 阻断 finalize；`README.md` 仍写 8 批前禁止 finalize、且 finalize 只发 612 只、`02983` 保持未解决。权威是代码 + UA-M1-001 + R2 留存。未同步前不得勾选路线图 M1。
5. **工作树合流：** 大量 HK 模块相对 git 未提交；主树宣称须 UA-REPO-001。不合流 ≠ 本发布失败，但「主树 M1 PASS」不可用。

U0C-R3 五日已关闭，不再列为本发布或 M1 的时间墙。

### 10.3 只阻止 Linux/ext4（不阻止本 Windows 发布）

- 默认发行版曾记录为 WSL1；DrvFS/wslfs 上的定向绿测
- `Path.replace` / NTFS hardlink ≠ Linux `RENAME_NOREPLACE` / ext4 不可变发布证据
- UA-ENV-001 未批的 WSL2+ext4 迁移
- 任何「Windows 已发布因此 Linux Gate 通过」的表述

G1 Windows 正式发布已存在的事实**不**传递给 HK60/M1；同样，本 HK Windows clean 发布也不传递给 ext4。

---

## 11. 明确反例（设计层；实现者勿做成「成功路径」）

1. `--finalize --hkex-retained-raw`（v2）：可写 clean 且只写 v2 `finalize.json`，随后同 journal 的 v3 四件套因 existing ≠ exact set 而 `HK_HISTORY_FINALIZE_V3_INVALID`。**污染正式 journal。**
2. 默认 execute 证明 8/8：构造 connector / 可能读 ignored 配置。
3. 对 R1 plan/journal finalize。
4. 无 metadata 的 `--finalize-v3`。
5. 把 P1B development 四文件改标 formal / 写入 `clean/bar_1d`。
6. 把用户例外扩成通配无交易规则，或把该键标成 HKEX 官方证据。
7. 四文件失败后删除竞争文件或声称已回滚 clean。
8. 用增加 loader 扫描轮数宣称跨进程不可篡改。

---

## 12. 审计边界与文档漂移

- 本报告不授权实现、不修改任务单、不创建 V3M-P1 文件、不运行 finalize。
- 与过期文档的冲突以**代码 + 用户 2026-08-15 裁决 + 02983-R2 报告**为准；路线图/README 仍描述 licensed-only 旧链，主 Agent 应在真实 8/8 发布**同一变更**中同步，而不是另写第三套说明。
- 01065 R1 licensed verifier 任务单仍正确适用于**任何其他**无交易键；仅本精确事件被 UA-M1-001 替换。

**最终裁决：** v2 plan 达到 8/8 后，到 Windows `clean/bar_1d` 正式发布的唯一诚实路径是「recover 证明闭包 → `--finalize-v3` 一次发布 → `load_verified_hk_bar_bundle`」。缺 V3M-P1 manifest 是治理前置，不是缺 CLI。该发布不关闭 HK60 双 Route、不关闭 M1、不关闭 Linux/ext4。
