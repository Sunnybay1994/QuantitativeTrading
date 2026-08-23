# M4 P8 RUN-0B2G-F2 R1 Formal Service Composition 任务单

状态：主 Agent 串行实现与 Windows 开发检查完成；target/planning loader、schedule/runner仍待实现。

## 1. 目标

把 formal OMS store、formal gateway factory 和 formal ledger provider 组合为 CLI 可消费的 `StoreOpener`、`PaperGatewayFactory` 与 `ServiceFactory`，实际复用既有 `ExecutionService`，不复制 planner/risk/outbox/ledger 逻辑。

## 2. 冻结值与不变量

- worker id：`formal-paper-worker-v1`。
- outbox lease：60 秒（沿用既有 CLI/service 工程基线）。
- clock：aware UTC system clock；dispatch 的同一显式 `now` 语义继续由已批准 gateway adapter保证。
- risk scope：只取 formal account capability 的 `risk_counter_scope`。
- gateway factory 首次 open 后复用同一 verified transport 对象；每次实际 dispatch仍 fresh验证底层 formal broker capability。
- ServiceFactory 只接受 composition 返回的同一 store/submit/cancel 对象，拒绝 caller替换。

## 3. 边界

本包不接 target/planning loader，不运行 CLI，不选择 schedule、不创建 evidence/anchor/log root，不启动 soak。缺 honest current G1 calendar时只完成组合工程，不宣称正式 PAPER 可运行。

## 4. 白名单

- 新 `src/quant/execution/paper_formal_service.py`
- 最小修改 `paper_formal_gateway.py`（同一 factory 缓存 verified open结果）
- `src/quant/execution/__init__.py` lazy export
- 新 `tests/unit/test_paper_formal_service.py`
- `tests/unit/test_paper_formal_gateway.py` 增加同一 open身份回归
- 本任务单与唯一交付报告
