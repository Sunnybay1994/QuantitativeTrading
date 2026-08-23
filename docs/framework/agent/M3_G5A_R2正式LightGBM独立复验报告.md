# M3 G5A R2 正式 LightGBM 独立复验报告

日期：2026-08-08  
角色：未参与 R2 返工实现的全新独立复验 Agent  
结论：**FAIL；R1 的 builder freshness 与 prediction row-key 两项阻断已修复，但 hostile verifier 异常仍会泄露敏感文本或异常 context。**

## 1. 边界与结论

本轮只读核对 G5A 任务单、R1 初验、R2 交付、生产代码和实现者测试；唯一写入为本报告及测试临时目录。
未修改生产代码/实现者测试，未触碰正式 artifact、journal、候选目录，未执行 Git add/commit。

R2 已完成以下关键修复：

- formal builder 在检查/创建输出内容或调用 LightGBM 前，把完整 G1→G4C 依赖交给正式
  `verify_alignment_artifact`；fresh capability 与传入 alignment（包括绝对 root）必须 exact 相等；
- development builder 接口保持不变，formal/development exact capability 仍 fail closed；
- prediction 现在核对 exact 两级 `("as_of", "symbol")` MultiIndex、唯一递增、metadata 精确列/schema、
  行数和逐行键同序；普通 NaN 合法，score 原顺序返回且不排序。

但冻结合同还要求 hostile verifier 异常脱敏并清空 cause/context。独立反例证明该要求未满足，因此 G5A R2
仍不得进入 G5B 或正式完整 folds/horizons 训练。

## 2. 逐项复验

| 要求 | 独立证据 | 结果 |
|---|---|---|
| builder 在任何输出/训练前 fresh verify 完整 formal 链 | `build_model_artifact` 先调用 `_fresh_verify_formal_alignment`；参数完整传递 release、snapshot/provider/experiment/folds/feature/label 及全部 specs、receipt/upstream paths、artifact roots；copied-root 返回在空输出与零 train call 前拒绝 | PASS |
| formal/dev、缺依赖、stale capability 混配 | exact `type(...) is ...`；缺参数由公开签名拒绝；development alignment 与 copied-root formal capability 均 fail closed | PASS |
| predict 行身份闭包 | 两级/names/unique/monotonic、metadata exact columns/dtypes、逐行同序均校验；实现者测试覆盖 RangeIndex、names、重复/反序、metadata 列/顺序/键漂移 | PASS |
| 日期/证券类型、NaN、score 顺序 | 独立探针中 Python `date`/`str` + Float64 NaN 合法，返回 `(0.125, 1.125, 2.125)`；`Timestamp` 日期漂移在 booster 前拒绝；输出未排序 | PASS |
| 三文件、receipt、native LightGBM、延迟 import | 精确三文件与内容 hash、正式 stage/scope receipt、top-level 不加载 LightGBM；Windows/WSL native 4.6.0 train/save/load/predict 均通过 | PASS |
| hostile verifier 异常稳定脱敏且 cause/context 为空 | 独立反例见第 3 节 | **FAIL** |

## 3. 阻断：hostile verifier 异常泄露

优先级：P1

- **现象 A**：令 `verify_alignment_artifact` 抛出 `RuntimeError("SECRET_TOKEN_X")`，builder 表面消息变为
  `M3_MODEL_ARTIFACT_INVALID`，但 `exc.__context__` 仍是包含敏感文本的原始异常；仅
  `__suppress_context__=True`，没有满足 context 为空。
- **现象 B**：令 verifier 直接抛出 `ValueError("SECRET_TOKEN_X")`，`_model_boundary` 的
  `except ValueError: raise` 使敏感文本原样穿透公共边界。
- **根因**：公共 decorator 信任所有 `ValueError` 都是本模块稳定错误；对其他异常使用
  `raise ... from None` 只抑制 traceback 显示，不会清空 `__context__`。
- **最小复现结果**：

  ```text
  runtime ValueError M3_MODEL_ARTIFACT_INVALID cause=None
          context=RuntimeError('SECRET_TOKEN_X') suppress=True files=[]
  value   ValueError SECRET_TOKEN_X cause=None context=None files=[]
  ```

- **已成立的安全部分**：两种异常均发生在任何 output 写入和 train call 前，输出目录保持为空。
- **应遵循规则**：来自上游 verifier/第三方边界的任意异常类型均不可信；在专用边界捕获后，应离开
  `except` 块再抛固定稳定错误，使 `str` 不含上游文本且 `__cause__ is None`、`__context__ is None`。
- **新增测试**：分别让 formal builder 和 formal verifier 的 alignment verifier 抛含 marker 的
  `ValueError` 与非 `ValueError`；断言固定错误码、marker 不出现、cause/context 均为空，并断言 builder
  零写入、零 LightGBM import/train。
- **通过条件**：上述四组反例全部满足脱敏与空异常链；现有 19 个定向测试、静态检查和 native smoke 保持绿色。

## 4. 验证证据

Windows 原生（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）：

```text
pytest test_m3_model_artifact.py + test_m3_formal_model_artifact.py:
19 passed, 18777 warnings in 302.28s
Ruff: All checks passed!
mypy: Success: no issues found in 3 source files
native smoke: G5A_NATIVE_LIGHTGBM_PASS 4.6.0 3 4; 1 passed
```

WSL Miniforge base（`/mnt/f` DrvFS，`PYTHONPATH=src`）：

```text
同组 pytest: 19 passed, 18777 warnings in 212.15s
Ruff: All checks passed!
mypy: Success: no issues found in 3 source files
native smoke: G5A_NATIVE_LIGHTGBM_PASS 4.6.0 3 4; 1 passed
```

warnings 均为既有 Pandera/Polars horizontal concat 弃用警告。WSL 结果仅证明 base Linux interpreter 在
DrvFS 上的工程兼容性，不是 ext4 Gate，也不关闭正式 G5/M3 Gate。

## 5. 最终判定

**FAIL。** R1 两项功能阻断本身已修复，但异常边界仍违反同一冻结任务的脱敏不变量。应按第 3 节做最小
返工，再由未参与该轮实现的独立复验者复验；复验 PASS 前不进入 G5B，不表述为正式 G5A/G5/M3 Gate 通过。
