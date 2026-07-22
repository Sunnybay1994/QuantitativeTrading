# M3 G1-R1A 合流 mypy 单点返工任务单

日期：2026-07-15  
状态：**返工、独立复验与主 Agent 最终验收均已完成**  
任务性质：R1A 合流静态类型单点返工；不改变公共接口、运行时行为或 R1L 代码  
执行模型：非 fast `cursor-grok-4.5-high`

## 1. 背景与当前证据

R1A 与 R1L 均已写入 `PARALLEL_BARRIER_READY`，R1L 外部实现 Agent 在持久锁
`/tmp/quant-m3-r1-validation.lock` 下完成首次合流验证：

- 全量 pytest：`832 passed`；
- Ruff `src tests`：通过；
- mypy `src`：失败，唯一错误位于
  `src/quant/research/m3/g1_planning.py:199`；
- R1L 三个生产文件单独 mypy：通过。

失败现象是 `G1RuntimeIdentityV1.__post_init__` 中先后使用同名循环变量 `item` 遍历
`tuple[G1SourceDigestV1, ...]` 和 `tuple[G1DependencyVersionV1, ...]`，mypy 将后一次赋值报告为
`G1DependencyVersionV1` 与先前推断的 `G1SourceDigestV1` 不兼容。运行时测试已经通过，但项目完成标准要求
全量静态类型门禁通过。

## 2. 根因与应遵循规则

根因：同一局部作用域内复用一个变量名承载两个无继承关系的 dataclass 类型，造成静态类型窄化冲突。

应遵循规则：异构领域对象必须使用含义明确且类型单一的局部变量；不得通过 `Any`、`cast`、
`# type: ignore`、放宽 dataclass 字段类型、删除 exact-type/重建校验或修改 mypy 配置来绕过问题。

## 3. 文件白名单

外部实现 Agent 仅可写：

```text
src/quant/research/m3/g1_planning.py
tests/unit/test_m3_g1_planning.py
docs/M3_G1_R1A运行身份与分阶段计划骨架交付报告.md
docs/M3_G1_R1A合流mypy单点返工交付报告.md
```

以下内容全部只读：R1L 生产代码、R1L 测试、R1L 交付报告、原 R1A 任务书、SSOT、配置、路线图、依赖。
不得写独立初验报告。

## 4. 最小实现要求

1. 将两个循环变量改为互不复用、含义明确的名称，或采用等价的最小类型安全写法；保留原有 exact-type、
   嵌套重建、排序、唯一性和失败码语义。
2. 检查本文件是否还有同类局部变量复用导致的 mypy 错误；只修复本次可复现问题，不做顺手重构。
3. 测试必须继续同时构造并验证非空 `source_files` 与 `dependencies`，证明两类嵌套对象的 exact-type 和
   重建校验没有被弱化。现有覆盖足够时可在交付报告指明具体测试；不足才补最小测试。
4. 不改变任何公共接口、digest、规范 JSON、错误码或 R1A 任务书冻结语义。

## 5. 最小复现与定向验证

所有项目命令必须从 Windows 外部 Agent 调用 WSL Miniforge `base`，禁止 Windows Python：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src/quant/research/m3/g1_planning.py
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q tests/unit/test_m3_g1_planning.py
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/research/m3/g1_planning.py tests/unit/test_m3_g1_planning.py
```

三项均通过后，才可进入合流重验。

## 6. 唯一一次合流重验

由于 R1A 生产代码在首次合流验证后发生变化，必须刷新一次合流证据。为避免重复约 50 分钟的重型回归，
不得在持久锁外另跑全量，也不得删除锁文件：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
flock /tmp/quant-m3-r1-validation.lock bash -lc '
  /home/mabw/miniforge3/bin/conda run -n base python -m pytest -q &&
  /home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests &&
  /home/mabw/miniforge3/bin/conda run -n base python -m mypy src
'
```

不得用 `rm`/`unlink` 清理 `/tmp/quant-m3-r1-validation.lock`。若重验失败，只记录首个有效失败摘要并停止，
不得擅自修改白名单外文件。

## 7. 交付报告要求

更新原 R1A 交付报告，另新增本返工交付报告。两者必须写明：

- 现象、根因、应遵循规则、最小复现、实际最小改动；
- 定向 mypy/pytest/Ruff 的真实结果；
- 持久锁下唯一一次合流 pytest/Ruff/mypy 的真实结果；
- 若全部通过，将状态改为“待独立初验”，不得宣称 R1A/G1/M3/Gate 通过；
- 未修改 R1L 文件、未读取 token、未联网、未写 raw/clean/release；
- 只返回压缩摘要，不回传完整测试日志。

## 8. 通过条件

- mypy 不再报告该异构循环变量冲突，且没有新增类型错误；
- R1A 定向测试与 Ruff 通过；
- 持久锁下全量 pytest、Ruff、mypy 全部为退出码 0；
- 公共合同和运行时行为无变化；
- 两份实现报告状态和验证证据一致，进入外部独立初验前置状态。
