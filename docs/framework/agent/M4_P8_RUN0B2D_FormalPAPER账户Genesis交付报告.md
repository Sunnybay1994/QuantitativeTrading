# M4 P8 RUN-0B2D：Formal PAPER 账户 Genesis 交付报告

日期：2026-08-12  
状态：实现与自验完成；待独立初验与主 Agent 终验  
模型：Cursor Agent `auto`

## 1. 交付结果

按冻结任务书与用户 2026-08-12 批准的四项 SSOT 新增只读 formal A 股 PAPER account genesis loader：

| SSOT 字段 | 批准值 |
|---|---|
| account selector | `formal_paper_a_share_v1` |
| non-secret label | `FORMAL_PAPER_A_SHARE` |
| genesis aware UTC | `2026-08-10T00:00:00Z` |
| initial settled/available CNY | `500000.00` |

实现要点：

- 只接受 fresh exact `VerifiedPaperRuntimeEnvironment`、`VerifiedPaperExecutionPolicy`、
  `VerifiedFormalPaperBrokerPolicyBinding`；load 顺序为 UTC 校验 → B2C existing verifier（两次，mint 前再验）
  → selector 精确匹配 → no-follow anchored 只读唯一 TOML → strict canonical keys/两位小数 →
  `AccountSnapshot` → B1 `PaperAccountDescriptor` → process-local HMAC mint；
- 路径仅从 `project_root` + `environment.config.account_selector` 派生；caller 不得传 path/hash/ID；
- `risk_counter_scope = "paper-" + account_id`，满足 service `_SCOPE` 长度约束；
- stable `account_id` 与 daily `snapshot_id` 分离；physical source identity 与 stable account identity 分离；
- `__all__` exact 四项；七类稳定脱敏错误码；零 mkdir/SQLite/socket/log/墙钟/正式 root 副作用。

## 2. 文件范围（白名单）

| 路径 | 动作 |
|---|---|
| `src/quant/execution/paper_account.py` | 新增 |
| `configs/trading/accounts/formal_paper_a_share_v1.toml` | 新增 |
| `configs/trading/accounts/development_account_v1.toml` | 新增（formal selector 拒绝示例） |
| `tests/unit/test_paper_account.py` | 新增 |
| `docs/framework/agent/M4_P8_RUN0B2D_FormalPAPER账户Genesis任务单.md` | 状态更新 |
| `docs/framework/agent/M4_P8_RUN0B2D_FormalPAPER账户Genesis交付报告.md` | 本报告 |

未修改 `__init__.py`、runtime/policy/binding/B1 store/gateway/service/CLI/soak 或正式 roots/journal。

## 3. 对抗覆盖

- development/example/unknown selector；cross environment/config/binding/session 漂移；
- 同 bytes inode replacement、parent/file drift、symlink/hardlink、persistent drift hook；
- whole-file rehash、未知/重复 key、非 canonical bytes、caller 64hex/ID 参数；
- 非 CNY、0/负/非 2dp、available≠settled、非零 receivable/payable；
- stable account_id vs snapshot_id；subclass/duck/dict/object-new/pickle/reload token；
- hostile B2C verifier 递归异常图脱敏；monkeypatch open/socket/sqlite/log/time 零副作用；
- from-star exact 四项、无 generic mint/key；cold import 不加载 soak/Qlib/LightGBM/MLflow。

## 4. 验证证据

Windows 原生 Miniforge，`PYTHONPATH=src`：

```text
pytest tests/unit/test_paper_account.py \
  tests/unit/test_paper_broker_binding.py tests/unit/test_paper_policy.py -q
74 passed, 2 skipped in 11.84s

ruff check src/quant/execution/paper_account.py tests/unit/test_paper_account.py
All checks passed!

mypy src/quant/execution/paper_account.py tests/unit/test_paper_account.py
Success: no issues found in 2 source files

cold import from-star exact __all__: RUN0B2D_COLD_IMPORT_PASS
```

Windows skips：hardlink（1）、symlink（1，权限）。

WSL Miniforge `base`，DrvFS worktree：

```text
PYTHONPATH=src conda run -n base python -m pytest \
  tests/unit/test_paper_account.py tests/unit/test_paper_broker_binding.py \
  tests/unit/test_paper_policy.py -q --basetemp=/tmp/quant-run0b2d-impl-wsl
76 passed in 10.31s
```

WSL 全绿；DrvFS 仅作兼容，不是 ext4 Gate。

## 5. 剩余风险

- 未做 actual WSL2/ext4 formal runtime 合流；B2D 只读 genesis，不关闭平台 Gate。
- `paper_account` 经 B1 `build_paper_account_descriptor` 间接 import `sqlite3`；cold import 不阻止该 B1 依赖。
- nested `account_descriptor` 替换由 rebuild exact compare 以 `PAPER_ACCOUNT_STALE` 拒绝（与 B2B policy 同类字段一致）。
- 独立初验须补实现者未使用的对抗反例；主验须 WSL base 全量回归与文档一致性核对。
