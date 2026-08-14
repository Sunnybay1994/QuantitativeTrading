# M4-P6-R1：PAPER 操作 CLI 任务单

日期：2026-08-02  
状态：设计冻结；实现等待 P4-R 精确派发与 P4-C durable cancel

## 目标与边界

新增唯一公开入口 `quant.execution.cli.main(argv, *, dependencies) -> int`，子命令 exact set 为
`inspect`、`plan`、`approve`、`paper-submit`、`cancel`、`reconcile`。M4 不存在 `live`、泛化 `submit`、
`--yes`、任意 Python 对象/pickle 或用户自报 broker snapshot 的入口。

CLI 只组合既有 domain/risk/store/service/recovery/gateway 公共接口，不复制 OMS、ledger、risk、identity 或
reconcile 公式，不 import QMT/PTrade/MiniQMT/其他 broker SDK。所有外部动作固定 `ExecutionMode.PAPER`。

## 前置条件

1. P4-R 提供 exact command allowlist 的原子 claim/dispatch；`paper-submit` 禁止退化为全局
   `dispatch_pending(limit)`。
2. P4-C 提供 cancel command/outbox、恢复闭包、exact claim、gateway fence、OMS+ledger 回调事务与 cancel 风控计数；
   `cancel` 禁止直接调用 `GatewayCancelTransport.cancel`。
3. broker snapshot 必须由注入的 PAPER query/evidence verifier port 构造并重新通过
   `build_broker_snapshot` 身份验证；CLI 不接受普通 JSON/dataclass 作为可信 broker 事实。

## 依赖端口

`CliDependencies` 只注入：trusted-root store opener；receipt-backed target loader；verified market/account/config
loader；`ExecutionService` factory；PAPER gateway factory；broker snapshot query/evidence verifier；UTC clock。
loader 返回后必须由生产包的 public identity builder 重证，不能只依赖 `isinstance`。

## 六命令

- `inspect`：仅执行 `recover_local_state(store)`；零网络、零写，输出 recovery id/disposition、数量与稳定 issue codes。
- `plan`：fresh load canonical target、market、account、config，重算 `OrderPlan` 与 plan challenge；零 store/gateway 写。
- `approve`：使用独立 approval challenge；fresh reload/recompute 后绑定 exact plan/config/account/market/target identities，
  再调用 service 原子 stage。输出 durable approval/stage receipt；不 dispatch。
- `paper-submit`：使用独立 submit challenge；fresh recovery 后 exact command set、store recovery、gateway identity 均匹配，
  仅调用 P4-R 精确派发。集合新增、缺失、UNKNOWN 或 lease drift 均非零退出。
- `cancel`：fresh recovery exact command/aggregate，构造并重证 `CancelCommand`；challenge 绑定 cancel id、command id、
  broker order id、aggregate identity、as_of 与 gateway identity；仅走 P4-C durable service。
- `reconcile`：可信 port 获取/验证 retained/query PAPER broker evidence 后构造 snapshot，调用 P5 `reconcile`；
  不倒灌 broker 状态，不自动修账。只有 EOD、零差异、local READY 才 Gate pass。

## 内容寻址二次确认

`approve`、`paper-submit`、`cancel` 首次调用只打印 canonical challenge，零 mutation/adapter crossing。challenge exact
字段为 `schema_version/action/mode/store_recovery_id/subject_ids/source_identities/gateway_identity/issued_at/expires_at`；
SHA-256 覆盖 canonical JSON。第二次调用必须提供 `--confirm-sha256 HEX64`，并 fresh 重算逐字段相同、尚未过期后才执行。
不同 action 的 challenge 不可互用；只给 `--yes`、复制 plan id 或跳过 fresh recompute 一律失败。

## 输出、错误与退出码

stdout 只输出 exact canonical JSON：schema、action、status、稳定 code、公开 content identity 与计数；不输出 payload、
绝对路径、SQL、配置正文、token、账户原文或 broker text。stderr 只允许稳定 code。底层异常离开 active `except` 后翻译，
最终 cause/context 均为空。

- `0`：只读成功、动作完成或 EOD reconcile Gate PASS；
- `2`：argparse/用法错误；
- `10`：输入或身份无效；
- `20`：需要确认、challenge 过期或漂移；
- `30`：QUERY_REQUIRED、UNKNOWN 或 intraday；
- `40`：MANUAL_REQUIRED、Gate blocked 或风控拒绝；
- `50`：store busy/可重试瞬态错误；
- `70`：稳定脱敏内部失败。

## 白名单

- `src/quant/execution/cli.py`
- 可选 `src/quant/execution/cli_ports.py`
- `tests/unit/test_execution_cli.py`
- 本任务单、交付报告、独立初验报告

P6 本体不得顺手修改 store/service/risk/reconcile；前置缺口必须在 P4-R/P4-C 独立包关闭。

## 必测反例

1. 任意 live alias、额外字段、未知参数或伪造 identity；
2. approve challenge 用于 submit，或 action/ID/config/as_of/gateway/expiry 任一漂移；
3. 确认后并发插入 pending：集合外命令绝不发送；确认内命令变 UNKNOWN/被 lease：零错误命令发送；
4. cancel 缺 broker id、终态订单、partial-fill 漂移、重复确认；
5. 用户自报 broker source hash、INTRADAY reconcile、manual difference；
6. gateway/loader 异常含敏感正文：stdout/stderr/异常图均不可恢复；
7. inspect/plan/首次 challenge 前后全库逐字节不变；重复已完成确认幂等且零重复经济影响。

## 验收边界

Windows 定向 Ruff/mypy/pytest 与 WSL Miniforge base 对应定向验证均需记录。P6 工程通过不关闭 P8 四周 PAPER/
SHADOW soak，不代表 broker live、Linux Gate 或 M4 里程碑已完成。
