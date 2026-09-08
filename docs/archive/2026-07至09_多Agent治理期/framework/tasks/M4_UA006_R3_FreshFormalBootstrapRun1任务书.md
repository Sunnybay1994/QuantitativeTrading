# M4-UA006-R3 Fresh Formal Bootstrap Run1 任务书

日期：2026-08-28<br>
状态：`FROZEN / FRESH_INITIALIZE_REOPEN_WINDOWS_ENGINEERING_VALIDATED / LOCKED_RETAINED`<br>
task id：`M4-UA006-R3-FRESH-FORMAL-BOOTSTRAP-RUN1`

## 1. 身份、目标与终态上限

- exact base：`aa84ebc8519a34dcc83b309db6fda0f2b95dc4a5`
- current tracked HEAD：`1a25284fc2db58d165ec59b43560c53214147850`
- branch：`codex/m4-ua006-r3-fresh-formal-bootstrap-run1`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-r3-fresh-formal-bootstrap-run1`
- tracked exact3：
  1. `docs/framework/tasks/M4_UA006_R3_FreshFormalBootstrapRun1任务书.md`（经理唯一写）
  2. `docs/framework/deliveries/M4_UA006_R3_FreshFormalBootstrapRun1交付报告.md`（运行执行者唯一写）
  3. `docs/framework/reviews/M4_UA006_R3_FreshFormalBootstrapRun1独立初验报告.md`（未参与运行的 reviewer 唯一写）

本包只用已合流的 package-owned CLI 对一个全新 Windows formal runtime 执行一次 `initialize`，完成只读身份核验后再执行一次 `reopen`，形成 UA-M4-006 的 fresh-root/new-epoch 工程证据。不得修改 production、tests、config SSOT、roadmap、shared governance 或其他 tracked 路径。

终态上限为 `FRESH_FORMAL_BOOTSTRAP_RUN1_EVIDENCE_RECORDED / LOCKED`。它不等于 PAPER、soak、order、submit、B1B2 以外的业务闭包、Linux Gate 或 UA-M4-006 整体完成。

## 2. 冻结运行身份

- `session_date`：`2026-08-27`
- mode：`PAPER_REAL_TIME_WINDOWS`
- account selector：`formal_paper_a_share_v1`
- source selector：`formal_source_v1`
- policy selector：`paper_a_share_v1`
- schedule selector：`formal_schedule_v1`
- Python：`D:\Miniforge3\python.exe`
- cwd：exact worktree
- `PYTHONPATH`：`<exact-worktree>\src`
- 资源：单实例、BelowNormal、affinity `0xF00`、数值线程 `<=2`；运行前由中央按当前真实现场重新授予，禁止硬编码已退出的 writer PID。

外部父目录 exact：

`F:\AI_Coding\QuantitativeTrading_runtime\m4-ua006-run1-20260827`

五个配置 sibling root 角色 exact：

1. `F:\AI_Coding\QuantitativeTrading_runtime\m4-ua006-run1-20260827\runtime`
2. `F:\AI_Coding\QuantitativeTrading_runtime\m4-ua006-run1-20260827\broker`
3. `F:\AI_Coding\QuantitativeTrading_runtime\m4-ua006-run1-20260827\evidence`
4. `F:\AI_Coding\QuantitativeTrading_runtime\m4-ua006-run1-20260827\anchor`
5. `F:\AI_Coding\QuantitativeTrading_runtime\m4-ua006-run1-20260827\log`

这里的 exact5 是 semantic layout 角色集合，不表示 initialize 后五个目录都必须物理存在。真实 public bootstrap 合同冻结为：`runtime`、`broker` physical materialized exact2；`evidence`、`anchor`、`log` physical absent exact3；五个角色均须进入 `root_identities` 与 `runtime_layout_identity`，其中 absent exact3 使用 package-owned `absent-paper-runtime-root-v2` identity。禁止为了迁就旧任务书而补建 absent exact3。

ignored config exact：

`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-r3-fresh-formal-bootstrap-run1\configs\trading\paper_runtime.ua006-run1.local.toml`

该路径由根 `.gitignore` 的 `*.local.toml` 覆盖。config 必须是 UTF-8 without BOM、LF 行尾、末尾恰好一个 LF；raw size exact `947` bytes，SHA-256 exact：

`4217f157885f3e304da7d834f8e80ed21bdd23273017e1fea42863abebd752cd`

```toml
[meta]
schema_version = "paper-runtime-config-v2"
runtime_version = "paper_runtime_v2"
mode = "PAPER_REAL_TIME_WINDOWS"

