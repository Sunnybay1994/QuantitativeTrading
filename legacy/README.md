"""死模块隔离区。

2026-09-15 重构把运行时无入口引用的模块从 ``src/quant`` 移到这里。
复现旧实验：

```powershell
$env:PYTHONPATH = "$PWD\legacy;$PWD\src"
```

不要从 ``src/quant`` 再 import 这些路径。``research/m3`` 的合约/发布/状态仍留在 src，
因为 A 股回测器依赖它们，只修不扩。
"""
