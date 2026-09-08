# M3 G1-R1A 返回前源码身份 TOCTOU 独立复验报告

日期：2026-07-15  
角色：外部独立复验 Agent（全新会话；未参与 TOCTOU 返工实现）  
模型：`cursor-grok-4.5-high`（非 fast）  
状态：**独立复验通过，可交主 Agent 终验**

本结论只针对 TOCTOU 返工独立复验。**不宣称** R1A / G1 / M3 或任何 Gate 通过。

权威输入：

- [`M3_G1_R1A运行身份与分阶段计划骨架外部闭环任务单.md`](M3_G1_R1A运行身份与分阶段计划骨架外部闭环任务单.md)
- [`M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md`](M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md)（保留 ADV1 不通过历史）
- [`M3_G1_R1A返回前源码身份TOCTOU返工任务单.md`](M3_G1_R1A返回前源码身份TOCTOU返工任务单.md)
- [`M3_G1_R1A返回前源码身份TOCTOU返工交付报告.md`](M3_G1_R1A返回前源码身份TOCTOU返工交付报告.md)
- [`M3_G1_R1A返回前源码身份TOCTOU独立复验任务单.md`](M3_G1_R1A返回前源码身份TOCTOU独立复验任务单.md)

## 0. 边界

| 项 | 内容 |
|---|---|
| 唯一写入 | 本报告 |
| 只读 | 生产代码、实现者测试、旧初验/交付报告、配置、数据 |
| 环境 | WSL Miniforge `base`（`/home/mabw/miniforge3/bin/python` 3.13.13）；禁止 Windows Python |
| 持久锁 | `flock /tmp/quant-m3-r1-validation.lock`；`LOCK_BEFORE=PRESENT` → `LOCK_AFTER=STILL_PRESENT`；**未 unlink** |
| 临时对抗 | `/tmp/quant-m3-r1a-toctou-reverify/`；结束后已删除；未进入 `src/` / `tests/` |
| 未做 | 读 token、联网、写 raw/clean/release、修复代码、全量 ~50min pytest |

## 1. 结论总览

| 阶段 | 结果 |
|---|---|
| 返回前完整 source tuple bytes digest + pyproject bytes 重 hash（非 mtime/size；无 sleep/retry/缓存/全局锁） | PASS |
| 独立重现原 ADV1（同大小同 inode 改写） | PASS → `G1_PLANNING_SOURCE_TREE_INVALID` |
| 四项实现者未直接复用的对抗组合 | 4/4 PASS |
| 无变化 identity 算法无漂移；错误码与脱敏 | PASS |
| ADV2–5 相关合同符号仍在；定向 R1A 相关测试重跑 | PASS |
| 持久 flock 定向 pytest / Ruff / mypy | PASS（exit 0；锁仍在） |
| **复验结论** | **独立复验通过，可交主 Agent 终验** |

## 2. 合同映射（TOCTOU 冻结面）

| 契约 | 证据 | 结论 |
|---|---|---|
| 返回前再 `_collect_source_digests` + `_hash_regular_file(pyproject)`；比较完整有序 tuple 与 digest bytes | `compute_g1_runtime_identity` L471–478；静态扫描 | PASS |
| 非仅 mtime/size；无 sleep/retry/缓存/全局锁 | 模块无 `time.sleep`/`lru_cache`/`threading.Lock`/`fcntl.flock`；比较式为 `rechecked_files != source_files or rechecked_pyproject != pyproject_sha256` | PASS |
| 新增/删除/重命名/同 inode 改写/pyproject 变化 → `G1_PLANNING_SOURCE_TREE_INVALID` | ADV1 + 四项新对抗 | PASS |
| 成功路径 digest 算法不变 | `ADV_digest_algorithm_stable`；实现者 `test_return_before_recheck_success_digests_match_algorithm` | PASS |
| `str/repr/cause/traceback` 不含临时绝对路径 | 各对抗 `_assert_sanitized` | PASS |
| 最终仍 `_assert_root_unchanged` | 源码 L478 | PASS |
| ADV2–5 相关入口/错误码仍在（本轮未扩大改写） | 静态符号；定向 `test_m3_g1_planning.py` 等绿 | PASS（定向重跑，非逐行历史 diff） |

## 3. 独立对抗（实现者未直接复用组合）

临时脚本仅 `/tmp`；patch `_read_dependencies` 或第二次 `_collect_source_digests` 窗口。

| ID | 场景 | 结果 |
|---|---|---|
| ADV1 | 第一次 source 收集后、依赖读窗口：同大小同 inode 覆写 `AAAA→ZZZZ` | PASS：抛稳定码；不返回陈旧 digest |
| ADV_R1 | 同窗口：重命名旧 `.py` + 新增不同名同内容 `.py` | PASS：同码拒绝 |
| ADV_R2 | 同窗口：删一 source + 新增另一 source；文件总数不变 | PASS：同码拒绝 |
| ADV_R3 | 同窗口：同大小改写 pyproject 后 `os.utime` 恢复原 mtime | PASS：仍因 bytes digest 拒绝（证明非 mtime） |
| ADV_R4 | 第二次 source 收集自身入口前同大小同 inode 改写 | PASS：fail-closed（`collects=2`） |
| ALG | 无变化时 source/tree/code/pyproject 与既有算法一致 | PASS |

## 4. 持久 flock 定向验证（本会话实跑）

```bash
flock /tmp/quant-m3-r1-validation.lock /tmp/quant-m3-r1a-toctou-reverify/reverify.sh
```

| 命令 | 结果 |
|---|---|
| 独立 ADV 套件（9 项） | **FAIL=0** |
| `pytest -q`（g1_planning + config + backfill_requests + index_membership） | **240 passed**（18.61s） |
| `ruff check`（planning + `__init__` + 实现者测试） | **All checks passed!** |
| `mypy src` | **Success: no issues found in 81 source files** |
| `/tmp/quant-m3-r1-validation.lock` | **STILL_PRESENT**（未 unlink） |
| 进程 | **REVERIFY_OK** / exit 0 |

说明：定向套件现为 240（含 TOCTOU 返工新增回归）；与初验报告当时的 235 差值为预期测试增量，非漏跑。

## 5. 证据区分

| 类别 | 内容 |
|---|---|
| 本会话实跑 | §3 全部对抗；§2 静态合同扫描；上表定向 pytest / Ruff / mypy；锁存在性 |
| 复用实现者合流证据（未本会话重跑全量） | 返工交付报告：全量 **837 passed**、全量 Ruff、mypy 81、`LOCK_STILL_PRESENT` |

## 6. 下一步

- **独立复验通过，可交主 Agent 终验。**
- 不得据此勾选路线图或宣称 R1A / G1 / M3 / Gate 通过。
