# M3 E3 严格 Receipt 独立初验任务单

日期：2026-07-13  
状态：等待未参与实现的外部 Agent 执行  
实现交付：[`M3_E3严格Receipt增量返工交付报告.md`](M3_E3严格Receipt增量返工交付报告.md)  
实现合同：[`M3_E3严格Receipt增量返工任务单.md`](M3_E3严格Receipt增量返工任务单.md)

## 1. 职责与范围

本轮只做独立初验，不修改生产代码、既有测试、SSOT、任务单或路线图。唯一允许新增的项目文件是：

```text
docs/M3_E3严格Receipt独立初验报告.md
```

实现报告和实现者自报测试只作线索，不作证明。禁止访问 `_old/`、`configs/tushare.local.toml`、网络、
真实数据；不得宣称 E3、M3 或 Gate 通过。结论只能是“独立初验通过，进入主验”或“独立初验不通过，返工”。

## 2. 必读顺序

1. 根 [`AGENTS.md`](../../AGENTS.md) 与 [`karpathy-guidelines.md`](../../karpathy-guidelines.md)；
2. [`M3实施与Agent交接.md`](../M3实施与Agent交接.md) 4.2、4.9；
3. [`M3_E3严格Receipt增量返工任务单.md`](M3_E3严格Receipt增量返工任务单.md)；
4. [`M3_E3设计审查与修订记录.md`](M3_E3设计审查与修订记录.md)；
5. 实现报告、七个修改文件及三组相关单测。

## 3. 必做审查

逐项把 R1–R4 映射到具体源码、既有测试和新造反例。至少检查：

- R1：值对象 direct constructor、严格字段集、duplicate-aware JSON、规范字节、ACCEPTANCE、裸 hash；
- R2：完整 root registry、root/ancestor/leaf symlink、规范 POSIX path、inode/hard-link 去重、双侧自引用、
  dangling symlink 与错误脱敏；
- R3：同目录临时文件、文件 fsync、artifact 再验真、`os.link` no-clobber、冲突不覆盖、复用前全量验真、
  cleanup 与目录 fsync 失败语义、DatasetSnapshot 解耦；
- R4：六个 public identity 的全部参数、变化传播、包根导出和 snapshot producer 裸 hash。

静态确认：生产路径无 `os.replace`；不得返回 `sha256:<hex>`；不存在 data→research 反向 import；修改范围
未扩到 G1/B2A/G8/G9。

## 4. 实现者未使用的对抗验证

可在 `/tmp` 创建临时脚本和数据，结束后清理；不得把临时测试写入项目。至少覆盖：

1. `artifact_roots` 中未被任何 digest 引用的非法 alias/root 也必须先失败；
2. tuple subclass、list、错误 receipt version、非法 scope key 的 direct constructor；
3. dangling symlink、FIFO、目录 receipt leaf、root 外 receipt、缺失 receipt parent；
4. inputs 侧 receipt 自引用/receipt hard-link、嵌套 root 与 hard-link 重复；
5. BOM、非法 UTF-8、nested duplicate key、CRLF/尾随换行/字段乱序等非规范 JSON；
6. `FileExistsError` race 后 existing 非规范、冲突、artifact 漂移三分支均不覆盖；非 `FileExistsError` 不得
   fallback；
7. cleanup 异常不掩盖主异常，目录 fsync 只忽略冻结 errno，link 后 fsync 失败保留可重验 receipt；
8. 对外异常的 `str`、traceback 和 exception chain 不泄露 receipt/root/artifact 绝对路径；
9. 六个 identity 每个参数的敏感性/非法类型，provider-validation 变化时 experiment/work 不变而
   reconciliation 改变；snapshot hash 只迁移输出前缀、不迁移 hash 输入。

必须在实际项目 Windows 挂载盘使用受控随机临时目录实测 WSL `os.link` no-clobber，并清理全部临时文件；
不能只用 `/tmp` 证明。若挂载盘不支持，提交真实最小复现，不得放宽为 `os.replace`。

## 5. 验证命令

只使用 WSL Miniforge base：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_run_state.py tests/unit/test_m3_contracts.py tests/unit/test_m3_snapshot.py -q
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

报告必须记录命令、真实数字和退出状态；Windows conda profile 噪声不得误判为 WSL 项目失败。

## 6. 问题与报告格式

发现问题按 P0/P1/P2，逐项写：

```text
现象 → 根因 → 应遵循规则 → 最小复现 → 新增测试建议 → 通过条件
```

即使无问题，也要给 R1–R4 逐项证据、额外反例结果、挂载盘 hard-link 证据、静态禁止项、完整验证结果与
已知限制。初验 Agent 不修代码；返工必须由实现 Agent 按主 Agent 复核后的任务执行。

初验不通过时，本报告作为下一轮返工输入：外部实现 Agent 修复并新增回归测试、提交返工交付报告，再由
未参与该轮实现的外部初验 Agent 重新执行本任务。重复“实现—初验”直到明确通过后，才交主 Agent 终验；
不得以“问题较小”为由跳过复验。
