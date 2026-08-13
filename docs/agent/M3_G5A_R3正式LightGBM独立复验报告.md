# M3 G5A R3 正式 LightGBM 独立复验报告

日期：2026-08-09  
角色：未参与 R3 实现的全新独立复验 Agent  
结论：**PASS**

## 1. 范围与边界

本轮完整阅读 `AGENTS.md`、`.ai` 相关规则、G5A R1–R3 合同、R2 独立复验与 R3
返工交付，只读核对了生产代码、实现者测试和实际 diff。唯一产品写入是本报告；未修改生产
代码或实现者测试，未执行 Git add/commit。验证产生的内容仅位于独立临时目录。

本 PASS 只表示 G5A R3 工程合同可进入主验；不关闭完整 folds/horizons 训练、G5B–G9、真实性能、
M3 或 Linux/ext4 Gate。

## 2. 合同映射

| 要求 | 独立证据 | 结果 |
|---|---|---|
| formal alignment fresh verifier 的任意普通异常稳定换译 | `_fresh_verify_formal_alignment` 捕获任意 `Exception`，离开 active `except` 后统一抛 `M3_MODEL_ALIGNMENT_VERIFY_FAILED` | PASS |
| builder/verifier × `ValueError`/`RuntimeError` 脱敏 | 独立注入 4 种含 marker 异常；固定错误码、`__cause__ is None`、`__context__ is None`，marker 不出现在错误或完整 traceback | PASS |
| builder 故障前零输出/零训练 | 两种 hostile builder 故障后输出目录均为空，fake LightGBM train 计数不变 | PASS |
| R2 fresh exact-root 不回归 | 复制 alignment bytes 到另一绝对路径，fresh verifier 返回 copied-root capability；builder 在零输出/零训练前以 `model alignment stale` 拒绝 | PASS |
| R2 prediction row-key/metadata 不回归 | 合法 exact MultiIndex/metadata 预测成功；RangeIndex、反序 index、反序 metadata、symbol 键漂移 4 类独立反例均 fail closed | PASS |
| 延迟 import 测试顺序无关 | 主 Agent 将旧的当前进程断言改为 fresh subprocess 断言；本轮以 formal→development 顺序运行完整定向组仍通过 | PASS |
| native LightGBM train/save/load/predict | Windows 与 WSL base 的 formal 定向组均包含该 smoke，对应测试通过 | PASS |

## 3. 独立对抗结果

Windows 原生 Miniforge 中的独立探针输出：

```text
G5A_R3_INDEPENDENT_ADVERSARIAL_PASS hostile=4 copied_root=1 prediction_drift=4
```

探针自行构造故障和断言，没有调用实现者的 hostile 测试函数。首次探针将临时 receipt 放在
artifact root 外，被既有 `receipt 不在 artifact root 内` 合同正确拒绝；该进程已结束且临时目录
已清理。按合同将 receipt 放入 fixture artifact root 后，上述全部对抗集通过。

## 4. 验证命令与结果

Windows 原生 Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）：

```text
pytest test_m3_formal_model_artifact.py + test_m3_model_artifact.py
  formal→development 顺序：20 passed, 20363 warnings in 260.89s
Ruff（model/__init__ + formal/development G5A tests）：All checks passed!
mypy（model/__init__ + formal G5A test）：Success: no issues found in 3 source files
```

`pytest` 中的 warnings 为既有 Pandera/Polars horizontal concat 弃用警告。一次将既有 development
测试文件也纳入 mypy 的扩大检查报告 7 项已知类型噪声（缺 pandas stubs 及动态 fake module 属性）；
生产模块、导出与 formal 测试的任务定向 mypy 已实际通过。

WSL Miniforge base（`/mnt/f` DrvFS，`PYTHONPATH=src`）：

```text
同组 pytest：20 passed, 20363 warnings in 150.12s
Ruff：All checks passed!
mypy：Success: no issues found in 3 source files
```

WSL 结果只证明 base Linux interpreter 在 WSL1/DrvFS 上的工程兼容性，不是 ext4 Gate。

## 5. 最终判定

**PASS。** R2 报告中的 hostile verifier 异常泄漏已按冻结规则关闭；R1/R2 已修复的 formal builder
fresh exact-root 与 prediction row-key/metadata 闭包未回归。G5A R3 可进入主 Agent 最终验收和 G5B
解锁，但不得表述为 M3 或 Linux/ext4 Gate 已通过。
