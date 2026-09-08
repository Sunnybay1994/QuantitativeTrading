# M4 P8 RUN-0B2E-F0 R1：broker root 物化态 Runtime Preflight 独立复验报告

日期：2026-08-12  
角色：未参与 R1 实现的全新外部独立初验 Agent  
模型：Cursor Agent `auto`（不声称具体底层模型）  
工作区：`artifacts/dev_worktrees/m3-g8ab-prereq`  
结论：**PASS（允许进入主 Agent 最终验收；不宣称 ext4 / 正式 Gate）**

## 1. 独立性与范围

- 只读核对：任务书、交付报告、`src/quant/execution/paper_runtime.py`、`tests/unit/test_paper_runtime.py`；未改生产代码、实现者测试、任务书或交付报告。
- 本报告为唯一仓库写入。未 `add`/`commit`/`push`，未联网。
- 实现者自测仅作待核证据；§4 对抗探针与 §5 命令均为本轮独立执行。
- 按用户指示：**本轮不以 Linux/ext4 为前置**；WSL/DrvFS 仅引用交付报告兼容记录，**不宣称 Gate**。

## 2. 契约—证据—结论

| 冻结标准 | 独立证据 | 结论 |
| --- | --- | --- |
| public API / 参数 / 无 `allow_materialized` / 无新 signer | `verify_paper_runtime_environment(*, config, now)` 签名不变；模块无 `__all__` 新增；无 generic mint / `_mint` 入口（`test_r3_public_api_*` + ADV11） | **通过** |
| formal 两态：cold 五根 absent；broker-materialized 仅 broker 真实目录 | `_probe_root_identity` / `_compute_root_identities`；ADV1–ADV2、ADV12；实现者 `test_formal_cold_*` / `test_formal_broker_materialized_*` | **通过** |
| development 五根 absent；broker 物化拒绝 | ADV3；`test_development_rejects_materialized_broker_root` | **通过** |
| 其余四根任一物化拒绝 | ADV4；`test_formal_rejects_non_broker_root_materialization` | **通过** |
| broker file/symlink/junction/reparse 拒绝 | `test_formal_rejects_invalid_broker_*`；ADV_JUNCTION（Windows mklink /J） | **通过** |
| materialized identity canonical（role/parent/path/device/inode/mode） | 源码 `_materialized_root_identity`；ADV2 `bid == _materialized_root_identity(...)` | **通过** |
| broker 内部树不参与 runtime 身份（store 边界） | 仅 `lstat(broker_root)`，无 tree walk；ADV5 深嵌文件/日志后 `layout_identity` 不变且 `_verify_retained_layout` 通过 | **通过** |
| cold→materialized 旧 capability fail-closed；新 identity 不同 | ADV6 `_verify_retained_layout` 在 broker mkdir 后 `PAPER_RUNTIME_PREFLIGHT_INVALID`；ADV12 cold/materialized `layout_identity` 不同 | **通过** |
| materialized 后 same-path 目录替换 / 父替换 / link 拒绝 | ADV7–ADV8；WSL 定向 `test_materialized_capability_rejects_*`（实现者报告 64 passed，本轮 Windows 跳过 mint 全链） | **通过** |
| hostile 异常脱敏；零 mkdir/SQLite/network | ADV10 替换 `_probe_root_identity` → `PAPER_RUNTIME_LAYOUT_INVALID`，无 marker 泄漏、目录集不变；源码无 `mkdir`/sqlite open/socket | **通过** |
| 只读探测；错误 cause/context 为 None | `_assert_sanitized` 覆盖；PaperRuntimeError 路径 `from None` | **通过** |
| cold import 不加载 soak/reporting/backtest | `RUN0A_R2_IMPORT_PASS` | **通过** |
| 白名单 scoped diff | 白名单四路径 `git diff --check` 无 trailing 问题；变更限于任务书列出的生产/测试/报告 | **通过** |

## 3. 独立对抗性反例（实现者 Windows 路径未单独覆盖的补充）

1. **ADV5**：broker 内多层子目录 + sqlite 占位 + journal 文件 → runtime `layout_identity` 与 retained verify 仍有效（诚实 store 边界）。
2. **ADV6–ADV8**：不经过 formal mint，直接对 `_verify_retained_layout` 验证 cold 物化后失效、同路径 inode 替换、parent 替换 fail-closed（Windows 可复现的核心 retained 语义）。
3. **ADV_JUNCTION**：Windows `mklink /J` broker root → `PAPER_RUNTIME_LAYOUT_INVALID`（补充 symlink 不可用时的 reparse 路径）。
4. **ADV10**：hostile `_probe_root_identity` 递归脱敏 + 文件系统零写入（独立于 `test_hostile_root_identity_probe_*` 的探针编排）。
5. **ADV12**：cold 与 broker-materialized 的 `layout_identity` 必异（canonical 两态分离）。

说明：formal **fresh mint** 全链（`verify_paper_runtime_environment` cold→materialized + `verify_existing_paper_runtime_preflight`）在 Windows 仍因 RUN-0A 平台约束跳过（`PAPER_RUNTIME_PLATFORM_UNSUPPORTED`）；retained/layout 层对抗已在 Windows 独立证实；实现者报告 WSL 64 passed 记为 DrvFS 兼容证据，**非 ext4 Gate**。

## 4. 交付报告差异说明

- 交付报告 §3 称 `test_paper_account.py` 29 fail；**本轮 Windows 独立复跑为 37 passed, 1 skipped**（与本次 runtime diff 无冲突，可能为 worktree/fixture 时态差异）。合流 policy/binding/account 均绿。

## 5. Windows 定向验证（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）

```text
pytest tests/unit/test_paper_runtime.py -q
30 passed, 35 skipped

pytest tests/unit/test_paper_policy.py tests/unit/test_paper_broker_binding.py -q
40 passed, 1 skipped

pytest tests/unit/test_paper_account.py -q
37 passed, 1 skipped

ruff check src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

mypy src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file

cold import: RUN0A_R2_IMPORT_PASS

独立对抗探针: 15/15 PASS (含 ADV_JUNCTION)

git diff --check (白名单): clean
```

## 6. 边界声明

- runtime 层只证明 broker **根目录实体**；内部 store tree/descriptor/journal 属后续 B2E，未在本包验证（与任务书 §2 一致）。
- 未修改 B2B/B2C/B2D/store/gateway/config；源码无 root 创建/SQLite 打开/网络调用。
- Windows formal mint 仍 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`（RUN-0A 不变）；两态 layout 可读探测已在 Windows 覆盖。

## 7. 裁决

**PASS** — formal cold 与 broker-materialized 两态 layout 语义、development 拒绝、四根 absent 约束、identity canonical、旧 capability fail-closed、hostile 脱敏与零写、public API 不变均满足任务书；Windows 定向 pytest/Ruff/mypy/cold import/scoped diff-check 通过；独立对抗探针补充实现者 Windows 跳过 mint 路径的 retained 语义验证。

允许进入主 Agent 最终验收。**不宣称** ext4 Gate、正式 runtime capability 签发 Gate 或 B2E store opener 前置已关闭。
