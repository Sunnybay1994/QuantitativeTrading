# M3 G7D-F0 R4：benchmark 510300 SSOT 返工交付报告

日期：2026-08-09  
角色：实现 Agent  
结论：**R4 实现与双平台自测完成，等待全新独立复验；本报告不宣布主验、G7E 恢复或 Gate PASS。**

## 1. 返工原因与合同裁定

权威 `docs/M3实施与Agent交接.md` 与 `configs/research/m3_qlib_example.toml` 均明确 M3 v1 benchmark 只能是
`510300.SH`，禁止与旧 `H00300.CSI` 混用。R3 的 formal F0 selector、fixture 以及 F1 date guard 仍保留旧代码，
导致同一 market-facts identity 无法与后续 G7F benchmark 指标闭合。

实现前核对发现初版 §13 的“只改 F0 selector、不得改 F1 语义”与“510300 capability 必须被 F1/F2 消费”存在
直接冲突：F1 guard 仍 exact 判断旧代码。本轮停止写码并回报最小复现；§13 item 4 随后重冻为方案 A：F1
只验证 exact F0 capability 的 benchmark frame 对请求日期恰一行，业务 selector 的唯一权威留在 F0 与 fresh
config。重冻后继续实现，没有以测试 fixture 绕开冲突。

## 2. 最小实现

- `src/quant/backtest/a_share_execution.py`
  - `_prepare_verified_a_share_market_facts` 在 G1 与 G7B fresh 返回且逐字段 exact 后，读取
    `fresh_context.config.section("data")["benchmark"]`；
  - selector 必须 exact `str` 且 exact `510300.SH`，不接受 caller 参数、裸 TOML、旧代码或模块平行常量；
  - 私有 F0 selector 只选择 `510300.SH x execution_dates`，继续保持每日一行、唯一键、物理顺序、Schema、
    source 与原窗口合同；
  - portable artifact digest、`input_market_facts_sha256`、八帧 whole hash 与 process-local attestation 沿原 R3
    路径自然绑定 selected 510300 frame 及原始 G1 artifact bytes；
  - F1 date guard 删除旧 benchmark code 判断，只验证已验真 exact capability 对请求 date 恰有一行。F1
    exact-type/property-before-use 边界、F2 订单执行语义均未改变。
- `tests/unit/test_m3_formal_a_share_market_facts.py`
  - formal fixture 与正向断言更正为 `510300.SH`；
  - 旧 `H00300.CSI` only frame 与旧/非字符串 selector 拒绝；
  - old/new 混表只选择 config selector，并证明 selected benchmark content digest 不等于旧 frame；
  - 证明调用顺序为 G1 fresh → G7B fresh → config section → 八表读取/selector；G7B drift 在 config/frame
    访问前拒绝；
  - hostile config section 异常统一为 `M3_A_SHARE_MARKET_FACTS_INVALID`，cause/context 为空且不泄露内容；
  - 保留 R3 fresh-subprocess reload 旧 capability 拒绝。F1 既有 fake/development 零 frame 访问反例继续通过，
    F1/F2 全套现通过更新后的 510300 F0 capability。
- F0 任务单状态更新为 R4 自测完成、待全新独立复验和主验。

`src/quant/backtest/__init__.py` 本轮零修改；未修改 config、G1、G7B、G7C、F1/F2 其他生产语义、development
tests 或正式 artifact/journal。未联网、add 或 commit。

## 3. 最终 revision 验证证据

所有命令均在 `artifacts/dev_worktrees/m3-g4-formal` 使用工作树自身 `src`。

### 3.1 Windows 原生 Miniforge

- F0 formal 单文件首轮：**23 passed**，28.63s；
- 最终 F0 + G7C + F1 + F2 formal 邻接：**76 passed**，332.07s；
- 固定顺序 reload subprocess → development facts → formal G7B → development G7E：
  **26 passed**，174.31s；
- Ruff：**PASS**；
- mypy：**PASS**；
- cold import/public signature/factory removal/heavy-dependency isolation：**PASS**。
- production 白名单 `git diff --check`：**PASS**；production 中不再残留 `H00300.CSI`。

### 3.2 WSL Miniforge base

- 最终 F0 + G7C + F1 + F2 formal 邻接：**76 passed**，310.60s；
- 固定顺序 reload subprocess → development facts → formal G7B → development G7E：
  **26 passed**，84.74s；
- Ruff：**PASS**；
- mypy：**PASS**；
- cold import/public signature/factory removal/heavy-dependency isolation：**PASS**。

两平台 warnings 仅为既有 Pandera Polars deprecation 与工作树 `.pytest_cache` 写权限告警。WSL 工作树位于
`/mnt/f`/DrvFS；这些结果只构成双平台兼容证据，不声称 Linux/ext4 Gate。

首轮 Windows 静态检查曾因 selector 参数与 selected frame 使用同名局部变量产生 5 个 mypy 类型错误；修正
为独立 `benchmark_frame` 后，最终生产 revision 的 Windows/WSL Ruff 与 mypy 均通过。该中间失败不计最终
绿测。

## 4. 待验与边界

- R4 只修复 benchmark selector SSOT；R3 capability、八表/root/file/窗口/FULL_DAY/attestation 合同保持不变。
- self-contained capability 仍不修改 G1 release；selected digest 同时绑定原始 artifact bytes 与 510300 窗口切片。
- G7E formal 继续暂停。只有全新独立复验和主 Agent 最终验收均 PASS 后，才可恢复其任务冻结。
- 本报告不证明真实 G1 数据、账户、完整 work、Linux/ext4、G7E/G7F 或 M3 Gate。
