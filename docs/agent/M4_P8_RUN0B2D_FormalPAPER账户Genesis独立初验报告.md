# M4 P8 RUN-0B2D：Formal PAPER 账户 Genesis 独立初验报告

日期：2026-08-12  
角色：外部独立初验 Agent（未参与实现）  
模型：Cursor Agent `auto`  
工作区：`m3-g8ab-prereq`  
结论：**PASS（仅解锁主 Agent 终验；不等同 Gate 关闭）**

## 1. 初验范围与依据

已只读核对：

- 根 `AGENTS.md`、`.ai/README.md`
- `docs/agent/M4_P8_RUN0B2D_FormalPAPER账户Genesis任务单.md`
- `docs/agent/M4_P8_RUN0B2D_FormalPAPER账户Genesis交付报告.md`
- RUN-0A/B2B/B2C/B1 公共契约：`paper_runtime.py`、`paper_policy.py`、`paper_broker_binding.py`、`paper_broker_store.py`（`build_paper_account_descriptor`）
- 实现：`src/quant/execution/paper_account.py`
- 配置：`configs/trading/accounts/formal_paper_a_share_v1.toml`、`development_account_v1.toml`
- 实现者测试：`tests/unit/test_paper_account.py`

未改生产代码、实现者测试、任务书、交付报告；未 add/commit/push/联网。

## 2. 合同逐项映射

| 合同项 | 证据 | 初验判定 |
|---|---|---|
| 四项 SSOT 批准值 | TOML 与 `paper_account.py` 常量均为 `formal_paper_a_share_v1` / `FORMAL_PAPER_A_SHARE` / `2026-08-10T00:00:00Z` / `500000.00` | PASS |
| 唯一 formal config 路径 | 仅 `project_root/configs/trading/accounts/{selector}.toml` 派生；无 caller path/hash | PASS |
| `__all__` exact 四项 | `test_public_surface_is_exact_and_has_no_generic_mint_or_key` + 初验 `from *` 探针 | PASS |
| load 顺序：UTC→B2C×2→selector→anchored read→canonical→snapshot→B1→mint | 代码 `_load_impl`；初验 B2C 调用计数=2 | PASS |
| existing 返回同一 capability | `test_exact_fresh_load_and_existing_contract` `is first` | PASS |
| stable `account_id` 跨平台语义相同 | Win/WSL 同值 `d4f95b2e…aaacb`；与 `snapshot_id` `ec654f48…576b` 分离 | PASS |
| physical source identity 不进 stable account_id | `source_file_identity != account_id` 测试 + 身份字段分离 | PASS |
| `risk_counter_scope = "paper-" + account_id` 且满足 service `_SCOPE` | 实现 `_SCOPE_RE` 与 `service.py` 同 regex；scope 长度合法 | PASS |
| 七类稳定错误码 + active except 外重建 | 全测试 `_assert_error`；hostile 探针 `__cause__`/`__context__` 为 None | PASS |
| 零 mkdir/SQLite/socket/log/墙钟 | `test_account_has_zero_io_db_log_socket_or_wall_clock`；初验 `os.mkdir` 探针 | PASS |
| 只读唯一 TOML；无正式 root/journal | 测试 absent-root 未创建；实现无 write/cache/log | PASS |
| 不可 pickle/reload 旧 token | pickle/reload/importlib.reload 测试；`copy.copy` 初验抛 TypeError | PASS |
| subclass/duck/dict/object.__new__ 拒绝 | 对应 parametrized/单测 | PASS |
| development/example selector 拒绝 | selector 参数化 + `development_account_v1.toml` 存在但不走 formal 路径 | PASS |
| 同 bytes inode 替换 → STALE | `test_same_bytes_inode_replacement_stales_existing` | PASS |
| persistent drift / rehash / 非 canonical bytes | 语义与 source 参数化测试 | PASS |
| B2C 环境/策略递归重验与码映射 | `_fresh_binding` 映射 `PAPER_BROKER_BINDING_*`→account 码 | PASS |
| 白名单外未改 runtime/policy/binding/B1/service/CLI | `git status` 仅 `??` 白名单三路径；`execution/__init__.py` 无 `paper_account` | PASS |

