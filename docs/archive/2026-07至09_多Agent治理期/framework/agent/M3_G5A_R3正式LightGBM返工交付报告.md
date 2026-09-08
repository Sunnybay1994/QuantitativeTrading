# M3 G5A R3：正式 LightGBM 异常脱敏返工交付报告

日期：2026-08-08  
状态：实现完成，等待全新独立复验

## 1. 返工范围

R3 只关闭 R2 初验发现的 hostile upstream verifier 异常泄露，不改变 G5A 模型、训练、预测、manifest、
receipt 或 development 公共接口。

- `model.py` 的 formal alignment fresh verifier 现在捕获上游普通异常，离开 active `except` 后统一抛出
  `M3_MODEL_ALIGNMENT_VERIFY_FAILED`。
- 新增 builder/verifier × `ValueError`/`RuntimeError` 四组对抗回归，断言 marker 不泄露且 cause/context
  均为空；builder 发生失败时保持空输出、零新增训练调用。
- 任务单同步记录“现象—根因—规则—最小复现—新增测试—通过条件”。

## 2. 当前验证

Windows 原生 Miniforge：

```text
新增脱敏回归：1 passed
formal + development（formal 先运行）：20 passed, 20363 warnings in 261.94s
fresh-process 包根延迟导入：1 passed
Ruff（model.py + formal test）：PASS
mypy（model.py + formal test）：PASS
WSL base /mnt/f 新增脱敏 + 延迟导入：2 passed
```

扩大回归曾因 formal native smoke 先加载 LightGBM，使既有 development 测试直接检查当前进程
`sys.modules` 而顺序敏感。该测试已改为 fresh subprocess import 后检查，随后以相同 formal→development
顺序复跑通过。warnings 为既有 Pandera/Polars 弃用警告。Windows/DrvFS 结果均不替代 Linux ext4 Gate。

## 3. 未关闭边界

本报告不宣称 G5A、G5B–G9、真实数据性能、M3 或 Linux/ext4 Gate 通过。只有未参与 R3 实现的全新独立
复验明确 PASS 后，G5A 工程合同才可进入主验并解锁 G5B。
