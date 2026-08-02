# M4 P5-P0B 共享 Canonical Wire 任务单

## 状态与边界

- 状态：冻结；当前轮按用户指示由主 Agent 自行实现、自验，不调用外部 Agent。
- 权威设计：[`M4_P5-P0恢复与账本持久化前置设计.md`](M4_P5-P0恢复与账本持久化前置设计.md) §3。
- 工作目录：独立开发 worktree `artifacts/dev_worktrees/m3-g8ab-prereq`。
- 禁止范围：正式 G1 进程、journal、候选映射和发布根；P0C store schema/migration/context/checkpoint；M1/M3 其他 worktree。
- 本包只建立可恢复持久化的公共 wire 前置，不宣称 P5、M4、Linux Gate 或正式发布通过。

## 冻结接口

`quant.execution.wire`：

- `encode_order_command` / `decode_order_command`
- `encode_execution_event` / `decode_execution_event(..., command=...)`
- `encode_order_aggregate` / `decode_order_aggregate(..., command=...)`

`quant.backtest.ledger_wire`：

- `encode_ledger_entry` / `decode_ledger_entry`
- `encode_ledger_state` / `decode_ledger_state`

command/event/aggregate 继续使用既有 `m4-*-v1`，且 P4 fixture 的 bytes/hash 不变。Ledger 首次冻结为
`m4-ledger-entry-v1` 和 `m4-ledger-state-v1`。

## 失败语义与不变量

- 输入必须是无 BOM、无空白、排序键、无重复键的 canonical UTF-8 JSON bytes。
- 字段必须 exact；缺失、额外字段、未知 enum、NaN/Infinity、非唯一 Decimal/date/UTC 文本均以
  `WIRE_INVALID` 失败关闭。
- `schema_version` 必须匹配对应 wire family 的 `m4-...-v<正规范整数>`；只有同一 family 的其他正规范
  版本（例如期望 `m4-order-command-v1` 时收到 `m4-order-command-v2`）返回
  `WIRE_VERSION_UNSUPPORTED`。空值、`v2`、错误 family、`v0`、`v02` 及非字符串均返回
  `WIRE_INVALID`。
- decoder 必须重建领域对象并复验 content identity；event/aggregate 还必须与调用方提供的 command 闭合。
- repository row 的 key/identity/payload 闭合继续由 service/store 边界检查；wire 不猜测或修复 row。
- 错误只暴露稳定 code，不带 payload、路径、SQL、broker 文本或异常上下文；任何 parse/领域构造器异常
  翻译后的 `WireError` 必须同时满足 `__cause__ is None`、`__context__ is None`，并显式抑制上下文展示。
- canonical JSON、schema、标量解析等低层原语的 SSOT 位于 `quant.domain.canonical_wire`；execution 与
  backtest 只能共同依赖该低层模块，`ledger_wire` 禁止反向依赖 `quant.execution.wire` 的私有 helper。

## Golden 与反例

重构前从现有 `tests/unit/test_execution_service.py` fixture 实际调用 P4 私有 encoder，冻结：

| 类型 | SHA-256 |
|---|---|
| command | `7a8a797d89c8736c35846bda6f2636a6fa2795892646389cf8ae12c956d103e5` |
| CREATED aggregate | `c6e6c8b39119092d3fd7fafd3e11ec3d303f24e70e1f472701c4884804ad08a7` |
| ACCEPTED event | `98c52676f5e9165f9d59cfcb11f578df88bb59ab621f4955254926586c7fddac` |

测试至少覆盖 extra/missing、重复键、BOM/空白/恶意 bytes、NaN/Infinity、Decimal 指数文本、非 UTC、
未知 enum/version、command-event 错配、aggregate quantity 错配及 ledger entry/state identity 篡改。

## 独立初验返工闭环

- 现象：任意字符串版本被误分为 unsupported、`raise ... from None` 仍保留隐藏 `__context__`，且 ledger
  从 execution wire 导入私有 helper。
- 根因：版本判定没有约束 family/正规范整数；异常翻译仍发生在活动 `except` 块；低层原语放错架构层。
- 应遵循规则：仅识别同 family 的 canonical future version；退出 `except` 后再构造稳定错误；跨消费者
  原语下沉到无 execution/backtest 依赖的 domain 模块。
- 最小复现与新增测试：参数化 `None`/空串/`v2`/错误 family/`v0`/`v02`/整数，未来 `v2`/`v17`，
  `b"\xffTOKEN"` 与恶意构造器异常链，以及 AST 依赖方向守卫。
- 通过条件：上述反例全部通过，三组 P4 golden SHA-256 不变，Windows 与 WSL base 定向
  Ruff/mypy/pytest 全绿后重新进入独立初验。

## 验收命令

Windows 原生 `D:\Miniforge3\python.exe` 与 WSL Miniforge base 均执行定向 Ruff、mypy、pytest。
Windows pytest 必须显式使用当前 worktree `src`，并使用工作区内独立 `--basetemp`，避免主机全局旧包与
系统临时目录 ACL 干扰。Windows 绿测只代表双平台开发契约的一侧，不替代 WSL/Linux Gate。
