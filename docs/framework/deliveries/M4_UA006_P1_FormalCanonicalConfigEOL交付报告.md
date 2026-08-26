# M4-UA006-P1 Formal Canonical Config EOL 交付报告

日期：2026-08-26<br>
状态：`FORMAL_CONFIG_EOL_WINDOWS_VALIDATED`（P1 formal config EOL Windows VALIDATION1 全绿；**UA-M4-006 仍 OPEN**；不等于主验合流、bootstrap 关闭、PAPER/soak 或 Linux Gate）<br>
task id：`M4-UA006-P1-FORMAL-CONFIG-EOL`<br>
exact base / HEAD：`eca54af513078ca6d000feb544329cba69797948`<br>
branch：`codex/m4-ua006-p1-formal-config-eol`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-p1-formal-config-eol`

## 1. 现象—根因—规则—最小复现—新增测试—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | UA006 bootstrap 越过 project-root 后，在 `load_verified_paper_execution_policy` 前置失败 |
| 根因 | Windows `core.autocrlf=true` 将两个 formal TOML checkout 为 CRLF；loader 要求 decode 文本逐字等于 `_render_canonical`（LF-only、单一 LF 终止）；索引 blob 已是 LF，缺 `.gitattributes` 冻结 |
| 规则 | 不为 CRLF 开第二 canonical；不改 renderer/loader/语义；仅对两精确路径 `text eol=lf`，并把工作树恢复为索引既有 LF bytes |
| 最小复现 | 在 `autocrlf=true` 且无属性时 checkout → 工作树 CR count>0 → public loader `PAPER_*_SOURCE_INVALID` |
| 新增测试 | 两文件各：(1) 真实版本化 source bytes 无 `\r`/无 BOM/恰一尾 `\n`，且 `decode == module._render_canonical(tomllib.loads(...))`；(2) 复制后 CRLF/BOM/额外 `\n` 经公共 loader fail closed（不 monkeypatch compare/renderer/read） |
| 通过条件 | `check-attr text:set eol:lf`；`hash-object --no-filters` = base index blob；STATIC dirty ⊆ exact8；cached=0；`git diff --check` PASS；正式 Windows VALIDATION1 全绿（见 §8） |

## 2. 实现摘要

- `.gitattributes`：仅为 `configs/trading/policies/paper_a_share_v1.toml`、`configs/trading/accounts/formal_paper_a_share_v1.toml` 增加 `text eol=lf`（无 `configs/**` 宽规则）。
- 两配置：自 index blob 写回工作树 LF bytes；字段/顺序/注释/数值未改。
- `tests/unit/test_paper_policy.py` / `test_paper_account.py`：追加上述权威 source/renderer 与 CRLF·BOM·额外换行反例；既有合法 load/verify/selector/identity/语义测保留。

未改：`paper_policy.py`、`paper_account.py`、bootstrap、`__init__.py`、其他 config/test、roadmap、初验报告。本轮 EVIDENCE_UPDATE 仅改任务书与本交付报告。

## 3. Blob / EOL 证据（STATIC 实现现场 + VALIDATION1 复核）

| 路径 | index blob | working `hash-object --no-filters` | CR | LF 终止 |
| --- | --- | --- | --- | --- |
| `configs/trading/policies/paper_a_share_v1.toml` | `2984975e42522bea2b19ba37ec603c414b30d263` | 同左 | 0 | 恰一 `\n` |
| `configs/trading/accounts/formal_paper_a_share_v1.toml` | `83dba597d500697f33fe0addac9b9632394e2b89` | 同左 | 0 | 恰一 `\n` |

`git check-attr text eol`：两路径均为 `text: set`、`eol: lf`。VALIDATION1 scope 再次确认两 config LF-only / 无 BOM / 单末尾 LF / raw 等于原 index blob。

说明：规范化后 `git status` 仍可能将两 config 标为 `M`（stat/EOL 属性刷新），但 content diff 为空且 working raw blob = base index blob；属允许的 exact8 dirty，非语义漂移。

## 4. exact 变更路径

实现者历史写集（1–5、7）及本轮证据更新（6、7）：

1. `.gitattributes`
2. `configs/trading/policies/paper_a_share_v1.toml`（EOL only）
3. `configs/trading/accounts/formal_paper_a_share_v1.toml`（EOL only）
4. `tests/unit/test_paper_policy.py`
5. `tests/unit/test_paper_account.py`
6. `docs/framework/tasks/M4_UA006_P1_FormalCanonicalConfigEOL任务书.md`（本轮 EVIDENCE_UPDATE）
7. `docs/framework/deliveries/M4_UA006_P1_FormalCanonicalConfigEOL交付报告.md`（本文件）

本轮未触碰：`.gitattributes`、configs、tests、review。

## 5. STATIC_ONLY 实现边界与流程偏差

实现交付当时强制 STATIC_ONLY：零 pytest/Ruff/mypy/cold/网络/真实 PAPER/stage/commit。

| 项 | 记录 |
| --- | --- |
| 流程偏差 | 实现阶段一次只读 `python -c` 统计工作树 CR/LF |
| 定性 | 偏离冻结 `STATIC_ONLY`（实现者零 Python） |
| 采信 | **不采信**为验证 / 初验 / Gate 证据；正式证据仅 §8 VALIDATION1 |

## 6. STOP

无。公共 loader 既有 `text != _render_canonical(...)` 路径已覆盖 CRLF/BOM/额外 newline，无需扩围 renderer/loader。

## 7. STATIC 退出核对（实现阶段）

- HEAD = exact base `eca54af513078ca6d000feb544329cba69797948`
- cached=0；`git diff --check` PASS
- dirty 落在 exact8
- 无临时产物 / 凭据 / 为验证拉起的进程（实现退出时）

## 8. 正式 VALIDATION1（全绿）

evidence root：`m4-ua006-p1-validation1-20260826T111408798Z`

| 检查 | 结果 |
| --- | --- |
| Parser / identity | PASS |
| focused（两 test 文件） | `72 passed` / `2 skipped` |
| Ruff（两 tests） | PASS |
| mypy（`paper_policy` + `paper_account`） | PASS |
| cold | PASS |
| exact8 Unicode scope；两 config LF-only / 无 BOM / 单末尾 LF / raw=原 index blob；cached=0 / diff / temp / process | PASS |
| `0xF00` residue | 无 |
| writer | PID `7692` / `0x3` 不变 |

| 产物 | SHA-256 |
| --- | --- |
| focused | `8a96851bfc93077c618bcc05da6924f092bc9e9a513e5723b7a022d5d1d1d399` |
| Ruff | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| mypy | `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2` |
| cold | `a84f078486ef5cab4b1d8b03bacd98b01a13959f9b68cd7fd08b20e0fb850c18` |
| scope | `3013556c2e9029b67c9595431dfae916ef10b17717d7ec8ac015a30e4eb30a4c` |
| summary | `abc96b77dce91fe1c803842d2853010d7e0f5c5818921cce80f36ff91f2d2f1a` |

收口声明：仅 `FORMAL_CONFIG_EOL_WINDOWS_VALIDATED`；**UA-M4-006 仍 OPEN**。

DELIVERY_READY docs/framework/deliveries/M4_UA006_P1_FormalCanonicalConfigEOL交付报告.md
