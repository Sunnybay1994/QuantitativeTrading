# M4 P8 RUN-0B2D R2：public loader closure 唯一签发路径独立复验报告

日期：2026-08-12  
角色：未参与 R2 实现的全新外部独立初验 Agent  
模型：Cursor Agent `auto`（不声称具体底层模型）  
工作区：`artifacts/dev_worktrees/m3-g8ab-prereq`  
结论：**PASS（关闭 R1 closure `_mint` 零 B2C 签发阻断；允许进入主 Agent 最终验收；不宣称正式 Gate / ext4 Gate）**

## 1. 独立性、范围与证据边界

- 复验前完整阅读根 `AGENTS.md`、`.ai/README.md` 及直接相关规则（`coding_rules.md`、`workflows/multi_agent_delivery.md`、`review_checklist.md`），并只读核对：
  - `M4_P8_RUN0B2D_R2_publicLoaderClosure唯一签发路径返工任务单.md`
  - `M4_P8_RUN0B2D_R2_publicLoaderClosure唯一签发路径返工交付报告.md`
  - `M4_P8_RUN0B2D_R1_publicLoaderClosure补充独立取证报告.md`
  - `src/quant/execution/paper_account.py`
  - `tests/unit/test_paper_account.py`
- 生产代码、实现者测试、配置、任务书与既有报告全部只读；本报告为唯一仓库写入。未 `git add`/`commit`/`push`，未联网，未读取或输出凭据，未触碰正式账户 / runtime / broker roots。
- 实现者自测仅作待核证据；下列 closure 图、R1 重放、对抗探针与双平台命令均为本轮独立执行。
- WSL 实际文件系统为 **DrvFS**（`findmnt`：`FSTYPE=drvfs SOURCE=F:\`），只记为兼容证据，**不宣称 ext4 Gate**。

## 2. 标准—独立证据—结论

| R2 标准 | 独立证据 | 结论 |
| --- | --- | --- |
| public loader / existing verifier / formal class constructor·new·reduce·repr（及 property getter）递归 callable closure 无 raw `_mint` / generic `_token` / prepared-facts mint | 自两 public API、`VerifiedFormalPaperAccountDescriptor.__init__` / `__new__` / `__repr__` / `__reduce_ex__` 递归 `__closure__`；闭包函数名集合为 `{load…, verify…, _load_impl, _verify_impl, _verify_token}`（另含无闭包的 dataclass 方法名）。**无 `_mint`、无 `_token`**；无 `(payload)->bytes` generic signer；无接受 `{environment,policy,binding,anchored,parsed}` 子集的独立 mint callable | **通过** |
| 精确重放 R1 §3.2：零 B2C 取 closure `_mint` 签发 exact capability 且 existing 接受 | closure 图 `mint_fns=0`；R1 路径不可定位 `_mint`。对照 public load：B2C×2 + hook×1 后成功；existing 返回**同一对象** | **通过（R1 阻断关闭）** |
| constructor / `object.__new__` / slots clone / `replace` / subclass / duck / dict / pickle / reload / 字段·identity·provenance·attestation 漂移；fail closed；cause/context 空；无路径/金额/hostile 泄漏 | 独立探针：`object.__new__`、subclass 全字段复制、`replace(account_id/verification_identity/broker_binding_identity/raw_sha256)`、`{}`/`object()`、错误 attestation 类型 → 均 `PAPER_ACCOUNT_INVALID`，`__cause__`/`__context__` 均为 `None`，repr 无 path/金额/hostile marker；`pickle.dumps` / `__reduce_ex__` → `TypeError`；`importlib.reload` 后旧 capability → `PAPER_ACCOUNT_INVALID`。同型同值 slots twin（已持合法 attestation）可被 existing 接受，不构成绕过 load-order 的 raw mint | **通过** |
| 正常 load 顺序：B2C fresh → 唯一配置 no-follow anchored 稳定读/语义重建 → 第二次 B2C fresh → 最后签发；existing 重建并返回原对象；零额外写入 | 源码 `_load_impl`：`_fresh_binding` → `_open_anchored_account`/`_parse_account`/descriptor 重建 → `_before_account_mint_hook` → `_fresh_binding` → `_fresh_verify_anchored_account` → 内联构造 + HMAC。事件探针顺序 `['b2c','hook','b2c','anchored_fresh']`；HMAC 仅在此后。existing：`rebuilt == capability` 后返回原 `capability`。`absent-runtime`/`absent-broker` 未创建 | **通过** |
| Windows + WSL base focused pytest / Ruff / mypy / cold import / scoped diff-check | 见 §5；WSL 为 DrvFS 兼容证据 | **通过** |

## 3. R1 阻断关闭复核

R1 依赖 `load_verified_formal_paper_account_descriptor → _load_impl → _mint → _token/_verify_token`。R2 后：

1. 独立 nested `_mint` 与 generic `_token` 已删除；
2. capability 分配、字段写入、attestation 计算内联于 `_load_impl`，位于两次 B2C、hook 与 anchored fresh 之后；
3. `_verify_token` 仅对既有 capability 重算 HMAC 并 `compare_digest`，签名参数为 capability 对象而非任意 caller payload；
4. 从 public callable 图无法再取得可直接调用的 raw mint/signer。

因此 R1 §3.2「closure `_mint` 零 B2C 签发 + existing 接受」**不可复现**。

**残留边界（不升格为 FAIL）**：`_verify_token` / `_load_impl` 闭包 cell 仍持有 process-local 32-byte key；同进程 `inspect` 可读 cell 并手工 `hmac.new` 组装 attestation。按 RUN-0A R3 / 本任务书允许 verifier-only 闭包的工程边界，**不声称抵抗任意 Python 内省**；该路径不是 R1 的 callable `_mint` 捷径，也不在 public callable 图中提供 generic `_token(payload)`。

## 4. 独立对抗性反例（实现者未单独作为初验焦点的补充）

1. **R1 精确重放**：搜索 allocation/signing/attestation/registry 入口；仅命中 `_verify_token`（比较器）与完整 `_load_impl`（含 B2C）；无零 B2C mint callable。
2. **私有 helper 组装**：`_open_anchored_account` / `_parse_account` / `_identity_payload` + 伪造 attestation → existing `PAPER_ACCOUNT_INVALID`（与正式测试一致，独立复跑）。
3. **identity/provenance 漂移**：`verification_identity` / `broker_binding_identity` / `raw_sha256` replace 均 fail closed 且无泄漏。
4. **module reload**：旧 process-local capability 在 reload 后被拒绝。
5. **I/O 边界**：正式 load/existing 未创建 `absent-runtime` / `absent-broker`。

## 5. 双平台定向验证

### 5.1 Windows Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）

```text
pytest tests/unit/test_paper_account.py tests/unit/test_paper_broker_binding.py tests/unit/test_paper_policy.py -q
77 passed, 2 skipped

