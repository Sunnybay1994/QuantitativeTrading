# M4 P8 RUN-0B2D R2：public loader closure 唯一签发路径返工交付报告

日期：2026-08-12  
状态：R2 实现与自验完成；待全新外部独立初验与主 Agent 终验  
模型：Cursor Agent `auto`  
工作区：`m3-g8ab-prereq`

## 1. 返工摘要

R1 阻断：`load_verified_formal_paper_account_descriptor` closure 图可达独立 `_mint`/`_token`，零 B2C 可签发 exact capability 且 existing verifier 接受。

R2 修复（对齐 RUN-0A R3 / `paper_policy._load_impl` 先例）：

- 删除 nested `_mint` 与 generic `_token` callable；
- capability 分配、字段写入、HMAC attestation 内联于 `_load_impl`，位于两次 B2C、`_before_account_mint_hook`、`_fresh_verify_anchored_account` 之后；
- `_verify_token` 保留为只读比较闭包，内联 HMAC 重算，不提供 caller payload 签名入口。

## 2. 文件范围（白名单）

| 路径 | 动作 |
|---|---|
| `src/quant/execution/paper_account.py` | 内联 mint；删 `_mint`/`_token` |
| `tests/unit/test_paper_account.py` | +3 closure/反例测试 |
| `docs/agent/M4_P8_RUN0B2D_R2_publicLoaderClosure唯一签发路径返工任务单.md` | 状态更新 |
| 本报告 | 新增 |

未改 TOML、R1 历史报告、上游模块、package root。

## 3. 新增测试

- `test_public_loader_closure_has_no_raw_mint_or_token`：自 public loader/existing verifier/formal class constructor·repr·reduce 递归 closure，断言无 `_mint`/`_token` 与 generic payload signer；
- `test_r1_zero_b2c_closure_mint_attack_cannot_be_reproduced`：closure 无 mint/signer；public load 仍 B2C×2 + hook×1；existing 返回同一对象；
- `test_private_helper_assembly_cannot_mint_accepted_capability`：private helper 组装 canonical 字段但不走 load → `PAPER_ACCOUNT_INVALID`。

R1 全部回归保留。

## 4. 验证证据

Windows `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

```text
pytest tests/unit/test_paper_account.py tests/unit/test_paper_broker_binding.py tests/unit/test_paper_policy.py -q
77 passed, 2 skipped

ruff check src/quant/execution/paper_account.py tests/unit/test_paper_account.py
All checks passed!

mypy src/quant/execution/paper_account.py tests/unit/test_paper_account.py
Success: no issues found in 2 source files

cold import: RUN0B2D_R2_COLD_IMPORT_PASS
closure probe: _mint=False _token=False CLOSURE_PROBE_PASS
git diff --check (scoped): clean
```

WSL Miniforge `base`，DrvFS worktree：

```text
PYTHONPATH=src conda run -n base python -m pytest \
  tests/unit/test_paper_account.py tests/unit/test_paper_broker_binding.py \
  tests/unit/test_paper_policy.py -q --basetemp=/tmp/quant-run0b2d-r2-wsl
79 passed
```

## 5. 行为不变

- SSOT 四值（`formal_paper_a_share_v1` / `FORMAL_PAPER_A_SHARE` / `2026-08-10T00:00:00Z` / `500000.00`）；
- public API 四项、七类稳定错误码、零副作用、identity/B2C×2/hook/anchored fresh 顺序不变。

## 6. 风险与后续

- `_verify_token` 仍在 closure 内但仅验证既有 capability，非 generic signer；初验应复跑 R1 §3.2 零 B2C 反例脚本确认不可复现；
- DrvFS 仅为兼容证据，不关闭 ext4 Gate；
- 待全新外部 `auto` 独立初验 PASS 后主 Agent 终验。