## 3. 实现者未覆盖、初验补做的对抗反例

| 反例 | 方法 | 结果 |
|---|---|---|
| B2C 每 load 调用 2 次（mint 前再验） | 计数 monkeypatch | 2 次，PASS |
| B2C 返回 value-equal 但非同一对象的 `replace(binding)` | 探针 | **接受**（合同用 `fresh != binding` 值语义；真 B2C 返回 `binding` 本体） |
| B2C 返回 unequal clone | `replace(..., binding_identity=…)` | `PAPER_ACCOUNT_POLICY_BINDING_INVALID`，PASS |
| 第二次 B2C hostile 递归异常 | 第二次调用抛 TOKEN/SQLite marker 图 | 固定码、无 marker、无 cause/context，PASS |
| parent 目录 inode 替换（同 bytes） | WSL `accounts` 目录 rename/replace 后 existing | `PAPER_ACCOUNT_STALE`，PASS |
| copied project_root（同 canonical TOML） | 另一 checkout existing | `PAPER_ACCOUNT_STALE`，PASS |
| 非空 `positions` | TOML 注入 position 行 | `PAPER_ACCOUNT_SEMANTICS_INVALID`，PASS |
| `copy.copy(capability)` slot 克隆 | 初验探针 | TypeError process-local，PASS |
| `os.mkdir` 禁止 | load+existing 全程 | 未触发，PASS |
| 跨 Win/WSL stable ID | 同 canonical genesis 双平台 load | `account_id`/`snapshot_id` 完全一致，PASS |

实现者已覆盖但初验复跑确认：hardlink/symlink（WSL 全绿；Win skip 2）、reload 失效、零 IO monkeypatch、from-star exact4、cold import 不加载 soak/Qlib/MLflow。

## 4. 验证命令与结果（独立执行）

### Windows 原生 Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`）

```text
pytest tests/unit/test_paper_account.py tests/unit/test_paper_broker_binding.py tests/unit/test_paper_policy.py -q
→ 74 passed, 2 skipped (hardlink/symlink)

ruff check src/quant/execution/paper_account.py tests/unit/test_paper_account.py
→ All checks passed!

mypy src/quant/execution/paper_account.py tests/unit/test_paper_account.py
→ Success: no issues found in 2 source files

cold import subprocess → RUN0B2D_COLD_IMPORT_PASS
from-star exact4 → FROM_STAR_EXACT4_PASS
```

### WSL Miniforge `base`（DrvFS worktree，兼容探针非 ext4 Gate）

```text
PYTHONPATH=src conda run -n base python -m pytest \
  tests/unit/test_paper_account.py tests/unit/test_paper_broker_binding.py \
  tests/unit/test_paper_policy.py -q --basetemp=/tmp/quant-run0b2d-review
→ 76 passed

ruff + mypy（同上路径）→ 全绿
```

## 5. 观察项（非阻断）

1. **B2C 值相等即通过**：`_fresh_binding` 使用 `fresh != binding` 而非 `fresh is not binding`；value-equal 克隆在恶意 verifier 下可通过，但真 B2C 返回原对象；建议主验记入 SSOT 为值语义而非身份语义。
2. **单测大量 mock B2C**：合流行为依赖 B2C 真实现；本包映射与调用次序已独立探针确认。
3. **parent 目录替换**：实现者未单测；初验 WSL 探针 PASS；Windows 目录原子替换受 OS 限制未探针，但文件 inode 替换已测。
4. **间接 `sqlite3`**：经 B1 `build_paper_account_descriptor` 导入；cold import 不阻止；与交付报告一致，不构成本包阻断。
5. **主验仍需**：WSL base 全量回归、文档一致性、ext4 平台 Gate（若路线图要求）。

## 6. 阻断项

无。未发现需返工的现象—根因—规则违反。

## 7. 初验裁决

**PASS** — 冻结合同、SSOT、公共面、失败语义、身份闭包与对抗边界均满足；实现者交付可信，可进入主 Agent 终验。初验通过不等于 RUN-0B2D Gate 关闭。
