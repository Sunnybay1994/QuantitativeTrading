# M4 P8 RUN-0B2F-S2 R1 Formal Gateway Policy Adapter 交付报告

## 1. 结论

UA-M4-003 批准的正常 submit、cancel、fault 与 dispatch clock 语义已在 formal PAPER durable gateway 路径闭合。当前只完成 policy adapter 与 gateway factory；service/CLI composition、runner、soak、Linux/ext4 与 M4 Gate 仍未完成。

本轮按用户指示由主 Agent 串行开发，不调用外部 Agent，也不创建内部 subagent 的“独立实现/独立初验”环节。

## 2. 变更

- 新增 `quant.execution.paper_formal_gateway`：
  - public `open_verified_formal_paper_gateway_factory`；
  - public stable `FormalPaperGatewayError`，固定 `PAPER_FORMAL_GATEWAY_INVALID`，cause/context 脱敏；
  - private full-limit fill、default cancel、SENT/no-duplicate fault 与 dispatch-anchored clock adapters；
  - factory 的 identity/open 及每次 submit/cancel 均 fresh 验证 exact formal store chain。
- `PaperGateway` 新增内部 dispatch-anchored clock 兼容路径；旧 `PaperClock.event_time` 与 development ordinal 行为不变。
- `DurablePaperGatewayFactory` 新增私有 formal construction path，只从 exact verified policy/binding 构造 B1-issued formal descriptor；development constructor 不变。
- `quant.execution` 增加 lazy-safe formal gateway exports。
- 新增 focused 测试，覆盖全量限价成交、费用、同 timestamp、retained replay 不重读 clock、unsupported selector、hostile verifier、closed store和 legacy ordinal clock。

## 3. 正常开发检查

Windows 原生 Miniforge、显式绑定本 worktree `src`：

- focused：`4 passed`；
- gateway/durable/formal store/formal gateway 邻接：`54 passed`；
- Ruff：目标生产文件与新测试通过；
- mypy：4 个目标生产文件通过；
- cold import：`FORMAL_GATEWAY_COLD_IMPORT_PASS`，未加载 Qlib/LightGBM/MLflow；
- scoped `git diff --check`：通过，仅出现工作树既有 LF/CRLF 提示。

pytest 报告 worktree `.pytest_cache` 无写权限 warning；实际 basetemp 位于系统临时目录，断言与测试结果不受影响。

## 4. 剩余风险与下一步

- 当前只实现无 drill 配置时的正常 fault 行为；显式 `UNKNOWN`/`NOT_SENT`/duplicate/partial/late-fill drill 仍应由后续版本化配置与 soak 任务冻结，不在本轮猜字段。
- 正常 submit 立即全量成交，因此正常路径没有可取消 open order；cancel adapter 已固定 `late_fills=()`/`confirm_cancel=True`，其公开 open/partial 场景要由后续显式 drill 创建后联测。
- 下一包可以实现 formal service composition，把 gateway factory 与 snapshot port 注入现有 execution service；之后才进入 runner 与 soak。
- Windows 结果不是 Linux/ext4 Gate，也不是 PAPER candidate 或 M4 完成。
