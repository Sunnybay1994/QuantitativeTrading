# M4 P8 RUN-0B2D R2：public loader closure 唯一签发路径主 Agent 最终验收报告

日期：2026-08-12  
角色：主 Agent 最终契约验收  
结论：**PASS；RUN-0B2D development 工程合同关闭，可进入后续 formal store 前置设计；不宣称正式运行或 ext4 Gate 通过**

## 1. 验收范围

主验核对了 R2 返工任务书、Cursor `auto` 实现交付报告、另一全新 Cursor `auto` 独立复验报告、R1 补充取证报告、生产实现与正式测试。R2 的实现者和独立复验者职责分离成立；主验未启动新的外部 Agent，也未修改生产代码、测试、账户 TOML、runtime/broker roots 或 journal。

R1 唯一阻断是 public loader 的递归 callable closure 可达独立 `_mint -> _token`，使 caller 能在零 B2C、零 hook、零 anchored fresh 的条件下签发 exact capability。R2 必须关闭该捷径，同时保持完整 public load/existing 行为不变。

## 2. 主验契约结论

1. `paper_account.py` 已删除独立 `_mint` 和 generic `_token(payload)` callable。
2. capability 分配、字段写入和 HMAC attestation 只存在于 `_load_impl(environment, policy, binding, now, verified_at)`；该函数先后执行 public input 校验、第一次 B2C、唯一账户配置 anchored read/语义重建、hook、第二次 B2C、anchored file/parent/raw fresh，再签发 capability。
3. `_verify_token(capability)` 只重算并比较既有 capability 的 attestation，不接受任意 payload，也不能独立构造 capability。
4. 从两个 public API 以及 formal class 的 constructor/new/repr/reduce 出发递归枚举 callable closure，仅得到 `load...`、`verify...`、`_load_impl`、`_verify_impl`、`_verify_token` 和 dataclass 方法；没有 `_mint`、`_token` 或 prepared-value signer。
5. existing verifier 先验 exact type/attestation，再通过完整 `_load_impl` fresh 重建并逐字段比较，成功返回传入同一对象；R1 零 B2C closure mint 反例不可复现。
6. SSOT 四值保持为 `formal_paper_a_share_v1`、`FORMAL_PAPER_A_SHARE`、`2026-08-10T00:00:00Z`、`500000.00`；public 四项、稳定错误、零副作用与 process-local 边界未漂移。

残留边界：同进程任意读取非 callable closure cell 并自行复刻 HMAC 不属于本任务冻结的 callable-closure 威胁模型；本报告不把 process-local Python capability表述为抵抗任意内省的安全边界。

## 3. 主验验证证据

Windows Miniforge（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）：

```text
pytest test_paper_account.py + test_paper_broker_binding.py + test_paper_policy.py
77 passed, 2 skipped

ruff: All checks passed
mypy: Success: no issues found in 2 source files
```

WSL Miniforge `base`，同一 DrvFS 工作树：

```text
同组三文件 pytest: 79 passed
ruff: All checks passed
mypy: Success: no issues found in 2 source files
```

主验新增但未落盘的 callable/cold-import 探针：

```text
MAIN_CLOSURE_AND_COLD_IMPORT_PASS
callable names = __init__, __reduce_ex__, __repr__, _load_impl, _verify_impl,
                 _verify_token, load_verified_..., verify_existing_...
HMAC callables = _load_impl(full fresh args), _verify_token(capability only)
qlib/lightgbm/mlflow 未加载
```

R2 白名单文件 `git diff --check` 退出 0。第一次并行 WSL 命令因主验探针自身的过窄断言提前失去摘要；确认相关 WSL 进程自然退出后，单独重跑取得上述明确绿色终态。另一次探针错误地把标准库 `sqlite3/socket` 当作禁止冷导入，按冻结的研究重依赖边界修正后通过；两次无效探针均不计产品失败或通过证据。

## 4. 最终裁决与后续边界

**PASS。** R1 的 callable closure 零 B2C raw mint 阻断已经关闭，R2 满足任务书、独立初验和主验通过条件。RUN-0B2D 的 formal PAPER 账户 genesis development 工程前置完成。

本结论不创建或打开 formal broker store/gateway/service，不授权 PAPER 正式运行，不关闭 WSL2/ext4 平台 Gate，也不解锁 28 日 soak。下一包仍须按既定顺序单独冻结 formal store opener，并继续执行“外部实现 Cursor `auto` → 另一全新 Cursor `auto` 独立初验 → 主 Agent 最终验收”。
