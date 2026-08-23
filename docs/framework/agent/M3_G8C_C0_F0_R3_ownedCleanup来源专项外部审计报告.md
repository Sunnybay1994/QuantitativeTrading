# M3 G8C C0 F0 R3 ownedCleanup 来源专项外部审计报告

| 项 | 值 |
|---|---|
| 角色 | 全新外部 Cursor 严格只读专项审计 Agent |
| 模型 | `cursor-grok-4.5-high` |
| 工作区 | `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal` |
| 审计范围 | `tests/support/m3_formal_public_chain/session.py` 的 `_entity_token`、`_owned_cleanup`、`public_formal_chain_session.finally` |
| 结论 | **FAIL / P0**（已复现） |
| 日期 | 2026-08-11 |
| 约束遵守 | 未改 production/support/tests/任务/交付/既有初验报告；未跑长链/联网/add/commit；探针仅在系统临时目录；结束后已清理 |

## 1. 压缩结论

主 Agent 怀疑成立：**`finally` 先对所有目录刷新 token，且 `_owned_cleanup` 仅对 file 在 token 失配时跳过**；session-owned 目录（如 `stage_root`）若被 **same-path、不同 inode** 的外来目录替换，cleanup 会 **`shutil.rmtree` 递归删除外来目录及其 sentinel**。

双路径均可触发：

1. **生产路径（刷新）**：刷新把 expected 改成外来目录 token → cleanup 直接删除。
2. **即使不刷新**：token 明明失配，但 `path.is_file()` 守卫使目录仍被删除。

对照：不刷新 + 对目录也做严格 token 比较 → 外来目录得以保留。刷新后再加严格目录 token 仍会被击败。

## 2. 代码证据（只读）

```121:151:tests/support/m3_formal_public_chain/session.py
def _entity_token(path: Path) -> tuple[int, int, int] | None:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_mtime_ns)


def _owned_cleanup(owned: Mapping[Path, tuple[int, int, int] | None]) -> list[str]:
    report: list[str] = []
    for path in sorted(owned, key=lambda p: len(p.parts), reverse=True):
        expected = owned[path]
        current = _entity_token(path)
        if current is None:
            report.append(f"missing:{path}")
            continue
        if expected is not None and current != expected and path.is_file():
            report.append(f"skip-changed-file:{path}")
            continue
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            ...
```

```238:245:tests/support/m3_formal_public_chain/session.py
    finally:
        # Refresh tokens for dirs created during build (G1 release id known late).
        # Session-owned config may be mutated then restored by hostile tests (mtime
        # drift); refresh its token so owned-only cleanup still removes it.
        for path in list(owned_tokens):
            if path.is_dir() or path == config_path:
                owned_tokens[path] = _entity_token(path)
        _owned_cleanup(owned_tokens)
```

关键语义缺口：

- token 失配跳过条件含 `and path.is_file()` → **目录永远不因 entity 变更而 skip**。
- `finally` 对 `path.is_dir()` **无条件重写** `owned_tokens[path]` → 即使日后给目录加严格比较，刷新也会把外来 inode 认作“owned”。

## 3. 最小探针（系统临时目录，无 G1 链）

解释器：`D:\Miniforge3\python.exe`。基目录：`%TEMP%\m3_g8c_f0r3_owned_audit_*`（探针结束后 `shutil.rmtree`，复查 leftover_count=0）。

逻辑镜像生产 `_entity_token` / `_owned_cleanup`；另加对照参数 `strict_dir_token`。每案：

1. `mkdir stage_root`，写 `owned_marker.txt`，记录 token；
2. `rename stage_root → owned_renamed_aside`；
3. 同路径再建 `stage_root` + `FOREIGN_SENTINEL.txt`（不同 inode，Windows 实测成立）；
4. 按变体模拟 finally 刷新与 cleanup。

