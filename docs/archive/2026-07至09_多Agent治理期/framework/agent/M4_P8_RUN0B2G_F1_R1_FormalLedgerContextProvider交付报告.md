# M4 P8 RUN-0B2G-F1 R1 Formal LedgerContextProvider 交付报告

## 结论

已新增只读 formal A 股 ledger provider。它从 fresh G1 v5 `trade_calendar.parquet` 派生 SH/SZ exact共同开市日，并在每个 command 的 `context_for` 边界重新验真 OMS capability、G1 release 与 calendar实体，再调用既有 ledger builder。

## 闭包

- caller不能传 sessions、source SHA、settlement rule或FX。
- calendar stable双读，物理顺序/唯一键/Schema/manifest bytes均校验。
- rule固定为正式 policy selector、CNY、settlement lag 0、sellable lag 1、sell receivable不可复用。
- 非SH/SZ、闭市日、calendar漂移、hostile verifier统一返回无 cause/context 的 `PAPER_FORMAL_LEDGER_CONTEXT_INVALID`。
- 不选择 soak窗口、不写文件、不读取普通 data root。

## 开发检查

- focused ledger：2 passed。
- ledger + service composition + formal gateway：8 passed。
- execution service + B2G-F0/F1/F2/gateway邻接：70 passed。
- Ruff/mypy：通过。

当前测试在模块边界使用 exact runtime class 的最小内存装配与 public verifier替身，验证本模块逻辑；它不冒充 retained honest G1。没有可保留的当前正式 G1 source，因此该外部依赖仍是后续实际运行 Gate，不影响本工程包完成。
