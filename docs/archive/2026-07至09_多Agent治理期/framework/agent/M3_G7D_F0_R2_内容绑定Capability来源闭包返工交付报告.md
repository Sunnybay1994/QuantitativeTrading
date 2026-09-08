# M3 G7D-F0 R2：内容绑定 Capability 来源闭包返工交付报告

日期：2026-08-09  
角色：返工实现 Agent  
状态：**R2 返工与双平台自测完成，待独立复验；不宣称 G7/M3/Linux ext4 Gate 通过**

## 1. R1 问题与 R2 最小修复

R1 的八表、`E/S/D` 窗口、root/file stable read、FULL_DAY 与 ledger/reconciliation 业务语义保持不变。
本轮只替换 formal capability 的签发和持续消费边界：

- 删除运行时模块级 `_FORMAL_FACTS_SEAL`；不保留 HMAC key、mint、signer、factory 或初始化 callable 的模块
  attribute。
- 模块初始化时由单一 closure 同时产生 exact public `VerifiedAShareMarketFacts` 类型和唯一 public loader；
  初始化函数随即 `del`。
- 32-byte 随机 HMAC key、内部 mint/verify 与 weak issued-instance registry 只位于 closure；registry 按实例
  身份登记，caller 用 constructor、`object.__new__` 或复制全部 slots 得到的对象均未签发。
- public constructor稳定拒绝；loader 完成 R1 全部 fresh/root/file/窗口/数学验证后，才由 closure 内部创建、
  attestation 并登记实例。

## 2. 内容绑定与持续验证

R2 capability slots 新增 process-local provenance、16-byte nonce、portable whole hash 和 HMAC attestation，并支持
weak reference。attestation payload exact 绑定：

1. formal portable identity；
2. 八帧各自 file/table/schema、列/dtype、identity key、权威物理顺序、row count 与完整 content hash；
3. identity + 八帧 descriptor 的 portable whole hash；
4. release root、plan root 与八文件 process-local `_PathEntity` provenance；
5. process-local nonce。

`identity`、八个 DataFrame property 和 `repr` 每次返回前都由同一 closure verifier 重新验证 registry 身份、
当前 module exact class、全部 frame schema/order/content、whole hash 和 HMAC，比较使用 `hmac.compare_digest`。
合法 DataFrame property 仍返回 clone。任一 slot 经 `object.__setattr__` 漂移后，下次公开消费 fail closed；module
reload 后旧 capability 因 current-class identity 不匹配而失效。

公开失败仍唯一为 `M3_A_SHARE_MARKET_FACTS_INVALID`，并在离开 active `except` 后抛出，cause/context 均为空。
attestation、key、nonce、registry 与 provenance 不进入 repr、portable identity、equality 或 pickle。

## 3. 新增 R2 对抗覆盖

`tests/unit/test_m3_formal_a_share_market_facts.py` 现含 22 项测试，新增覆盖：

- 旧 seal/import 与 module key/mint/signer/factory surface 不存在；
- public constructor、空 `object.__new__`、完整 slots clone 均拒绝；
- 合法 capability 的 13 个签发 slots 逐一原地漂移后拒绝，恢复 exact 内容后重新可用；
- attestation 漂移后 identity、八 property 与 repr 全部在返回前拒绝；
- attacker 同时改写八帧并用 content helper 重算 portable whole hash，仍因缺 HMAC/registry 来源证明而拒绝；
- module reload 后旧 capability 拒绝；合法 capability property clone 与 pickle 拒绝。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，隔离 `PYTHONPATH=src`：

```text
Ruff（两个生产文件 + formal facts 测试）          PASS
mypy（两个生产文件）                              PASS
R2 formal facts 完整对抗                           22 passed / 19.07s
R1 四节点 + G7B + development facts + G7E        29 passed / 144.07s
cold import surface + 无 Qlib/LightGBM/MLflow     PASS
```

WSL Miniforge base：

```text
Ruff（两个生产文件 + formal facts 测试）          PASS
mypy（两个生产文件）                              PASS
R2 formal facts 完整对抗                           22 passed / 17.18s
R1 四节点 + G7B + development facts + G7E        29 passed / 63.11s
cold import surface + 无 Qlib/LightGBM/MLflow     PASS
```

两平台 warnings 仅为既有 Pandera Polars deprecation 与工作区 `.pytest_cache` 权限告警。WSL 工作区解析为
`/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`，是 DrvFS 兼容证据，不是 ext4 Gate。
白名单 `git diff --check` 通过。

## 5. 白名单与剩余验收

- R2 仅修改 `src/quant/backtest/a_share_execution.py` 与既有 formal facts 测试，并更新任务状态、新增本 R2
  报告；`src/quant/backtest/__init__.py` 的 R1 安全导出保持不变。
- 未修改 R1 交付报告或独立初验报告，未联网、add、commit、写正式 artifact/journal 或触碰正式 G1。
- 工作树其他既有脏文件与临时目录保持原状。
- 当前仅为实现自测通过；仍需未参与实现者按 §11 独立攻击 closure 来源、reload、whole-hash 与 slot 漂移，
  再由主 Agent 最终验收。
