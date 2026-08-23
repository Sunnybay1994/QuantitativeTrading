# M4-C0 主 Agent 终验报告

日期：2026-07-16  
结论：**不通过，退回“外部实现 → 全新外部独立初验”闭环**  
范围：M4-C0 交易配置、安全开关与 canonical identity  
声明：不关闭 M4 或实盘 Gate，不勾选路线图；不评价正在续推的 M4-D0 领域合同

## 1. 已复核证据

- 冻结合同：[`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) §2、§5 M4-C0。
- 外部实现报告：[`M4_C0交易配置交付报告.md`](M4_C0交易配置交付报告.md)。
- 外部独立初验：[`M4_C0交易配置独立初验报告.md`](M4_C0交易配置独立初验报告.md)，结论为可交主验。
- 主 Agent 复跑：`tests/unit/test_trading_config.py` **14 passed**；C0 白名单 Ruff 通过；
  `src/quant/execution/config.py` mypy 通过。
- 未跑全量 pytest：M4-D0 在主验期间写入共享 `execution/__init__.py`、领域合同及其测试，且以下最小反例
  已足以确定 C0 不通过；不把并发工作树的瞬态全量结果当作 C0 证据。

## 2. 主验新增反例

### P0-A：调用方可绕过严格 loader，为非法 LIVE 配置生成 identity

- **现象**：加载合法示例后 thaw `document`、把 `execution.mode` 改为 `LIVE`，再直接调用公开
  `TradingConfig(document=..., schema_version=...)`；`trading_config_identity` 返回合法 64 位 SHA-256，未拒绝。
- **根因**：`TradingConfig` 的 frozen 只冻结字段赋值，不验证或递归冻结调用方传入的 Mapping；identity 入口只做
  `isinstance`，把“对象类型正确”误当作“内容已由严格入口验真”。
- **被破坏规则**：M4 全链安全默认只接受 PAPER/SHADOW；config identity 必须基于 strict canonical 内容，调用方
  不得用自报包装绕过验真。
- **最小复现结果**：`FORGED_LIVE_ID_ACCEPTED 64 LIVE`。
- **影响**：后续 OMS/风控若把 `TradingConfig` 类型或其 identity 当作可信门票，非法配置可越过 C0 门禁。

同一根因还允许构造 `schema_version="caller-forged-version"`、但 `document.meta.schema_version` 仍为 v1 的对象；
两者 identity 完全相同，结果为 `DIVERGENT_VERSION_ACCEPTED True`。公开对象存在两个可漂移的版本事实，违反 SSOT。

### P1-B：`file://` 可绕过绝对个人路径门禁

- **现象**：把 A 股规则 selector 改为 `file:///home/mabw/private/rules_v1`，loader 接受并写入可信配置。
- **根因**：通用字符串路径扫描遇到任意 `://` 直接返回；rule/fee/FX selector 仅检查非空，没有按版本 selector
  的语法收紧，导致 `file://` 和其他 URI 绕过绝对路径检查。
- **被破坏规则**：冻结反例明确要求拒绝绝对个人路径；规则字段是 versioned selector，不是任意 URI。
- **最小复现结果**：`FILE_ABSOLUTE_SELECTOR_ACCEPTED file:///home/mabw/private/rules_v1`。
- **影响**：绝对个人路径进入 config identity、异常或后续报告，既破坏环境可移植性，也扩大路径泄露面。

## 3. 结论与边界

正常样例、任务内既有反例和静态检查均通过，但不能抵消两个信任边界缺口。M4-C0 当前状态为
**主验不通过、待外部返工**。M4-D0 可保留为基于 C0 待返工接口的预实现，但不得据此启动依赖已通过 C0 的
后续 Gate，也不得宣称 C0/M4 完成。

返工合同见 [`M4_C0主验返工任务单.md`](M4_C0主验返工任务单.md)。
