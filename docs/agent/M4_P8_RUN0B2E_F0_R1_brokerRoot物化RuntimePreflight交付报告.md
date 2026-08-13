# M4 P8 RUN-0B2E-F0 R1：broker root 物化态 Runtime Preflight 交付报告

日期：2026-08-12  
角色：外部实现 Agent（Cursor `auto`）  
状态：**已交付；待独立初验**

## 1. 实现摘要

- `FormalPaperRuntimeConfig` layout 现支持互斥两态：**cold**（五根 absent）与 **broker-materialized**（仅 `broker_root` 为真实目录，其余四根 absent）。
- `DevelopmentPaperRuntimeConfig` 仍要求五根全部 absent；broker 物化一律 `PAPER_RUNTIME_LAYOUT_INVALID`。
- broker absent → `absent-paper-runtime-root-v2`；broker 物化 → `materialized-paper-runtime-root-v1`（绑定 role、parent_identity、leaf/resolved path、device、inode、mode）。
- broker 内部文件树不参与 runtime 层身份（仅根目录实体）；store tree 由后续 B2E 负责。
- public API / 参数 / `__all__` 未变；零 mkdir/SQLite/network。
- cold capability 在 broker 物化后 `verify_existing_paper_runtime_preflight` 稳定失败；fresh `verify_paper_runtime_environment` 签发不同 layout/verification identity。

## 2. 变更文件（白名单内）

| 路径 | 变更 |
|---|---|
| `src/quant/execution/paper_runtime.py` | `_probe_root_identity`、`_materialized_root_identity`、`_compute_root_identities`；`_build_layout` / `_verify_retained_layout` 两态逻辑 |
| `tests/unit/test_paper_runtime.py` | 8 组必测反例 + 状态转换/替换/link 脱敏 |
| `docs/agent/M4_P8_RUN0B2E_F0_R1_brokerRoot物化RuntimePreflight任务单.md` | 状态更新 |

## 3. 验证证据

### Windows Miniforge (`D:\Miniforge3\python.exe`, `PYTHONPATH=src`)

```
pytest tests/unit/test_paper_runtime.py -q  → 30 passed, 35 skipped
pytest tests/unit/test_paper_policy.py tests/unit/test_paper_broker_binding.py -q  → 40 passed, 1 skipped
ruff check paper_runtime.py test_paper_runtime.py  → All checks passed
mypy src/quant/execution/paper_runtime.py  → Success
cold import  → RUN0A_R2_IMPORT_PASS
```

`test_paper_account.py` 在本 worktree 29 fail（`PAPER_ACCOUNT_POLICY_BINDING_INVALID`，缺 formal 配置 fixture）；与本次 diff 无关，未改 account 模块。

### WSL Miniforge base（兼容记录，非 ext4 Gate 宣称）

```
pytest tests/unit/test_paper_runtime.py -q  → 64 passed, 1 skipped
```

含 cold→materialized 转换、materialized replacement/parent/link 全套 formal mint 路径。

## 4. 必测反例映射

| # | 反例 | 测试 |
|---|---|---|
| 1 | formal/development cold 正向 | `test_formal_cold_layout_*`, `test_development_environment_*` |
| 2 | formal broker 空目录/内部文件 | `test_formal_broker_materialized_*` |
| 3 | development broker 物化拒绝 | `test_development_rejects_materialized_broker_root` |
| 4 | 其他四根/ broker file·link·junction | `test_formal_rejects_non_broker_*`, `test_formal_rejects_invalid_broker_*`, `test_formal_rejects_broker_junction` |
| 5 | cold→materialized 旧 cap 失效 | `test_cold_capability_invalidates_after_broker_materialization` (WSL) |
| 6 | materialized replacement/parent/link | `test_materialized_capability_rejects_*` (WSL) |
| 7 | hostile lstat 脱敏零写 | `test_hostile_root_identity_probe_*` |
| 8 | public surface / cold import | `test_r3_public_api_*`, `test_fresh_import_*` |

## 5. 边界声明

- 未实现 store opener / broker tree 验证（B2E 范围外）。
- 未修改 B2B/B2C/B2D/store/gateway/config。
- Windows 正式 mint 仍 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`（RUN-0A 不变）；layout 两态在 Windows 可读探测层已覆盖。

## 6. 停止条件

未发现任务书合同冲突；未 add/commit/push/联网。
