# M4 PAPER soak 操作手册

## 当前状态

P8 R3 harness 已具备开发合同，但正式状态固定为 `WAITING_FOR_SOAK_EVIDENCE`。只有真实 PAPER 调度连续跨越至少
28 个自然日、覆盖 manifest 内全部预期交易 session、每日无阻断 issue，并完成全部强制故障演练后，正式
证据才可能返回 `PASS`。开发 fixture、fake clock、回放、Windows 绿测和一次长测均不关闭该 Gate。

本手册不注册正式计划任务；正式启动需另行冻结根路径、账户、PAPER gateway、日历来源和运行时配置。

## 身份与目录边界

- development example 根必须以 `artifacts/development_example/m4_p8` 结尾；manifest 固定
  `evidence_kind=development_example`、`formal_gate_eligible=false`，Gate 决策永远不返回 `PASS`。
- 正式 PAPER 根必须由调用方显式传入，且不得是 development 根；manifest 固定
  `evidence_kind=paper_real_time`。harness 不发现或扫描 `data/`、`data/legacy/`、正式 G1 或其他 artifacts。
- 运行目录为 `<explicit-root>/<run_id>/`；session 精确目录是
  `sessions/YYYY-MM-DD/{receipt.json,facts.json}`，fault 精确目录是
  `faults/<drill>/{receipt.json,before_facts.json,after_facts.json}`。文件均为 canonical JSON、append-only；
  相同 bytes 重试幂等，不同 bytes 使用同一键时稳定报 `SOAK_APPEND_CONFLICT`，缺失或增加 sidecar 均关闭。
- manifest 只保存 source/config/gateway/store/account 的不可逆 identity，不保存绝对路径、凭据或账户原文。
  `root_identity` 是规范化绝对 root 的不可逆摘要并进入 `run_id`；复制到另一物理 root 后不能继续验收。
  每次 session/fault append 必须再次显式提交五个 identity，并与 manifest 精确一致。
- 每个 run 还必须显式提供独立绝对 `anchor_root`。它与 evidence root 不得相同、互为祖先/后代或经过
  symlink/junction；manifest 的 `anchor_root_identity` 同样进入 `run_id`。anchor 精确目录为
  `<anchor_root>/<run_id>/anchors/<十位sequence>.json`，保存首次完成 append 的连续 hash-chain。

## 公共调用顺序

1. 从已验证交易日历得到有序、唯一、非空的 expected sessions，调用
   `expected_schedule_identity(expected_sessions)`。
2. 使用显式 `root`、独立 `anchor_root` 和五类不可逆 identity 调用 `build_soak_run(...)`。同参数重复调用
   返回同一 run。
3. 每个预期 session 完成 P6 PAPER 操作后，取得 P5 `RecoveryResult`、`ReconciliationResult` 与 P7
   `ExecutionReport`，以同一双根调用 `append_soak_session(...)`。调用顺序必须与 expected sessions 相同，且下一次
   `invocation_started_at` 严格晚于前一次 `invocation_completed_at`。
4. 故障演练必须保存演练前后各一份完整 `RecoveryResult`，再调用 `append_fault_drill(...)`。调用方不传
   outcome、stable code 或经济影响摘要；harness 从前后 command、cancel、event、ledger entry、checkpoint
   闭包重算，并显式提交同一 `anchor_root`。
5. 使用同一双根与 manifest 调用
   `verify_soak_evidence(root=root, anchor_root=anchor_root, manifest=...)`；再以同一双根和真实 UTC `as_of`
   调用 `decide_soak_gate(verified, root=root, anchor_root=anchor_root, as_of=...)`。decision 会 fresh 重读双根并
   要求新 capability 与传入 capability 精确相等；不得缓存旧 verified 后脱离磁盘判定。

正式 `PAPER_REAL_TIME` 的 build `started_at`、session/fault `completed_at` 和 Gate `as_of` 必须取调用时本机
UTC，且只能落在私有生产 wall-clock 的过去五分钟内；正式调用方没有 clock 注入接口。development fixture
可使用确定性时间，但不会产生正式 PASS。

## 每日阻断条件

以下任一条件使 session `gate_passed=false`：P5 recovery 非 `READY` 或包含 issue；P5 reconciliation 有差异、
非 `READY` 或 Gate false；P7 report Gate false；order/cancel delivery 仍为 `LEASED` 或已经进入 `UNKNOWN`。
上游 code 只有符合稳定 code 格式时才写入 receipt，否则统一写为 `SOAK_UPSTREAM_ISSUE_REDACTED`。

