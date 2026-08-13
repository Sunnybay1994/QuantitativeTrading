# M4-P7-R1：EOD 执行报告任务单

日期：2026-08-02  
状态：R2 返工实现、外部独立复验与主 Agent 最终验收均已通过；仅关闭 EOD 执行报告工程合同

## 目标与边界

新增零 IO 纯报告接口，将 P5 的严格 `RecoveryResult`、同一 recovery 上的 `ReconciliationResult` 和本轮
`RiskDecision` 序列汇总为内容寻址、确定、可 JSON 序列化的 EOD PAPER 执行报告。报告覆盖命令、订单状态、
成交、持仓、现金、风险事件与对账差异；不查询 broker、不打开 store、不修改账本、不写文件、不触发重试或下单。

本报告是运维/审计视图，不成为 OMS、ledger、risk 或 reconcile 的新 SSOT；所有输入先用现有 public identity/
reducer 不变量重新验证。P7 工程通过不等于 EOD reconcile Gate、PAPER soak 或 M4 通过。

## 公共接口

生产文件：`src/quant/reporting/execution_report.py`。

```python
def build_execution_report(
    *,
    recovery: RecoveryResult,
    reconciliation: ReconciliationResult,
    risk_decisions: tuple[RiskDecision, ...],
    as_of: datetime,
) -> ExecutionReport: ...

def encode_execution_report(report: ExecutionReport) -> bytes: ...
```

所有公开 dataclass 均 `frozen=True, slots=True`。`ExecutionReport.report_id` 为 canonical JSON（不含自身）SHA-256；
编码固定 UTF-8、排序 key、紧凑 separators、禁止 NaN，末尾无平台相关换行，因此 Windows/Linux bytes 一致。

## 输出内容

- order：command id、symbol、market、side、requested/filled quantity、status、broker order **哈希身份**；
- fill：event id、command id、event type、cumulative/last quantity、价格与按币种费用汇总；
- position/cash：只来自 verified ledger checkpoint，保留明确币种与 Decimal 字符串；checkpoint 缺失时为空并保留状态；
- risk：rule/accepted/code 与 subject 的 SHA-256 身份；永不输出 `detail`；
- reconciliation：Gate/disposition、difference code/action 与 subject/local/broker 身份；非 canonical subject 一律仅哈希；
- totals：命令、订单、fill、position、cash、risk、difference 数量。

输出不包含 raw broker order id、账户原文、绝对路径、SQL、token、配置正文、异常文本或 risk detail。

## 输入闭包与失败语义

1. `reconciliation.local_recovery_id == recovery.recovery_id` 且 `as_of == reconciliation.as_of`，UTC aware；否则失败。
2. 重算 recovery/reconciliation identity；每个 command/event/ledger checkpoint/risk command 均调用现有 public verifier。
3. aggregate、event、risk command 必须引用 recovery 中存在的 command；重复 id、乱序、同 plan 重复 risk decision 拒绝。
4. report 内序列全部按冻结主键排序；调用方输入顺序不得影响 bytes/report id。
5. 错误只暴露 `ExecutionReportError` 固定 code `EXECUTION_REPORT_INVALID`，离开 active `except` 后 `raise from None`，
   cause/context/object graph 不保留 hostile payload。

## 白名单

- `src/quant/reporting/execution_report.py`
- `src/quant/reporting/__init__.py`
- `tests/unit/test_execution_report.py`
- 本任务单、交付报告、独立初验报告

## 必测反例

1. recovery/reconciliation/as_of 任一身份漂移或错配；
2. 冻结对象被 `object.__setattr__` 修改，或 risk command 不属于 recovery；
3. broker order id、risk detail、difference subject、TOKEN/路径只可见哈希且原文不在 bytes/repr；
4. 输入逆序、跨 Windows/Linux newline 环境，输出 bytes 与 report id 完全相同；
5. 空账本与 checkpoint 存在两种合法报告；INTRADAY/MANUAL 报告如实 Gate false，不伪装 PASS；
6. builder/encoder monkeypatch `open/socket/sqlite3.connect` 证明零 IO/网络。

## 验收

Windows 定向 Ruff、mypy、pytest；WSL Miniforge base 对应定向验证。独立复验必须增加未公开的身份漂移或脱敏反例。