| 案 | 变体 | foreign/sentinel 是否被删 | 含义 |
|---|---|---|---|
| A | 刷新全部目录 token → 生产 cleanup | **是** | 生产 finally 路径复现 |
| B | 不刷新 → 生产 cleanup | **是** | 即使 stale token 失配也删目录 |
| C | 不刷新 → 严格目录 token | **否**（`skip-changed-dir`） | 对照保护有效 |
| D | 刷新 → 严格目录 token | **是** | 刷新击败严格目录比较 |
| E | 未替换的 owned 目录 | owned 被删 | 正常 cleanup 仍可用 |

探针关键观测（Case A 摘录）：owned inode ≠ foreign inode；刷新后 expected 等于 foreign token；cleanup report `removed:.../stage_root`；sentinel 消失；aside 原 owned 仍在。

## 4. 现象—根因—规则—最小复现—新增测试—通过条件

### 现象

session-owned 目录路径被外来同 path 不同 inode 目录占据时，`public_formal_chain_session` 退出 cleanup 会递归删除该外来目录（含无关 sentinel），而非 skip。

### 根因

1. `_owned_cleanup` 仅对 **file** 做 `current != expected` 跳过；**directory 忽略 entity 变更**。
2. `finally` 在 cleanup 前对所有 `is_dir()` 路径 **刷新 token**，把外来目录 entity 写入 `owned_tokens`，进一步抹掉“曾 owned 的 inode”记忆。

### 应遵循规则

- owned cleanup 必须按 **创建时记录的 entity token（dev/ino，必要时含不可变身份）** 确认仍是同一目录实体，再删除。
- **不得**在可能发生替换后无条件刷新目录 token 再删。
- same-path 不同 inode 的目录必须 **skip**，不得 `rmtree`。
- 文件路径已有 skip-changed-file；目录应对称保护（或更强：仅 unlink 确认 inode 匹配的空/owned 树）。

### 最小复现（与探针 A 同构，可落单测）

```text
owned = tmp/stage_root; mkdir; token0 = entity_token(owned)
rename owned -> aside
mkdir same path; write FOREIGN_SENTINEL
# mirror finally:
owned_tokens = {path: token0}
for p in owned_tokens:
    if p.is_dir(): owned_tokens[p] = entity_token(p)
_owned_cleanup(owned_tokens)   # 当前：foreign 被删
assert foreign.exists() and sentinel.exists()  # 期望：仍存在
```

### 建议新增测试（实现者侧；本审计未改 tests）

- `test_owned_cleanup_skips_same_path_replaced_directory`：rename 替换后，生产 `_owned_cleanup`（或 session finally 抽出的纯函数）不得删除 foreign/sentinel。
- `test_finally_must_not_refresh_dir_token_over_replacement`：若保留 refresh，refresh 不得覆盖“创建时 token”；或 refresh 仅允许 mtime 漂移且 **ino 不变**。
- 对照：未替换时 owned 目录仍应被清理（回归 Case E）。
- 可选：file 替换路径已有 skip；补一条目录对称断言，防止回归。

### 通过条件

1. same-path 不同 inode 目录替换后，cleanup **不** `rmtree` 外来树；report 含明确 skip（如 `skip-changed-dir`）。
2. `finally` 不得仅凭 path 存在就用当前 entity 覆盖创建时目录 token；若需容忍 mtime 漂移，须 **ino（及 st_dev）不变** 才允许刷新 mtime 分量。
3. 正常未替换 owned 目录/文件仍可清理。
4. 定向单测绿；本审计场景复跑 A/B 应变为 skip，C 行为成为生产默认语义。

## 5. 范围外说明

- 未执行 G1 formal chain、未触网、未 git add/commit。
- 未修改 `session.py` 或任何 support/production/tests。
- Windows 上 `st_ino` 对不同新建目录可区分；本机探针已观察到不同 inode，复现不依赖 Linux。

## 6. 临时目录清理

探针基目录已删除；复查 `%TEMP%\m3_g8c_f0r3_owned_audit_*` leftover_count=0。
