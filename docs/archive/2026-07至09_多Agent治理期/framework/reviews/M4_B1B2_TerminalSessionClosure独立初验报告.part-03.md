| 检查 | 结果 |
|---|---|
| 本审查写入 | **仅本报告** §14；business/tests/taskbook/delivery 只读 |
| §12/§15.4 | 仍为无效证据；不洗白 |
| 本会话 | 零解释器 / 零 Ruff·mypy·pytest 重跑 |
| 未运行 | cold / final scope **UNRUN**；mypy 14 项 **未**在注解后重跑（postfix=VALIDATION4） |
| 下一步 | 窄 VALIDATION4：identity→Ruff 本文件→mypy production16→cold production16→exact33 scope；不重复 focused559 |
| 终态 | B1B2 候选；`UA-M4-006` OPEN |

### 14.7 交接

- 裁决：`TYPE_ANNOTATION_REVIEW_PASS`
- 历史全文保留至 §13
- 本审查者退出；唯一写路径为本报告

---

## 15. EVIDENCE_REVIEW（2026-08-26）

> 原独立初验者 · 任务书 §15 / delivery §20 · `STATIC_ONLY`
> 只读：各 evidence root 磁盘产物、delivery §20、任务书 §15、exact33 白名单、当前 `git status`/`diff --check`、本报告 §0–§14 历史链。
> **完整保留** §0–§14 全部裁决（含 FAIL/PASS 与违约记录），不删改、不洗白。

### 15.1 裁决

**`EVIDENCE_REVIEW_PASS`**

组合证据闭合成立且不伪造单轮全绿：V2 focused **559/7** + V4 identity/Ruff(本文件)/mypy16/cold16 **PASS** + scope-close5 actual19⊆exact33 / cached0 / diff-check / residue/writer **PASS**；V1–V3 与 scope-close1–4（及附加 SCOPE_EXTRA）首失败/UNRUN **均仍在磁盘且 SHA 与 delivery §20 一致**。F1→R1-F2/F3→采用→V1返工→Ruff→注解审查链完整保留。delivery 本包状态 `B1B2_WINDOWS_ENGINEERING_VALIDATED` 与 `SUBSTRATE+B1B1+B1B2 / UA-M4-006 OPEN` 边界诚实；**无**真实 PAPER/soak/Linux Gate 关闭声明。本 PASS **仅**授权进入安全提交申请，**不是** UA-M4-006 关闭或 M4 完成。

### 15.2 VALIDATION1–4 关键 SHA / exit（磁盘核对）

| 轮次 | root 存在 | 关键核对 | vs delivery §20.2 |
|---|---|---|---|
| **V1** | `...validation1-20260826T062412Z` | summary=`8503F566…B7B0`；focused stdout=`29728EC6…C845`；exit focused=1 / identity=0；尾 `4 failed, 555 passed, 7 skipped`；无 `03-ruff`；`VALIDATION_STOP=STAGE_FAILED:02-focused:1` | **MATCH**；UNRUN 后续如实 |
| **V2** | `...validation2-20260826T064500Z` | summary=`452F153B…09DB`；focused=`EF6A236E…959E0E` exit=0 `559 passed, 7 skipped`；ruff=`366B9997…8064` exit=1；无 `04-mypy`；`STOP:03-ruff:1` | **MATCH** |
| **V3** | `...postfix-validation3-20260826T071119Z` | summary=`6EDCE34C…4B67`；ruff=`AF352A86…D9AF` exit=0；mypy=`50441960…5299` exit=1；无 focused/cold；`STOP:04-mypy:1` | **MATCH** |
| **V4** | `...postfix-validation4-20260826T072258Z` | summary=`E32F8154…8B44`；identity=`87CDF981…473E` exit=0；ruff=`AF352A86…D9AF` exit=0（runner **仅** `paper_formal_service.py`）；mypy=`6F0C27F6…3061` exit=0 `Success: no issues found in 16 source files`；cold=`756443DB…0B65` exit=0（16 production 路径列出）；06-scope stderr=`DCFC2A99…24E4` exit=1 `SCOPE_EXTRA` 三 docs；**无** `06-scope.stdout`（summary 记缺文件 STOP） | **MATCH**；工程四段绿 + 内嵌 scope FAIL **不洗白** |

组合要件映射：focused559 ← V2；Ruff/mypy/cold ← V4；**非**同一 runner 全绿。

### 15.3 scope-close1–5

