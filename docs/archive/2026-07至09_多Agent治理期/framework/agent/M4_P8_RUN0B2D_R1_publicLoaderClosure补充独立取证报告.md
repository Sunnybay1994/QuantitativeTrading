# M4 P8 RUN-0B2D R1：public loader closure 补充独立取证报告

日期：2026-08-12  
角色：全新外部窄故障取证 Agent（未参与实现或上一轮初验）  
模型：Cursor Agent `auto`  
工作区：`m3-g8ab-prereq`  
结论：**P1 / FAIL（closure 可达 raw `_mint`；初验“public 无 mint/key”表述不成立）**

## 1. 范围与只读依据

已只读核对：根 `AGENTS.md`、`M4_P8_RUN0B2D_FormalPAPER账户Genesis任务单.md`、
`M4_P8_RUN0B2D_FormalPAPER账户Genesis交付报告.md`、
`M4_P8_RUN0B2D_FormalPAPER账户Genesis独立初验报告.md`、
`src/quant/execution/paper_account.py`、`tests/unit/test_paper_account.py`，以及 RUN-0A R2/R3 历史（
`M4_P8_RUN0A_平台路径与Runtime身份任务单.md` §14、
`M4_P8_RUN0A_R3_formal环境唯一签发路径独立复验报告.md`）。  
未改生产/测试；未 add/commit/push/联网。本报告为唯一写入。

说明：仓库无名为 `G7D-F0 R2/R3` 的 closure 报告；同类先例为 **RUN-0A R2 FAIL → R3 返工**（删除模块级 generic signer，runtime 将 mint 内联于唯一 public 路径，callable 图不暴露独立 `_mint`）。

## 2. 取证方法（不落盘 / 临时目录）

1. 自 `load_verified_formal_paper_account_descriptor.__closure__` 递归枚举 nested function。
2. **不调用** public `load_verified_formal_paper_account_descriptor` 与 `_fresh_binding`（B2C）。
3. 在 `tempfile.mkdtemp` 写入 canonical `formal_paper_a_share_v1.toml`；用测试同款 mock
   `VerifiedPaperRuntimeEnvironment` / `VerifiedPaperExecutionPolicy` /
   `VerifiedFormalPaperBrokerPolicyBinding`。
4. 经模块私有 helper（`_require_formal_selector`、`_open_anchored_account`、`_parse_account`、
   `_build_snapshot`、`build_account_snapshot_identity`、`build_paper_account_descriptor`）组装
   `_mint` 所需参数。
5. 直接调用 closure 内 `_mint`；再调用 public `verify_existing_formal_paper_account_descriptor`
   （B2C 仅在 verifier 内部 `_load_impl` 路径触发，mint 路径零次 B2C）。

环境：`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`。

## 3. 独立证据

### 3.1 Callable closure 图（account vs 先例 runtime）

| 模块 | public 入口 | 图内 `_mint` | 图内 `_token` |
|---|---|---|---|
| `paper_runtime` | `verify_paper_runtime_environment` | **否** | **否**（mint 内联） |
| `paper_policy` | `load_verified_paper_execution_policy` | **否** | 是（mint 内联于 `_load_impl`） |
| `paper_broker_binding` | `bind_verified_formal_paper_broker_policy` | 是 | 是 |
| **`paper_account`** | **`load_verified_formal_paper_account_descriptor`** | **是** | **是** |

account 图（自 public loader 递归）：

```text
load_verified_formal_paper_account_descriptor
  └─ _load_impl
       └─ _mint(environment, policy, binding, anchored, parsed, account_descriptor, selector, verified_at)
            ├─ _token(payload)
            └─ _verify_token(capability)
```

与主 Agent 描述一致；初验仅检查 `__all__` / `from *` / `vars(account)` 无 32-byte 模块值 /
`hasattr(_create_account_api)`，**未覆盖 closure 可达性**。

### 3.2 Closure mint + existing verifier（核心反例）

