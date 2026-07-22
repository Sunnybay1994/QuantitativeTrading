# M4 P0-H1 可信 SQLite 根目录交付报告

状态：**外部实现完成，待独立初验**（不宣称 P0/M4 Gate 通过）  
日期：2026-07-17  
模型：`cursor-grok-4.5-high`（非 fast）  
任务单：[`M4_P0-H1可信SQLite根目录实现任务单.md`](M4_P0-H1可信SQLite根目录实现任务单.md)

## 1. 摘要

为 `ExecutionStore.open` 增加强制 keyword-only `trusted_root: Path`；URI 仅保留 lexical 相对路径合同，实际路径由显式 root 组合，不再读取 `Path.cwd()`。对 root 与 URI 组件做物理边界校验（禁 symlink、非目录祖先、特殊文件、多硬链接；containment 用 resolved `relative_to`）。失败码：`TRUSTED_ROOT_INVALID` / `URI_PHYSICAL_BOUNDARY_INVALID`，脱敏且 `__cause__`/`__context__` 为空。schema/migration/repository/事务未改。

## 2. 修改文件（白名单）

| 文件 | 变更 |
|---|---|
| `src/quant/execution/store.py` | `open(uri, *, trusted_root)`；`_parse_sqlite_uri` 返回相对 Path；root/物理边界校验与 connect 后复验 |
| `tests/unit/test_execution_store.py` | 既有 `open` 改显式 `trusted_root`；新增 H1 反例；目录/文件祖先改为边界码 |
| `docs/agent/M4_P0-H1可信SQLite根目录交付报告.md` | 本报告（新建） |

未改：config/migrations/contracts/其他测试/任务书/README/路线图/B2 文件。

## 3. 契约映射

| 冻结项 | 实现 |
|---|---|
| `trusted_root` 强制 keyword-only，无 default | 缺省 → `TypeError` |
| concrete `Path`、绝对、存在、目录、非 symlink、非 `/`、`resolve(strict=True)` 仍为目录 | `_validate_trusted_root` → `TRUSTED_ROOT_INVALID` |
| lexical URI 不放宽 | `_parse_sqlite_uri` 原规则保留，返回相对 Path |
| 逐段现存祖先：禁 symlink/非目录/出界；缺失可建且复验 | `_materialize_db_path` |
| leaf：非 symlink 普通文件且 `st_nlink==1` | `_check_leaf` |
| connect 后复验失败关闭连接，close 失败不覆盖主错误 | post-check + `_safe_close` |
| 异常脱敏、空 cause/context | except 外再抛稳定码 |

## 4. 定向验证（WSL Miniforge `base`）

```text
pytest tests/unit/test_execution_store.py -q  →  130 passed
ruff check store.py test_execution_store.py   →  All checks passed
mypy src/quant/execution/store.py             →  Success
```

未跑全量 pytest；未联网、未用真实数据/token。

## 5. 限制与下一步

- 仅防静态 symlink/hardlink/特殊文件逃逸；不宣称抵抗同账户并发 rename TOCTOU。
- 实现者不得宣布 Gate 通过。下一步：全新只读外部会话写 `M4_P0-H1可信SQLite根目录独立初验报告.md`，并补任务单 §8 三个未公开反例。
