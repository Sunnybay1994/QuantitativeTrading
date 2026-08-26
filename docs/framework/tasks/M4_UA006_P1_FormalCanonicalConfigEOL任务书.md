# M4-UA006-P1 Formal Canonical Config EOL 任务书

状态：`FORMAL_CONFIG_EOL_WINDOWS_VALIDATED`（仅表示 P1 formal config EOL 的 Windows VALIDATION1 全绿；**UA-M4-006 仍 OPEN**；不表示 bootstrap、PAPER、soak、主验合流或 Linux Gate 完成）<br>
task id：`M4-UA006-P1-FORMAL-CONFIG-EOL`<br>
exact base / HEAD：`eca54af513078ca6d000feb544329cba69797948`<br>
branch：`codex/m4-ua006-p1-formal-config-eol`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-p1-formal-config-eol`

## 1. 现象与根因

UA006 bootstrap VALIDATION3 已越过 project-root 拓扑门禁，但在 `load_verified_paper_execution_policy` 前置停止。Windows checkout 的两个 formal TOML 被 `core.autocrlf=true` 物化为 CRLF，而 `paper_policy.py` 与 `paper_account.py` 均要求解码文本逐字等于唯一 canonical renderer：LF-only，且以单一 LF 终止。索引 blob 已是正确 LF bytes，缺口只在 `.gitattributes` 未冻结这两个安全 SSOT 的 checkout EOL。

本包只闭合 formal canonical config 的跨平台 checkout bytes；不得修改 renderer、loader、配置数值、schema 或接受 CRLF 为第二 canonical 表达。

## 2. 唯一写白名单（exact8）

1. `.gitattributes`
2. `configs/trading/policies/paper_a_share_v1.toml`
3. `configs/trading/accounts/formal_paper_a_share_v1.toml`
4. `tests/unit/test_paper_policy.py`
5. `tests/unit/test_paper_account.py`
6. `docs/framework/tasks/M4_UA006_P1_FormalCanonicalConfigEOL任务书.md`（经理独占）
7. `docs/framework/deliveries/M4_UA006_P1_FormalCanonicalConfigEOL交付报告.md`（实现者独占）
8. `docs/framework/reviews/M4_UA006_P1_FormalCanonicalConfigEOL独立初验报告.md`（独立 reviewer 独占）

实现者只写1–5、7；reviewer只写8；任务书只读。禁止修改 `paper_policy.py`、`paper_account.py`、bootstrap、`__init__.py`、其他config/test、roadmap或共享文档。

## 3. 字节与属性合同

- `.gitattributes` 仅为上述两个精确路径增加 `text eol=lf`，不得用覆盖整个 `configs/**` 的宽泛规则。
- 两个配置的 Git canonical blob 必须保持 base 现有值：
  - policy：`2984975e42522bea2b19ba37ec603c414b30d263`
  - account：`83dba597d500697f33fe0addac9b9632394e2b89`
- 工作树物理 bytes 必须 LF-only（CR count=0），且恰好以单一 LF 终止；不得有 BOM、尾随空白或额外 EOF 空行。
- 配置字段、顺序、数值、注释与语义相对 base 索引 blob逐字不变。规范化只允许把 checkout CRLF 恢复为索引既有 LF bytes。
- `git check-attr text eol` 必须对两路径分别得到 `text: set`、`eol: lf`；`git hash-object --no-filters` 必须与各自索引 blob一致。

## 4. 测试合同与反例

- 两个权威单测分别读取仓库真实版本化 source bytes，并证明其 decode 后逐字等于对应模块既有 `_render_canonical(tomllib.loads(...))`；不得复制 renderer 或手写第二份 expected 文本。
- 锁定 source bytes 中不存在 `\r`、不含 UTF-8 BOM、末尾恰好一个 `\n`。
- 复制 canonical source到 `tmp_path` 后将 LF替换成CRLF；公共 loader必须继续以现有稳定错误 fail closed。测试不得 monkeypatch canonical compare、renderer或 source read。
- 保持既有合法 policy/account load、fresh verify、selector、identity与语义测试不变。
- 新增至少一个独立反例：例如仅改变末尾换行数量或加入BOM，仍由公共 loader拒绝；不得把非canonical输入先normalize再接受。

## 5. 实现、初验与验证边界

外部实现者使用全新 Cursor Grok 4.5 High 会话，STATIC_ONLY 完成属性、工作树LF规范化、定向测试与delivery；零Python/pytest/Ruff/mypy/cold/网络/真实PAPER/stage/commit。delivery记录“现象—根因—规则—最小复现—新增测试—通过条件”，并列出base/index/working blob与CR/LF证据。

另一全新、未参与实现的外部 reviewer 只读1–7并只写8，必须挑战：属性是否过宽、两个config语义blob是否漂移、真实source测试是否绕过renderer、CRLF/BOM/额外newline是否仍fail closed。只有 `REVIEW_PASS` 后才申请Windows验证。

Windows验证建议顺序：identity → 两个focused test文件 → Ruff两个tests → mypy既有production loaders（只作未改回归）→ cold loader imports → exact8 scope/cached/diff/EOL/temp/process。验证与最终integration均不得声称Linux Gate或UA006完成。

## 6. STOP 与退出条件

若实现需要修改renderer/loader、扩大属性范围、改变配置索引blob/语义、或公共loader不能拒绝CRLF/BOM/额外newline，立即STOP举证，不得自行扩围。

STATIC退出要求：actual dirty只在exact8，cached=0，`git diff --check` PASS；两个config working raw blob分别等于上述base blob；无临时产物、凭据或运行进程。P1合流后，当前UA006 bootstrap事故现场才可按中央裁定退休并从latest clean integration重建。

## 7. EVIDENCE_UPDATE（VALIDATION1 / 流程偏差）

本节目的仅为记录正式 Windows VALIDATION1 与实现阶段 STATIC_ONLY 流程偏差；**不**扩大白名单、**不**改合同、**不**关闭 UA-M4-006。

### 7.1 STATIC_ONLY 流程偏差（不采信）

实现阶段曾出现一次只读 `python -c`，用于统计工作树 CR/LF。该调用偏离本包冻结的 `STATIC_ONLY`（实现者零 Python）约束；**不得**采信为验证、初验或 Gate 证据，正式证据以 §7.2 VALIDATION1 为准。

### 7.2 正式 VALIDATION1（全绿）

- 状态收口：`FORMAL_CONFIG_EOL_WINDOWS_VALIDATED`；**UA-M4-006 仍 OPEN**
- evidence root：`m4-ua006-p1-validation1-20260826T111408798Z`
- Parser / identity：PASS
- focused：`72 passed` / `2 skipped`
- Ruff（两 tests）：PASS
- mypy（`paper_policy` + `paper_account`）：PASS
- cold：PASS
- exact8 Unicode scope、两 config LF-only / 无 BOM / 单末尾 LF / raw 等于原 index blob、cached=0 / diff / temp / process：PASS
- 无 `0xF00` residue；writer PID `7692` / `0x3` 不变

| 产物 | SHA-256 |
| --- | --- |
| focused | `8a96851bfc93077c618bcc05da6924f092bc9e9a513e5723b7a022d5d1d1d399` |
| Ruff | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| mypy | `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2` |
| cold | `a84f078486ef5cab4b1d8b03bacd98b01a13959f9b68cd7fd08b20e0fb850c18` |
| scope | `3013556c2e9029b67c9595431dfae916ef10b17717d7ec8ac015a30e4eb30a4c` |
| summary | `abc96b77dce91fe1c803842d2853010d7e0f5c5818921cce80f36ff91f2d2f1a` |
