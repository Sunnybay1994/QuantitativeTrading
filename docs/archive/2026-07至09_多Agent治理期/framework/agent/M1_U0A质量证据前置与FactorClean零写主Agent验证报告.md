# M1-U0A 质量证据前置与 Factor Clean 零写主 Agent 验证报告

## 结论

通过。`BarUpdatePipeline` 现在只在 bar Schema/质量门禁通过且质量报告成功持久化后，才依次写入 factor clean 与 bar clean。合法 factor 不会再在 bar 质量失败时提前发布。

本轮按用户 2026-07-18 的 24 小时临时授权，由主 Agent 直接实现、审查和验证；暂停外部实现 Agent 与外部独立初验，因此本报告不声称完成了外部独立初验。

## 现象与根因

- 现象：启用复权因子时，旧实现会在 bar 质量验证之前调用 `factor_store.upsert()`。当 bar quality gate 随后失败时，factor clean 已经发生变化，与“质量通过前不写任一 clean store”的失败语义冲突。
- 根因：factor clean 发布语句放在 `validate_bars()` 之前，流水线的证据生成与 clean 发布顺序错误。
- 应遵循规则：raw 可在失败时保留；任何 clean 发布必须晚于 bar Schema/质量门禁及对应质量证据成功持久化。

## 最小修改

- `src/quant/data/pipeline.py`
  - factor raw 抓取、映射及 coverage preflight 保持原位；
  - 将 factor clean upsert 移至成功质量报告写入之后；
  - bar clean 仍在 factor clean 之后写入。
- `tests/integration/test_bar_pipeline.py`
  - 新增“factor 合法但 bar quality 失败”反例，断言两类 raw 均保留、两个 clean store 的 upsert 调用均为零；
  - 新增“成功质量报告写入失败”反例，断言两个 clean store 均不写入。

未改变公共接口、配置结构、CLI 或目录职责，因此不修改 README/路线图。

## 验证

Windows 原生 `py312`：

```text
python -m pytest tests/integration/test_bar_pipeline.py -q  -> 10 passed
ruff check src/quant/data/pipeline.py tests/integration/test_bar_pipeline.py -> passed
mypy src/quant/data/pipeline.py -> passed
```

WSL Miniforge `base`（项目权威环境）：

```text
python -m pytest tests/integration/test_bar_pipeline.py -q  -> 10 passed
ruff check src/quant/data/pipeline.py tests/integration/test_bar_pipeline.py -> passed
mypy src/quant/data/pipeline.py -> passed
```

两端测试各出现 341 条既有 Pandera/Polars concat 弃用警告，不影响本次结论。

## 剩余风险

- 本修复保证门禁或质量证据失败时两个 clean store 都不写入，但 factor clean 与 bar clean 仍是两个独立 upsert，不构成跨 store 事务。若 factor upsert 成功后进程或存储故障，可能留下可重试的部分发布状态。
- 后续 M1-U0B 应使用单实例 journal、完成收据及完整产物重验，使崩溃后重跑能够识别未完成状态；不得仅凭文件存在判定成功。
- 真实“连续 5 个交易日无人干预”Gate 仍需未来五个真实开市日和外部 OS 调度证据，离线测试不能替代。
