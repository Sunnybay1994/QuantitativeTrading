# M4-P1-ROUTE-TEST Route 参数测试漂移返工任务单

日期：2026-07-18  
状态：已完成（双平台完整测试与 Ruff 通过；见返工验证报告）

## 1. 现象

`tests/unit/test_execution_oms.py::_command()` 为 `600000.SH` 构造 `OrderIntent` 时，仍按旧调用形态调用
`build_order_intent()`，遗漏新增必填参数 `connect_route`。因此该文件 41 项测试在进入 OMS 状态机前统一因
Python 调用签名抛出 `TypeError`，无法验证原本的 OMS 行为。

生产合同已明确：`connect_route` 是显式必填参数；HK 市场必须提供合法 Route，非 HK 市场必须显式为
`None`。本返工不得通过恢复默认值或放宽生产校验掩盖测试夹具漂移。

## 2. 根因与应遵循规则

- 根因：P1 Route 合同扩展后，OMS 测试的共享 helper 未同步新增的显式市场上下文参数。
- 规则：测试 helper 必须与生产公共接口同步；A 股订单没有港股通 Route，但必须显式传
  `connect_route=None`，以保留“调用者必须作出市场语义选择”的生产合同。
- 最小复现：运行 `python -m pytest tests/unit/test_execution_oms.py -q`；修复前 41 项应在
  `_command() -> build_order_intent()` 处因缺少 `connect_route` 失败，而非在 OMS 断言处失败。

## 3. 最小修改与白名单

仅允许：

- 修改 `tests/unit/test_execution_oms.py`：在 A 股 `_command()` helper 中显式传
  `connect_route=None`；增加一个最小断言证明生成的 `intent.connect_route is None`；
- 新建本任务单；
- 新建 `docs/agent/M4_P1Route参数测试漂移返工验证报告.md`。

严格只读：

- `src/quant/execution/contracts.py`；
- `src/quant/execution/oms.py`；
- 所有 M4 store 文件；
- README、项目实施路线图与 `docs/CODEX_HANDOFF.md`；
- 其他生产代码和测试。

## 4. 禁止项

- 不给 `build_order_intent()` 的 `connect_route` 添加生产默认值；
- 不把 SH 订单伪装成任一港股通 Route；
- 不改变 intent identity、OMS reducer、状态迁移或错误语义；
- 不扩大为 M4 全量回归或相邻测试清理。

## 5. 验收

Windows 原生 Miniforge 与 WSL Miniforge `base` 各执行：

```text
python -m pytest tests/unit/test_execution_oms.py -q
ruff check tests/unit/test_execution_oms.py
```

若定向类型检查能提供额外证据且不引入无关噪声，再运行相关 mypy。通过条件：

1. 41 项 OMS 测试全部到达并通过既有行为断言；
2. A 股 helper 生成的 `OrderIntent.connect_route is None`；
3. Ruff 通过；
4. 生产 contracts/OMS 及其他白名单外文件保持未修改；
5. 验证报告准确说明这是测试漂移返工，不宣称因此关闭 M4-P1 或 M4 里程碑 Gate。
