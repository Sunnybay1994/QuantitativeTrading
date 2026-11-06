# M3 E3 严格 Receipt 主 Agent 最终验收报告

日期：2026-07-13  
结论：**E3 严格 Receipt 增量子包 R1–R4 通过主 Agent 最终验收**

本结论只关闭 R1–R4 严格 Receipt、路径边界、不可变发布和六类 identity 的增量范围；不代表 E3 之外的
staging/run-state 工作、M3 或任何 G0–G9 Gate 已完成。

## 1. 证据链

- 任务书：[`M3_E3严格Receipt增量返工任务单.md`](M3_E3严格Receipt增量返工任务单.md)
- 首轮实现：[`M3_E3严格Receipt增量返工交付报告.md`](M3_E3严格Receipt增量返工交付报告.md)
- 首轮独立初验：[`M3_E3严格Receipt独立初验报告.md`](M3_E3严格Receipt独立初验报告.md)
- 主验问题与返工规则：[`M3_E3严格Receipt主验一次返工任务单.md`](M3_E3严格Receipt主验一次返工任务单.md)
- 外部返工：[`M3_E3严格Receipt主验一次返工交付报告.md`](M3_E3严格Receipt主验一次返工交付报告.md)
- 外部独立复验：[`M3_E3严格Receipt主验一次返工独立复验报告.md`](M3_E3严格Receipt主验一次返工独立复验报告.md)

实现与复验由不同外部 Agent 完成；独立复验通过后，主 Agent 重新审阅生产路径并亲自执行本报告中的
验证，未以外部 Agent 自报结果代替终验。

## 2. 主验结论

以下阻断不变量均已关闭：

1. `mkstemp`、临时文件写入/fsync、link、cleanup 和父目录 fsync/close 的公开失败均转换为稳定、脱敏的
   `ValueError`；注入的绝对路径不出现在消息、显式 cause 或格式化 traceback 中。
2. link 或严格复用成功后，临时文件 cleanup 失败不再返回伪成功；已经发布的 receipt 保留且可严格验真。
3. 主失败优先于 cleanup/close 的次失败；单独 cleanup/close 失败不会被静默吞掉。
4. list/dict 等非法 `scope` 在构造、JSON 验真和发布入口均稳定失败为 `ValueError`。
5. 发布仍使用 `os.link` no-clobber，没有回退 `os.replace`；项目目录没有遗留 `*.tmp`。
6. `quant.data` 未新增对 `quant.research` 的反向依赖，六类 public identity 与裸 64 位小写 hex 契约保持不变。

主 Agent 另行在 `/tmp` 原生 Linux 文件系统执行未依赖 pytest fixture 的最小反例：

- `mkstemp` 抛出包含私有绝对路径的 `PermissionError`：稳定脱敏失败；
- link 成功后临时文件 `unlink` 失败：不得返回成功，receipt 保留并可验真；
- list/dict scope：均为 `ValueError`。

结果：`MAIN_ADVERSARIAL_PASS`。

## 3. 主 Agent 实际验证

环境：WSL Miniforge `base`，`PYTHONPATH=src`。

```text
pytest tests/unit/test_m3_run_state.py tests/unit/test_m3_contracts.py tests/unit/test_m3_snapshot.py -q
86 passed

pytest -q
486 passed

ruff check src tests
All checks passed!

mypy src
Success: no issues found in 72 source files
```

静态检查同时确认：生产路径无 `os.replace`、`quant.data` 无 research 反向 import、项目目录无临时 receipt
残留。

## 4. 反馈闭环与后续规则

本轮主验暴露的通用遗漏不是单一 API bug，而是“只验证成功路径，没有穷举公开 I/O 边界与 finally
优先级”。后续不可变证据发布任务必须在任务书中显式枚举 create/write/fsync/publish/cleanup/close 每个
失败点，并验证：稳定错误类型、脱敏、主异常优先、无伪成功、无资源泄漏、已发布证据可重试验真。
该规则已写入返工任务单和设计审查记录，并由新增回归测试固定。

## 5. 非阻塞事项

- 全量测试有 1179 条来自 Pandera/Polars 的上游弃用警告；当前全部测试通过且不改变 Receipt 业务结果，
  按“抓大放小”原则记录为依赖升级技术债，不阻塞本子包。
- 单 receipt 的原子发布不等于多个 artifact 的跨文件事务；外部 TOCTOU 仍按 SSOT 通过消费前再次验真
  fail-closed。这是已披露边界，不是本轮缺陷。

## 6. 状态边界

允许更新为“E3 严格 Receipt 增量子包 R1–R4 已通过主验”。不得据此勾选 G0–G9、宣称 G1、E3 的其他
范围或 M3 完成。当时的下一实施依赖见已归档的 [`M3当前验收与返工总览`](../../../agent-history/M3当前验收与返工总览_截至2026-07-31.md)；当前状态以代码、路线图与 `CODEX_HANDOFF.md` 为准。
