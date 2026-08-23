# M3 G1-R1A 返回前源码身份 TOCTOU 返工任务单

日期：2026-07-15  
状态：**外部返工与独立复验完成，主 Agent 最终验收通过**  
任务性质：独立初验失败后的 P0 fail-closed 返工  
执行模型：非 fast `cursor-grok-4.5-high`

## 1. 现象—根因—规则

权威失败证据：[`M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md`](M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md)
§4 ADV1 与 §5。

| 项 | 冻结结论 |
|---|---|
| 现象 | `_collect_source_digests` 完成后，在 `_read_dependencies` 窗口对已 hash 的 `.py` 做同大小、同 inode 原地改写；`compute_g1_runtime_identity` 仍返回改写前 digest。 |
| 根因 | 单文件 helper 只保护单次读取窗口；返回前只复核项目根/祖先 identity，没有重新证明整个 source 集及内容仍等于已生成 identity。 |
| 应遵循规则 | 运行身份不得成功交付已经过期的源码闭包。hash 后、返回前发生新增、删除、重命名、inode 替换或原 inode 内容改写必须稳定 fail-closed。 |
| 稳定失败码 | `G1_PLANNING_SOURCE_TREE_INVALID`；`str/repr/cause/traceback` 不得泄露绝对路径。 |

## 2. 文件白名单

外部实现 Agent 仅可写：

```text
src/quant/research/m3/g1_planning.py
tests/unit/test_m3_g1_planning.py
docs/M3_G1_R1A运行身份与分阶段计划骨架交付报告.md
docs/M3_G1_R1A返回前源码身份TOCTOU返工交付报告.md
```

R1L 生产代码、测试、交付/初验报告，R1A 既有初验报告，配置、路线图、依赖、数据和产物全部只读。不得写
独立复验报告，不得修改初验失败历史。

## 3. 冻结最小实现

1. 第一次收集 `source_files` 和 `pyproject_sha256` 后照常读取依赖与平台身份并构造候选 identity。
2. 返回候选 identity 前，再从同一受控真实根完整收集一次 `src/quant/**/*.py` digest tuple，并重新 hash
   `pyproject.toml`；必须比较**完整有序 tuple 和 bytes digest**，而非只比较 size/mtime/inode。
3. 任一 source 的新增、删除、重命名、内容变化、inode/类型/symlink 异常，或 pyproject 内容变化，均抛
   `G1_PLANNING_SOURCE_TREE_INVALID`。最终仍执行祖先与 root identity 复核。
4. 不接受只检查 mtime/size 的方案；目标文件系统可能存在时间精度、时间回拨或同大小写入。不得用 sleep、
   全局锁、Git 状态、缓存、重试直到一致或忽略短暂变化。
5. 不改变公共接口、成功路径 digest/规范 JSON、依赖集合、配置闭包和其他错误码。
6. 这是确定性 fail-closed 检查，不要求对“最终复核完成后的纳秒级外部改写”提供文件系统事务保证；必须关闭
   已公开的“第一次 hash 后至最终复核期间”窗口。

## 4. 必须新增的实现者回归

至少覆盖：

1. patch `_read_dependencies`，在真实依赖读取前对已 hash source 做**同大小、同 inode**原地写入：稳定抛
   `G1_PLANNING_SOURCE_TREE_INVALID`，不得返回旧 identity；
2. 同一窗口用同大小新 inode 原子替换 source：同码拒绝；
3. 同一窗口新增或删除一个 `.py`：同码拒绝；
4. 同一窗口同大小改写 `pyproject.toml`：同码拒绝；
5. 无变化成功路径的 `source_tree_sha256`、`code_version`、`pyproject_sha256` 仍与既有算法相同；
6. 异常的 `str/repr/cause/traceback` 不含临时绝对路径。

测试不得依赖 `sleep` 或文件时间自然推进；必须直接用内容/digest 断言证明。

## 5. 验证顺序

所有命令在 WSL Miniforge `base` 中执行，禁止 Windows Python：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q tests/unit/test_m3_g1_planning.py
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/research/m3/g1_planning.py tests/unit/test_m3_g1_planning.py
/home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  src/quant/research/m3/g1_planning.py
```

定向三项通过后，因为生产代码在上一份 `832 passed` 证据后变化，必须在不得 unlink 的持久锁下刷新**一次**
合流证据：

```bash
flock /tmp/quant-m3-r1-validation.lock bash -lc '
  /home/mabw/miniforge3/bin/conda run -n base python -m pytest -q &&
  /home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests &&
  /home/mabw/miniforge3/bin/conda run -n base python -m mypy src
'
```

不得重复启动第二份全量，不得删除 `/tmp/quant-m3-r1-validation.lock`。失败时只记录首个有效失败并停止扩大
修改。

## 6. 交付报告与通过条件

专项返工报告及更新后的 R1A 原交付报告必须记录：

- 六项格式、最小改动与新增测试逐项映射；
- 定向 pytest/Ruff/mypy 的真实结果；
- 持久锁下唯一一次全量 pytest/Ruff/mypy 的真实结果和锁仍存在；
- 未修改 R1L、未读取 token、未联网、未写 raw/clean/release；
- 状态仅为“返工已交，待全新外部独立复验”，不得宣称 R1A/G1/M3/Gate 通过。

通过条件是四类变更窗口均稳定拒绝、成功 identity 无漂移、定向与一次合流全绿、文件白名单无越界。随后必须
由未参与本轮实现的全新外部 Agent 复验至少原 ADV1、上述新增/删除/pyproject 反例及合同映射。
