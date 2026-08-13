# M4-P2B PaperGateway 任务单

状态：**外部独立初验与主 Agent 最终验收 PASS；仅关闭 P2B PaperGateway 工程合同，不宣布 P2/M4 Gate。**

## 目标

实现无 IO、网络、随机和系统时钟的确定性 `PaperGateway`，同时实现现有
`GatewayTransport` 与 `GatewayCancelTransport`。唯一经济回报格式为公共
`ExecutionEvent`；submit/cancel 返回现有 fenced result。

## 冻结边界

- 时间、fill policy、fault plan 全部构造注入；B3 cost schedule/FX 显式注入。
- `NOT_SENT/UNKNOWN` callbacks 必须为空；UNKNOWN 在实例内保持自动化终态。
- broker/event/fee 身份不得依赖 attempt 或进程状态；相同输入重启重放完全一致。
- submit 只生成 `REJECTED` 或 `ACCEPTED -> PARTIAL_FILL* -> FILL?`。
- cancel 只生成 `CANCEL_ACCEPTED -> late fill* -> CANCELLED/FILL`；满成交赢得竞态，
  `CANCELLED` 后 fill 由共享 OMS 拒绝。
- 每笔 fill 调用公共 `calculate_execution_cost`；不复制 B1/B2/B3、OMS 或 transport verifier。
- 所有 adapter 错误使用稳定脱敏 code，异常链为空。
- broker/PAPER 拒单只允许固定 `PAPER_RULE_REJECT`；未知但格式合法的自由文本、路径、token 和控制字符
  均须在生成持久化 `ExecutionEvent` 前失败。

## 白名单

- `src/quant/execution/gateways/paper.py`
- `src/quant/execution/gateways/__init__.py`
- `tests/unit/test_paper_gateway.py`
- 本任务单与 `M4_P2B_PaperGateway实现报告.md`

禁止修改 contracts、OMS、store、domain、B1-B3、顶层 execution 导出；禁止新增依赖或持久层。

## 验收

覆盖正常/拒单/延迟 ACK、partial/full fill、精确 duplicate、NOT_SENT/UNKNOWN、断线后安全重连、
cancel-fill 竞态、重启重放、限价、伪造身份、hostile 注入对象脱敏。Windows 与 WSL base 各执行
定向 pytest、Ruff、mypy；DrvFS 结果不表述为 ext4 Gate。
