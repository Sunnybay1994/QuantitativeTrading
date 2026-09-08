# M4-P1-ROUTE-TEST Route 参数测试漂移返工验证报告

日期：2026-07-18  
结论：**测试漂移返工通过；不代表 M4-P1 或 M4 里程碑 Gate 关闭**

## 1. 现象与根因复核

`build_order_intent()` 的现行生产合同把 `connect_route` 设为显式必填参数：HK 市场必须传合法 Route，非 HK
市场必须显式传 `None`。`tests/unit/test_execution_oms.py::_command()` 构造 `600000.SH` 买单时遗漏该参数，
使主任务失败摘要中的 41 项受影响用例在进入 OMS reducer 前因调用签名 `TypeError` 失败。

根因是共享测试 helper 未随 P1 Route 合同同步，不是生产 `contracts.py` 或 `oms.py` 的行为缺陷。应遵循的
规则是修正调用者，而不是为生产必填参数增加默认值或放宽非 HK Route 校验。

## 2. 最小修改

仅修改 `tests/unit/test_execution_oms.py::_command()`：

- 在 `build_order_intent()` 调用中显式传入 `connect_route=None`；
- 紧接构造后断言 `intent.connect_route is None`；
- 既有 A 股 symbol、market、currency、identity、command mode 与所有 OMS 断言保持不变。

生产 `src/quant/execution/contracts.py`、`src/quant/execution/oms.py`、M4 store 文件、其他测试及共享文档均未
修改。除本报告外仅新增冻结任务单
`docs/framework/agent/M4_P1Route参数测试漂移返工任务单.md`。

## 3. 实际验证

WSL Miniforge `base`：

```text
/home/mabw/miniforge3/bin/conda run -n base python -B -m pytest \
  tests/unit/test_execution_oms.py -q -p no:cacheprovider
69 passed in 1.88s

/home/mabw/miniforge3/bin/conda run -n base ruff check --no-cache \
  tests/unit/test_execution_oms.py
All checks passed!
```

Windows 原生 Miniforge `base`：

```text
D:\Miniforge3\python.exe -B -m pytest tests/unit/test_execution_oms.py -q -p no:cacheprovider
69 passed in 3.06s

D:\Miniforge3\python.exe -m ruff check --no-cache tests/unit/test_execution_oms.py
All checks passed!
```

测试文件包含 41 个 `test_*` 函数；参数化后完整收集并执行 69 个用例。两平台均无 warning。未运行 mypy：
本轮没有生产类型、接口或实现变更，pytest 已直接执行必填参数调用并验证生成对象字段，Ruff 覆盖唯一修改
文件；额外全模块类型检查不会为该测试数据修正增加有效证据。

## 4. 通过条件与 Gate 边界

- 原受影响 helper 现显式表达 A 股无港股通 Route 的语义；
- 完整 OMS 测试文件在 WSL/Windows 均为 69 passed；
- 唯一修改测试文件在两平台 Ruff 通过；
- 生产合同仍保持 `connect_route` 必填，非 HK 必须为 `None`，没有默认值或接口回退；
- 生产 contracts/OMS 与 store 文件保持只读。

本报告只证明 P1 Route 合同扩展引起的 OMS 测试夹具漂移已消除。它不验证新的 M4 store 实现、不替代更大
范围 M4 合流回归，也不关闭 M4-P1、Paper Gateway、对账恢复、连续运行或 M4 里程碑 Gate。