| # | root | 磁盘结论 | 关键 SHA | vs §20.3 |
|---|---|---|---|---|
| 1 | `...raw-bytes-scope-20260825T235204Z` | FAIL `GIT_STATUS_RECORD_INVALID`；exit=1 | stderr=`2AA21EDA…3AFB`；git-status.raw=`48132F7E…CD0E` | **MATCH** |
| 2 | = V4 `06-scope` | FAIL `SCOPE_EXTRA` 三 docs | stderr=`DCFC2A99…24E4` | **MATCH**（无独立 close2 目录 — 交付已声明） |
| 3 | `...scope-close3-20260825T235504Z` | FAIL 再次 `GIT_STATUS_RECORD_INVALID` | stderr=`1BCC8BC2…384E` | **MATCH** |
| 4 | `...scope-close4-20260825T235812Z` | FAIL 空 cached `ConvertFrom-NulPayload` | stderr=`007A9FA6…819A` | **MATCH** |
| **5** | `...scope-close5-20260826T000341Z` | **PASS** `RAW_BYTES_SCOPE_PASS`；ACTUAL=19；ALLOWED=33；CACHED=0；DIFF_CHECK=PASS；TEMP_CACHE=ABSENT；F00_RESIDUE=0；WRITER_PID=7692 / BelowNormal / 0x3；exit_code=0 | stdout=`DE6BE7EB…F27F`；exit 文件 SHA=`5FECEB66…57E9`；git-status.raw=`48132F7E…CD0E`；cached/diff-check empty=`E3B0C442…855` | **MATCH** |
| 附加 | `...scope-close-20260826T074843Z` | 再次 SCOPE_EXTRA（保留） | stderr=`1E1404DF…50B3` | **MATCH**；不推翻 sc5 |

时间戳备注（非 FAIL）：sc5 目录时戳 `000341Z` 早于 V4 `072258Z`；属组合路径集合证据，非“V4 之后单轮 scope 绿”。当前 WT 路径集仍与 sc5 ACTUAL19 **一致**（见下）。

### 15.4 actual19 ⊆ exact33 / cached0 / diff / residue（当前 WT）

- 任务书 §3 exact33 = 33；当前 `git status --porcelain -z` **19** 条；**extras=0** → **⊆ exact33**。
- 19 路径与 delivery §20.3 / sc5 ACTUAL 清单**逐条同集**（3 docs + 11 production/migration + 5 tests）。
- `git diff --cached --name-only` 空 → **cached0**。
- `git diff --check` exit=0 → **PASS**。
- 本审查未发现 temp/cache/0xF00 业务残留要求之外的额外 dirty。

### 15.5 F-chain 与审查史保全

| 链环 | 本报告位置 | 状态 |
|---|---|---|
| F1–F4 初验 FAIL | §0–§8 | **保留** |
| R1-F2 / R1-F3 FAIL | §9 | **保留** |
| R2 产品闭合 PASS | §10 | **保留** |
| ADOPTION_R2 PASS | §11 | **保留** |
| VALIDATION1 返工 PASS | §12 | **保留** |
| RUFF 返工 PASS | §13 | **保留** |
| TYPE_ANNOTATION PASS | §14 | **保留** |
| §12/§15.4 违约 | delivery 历史 + 历次审查声明 | **不洗白**（仍为无效探针证据） |

无发现把 V1 focused FAIL、V2 Ruff FAIL、V3 mypy FAIL、sc1–4 FAIL 改写成通过的矛盾表述；delivery §20 明确“首失败保留”。

### 15.6 Gate / 过度声明核对

| 声明 | 结论 |
|---|---|
| `B1B2_WINDOWS_ENGINEERING_VALIDATED` | **允许**：组合证据满足任务书 §15；delivery §20.1/§20.5 已写 |
| `SUBSTRATE+B1B1+B1B2 / UA-M4-006 OPEN` | delivery §20.1 **明确 OPEN**；§20.5 重申 — **诚实** |
| 真实 PAPER / soak / 28 日 / fault-drill / Linux Gate / 新 root·epoch / M4 完成 | delivery 终态与 §20 **禁止声称** — **无过度声明** |
| `UA-M4-006_WINDOWS_ENGINEERING_CLOSED` | §20 **未**宣称关闭（历史 § 文仅“候选上限”） — **未越界** |

### 15.7 本审查边界

| 项 | 结果 |
|---|---|
| 本会话写入 | **仅本报告** §15 |
| business / taskbook / delivery | **只读未改** |
| 工具 | 零 Python/pytest/Ruff/mypy/cold；只读哈希与 git status/diff-check |
| stage/commit | **无** |
| 下一步 | 经理可申请**安全提交**；提交后仍不得宣称 UA-M4-006 用户关闭或真实 PAPER/soak/Linux |

### 15.8 交接

- 裁决：`EVIDENCE_REVIEW_PASS`
- 历史全文保留至 §14
- 本审查者退出；唯一写路径为本报告