session append 会重新构造并验证 RecoveryResult/ReconciliationResult，重新验证所有 command/event identity、
ledger entry/checkpoint encoding 和 ExecutionReport canonical bytes，随后把 strict versioned retained facts 与
receipt 分开落盘。磁盘 verifier 从 retained wire 重建 recovery/reconciliation/report、链接和摘要，不相信
receipt 自报的 id/hash。fault verifier 同样从 before/after facts 重算经济影响、outcome 和 stable code。

从 RUN-0B2A2 起，session recovery facts 固定为 `m4-soak-recovery-facts-v2`，fault recovery facts 固定为
`m4-soak-fault-recovery-facts-v2`；两者都必须包含 P5 `risk_receipts` 的 strict canonical wire。decoder 通过
公共 durable risk receipt codec fresh 解码，再由 `RecoveryResult` 重建 command/cancel exact ownership 闭包。
v1 retained facts 不携带该字段，不能用于有 command/cancel 的新闭包，也没有生产兼容回填旁路。

session/fault writer 在 evidence exact sidecar 完整并自验后，才 exclusive-create 下一条 `SoakAppendAnchor` 作为
唯一 completion marker。anchor 绑定 run、entry kind/key、evidence root identity、receipt id、facts digests、
前驱 anchor 和私有 UTC `anchored_at`。anchor 前崩溃时，只有 exact evidence 重试可以补锚；不同 bytes 冲突。
同 key 重试不增加 anchor，并发不同 next entry 竞争同一 sequence 时只允许一个创建成功，失败者 exact 重试后
从最新 terminal 接续，不能覆盖、跳号或分叉。

## 强制故障演练

manifest 固定包含以下 exact set：

- `stage_exit_recovery_exact_submit`
- `gateway_unknown_to_query`
- `duplicate_callback_idempotent`
- `callback_payload_conflict_closed`
- `out_of_order_callback_closed`
- `cancel_transaction_rollback_unknown`
- `sqlite_atomic_failure`
- `scheduler_inputs_blocked`
- `completed_actions_idempotent`
- `redaction`

exact submit 必须证明演练后经济影响严格增加且演练前集合是其子集；幂等、阻断、回滚及错误注入演练必须证明
经济影响不变。UNKNOWN/QUERY、callback close 与 cancel rollback 还必须由 recovery disposition 和 delivery
状态证明，不能依赖调用者描述。

## 正式 PASS 判定

正式 verified evidence 同时满足下列条件才返回 `PASS`：

- `last_observed_at - first_observed_at >= 28 days`，判定不读取 fake sleep；
- expected sessions 全部按序覆盖，时间严格递增；
- 每个 session Gate 通过且 issue codes 为空；
- 强制故障演练 exact set 全部存在且 outcome 为 `PASS`；
- 每次 append 的 source/config/gateway/store/account identity 与 run manifest 完全一致。
- 每份 evidence 与独立 anchor chain 双向 exact 对应，verified/evidence identity 绑定 terminal anchor；Gate
  decision 前 fresh 复验双根且 capability 未漂移。

缺 session、自然时间或演练证据时返回 `WAITING_FOR_SOAK_EVIDENCE`；已有 session 或 drill 阻断时返回
`BLOCKED`。Windows 与 WSL DrvFS 开发验证不等同于 Linux/ext4 正式 Gate。

## 失败处置

- `SOAK_APPEND_CONFLICT`：保留冲突文件和调用参数的不可逆 identity，停止该 run 的自动推进并人工核对；不得
  删除或覆盖旧 receipt/facts/anchor。若 evidence exact 完整但 anchor 缺失，可用相同调用补锚；异 bytes 不可补。
- `SOAK_SESSION_INVALID` / `SOAK_FAULT_DRILL_INVALID`：检查输入类型、UTC 时间、session 顺序、五类 identity
  与 P5/P7 闭包；公开异常不会携带内部路径或下游异常链。
- `SOAK_EVIDENCE_INVALID`：把 run 视为不可用于 Gate；保留原目录，只读调查 canonical bytes、root identity、
  retained facts/receipt 链接、anchor chain/terminal、sidecar exact set 或时间顺序漂移。
- 正式运行期间 source/config/gateway/store/account 任一 identity 改变时，新建 run，不延续旧 run 的天数。

本地 anchor journal 的信任边界是可信本机、exclusive append 与首次 bytes 保留；它不是数字签名、WORM、硬件
可信时间或抵抗本机管理员的证明。需要抵抗同机任意改写时，应另行接入外部签名或远端不可变审计。
