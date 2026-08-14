# M4 P8 RUN-0B2G-F2 R1 Formal Service Composition 交付报告

## 结论

已把 formal OMS capability、formal gateway 与 formal ledger provider 组合为 CLI 所需的 `StoreOpener`、`PaperGatewayFactory`、`ServiceFactory`，实际服务仍是既有 `ExecutionService`。

## 实现

- worker id为 `formal-paper-worker-v1`，lease为60秒，clock为aware UTC system clock。
- risk counter scope只取 formal account capability。
- gateway factory在同一进程缓存同一 verified transport；每次 dispatch仍由 transport对底层 broker capability fresh验真。
- ServiceFactory只接受同一 composition 返回的 store、submit和cancel对象；caller替换稳定拒绝。
- composition及其 existing verifier绑定 store/gateway/provider/account/worker/lease identity，并保持process-local。

## 开发检查

- F2 focused：2 passed。
- F1/F2/formal gateway focused：8 passed。
- execution service + B2G-F0/F1/F2/gateway邻接：70 passed。
- Ruff/mypy：通过。
- 尚未运行 CLI，也未创建正式 root、schedule、evidence、anchor、log或soak。

剩余关键路径是 formal target/planning loader、VerifiedSoakSchedule 与 daily runner。Linux/ext4仍按用户当前指示排除。