[paths]
runtime_root = "F:/AI_Coding/QuantitativeTrading_runtime/m4-ua006-run1-20260827/runtime"
broker_root = "F:/AI_Coding/QuantitativeTrading_runtime/m4-ua006-run1-20260827/broker"
evidence_root = "F:/AI_Coding/QuantitativeTrading_runtime/m4-ua006-run1-20260827/evidence"
anchor_root = "F:/AI_Coding/QuantitativeTrading_runtime/m4-ua006-run1-20260827/anchor"
log_root = "F:/AI_Coding/QuantitativeTrading_runtime/m4-ua006-run1-20260827/log"
project_root = "F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m4-ua006-r3-fresh-formal-bootstrap-run1"

[store]
oms_sqlite_filename = "oms.sqlite3"
broker_sqlite_filename = "broker.sqlite3"

[selectors]
account_selector = "formal_paper_a_share_v1"
source_selector = "formal_source_v1"
policy_selector = "paper_a_share_v1"
expected_schedule_selector = "formal_schedule_v1"
```

任何 path、raw bytes、size、SHA、selector、mode、session date 或 base 漂移均 `CONTRACT_STOP`，不得现场修补。

## 3. 用户分段授权 Gate

2026-08-30，用户明确回复“按照你的建议推进”；中央将该回复接受并登记为 A-D 四项授权。授权只解除用户决策门禁，不合并执行阶段，也不替代各阶段开始前的 exact identity、no-clobber、网络、真实 I/O 与 CPU 资源准入。执行仍严格保持 A → B → 条件 C → D：A 完成并复核前不得执行 B；C 仅在 B 成功且只读身份核验通过时有效；D 只授权原样锁定保留，不能解释为清理、adopt、补写或重试权限。A 已完成，B 的唯一 initialize 已在 B2 消费；当前仅等待修订合同独立复核和中央对 `C_REOPEN_ONCE` 的另行裁定。

- **A — CONFIG_AND_PARENT_CREATE**：允许创建上述 exact external parent，并在 exact ignored config path 写入已审阅的 947 bytes / SHA；创建后五个 child roots仍须全部不存在。不得创建 epoch、SQLite、descriptor 或运行证据。
- **B — INITIALIZE_ONCE**：A 的 bytes/no-clobber/五根 absent 复核通过且中央另授真实 I/O/CPU 租约后，允许创建一个新的 no-clobber ignored carrier evidence root，并对 exact config/session date 执行一次且仅一次 `initialize`；由 public API 物化 `runtime`、`broker` exact2、保持 `evidence`、`anchor`、`log` absent exact3，并为 semantic exact5 生成 `root_identities`、`runtime_layout_identity`、new epoch 与 durable runtime bytes。失败不重试。
- **C — REOPEN_ONCE**：只有 initialize exit `0`、stdout/stderr/identity/根布局只读核验通过后，允许对同一 config/session date 执行一次且仅一次 `reopen`。initialize 失败、输出不完整、身份漂移或 barrier 非 OPEN 时 C 自动失效。
- **D — LOCK_AND_RETAIN**：无论 CLI 进入后的成功或失败，允许将 exact external parent、ignored config、carrier evidence 与 partial/full runtime evidence原样标为 `LOCKED` 保留；不得自动清理、adopt、补写或重试。后续解锁/清理必须另包授权。

## 4. 前置与 no-clobber 检查

每一步开始前均重新核验 exact worktree/base/branch、tracked clean（除本任务 exact docs）、cached `0`、config与外部路径身份以及资源 owner。A 前必须证明 external parent、config 与 carrier evidence root均不存在；A 后、B 前必须证明 parent 为 exact real directory、config raw bytes/SHA exact、五个 sibling roots exact absent，且无 symlink/junction/reparse、nested/alias/root overlap。

运行载体 evidence 使用新的项目内 ignored no-clobber root：

`<exact-worktree>\artifacts\agent_runs\m4-ua006-r3-run1-20260827-<UTC>-<random>\`

它只能在 B 获批后创建。parser/preflight/initialize/identity/reopen/final-scope 每阶段无条件持久化 stdout、stderr、exit 与 append-only summary；空流也必须创建 0-byte 文件。日志不得包含 config raw bytes、绝对 root、账号、token、credential、`verified_at` 或对象 repr；需记录路径时只记录冻结逻辑名及其 SHA/identity。

## 5. 唯一执行序列

1. 纯只读核 exact Git/config/raw SHA/external no-clobber/进程与资源现场。
2. A 获批后只创建 external parent与config；复核五根仍 absent。
3. B 获批后先对实际完整 PowerShell carrier做 Parser.ParseFile 零执行检查；设置当前短命 PowerShell 为 BelowNormal/`0xF00`并保存原 priority/affinity，线程环境变量均 `<=2`。
4. identity preflight：`quant`、`paper_runtime`、`paper_formal_bootstrap`、`run_paper_formal_bootstrap`全部来自 exact worktree；config bytes/SHA仍 exact。
5. direct call exact一次：

   `D:\Miniforge3\python.exe -m quant.execution.run_paper_formal_bootstrap --config <exact-config> --session-date 2026-08-27 --initialize`

6. 无写只读核 initialize：exit `0`、stderr `0B`、stdout exact一行 canonical JSON、schema与exact18 keys、mode=`initialize`、session date exact；物理布局必须为 `runtime`、`broker` exact2 real/non-reparse 与 `evidence`、`anchor`、`log` exact3 absent，semantic layout exact5、absent identities、`runtime_layout_identity` 与 new epoch 必须闭合。失败立即 STOP，C 不得执行。
7. C 获批且步骤6通过后 direct call exact一次：

   `D:\Miniforge3\python.exe -m quant.execution.run_paper_formal_bootstrap --config <exact-config> --session-date 2026-08-27 --reopen`

8. 无写只读核 reopen：exit `0`、stderr `0B`、stdout exact一行 canonical JSON、mode=`reopen`、schema/session/key集合闭合。
9. 对 initialize/reopen 做 §6 identity 比较；随后核 exact3 tracked scope、cached0、diff-check、temp/cache/process residue并释放 `0xF00`。
10. D 获批后保留 config、external parent、已物化 exact2、absent exact3 事实与所有 evidence，记录 `LOCKED / OWNER_DECISION_REQUIRED`；只更新 delivery，交独立 reviewer复核，禁止自动清理或退休。

任何首失败均停止后续业务调用；不自动重试、不把 partial root 补全、不调用 reopen、不删除现场。

## 6. 输出与身份比较合同

两次成功输出的字段必须 exact18，且三组互斥并完整覆盖：

- control exact2：`schema_version`、`mode`。schema 两次均 exact `m4-formal-bootstrap-operator-result-v1`；mode 分别 exact `initialize` / `reopen`。
- time-bound exact6：`bootstrap_identity`、`runtime_environment_identity`、`execution_policy_identity`、`broker_binding_identity`、`account_verification_identity`、`broker_capability_identity`。每值均 canonical lowercase 64-hex；initialize 与 reopen 对应字段必须逐项不同。
- durable exact10：`session_date`、`config_identity`、`config_raw_sha256`、`source_file_identity`、`runtime_layout_identity`、`gateway_identity`、`execution_store_identity`、`barrier_epoch`、`barrier_capability_identity`、`barrier_lock_identity`。两次必须逐字段 exact相等；`session_date` exact `2026-08-27`，其余九项 canonical lowercase 64-hex。

禁止把 `runtime_layout_identity` 误归 time-bound；禁止暴露或比较 `verified_at`。任一 key 缺失/额外、非canonical hash、durable漂移、time-bound相等、路径泄露或非canonical stdout均 fail closed。

## 7. 禁止项与失败语义

- 禁止 PAPER daily/session、soak、scheduler、order、cancel、gateway submit、broker network、browser、真实行情/账户 I/O、actual worker、Linux/WSL Gate。
- 禁止第二次 initialize/reopen、自动 retry、resume、adopt旧root、复用 retained/历史root、修改config bytes、从 env/cwd/default发现参数。
- 禁止修改 production/tests、stage/commit/merge、写 integration、清理历史 evidence 或触碰 M3 retained/data writer/state.sqlite。
- A 前失败：零创建；A 后 B 前失败：parent/config原样保留并 STOP，等待D或另行处置裁定。
- CLI 进入后失败：保留所有 partial bytes/evidence，禁止清理；只有D明确授权后才标LOCKED，不得声称初始化完成。
- initialize成功但 C 未获授权：保持 OPEN bundle只读冻结，不运行reopen。

## 8. 交付与独立审查

delivery须逐阶段记录授权、时间、原生exit、stdout/stderr/summary SHA、exact18解析结果、physical exact2/absent exact3/semantic exact5、epoch/no-clobber、资源释放、Git scope、实际失败与LOCKED处置；不得复制敏感内容或路径到CLI输出引用，不得把未运行阶段写成PASS。

independent reviewer只读核 taskbook/config SHA、A-D授权、initialize/reopen原生证据、identity分组、失败保留、exact3与禁止边界；唯一写review路径。至少补一个实现者未使用的静态反例，优先检查“initialize成功但未获C时不得隐式reopen”或“time-bound相等被误判为durable”。

本任务书已记录用户对 A、B、C、D 的明确授权，但用户授权不替代逐阶段执行资源 grant。A 已按 grant 创建 external parent 与 config；B 的唯一 initialize 已在 B2 消费；当前 external parent、config、physical exact2 与 B1/B2 evidence 按 D 原样 `LOCKED_RETAINED`，absent exact3 不得补建。C 虽有用户条件授权，但在修订合同独立复核与中央 `C_REOPEN_ONCE` grant 前仍不可执行。

## 9. B1/B2 执行历史与合同纠正

- B1 carrier 在业务 Python 前因外层资源检查误把“affinity 与 `0xF00` 有交集”当成“affinity exact `0xF00`”而 STOP；`Python=0`、`initialize=0`。B1 leaf 永久 `LOCKED_RETAINED`，不得覆盖、追加、删除或复用。
- B2 使用新 no-clobber leaf，外层资源检查改为 `ProcessorAffinity.ToInt64() == 0xF00`；Parser errors exact0、identity exit0/stderr0、initialize exact一次 exit0/stderr0，stdout 为 exact18 canonical JSON。该唯一 initialize 授权已经消费，禁止重跑。
- B2 的 runner 按旧任务书对五个角色逐项要求 physical directory，在 `evidence` absent 处触发 `POSTCHECK_CONTRACT_STOP`。中央源码审计确认这是任务书预期漂移，不是 bootstrap production 失败：`paper_runtime.py` 对 absent root 生成 package-owned identity，formal execution/broker store 分别只物化 `runtime` 与 `broker`，reopen 也只要求这两个 operational roots 存在。
- 修订后的 initialize 合同只使用 immutable B2 evidence 做只读复核：physical materialized exact2=`runtime,broker`；physical absent exact3=`evidence,anchor,log`；semantic identity exact5 全部闭合。禁止重跑 initialize、补建 absent exact3、修改 production/tests/config/external roots 或 B1/B2 evidence。
- 独立静态复核确认 B2 evidence 满足修订合同后，中央另发 `C_REOPEN_ONCE` grant；C 已按 exact-once 合同执行并通过。initialize 与 reopen 各 exact1，两个业务调用均已消费，禁止再次调用。

## 10. C reopen 终态证据

- C 使用全新 no-clobber ignored leaf；runner 以 mandatory `EvidenceRoot` 绑定本轮唯一 leaf，源码不含 `--initialize` 调用，Parser errors exact0。
- reopen 原生 exit `0`、stderr `0B`，stdout 为单行 canonical JSON、schema与 exact18 keys闭合、mode=`reopen`。
- control exact2闭合；durable exact10与 B2 initialize逐项 exact相等；time-bound exact6逐项不同且均为 canonical lowercase 64-hex。
- physical materialized exact2=`runtime,broker`、physical absent exact3=`evidence,anchor,log`、semantic identity exact5保持；未补建 absent exact3。
- C 完成后 Python/pythonw=`0`、exact affinity `0xF00`=`0`；B1/B2/C evidence、external parent、config、runtime、broker按 D 永久 `LOCKED_RETAINED`，不得自动清理、adopt、追加或退休。
- 本证据只把终态上限推进到 fresh initialize+reopen 的 Windows 工程闭包。PAPER、28日 soak、OMS/order、UA-M4-006整体 Gate和Linux Gate均保持未完成。
