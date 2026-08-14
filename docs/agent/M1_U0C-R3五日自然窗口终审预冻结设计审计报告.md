# M1 U0C-R3 五日自然窗口终审预冻结设计审计报告

日期：2026-08-12  
角色：外部独立只读设计审计 Agent（UA-AGENT-002；模型 `auto`）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m1-hkex-02983`  
唯一写入：本报告  
状态：**预冻结设计完成；不是终审，不是 U0C 5/5，不是 M1 Gate**

## 0. 审计边界与查询时刻

- 只读：AGENTS.md、`.ai/README.md`、U0C/U0C-R3 任务单与注册报告、`audit_daily_streak`/`scheduled_daily`/`run_scheduled_daily`/runner/测试、主树 `docs/agent/用户待批示与参与事项.md` 之 UA-M1-003、五任务状态、既有正式日证据与 registration 产物。
- 严禁：手工触发、重注册、改任务、补跑、写 `data/`/`run_state/`/`artifacts/`（除本报告）、联网、`git add/commit/push`。
- **查询时刻（权威）**：`2026-08-12 14:08:47 +08:00`。
- **当前仅允许记 2/5**：仅 `2026-08-10`、`2026-08-11`。`2026-08-12` 仍为 `Ready`，`NextRunTime=2026-08-12 21:30:30 +08:00`（相对查询时刻为未来），不得预计。

## 1. 可直接冻结的终审目标（给主 Agent）

在 **2026-08-14 对应任务自然结束后**（建议不早于 `2026-08-14 23:40 +08:00`，且五任务均已离开未运行哨兵），由全新外部实现/取证会话只读采集证据，再由另一全新外部独立初验只读核对，最后由主 Agent 终验。目标是裁定：

> R3 窗口 `2026-08-10`…`2026-08-14` 是否由已注册五任务在 Asia/Shanghai 21:30 合同下无人干预完成，且五份 streak 日志与五份 fresh-verified daily receipt 来源闭包全部成立。

本设计把验收拆成两层，避免把“项目日志绿”误当成“无人干预 Gate”：

| 层 | 职责 | 权威实现 |
|---|---|---|
| A. Scheduler 合同与自然触发轴 | 任务定义未漂移、各日 LastResult/LastRunTime、无重注册正证据、时间窗 | Windows Task Scheduler 只读查询 + 注册收据语义比对 |
| B. 数据闭包轴 | 五日日历、日志 exact schema、receipt/raw/quality 字节闭包 | `python -m quant.data.audit_daily_streak`（零网络） |

**A 与 B 同时 PASS 才可记 U0C-R3 5/5。** 任一轴 FAIL → 本窗口失败；不得补跑计入。历史通道关闭时，A 轴只能使用正面可观察量，不得用“无事件日志”推断人工运行。

## 2. 冻结常量与路径

| 项 | 冻结值 |
|---|---|
| 会话日 | `2026-08-10` `2026-08-11` `2026-08-12` `2026-08-13` `2026-08-14` |
| 任务名 | `QuantTrading-M1-U0C-R3-20260810` … `20260814` |
| 触发 | 各日 `StartBoundary=YYYY-MM-DDT21:30:00+08:00`（XML 权威）；调度器 UI/`NextRunTime` 常见 `21:30:30` 为已知显示粒度差，**不以 :30 判漂移** |
| Command | `C:\Windows\System32\wsl.exe` |
| Arguments 模板 | `-d Ubuntu -- bash /home/mabw/AI_Coding_win/QuantitativeTrading/scripts/run_m1_daily_streak_20260810_20260814.sh YYYY-MM-DD` |
| Runner SHA-256 | `bdedb95335c8bbeaf2238a443eb321dee2a9120d9caf74d65bc7de31af2df02c` |
| Symbols（runner 字面） | `000001.SZ 600000.SH 00005.HK 00700.HK` |
| Spec 规范序（intent） | `["000001.SZ","00005.HK","00700.HK","600000.SH"]` |
| source / 复权 | `tushare` / `use_adjustment_factors=false` |
| 正式 log_root | `artifacts/data_quality/m1_daily_streak/20260810_20260814/`（WSL/DrvFS 正式树；本机 Windows 路径等价于 `F:\AI_Coding\QuantitativeTrading\artifacts\data_quality\m1_daily_streak\20260810_20260814\`） |
| 注册收据 | 同目录 `registration_receipt.json`（schema `m1-u0c-r3-task-registration-v1`） |
| 注册导出快照 | 同目录 `registered_definitions/*.xml`（**定义身份以该快照 SHA 为准**） |
| data / artifacts 根 | 正式项目 `data/`、`artifacts/`（与 runner `--data-root data --artifact-root artifacts` 一致） |
| 未运行哨兵 | `LastRunTime=1999-11-30`，`LastTaskResult=267011` |

### 2.1 注册 export_sha256（定义身份，终审必须复核）

| task | export_sha256 |
|---|---|
| 20260810 | `3b2809bc3536a7a9ffdbbead27b282ae2f6a4dcf520ca7f7e93a5d446bde6d85` |
| 20260811 | `ae4ac728734468c737832956e0096be97830c89f49aa645f014f9e06bd36ec17` |
| 20260812 | `1bf3ba07525528dec58b80db8a51c45c635dd0ab2af42d57b359841a333be113` |
| 20260813 | `3224c68a071df5aad0755f83a80863449f42d69c54d14ab041e0a48f30f9c675` |
| 20260814 | `ca240d0af794b1b7e1ed33c8a5b68fd9074860d46f0b5c9ebccd7623df8084f5` |

**重要**：任务运行后 `schtasks /Query /XML` 的整文件 SHA 会因状态字段变化而与注册时不同。终审 **禁止** 用 live 整文件 SHA 对 `export_sha256` 做相等判定。应：

1. 确认 `registered_definitions/<task>.xml` 的 SHA-256 仍等于上表；
2. 对 live 任务只做 **语义字段** 与注册快照相等：`StartBoundary`、`Command`、`Arguments`、`LogonType=InteractiveToken`、`MultipleInstancesPolicy=IgnoreNew`、`StartWhenAvailable=true`、`WakeToRun=true`、`ExecutionTimeLimit=PT2H`、无 `RestartOnFailure` / repetition。

本审计在查询时刻已抽样确认 08-10（已跑）与 08-12（未跑）语义字段均与注册快照一致；runner SHA 与收据一致。

## 3. 查询时刻 Task Scheduler 证据矩阵（2/5）

| 日期 | State | LastRunTime (+08) | LastTaskResult | NextRunTime (+08) | 可计数 |
|---|---|---|---|---|---|
| 08-10 | Ready | 2026-08-10 21:30:30 | 0 | 空 | 是（待终审复核闭包） |
| 08-11 | Ready | 2026-08-11 21:30:30 | 0 | 空 | 是（待终审复核闭包） |
| 08-12 | Ready | 1999-11-30 哨兵 | 267011 | 2026-08-12 21:30:30 | **否**（未来触发） |
| 08-13 | Ready | 哨兵 | 267011 | 2026-08-13 21:30:30 | 否 |
| 08-14 | Ready | 哨兵 | 267011 | 2026-08-14 21:30:30 | 否 |

`schtasks /V` 对已跑任务可能显示 `Last Run Time=21:30:00`，与 `Get-ScheduledTaskInfo` 的 `:30` 并存；两者均落在合同日 21:30 窗口，终审记为同一自然触发，不因粒度差判 FAIL。

## 4. 日证据 JSON exact schema（层 B 输入）

权威生产：`ScheduledDailyResult.as_dict()` / `audit_daily_streak._LOG_KEYS`。

### 4.1 Exact key set（不多不少）

```text
schema_version, status, date, started_at, finished_at,
run_id, receipt_selector, replay_status, exit_code
```

### 4.2 Exact 取值约束

| 字段 | 约束 |
|---|---|
| `schema_version` | 精确 `"m1-scheduled-daily-v1"` |
| `status` | 精确 `"SUCCESS"` |
| `date` | 文件名同日 ISO `YYYY-MM-DD`，且 ∈ 冻结五日 |
| `started_at` / `finished_at` | 规范微秒 UTC，后缀 `Z`；`finished_at >= started_at`；解析后 offset 必须为 0 |
| `run_id` | 64 位小写 hex；等于当日 `DailyRunSpecV1.run_id` 与 receipt `run_id` |
| `receipt_selector` | 精确 `run_state/m1_daily/<run_id>/receipt.json` |
| `replay_status` | 精确 `"ALREADY_COMPLETE"`（同 invocation 二次零网络重放；不是“首次即已完成”） |
| `exit_code` | 整数 `0`（JSON number，非字符串） |
| 文件形态 | 普通文件、非 symlink；**恰好一行** JSON + 可选单行尾换行；禁止多行/额外键/缺键 |

### 4.3 已存在正式日证据（查询时刻；只读摘要）

路径前缀：`…/m1_daily_streak/20260810_20260814/`

| 日期 | 文件 SHA-256 | status/exit/replay | started_at → finished_at (UTC) | run_id 前缀 | 本地 Creation→mtime (+08) |
|---|---|---|---|---|---|
| 08-10 | `f0ef3ae1ace1d1bf5766d4fa56a1d7fd78e9a48036ae76870aabfde29bacf0fb` | SUCCESS / 0 / ALREADY_COMPLETE | `13:30:13.266273Z` → `13:30:15.027442Z` | `b59805f9…af5c` | 21:30:03 → 21:30:16 |
| 08-11 | `41c816254ef077a20c3edcdbd727c5beafab8ab7cd27346b8d726bad6d43bdb2` | SUCCESS / 0 / ALREADY_COMPLETE | `13:30:11.142479Z` → `13:30:12.623817Z` | `88ec86f1…b199` | 21:30:03 → 21:30:13 |

UTC `13:30` ≡ Asia/Shanghai `21:30`。日志 `CreationTime≈21:30:03` 对齐 runner `set -C` 独占创建；与 Task `LastRunTime` 同日落在 21:30 窗口。

08-12/13/14：**不得** 在查询时刻要求存在日 JSON；若提前出现，视为异常（可能手工触发或时钟/补跑），终审记 `U0C_R3_PREMATURE_DAY_LOG`。

## 5. Receipt / raw / quality 来源闭包（层 B）

`verify_daily_receipt` 要求：重建同日 spec → `intent.json` 字节 ≡ canonical spec；`manifest.json`/`receipt.json`（schema `m1-daily-receipt-v1`）校验；receipt `artifacts[]` 每项 `{alias,selector,sha256,size_bytes}` 与磁盘普通文件字节一致；并校验 clean 投影闭包。

### 5.1 查询时刻已核对象（2 日）

| 日期 | run_id | receipt SHA-256 | artifacts 闭包（本审计只读复算） |
|---|---|---|---|
| 08-10 | `b59805f9a7828e4d9fbbc4a9b7e42d84e7542aec4b6d1bdc3f8a77b71a6caf5c` | `729b659ca6da5c834697a263d78739fee1255b2b0a89b0a571db91d5a04dcd7c` | quality + raw json/parquet + intent/manifest：**5/5 size+sha 一致** |
| 08-11 | `88ec86f1a85549d588e35fbe92bba7a8ef16ce1a83efb405ff819a1ee78cb199` | `dfa9c547751bf79a99160b9de5f443686d600db91888ef3d3f4e65306fb648af` | 同上：**5/5 一致** |

同一日期 identity 绑定：

- 日 JSON `date` == intent `session_date` == raw selector `date=` == Task Arguments 日期；
- 日 JSON `run_id` == intent/manifest/receipt `run_id` == 目录名；
- 日 JSON `receipt_selector` 指向上述 receipt。

终审必须对五日全部重跑 `verify`（经 `audit_daily_streak`），不得只引用本预冻结报告中的 SHA。

## 6. 时区、21:30 窗口与跨午夜

| 规则 | 冻结判定 |
|---|---|
| 合同时区 | Asia/Shanghai（`+08:00`）；日志时间只允许 UTC `Z` |
| 自然触发窗 | 当日 `StartBoundary` 起，允许调度器显示粒度到 `21:30:30`；进程日志 `started_at` 换算到 +08 后应落在 **当日 21:30:00–21:40:00**（覆盖 WSL/conda 启动）；`finished_at` 应在同窗启动后、且早于 Task `ExecutionTimeLimit=PT2H` |
| 跨午夜 | `finished_at`（+08）若跨入次日：仅当 `LastRunTime` 仍为合同日且 `started_at` 在 21:30 窗内、且无二次 LastRun 正证据时可接受；否则 `U0C_R3_NATURAL_WINDOW_MISMATCH` |
| StartWhenAvailable 补跑 | 允许主机休眠后在 **同合同日之后** 补启一次，但 R3 已有跨任务 flock；若 `LastRunTime` 落到 **次日或更晚**，或五日日志时间簇中出现同秒级并发冲突残留，判窗口合同风险 → FAIL（不得静默算 5/5） |
| 未来 mtime | 日 JSON / receipt / raw 的 mtime 若显著晚于该日 `finished_at+ε` 且内容仍声称同 run_id，记篡改风险；与 `verify_daily_receipt` 字节失败一并归 `M1_STREAK_RECEIPT_INVALID` 或外层 `U0C_R3_EVIDENCE_TAMPER` |

## 7. 只读离线审计命令（终审强制）

在正式 WSL 项目根、Miniforge `base`（Gate 环境）执行；**零网络**；不写正式 data（`audit_daily_streak` 只读验证）：

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading
/home/mabw/miniforge3/bin/conda run -n base \
  python -B -m quant.data.audit_daily_streak \
  --dates 2026-08-10 2026-08-11 2026-08-12 2026-08-13 2026-08-14 \
  --symbols 000001.SZ 600000.SH 00005.HK 00700.HK \
  --data-root data \
  --artifact-root artifacts \
  --log-root artifacts/data_quality/m1_daily_streak/20260810_20260814
```

期望 PASS stdout（单行）：

```json
{"schema_version":"m1-daily-streak-audit-v1","status":"PASS","sessions":5,"dates":["2026-08-10","2026-08-11","2026-08-12","2026-08-13","2026-08-14"]}
```

FAIL：stderr 单行 `{"status":"FAILED","code":"<CODE>"}`，exit 2。

### 7.1 稳定 FAIL 分类

**层 B（已实现）**

| code | 含义 |
|---|---|
| `M1_STREAK_INPUT_INVALID` | 日期/符号/路径输入不合法 |
| `M1_STREAK_CALENDAR_INVALID` | 非恰好五日共同开市或日历读失败 |
| `M1_STREAK_RECEIPT_INVALID` | spec/receipt/字节闭包失败（含复制错位、whole-rehash、缺文件） |
| `M1_STREAK_LOG_INVALID` | 日志缺失、symlink、多行、键集错、状态非 SUCCESS/ALREADY_COMPLETE/0、时间非法、与 run_id/selector 不一致 |

**层 A（终审任务书必须写入的报告级分类；现有 Python 审计器不覆盖）**

| code | 含义 |
|---|---|
| `U0C_R3_WINDOW_INCOMPLETE` | 08-14 未结束或仍有哨兵/`NextRunTime` 未来 |
| `U0C_R3_SCHEDULER_DEFINITION_DRIFT` | 语义字段或 registered_definitions SHA 与注册收据不一致；或 runner SHA 漂移 |
| `U0C_R3_SCHEDULER_RESULT_INVALID` | 终态 `LastTaskResult≠0`，或应完成日仍为哨兵 |
| `U0C_R3_NATURAL_WINDOW_MISMATCH` | LastRunTime/日志时间落在合同 21:30 窗外或跨午夜规则失败 |
| `U0C_R3_PREMATURE_DAY_LOG` | 触发前已存在该日正式日志 |
| `U0C_R3_MANUAL_INTERVENTION_EVIDENT` | **正面**证据：任务曾被 Delete/Create 替换、Arguments 曾改、用户明确 Run、或注册后 `registered_definitions` 被改写 |
| `U0C_R3_EVIDENCE_TAMPER` | 敌对 JSON/复制/重哈希等在调度轴上的附加正证据（若层 B 已覆盖可只报 B） |

**非 FAIL（必须诚实记录）**

| 记号 | 含义 |
|---|---|
| `U0C_R3_HISTORY_CHANNEL_DISABLED` | `Microsoft-Windows-TaskScheduler/Operational` `IsEnabled=False`；**不得**用缺历史推断人工运行，也不得假装有事件级“无人干预证明” |

查询时刻实测：`IsEnabled=False`；对三任务名查询无匹配 Operational 事件。终审报告必须原样记录该边界。

## 8. “无人工运行 / 无重注册”可证明边界

在历史通道关闭时，**可证明**的只有：

1. 注册快照 SHA 未变 + live 语义字段未变 → 无重注册/无改 action 的正面支持；
2. 各日 `LastRunTime` 落在该日 21:30 窗 + 日日志 `started_at` 对齐 + `LastTaskResult=0` → 与自然触发一致的正面支持；
3. 08-09 注册报告与后续只读回查曾记录全员哨兵；已跑日离开哨兵的时间与合同日一致。

**不可证明**（禁止写成已证明）：

- “从未有人点击 Run”（无 Operational 历史）；
- “进程一定由 Task Scheduler 拉起而非同命令手工 bash”（无过程审计时，仅能说证据与 scheduler 合同一致）；
- 用“没有事件”反推“没有人工”。

若出现正面矛盾（例如 Arguments 漂移、registered SHA 变、日志早于 StartBoundary、同日多次可区分成功痕迹且第二次改写 exclusive log），则 `U0C_R3_MANUAL_INTERVENTION_EVIDENT` 或对应漂移码 → 窗口失败。

## 9. 对抗性反例（终审独立初验必须至少覆盖未在实现取证中使用的子集）

| 反例 | 期望 |
|---|---|
| 缺一日 JSON | `M1_STREAK_LOG_INVALID` |
| 重复日期输入 / 非升序五日 | `M1_STREAK_INPUT_INVALID` |
| 日历缺一共同开市日 | `M1_STREAK_CALENDAR_INVALID`（且不得先碰 receipt） |
| 日志多一行或缺键/多键 | `M1_STREAK_LOG_INVALID` |
| `status!=SUCCESS` 或 `replay_status!=ALREADY_COMPLETE` 或 `exit_code!=0` | `M1_STREAK_LOG_INVALID` |
| 篡改 `run_id` 与 receipt 不一致 | `M1_STREAK_LOG_INVALID` |
| 复制他日 JSON 改 `date` 字段 | identity 破裂 → LOG/RECEIPT INVALID |
| whole-rehash：改 raw 字节但保留旧 receipt sha | `M1_STREAK_RECEIPT_INVALID` |
| symlink 日志 | `M1_STREAK_LOG_INVALID` |
| 未来 mtime + 内容声称旧 run 但字节已变 | RECEIPT_INVALID / TAMPER |
| 敌对 JSON：绝对路径 selector、非 hex run_id | 不得进入 PASS；现网 wrapper 已拒，审计侧亦应 LOG 对齐失败 |
| 触发前写入 08-12 JSON | `U0C_R3_PREMATURE_DAY_LOG` |
| 改 Task Arguments 日期后“补成功” | `U0C_R3_SCHEDULER_DEFINITION_DRIFT` 或 MANUAL_INTERVENTION |
| 仅层 B PASS 但 LastResult≠0 | 不得 5/5 |

## 10. 5/5 通过与非通过条件

### 10.1 通过（同时满足）

1. 执行时刻 ≥ 08-14 自然任务完成，且五任务均非未运行哨兵；
2. 五任务 `LastTaskResult=0`；`LastRunTime` 落在各自合同日 21:30 窗（含已知 :00/:30 粒度）；
3. `registered_definitions` SHA = 注册收据；live 语义字段未漂移；runner SHA = `bdedb953…02c`；
4. 五日 JSON 均存在且满足 §4；无提前日志记录；
5. `audit_daily_streak` 返回 PASS且 `sessions=5`、dates 精确等于冻结五日；
6. 无 §8 正面人工/重注册证据；
7. 报告如实记载 `U0C_R3_HISTORY_CHANNEL_DISABLED`，不把它解释成已证明或已否证。

### 10.2 非通过（任一即否）

- 任一日失败码日志、`LastTaskResult≠0`、零字节/独占创建失败、序列化超时；
- 层 A/B 任一 FAIL；
- 手工补跑、改任务、重注册后计入；
- 把 2/5、单日 SUCCESS 或 Windows 绿测写成 5/5 / M1 Gate；
- 在 08-12 21:30 前宣称含 08-12 及之后的通过。

### 10.3 当前冻结进度句（必须写入后续任务书）

> 截至 2026-08-12 14:08:47 +08:00，U0C-R3 仅 **2/5**（08-10、08-11）。08-12 仍 Ready，下一次自然触发 21:30:30 为未来时间。禁止预支。

## 11. 08-14 后执行顺序、白名单与职责分离

```text
08-14 自然结束后
  → 主 Agent 冻结《U0C-R3 五日自然窗口终审任务单》（吸收本设计，不改合同）
  → 外部取证/实现会话（全新，--model auto）：只读采集 Task 矩阵 + 跑 audit_daily_streak + 写交付报告
  → 另一外部独立初验（全新，--model auto）：只读复核 + 对抗反例 + 写初验报告
  → 初验 FAIL 则返工任务循环；PASS 后主 Agent 终验
```

### 11.1 文件白名单

| 角色 | 可写 | 只读 |
|---|---|---|
| 本预冻结审计 | **仅** `docs/agent/M1_U0C-R3五日自然窗口终审预冻结设计审计报告.md` | production/tests/既有 docs/正式 data |
| 终审任务单（主 Agent） | 新任务单路径（建议 `docs/agent/M1_U0C-R3五日自然窗口终审任务单.md`） | 同上 |
| 外部取证会话 | **仅**其交付报告 | 禁止改 production/tests；禁止改任务；禁止写 data/run_state/artifacts |
| 外部独立初验 | **仅**其初验报告 | 生产代码、实现者测试、正式证据只读 |
| 主验 | 终验报告；仅在验收通过后按 SSOT 更新 UA-M1-003 / 路线图勾选 | 不得跳过独立初验直接改码宣称通过 |

禁止并行写同一报告路径。正式日证据目录在终审期间保持不可变；任何“修复”只能开启 **新的未来窗口**，不得补写本窗口。

### 11.2 API / 模块锚点（任务单可直接引用）

- `quant.data.audit_daily_streak.audit_daily_streak` / `DailyStreakAuditError`
- `quant.data.scheduled_daily.run_scheduled_daily` → 日志 schema 源
- `quant.data.daily_run.build_daily_run_spec` / `verify_daily_receipt`
- `scripts/run_m1_daily_streak_20260810_20260814.sh`（flock + 20m timeout + exclusive log）
- Windows：`Get-ScheduledTask`/`Get-ScheduledTaskInfo`；语义比对 live vs `registered_definitions`；`Get-WinEvent -ListLog Microsoft-Windows-TaskScheduler/Operational`

## 12. 停止条件

立即停止并升级主 Agent / 用户（UA-M1-003）：

1. 发现 live 语义漂移或 registered SHA 被改；
2. 未来日日志提前出现或有人要求手工 Run/补跑计入；
3. 正式 runner SHA 不再等于注册值；
4. 历史通道被临时开启后又关闭并企图用选择性事件证明无人干预；
5. 任何将本预冻结报告表述为终审通过或 M1 Gate 通过。

## 13. 本审计结论（压缩）

- 设计已足够让主 Agent **直接冻结终审任务书**：层 A scheduler 矩阵 + 层 B `audit_daily_streak`，含 exact schema、命令、证据路径、FAIL 码、反例、历史通道诚实边界、08-14 后四段流程与白名单。
- 查询时刻实证：**2/5**；08-10/11 日志与 receipt/raw/quality 字节闭包正向一致；08-12 仍 Ready 且 21:30:30 未来；Operational 历史 **关闭**。
- **不宣称** U0C 5/5、不宣称终审完成、不宣称 M1 Gate。
