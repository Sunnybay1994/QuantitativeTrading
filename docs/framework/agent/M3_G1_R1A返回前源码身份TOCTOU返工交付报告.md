# M3 G1-R1A 返回前源码身份 TOCTOU 返工交付报告

日期：2026-07-15  
角色：外部实现 Agent（R1A-TOCTOU 返工）  
模型：`cursor-grok-4.5-high`（非 fast）  
状态：**返工已交，待全新外部独立复验**

本报告不宣称 R1A / G1 / M3 / Gate 通过。权威任务单：
[`M3_G1_R1A返回前源码身份TOCTOU返工任务单.md`](M3_G1_R1A返回前源码身份TOCTOU返工任务单.md)。

## 1. 白名单写入

| 文件 | 说明 |
|---|---|
| `src/quant/research/m3/g1_planning.py` | 返回前重收集 source digest tuple + 重 hash pyproject，完整比较后才 `_assert_root_unchanged` |
| `tests/unit/test_m3_g1_planning.py` | 六项回归（同 inode 改写 / 新 inode 替换 / 增删 / pyproject / 成功算法 / 脱敏） |
| 本报告 | 返工专项交付 |
| `docs/M3_G1_R1A运行身份与分阶段计划骨架交付报告.md` | 同步追加本轮返工节 |

未修改：R1L 生产/测试/报告、R1A 独立初验报告、配置、路线图、依赖、raw/clean/release。  
未 unlink：`/tmp/quant-m3-r1-validation.lock`。未读 token、未联网。

## 2. 现象—根因—最小改动

| 项 | 内容 |
|---|---|
| 现象 | `_collect_source_digests` 后、`_read_dependencies` 窗口内同大小同 inode 改写 source，仍返回陈旧 digest |
| 根因 | 返回前仅复核 root/祖先 identity，未重证明整棵 source 闭包 |
| 规则 | hash 后至返回前：新增/删除/重命名/inode 替换/原 inode 内容改写/pyproject 变化 → `G1_PLANNING_SOURCE_TREE_INVALID` |
| 最小改动 | 构造候选 identity 后再次 `_collect_source_digests` + `_hash_regular_file(pyproject)`；比较完整有序 tuple 与 digest bytes；不等则抛稳定码；最后仍 `_assert_root_unchanged` |

未改公共接口、成功路径 digest/规范 JSON、依赖集合、其他错误码。

## 3. 新增测试映射

| # | 用例 | 断言 |
|---|---|---|
| 1 | `test_return_before_source_same_inode_rewrite_rejected` | patch `_read_dependencies` 前同大小同 inode 覆写 → 稳定抛码，不返回旧 identity |
| 2 | `test_return_before_source_new_inode_replace_rejected` | 同窗口 `os.replace` 同大小新 inode → 同码 |
| 3 | `test_return_before_source_add_or_delete_rejected` | 同窗口新增/删除 `.py` → 同码 |
| 4 | `test_return_before_pyproject_same_size_rewrite_rejected` | 同窗口同大小改写 pyproject → 同码 |
| 5 | `test_return_before_recheck_success_digests_match_algorithm` | 无变化时 `source_files`/`source_tree_sha256`/`code_version`/`pyproject_sha256` 与既有算法一致 |
| 6 | 各失败用例 + `_assert_planning_error_sanitized` | `str/repr/cause/traceback` 不含临时绝对路径 |

无 `sleep`、无依赖 mtime 自然推进。

## 4. 定向验证

环境：WSL Miniforge `base`。

| 命令 | 结果 |
|---|---|
| `pytest -q tests/unit/test_m3_g1_planning.py` | **18 passed** |
| `ruff check`（planning + 测试） | **All checks passed!** |
| `mypy src/quant/research/m3/g1_planning.py` | **Success: no issues found in 1 source file** |

## 5. 持久锁下唯一一次合流

```bash
flock /tmp/quant-m3-r1-validation.lock /tmp/quant-m3-r1a-toctou-validate.sh
```

（脚本内容即任务单三项：`pytest -q` → `ruff check src tests` → `mypy src`；WSL Miniforge `base`。）

| 项 | 结果 |
|---|---|
| pytest -q | **837 passed**（3050.96s / 0:50:50） |
| ruff check src tests | **All checks passed!** |
| mypy src | **Success: no issues found in 81 source files** |
| 收尾标记 | `VALIDATE_OK`；进程 exit 0 |
| 锁文件 | **LOCK_STILL_PRESENT**（未 unlink `/tmp/quant-m3-r1-validation.lock`） |

本轮仅启动上述唯一一次合流；未重复第二份全量。

## 6. 通过条件自检（实现者）

- 四类变更窗口稳定拒绝；成功 identity 无算法漂移；定向三项绿；白名单无越界。
- 下一步：未参与本轮实现的全新外部 Agent 复验 ADV1 + 增删/pyproject 反例 + 合同映射。