| 步骤 | 结果 |
|---|---|
| closure `_mint`（0 次 B2C） | `VerifiedFormalPaperAccountDescriptor`，`account_id=d4f95b2e…aaacb` |
| `_verify_token(forged)` | `True` |
| public existing verifier | **`ACCEPTS`，`result is forged`** |
| 对照 public load（B2C mock 为 identity） | 同 `account_id`；`forged == legit` 但 `forged is not legit` |
| load 路径 B2C 调用次数 | **2** |
| closure mint 路径 B2C 调用次数 | **0** |
| `_before_account_mint_hook` | load 调用 1 次；closure mint **0 次** |

### 3.3 Raw signer 能力（binding 字段可任意嵌入）

对 `binding_identity='f'*64` 的 unequal binding 直接 closure `_mint`：

- `_verify_token(forged_bad)` → **True**（attestation 对嵌入字段自洽）
- public existing verifier（caller 仍传 canonical binding）→ **`PAPER_ACCOUNT_STALE`**

说明 `_mint` 是独立 raw signer，不限于 canonical B2C 输出；仅 existing 的全量 `_load_impl` 重建能阻断错误嵌入。

## 4. 威胁模型裁定

**落在冻结合同内，不是“任意外部攻击者无 import 权限”场景，但超出初验所声称的 public 边界：**

| 边界 | 裁定 |
|---|---|
| 任务单 §4 load 顺序（UTC → **B2C×2** → … → mint） | **违反**：closure mint 跳过全部 B2C 与 mint 前 hook/二次 anchored fresh |
| 任务单 §6.8 / 初验“无 mint/key” | **违反**：模块表面无 mint，但 **public loader closure 图暴露 `_mint`/`_token`** |
| RUN-0A R3 §14.2.5“不宣称抵抗 Python 内省” | 不豁免 **工程 load-order 不变量**；R3 先例要求 callable 图无独立 raw mint（runtime 内联） |
| existing verifier 全量重建 | 对 **canonical 输入** 仍接受 closure-mint 对象 → mint 路径与 load 路径不等价 |
| 持整库离线写权限者 | 不在本包 scope；本反例为 **同进程 import + inspect** |

**结论：攻击未超出“同进程可 import `quant.execution`”的取证假设，但明确落在 B2D 冻结 load-order / 唯一签发路径合同内，应判 P1/FAIL。**

## 5. 初验缺口

`M4_P8_RUN0B2D_FormalPAPER账户Genesis独立初验报告.md` §2 将 `__all__` + `test_public_surface_is_exact_and_has_no_generic_mint_or_key` 标 PASS；
该测试 **不遍历 `__closure__`**，故 **“public 无 mint/key”对 closure 可达性为假阴性**。

## 6. 最小返工（对齐 RUN-0A R3 / policy 先例）

1. **删除独立 nested `_mint` callable**；HMAC/key 仅服务于唯一 public load 路径，mint 逻辑内联于 `_load_impl`（与 `paper_runtime.verify_paper_runtime_environment`、`paper_policy._load_impl` 同型）。
2. 自 public loader 递归 callable 图：**除完整 public loader / existing verifier 外，不得出现可签任意 payload 的 `_mint` 或 `_token`**；verifier-only 比较函数可保留但不可单独构造 attestation。
3. **新增正式测试**（示例名）：`test_public_loader_closure_has_no_raw_mint_or_token`  
   - 自四项 public API 递归 `__closure__`；断言无名为 `_mint`/`_token` 的 nested function。  
   - 补回归：R2 式路径（private helper 组装输入 + 任意 attestation / 非 load 顺序）不能得到被 existing 接受的 capability，除非走 public load。
4. **通过条件**：上述测试绿；closure 图探针与 §3.2 反例不可复现；load 顺序（B2C×2、hook、anchored fresh）不可 bypass。

## 7. 裁决

**P1 / FAIL** — closure 可达 raw `_mint` 可在零 B2C 下签发 process-local exact capability，且 public existing verifier 对 canonical 输入 **接受同一对象**；违反任务单 load-order 与 RUN-0A R3 callable 图先例。解锁：实现 Agent 按 §6 返工 → 全新外部初验 → 主 Agent 终验。
