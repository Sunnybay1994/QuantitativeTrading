# M3 G1-R1A 返回前源码身份 TOCTOU 独立复验任务单

日期：2026-07-15  
状态：**独立复验完成，主 Agent 最终验收通过**  
执行模型：非 fast `cursor-grok-4.5-high`

## 1. 角色与证据边界

本复验必须由未参与 TOCTOU 返工实现的全新外部会话执行。权威输入：

- `docs/M3_G1_R1A运行身份与分阶段计划骨架外部闭环任务单.md`
- `docs/M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md`（保留首次不通过历史）
- `docs/M3_G1_R1A返回前源码身份TOCTOU返工任务单.md`
- `docs/M3_G1_R1A返回前源码身份TOCTOU返工交付报告.md`
- 当前 R1A 生产代码与实现者测试

唯一允许写入：

```text
docs/M3_G1_R1A返回前源码身份TOCTOU独立复验报告.md
```

生产代码、实现者测试、旧初验报告和其他项目文件全部只读。发现问题不得修复；必须按六项格式判不通过并
返回外部实现闭环。

## 2. 必做复验

1. 逐行确认实现为返回前完整 source tuple **bytes digest** 重收集和 pyproject bytes 重 hash，不是仅依赖
   mtime/size，也没有 retry/sleep/缓存/全局锁。
2. 独立重现原 ADV1：第一次 source 收集后，在依赖读取窗口同大小、同 inode 改写，必须抛
   `G1_PLANNING_SOURCE_TREE_INVALID`。
3. 使用实现者未直接复用的临时对抗组合验证：
   - 在同一窗口重命名旧 `.py` 并新增不同名同内容 `.py`；
   - 同一窗口删除一个 source 同时新增另一 source，保持文件总数不变；
   - 同一窗口改写 pyproject 后用 `os.utime` 尝试恢复原 mtime；
   - 第二次 source 收集自身读窗口内改写文件，仍 fail-closed。
4. 确认无变化时 identity 的 source/tree/code/pyproject digest 算法没有漂移。
5. 确认稳定错误码及 `str/repr/cause/traceback` 脱敏。
6. 复核原初验其余 ADV2–5 对应代码未被本轮返工改变；至少定向重跑现有 R1A 测试。

临时对抗脚本只能位于项目外临时目录，结束后不留在 `src/`/`tests/`。

## 3. 验证与 usage 边界

在不得 unlink 的 `/tmp/quant-m3-r1-validation.lock` 下串行执行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_m3_g1_planning.py tests/unit/test_m3_config.py \
  tests/unit/test_m3_backfill_requests.py tests/unit/test_index_membership.py
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/research/m3/g1_planning.py src/quant/research/m3/__init__.py \
  tests/unit/test_m3_g1_planning.py
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

不重复约 50 分钟的全量 pytest；返工实现已在相同持久锁下刷新 `837 passed`、Ruff、mypy 81 全绿证据。
报告必须区分本会话实跑与复用证据。

## 4. 结论格式

- 全部通过：状态写“独立复验通过，可交主 Agent 终验”；不得宣称 R1A/G1/M3/Gate 通过。
- 任一失败：按“现象—根因—应遵循规则—最小复现—新增测试—通过条件”写明并返回外部实现返工。
- 报告记录唯一写入、持久锁仍存在、无 Windows Python、无 token/网络/raw/clean/release 操作。
