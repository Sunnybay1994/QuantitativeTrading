# M4-P5-P0B 共享 Canonical Wire 返工独立复验报告

日期：2026-08-02（Asia/Shanghai）

角色：原独立 reviewer 同一人返工复验
结论：**PASS，可进入主 Agent 终验**

## 上轮问题关闭情况

1. **版本分类已关闭**：command、event、aggregate、ledger entry、ledger state 五类 wire 均将空串、
   `garbage`、`v2`、错误 family、`v0`、前导零版本及非字符串稳定分类为 `WIRE_INVALID`；仅同 family、
   正整数 canonical future version 返回 `WIRE_VERSION_UNSUPPORTED`。
2. **异常上下文泄漏已关闭**：非法 UTF-8 及 hostile domain constructor 均产生固定 `WireError`；
   `__cause__ is None`、`__context__ is None`、`__suppress_context__ is True`，异常的 string、repr、args、
   cause/context/notes 可见面无法恢复输入中的 `TOKEN`。
3. **私有 helper 依赖已关闭**：canonical primitives 下沉到 `quant.domain.canonical_wire`；ledger wire
   不再 import `quant.execution.wire`。独立 AST 核对确认 domain primitive 只依赖标准库，未形成
   execution/backtest 回边；ledger 对 execution 的剩余依赖仅为既有公开领域 contracts。

## 合同回归

- P4 command、aggregate、event golden SHA-256 分别保持
  `7a8a797d89c8736c35846bda6f2636a6fa2795892646389cf8ae12c956d103e5`、
  `c6e6c8b39119092d3fd7fafd3e11ec3d303f24e70e1f472701c4884804ad08a7`、
  `98c52676f5e9165f9d59cfcb11f578df88bb59ab621f4955254926586c7fddac`。
- canonical JSON duplicate/BOM/whitespace、Decimal/UTC、command/event/aggregate closure、ledger identity
  与嵌套排序的既有反例继续通过。
- service 继续只复用 public execution codec，没有恢复第二套 command/event/aggregate 字段实现。

## 双平台验证

- Windows Miniforge：定向 Ruff PASS；mypy（4 个生产文件）PASS；pytest `73 passed`。
- WSL Miniforge base：对应 Ruff PASS；mypy PASS；pytest `73 passed`。
- `git diff --check` 无内容错误；仅保留工作树既有 Windows 行尾提示。

复验期间生产代码、实现者测试和既有文档只读；仅新增本报告，未提交。该 PASS 只表示 P0B 返工满足
冻结开发合同，不表示 P0C/P5、M4、正式 G1 或 Linux/ext4 Gate 已关闭。
