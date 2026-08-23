# M4 P8 RUN-0B2D R2：public loader closure 唯一签发路径返工任务单

日期：2026-08-12  
状态：**R2 外部实现、全新外部独立初验与主 Agent 最终验收均已 PASS；RUN-0B2D 工程合同关闭**  
前置：R1 的 P1/FAIL 已由 R2 唯一签发路径返工关闭；不等于正式运行或 ext4 Gate 通过

## 1. 唯一阻断

R1 的 public `load_verified_formal_paper_account_descriptor` 递归 callable closure 图可达
`_load_impl -> _mint -> _token/_verify_token`。caller 可通过 `inspect` 取得 `_mint`，在零次 B2C fresh、零
`_before_account_mint_hook`、零 mint 前 anchored fresh 的情况下，用 ordinary/private value helpers 组装 canonical
输入并签发 exact `VerifiedFormalPaperAccountDescriptor`；public existing verifier 对 canonical 输入返回该同一对象。

这违反 R1 任务冻结的 load 顺序与本项目 RUN-0A R3 的唯一签发路径规则。模块 `__all__`、`vars(module)` 无 signer
不等于 public callable closure 不可达 signer。

权威复现与完整证据：
`M4_P8_RUN0B2D_R1_publicLoaderClosure补充独立取证报告.md`。

## 2. 最小生产返工

仅修改 `src/quant/execution/paper_account.py`：

1. 删除独立 nested `_mint(...)` callable。
2. capability 分配、全部字段写入、attestation 计算与返回必须内联到唯一完成全部 fresh 检查的 load 路径；
   raw allocation/signing 之前必须已经完成两次 B2C、hook 与 anchored file/parent/raw fresh。
3. public loader、existing verifier、formal class constructor/new/reduce/repr 及其传递 callable closure 图中，不得存在
   接受 prepared account/environment/policy/binding/anchored/descriptor/payload 后可独立签发 capability 的 callable。
4. verifier 可保留只验证既有 attestation 的闭包，但不得提供可被 caller 用任意 payload 计算新 attestation 的
   generic signer。若 `_token(payload)` 仍能由 public callable 图传递取得并为 caller 自构 capability 签名，也必须内联/消除。
5. 保持 R1 public API、七类稳定错误、SSOT 四值、identity、两次 B2C、零副作用和所有现有行为不变。

不得以重命名 `_mint`、把 signer 放进对象属性、仅过滤函数名、仅删除 `__all__` 或仅修改测试规避反例。

## 3. 正式测试返工

仅修改 `tests/unit/test_paper_account.py`：

1. 从两个 public 函数以及 formal class 的 constructor/new/reduce/repr 出发，递归枚举所有 callable closure cells；
   断言没有独立 raw mint/signer，也没有可用 caller payload 生成有效 attestation 的 callable。
2. 固化 R1 反例：private helpers/ordinary constructors 可组装相同 account values，但不走 public load 时不能得到会被
   public existing verifier 接受的 exact capability。
3. 对照 public load 仍须两次 B2C、一次 hook、fresh anchored source 后成功；existing 成功返回传入同一对象。
4. 现有 constructor/object.__new__/clone/reload、same-bytes inode replacement、hostile exception、零 I/O、SSOT、
   stable identity、from-star/cold import 回归全部保留。

## 4. 白名单与禁止项

允许修改：

- `src/quant/execution/paper_account.py`
- `tests/unit/test_paper_account.py`
- 本任务状态
- 唯一 `docs/framework/agent/M4_P8_RUN0B2D_R2_publicLoaderClosure唯一签发路径返工交付报告.md`

禁止修改 account TOML、R1任务/交付/初验/取证报告、runtime/policy/binding/store/gateway/service/CLI/soak、
package `__init__.py`、其他测试、正式 roots/journal。不得 add/commit/push/联网。

## 5. 验证与通过条件

Windows 与 WSL base/DrvFS 均执行：

- `test_paper_account.py` + binding + policy focused pytest；
- 定向 Ruff、mypy、cold import/from-star；
- callable closure 图探针；
- scoped `git diff --check`。

通过条件：R1 §3.2 的 closure `_mint` 零 B2C 签发反例不可复现；递归 callable 图只允许完整 public fresh 路径创建
capability；所有 R1 行为与定向回归保持绿色。DrvFS 仍仅是兼容证据，不关闭 ext4 Gate。

实现后必须由未参与 R2 实现的全新外部 Cursor `auto` 会话独立复验；初验 PASS 后才进入主 Agent 主验。