ruff check src/quant/execution/paper_account.py tests/unit/test_paper_account.py
All checks passed!

mypy src/quant/execution/paper_account.py tests/unit/test_paper_account.py
Success: no issues found in 2 source files

cold import / from-star: RUN0B2D_R2_COLD_IMPORT_PASS
closure probe: _mint=False _token=False
git diff --check -- src/quant/execution/paper_account.py tests/unit/test_paper_account.py
DIFF_CHECK_CLEAN
```

### 5.2 WSL Miniforge `base`（实际 DrvFS worktree，非 ext4）

```text
FSTYPE=drvfs SOURCE=F:\

PYTHONPATH=src conda run -n base python -m pytest \
  tests/unit/test_paper_account.py tests/unit/test_paper_broker_binding.py \
  tests/unit/test_paper_policy.py -q --basetemp=/tmp/quant-run0b2d-r2-reverify
79 passed

ruff / mypy: All checks passed! / Success: no issues found in 2 source files
cold import: RUN0B2D_R2_COLD_IMPORT_PASS_WSL
closure probe: has_mint False has_token False CLOSURE_PROBE_PASS
```

说明：WSL 侧 `git diff --check` 因 worktree `gitdir` 指向 Windows 风格路径而失败（`fatal: not a git repository: .../F:/AI_Coding/...`）；**scoped diff-check 以 Windows 侧 clean 为准**。DrvFS 结果仅为兼容证据，**不得表述为 WSL2/ext4 Gate 已关闭**。

## 6. 裁决

**PASS** — R1 public callable closure 可达 raw `_mint` 的零 B2C 签发阻断已关闭；递归 callable 图无 generic token/signer 与 prepared-facts mint 捷径；对抗性 fail-closed、load 顺序与双平台定向检查满足 R2 任务书通过条件。

允许进入主 Agent 最终验收。本报告**不宣称**正式 Gate、正式账户启用或 ext4 平台终验通过。
