# M3 G7D-F0 R1：正式 A 股八表 MarketFacts 交付报告

日期：2026-08-09  
角色：实现 Agent  
状态：**实现与自测完成，待独立初验；不宣称 G7/M3/Linux ext4 Gate 通过**

## 1. 交付范围

- 在 `src/quant/backtest/a_share_execution.py` 新增唯一 formal loader
  `load_verified_a_share_market_facts`、process-local fresh context、portable identity/digest，及只能由私有 seal
  签发且不可 pickle 的 `VerifiedAShareMarketFacts`。
- loader 固定执行 fresh G1 exact once、fresh G7B exact once；只有二者逐字段匹配 outer capability 后才读取八表。
- 八表只从 fresh G1 `artifact_paths` 选择；逐项验证 G1 manifest v5、schema name、v3、identity key、文件
  bytes/size/hash/content hash、独立权威物理顺序和物理文件唯一性。读取使用同一文件句柄双读、fd/path identity
  与调用前后 root/file snapshot，拒绝 symlink/reparse、hardlink/alias、same-bytes replacement。
- 窗口按冻结的 `E/S/D` 构造；验证 A 股 STOCK/CNY/SH|SZ 生命周期、bar XOR FULL_DAY、PARTIAL、limit、
  H00300.CSI benchmark、SH calendar 与 settlement-session 可映射性。
- corporate-action ledger/reconciliation 验证 canonical sorted unique event set、冻结 hash、允许状态、正 factor，
  并执行 ledger→reconciliation 与 reconciliation→ledger 双向 exact 闭包；保留合法 `NO_EVENT` 审计行。
- portable identity 不含绝对路径、inode、PID 或时间戳；物理 provenance 仅保存在 capability 私有状态。
- `src/quant/backtest/__init__.py` 只增加上述 formal 安全导出；未修改 development 类型或路径。

## 2. 关键失败语义与副作用

- public loader 的所有 upstream、IO、JSON、Polars 与 hostile 异常统一翻译为
  `M3_A_SHARE_MARKET_FACTS_INVALID`，公开异常的 cause/context 为空。
- 本包无写文件、mkdir、receipt、artifact、日志、网络、账户或 credential 入口；测试只使用 pytest 临时目录和
  现有 deterministic fixture。
- formal/development capability 不共享构造器、seal 或字段重签路径。

## 3. 新增测试覆盖

`tests/unit/test_m3_formal_a_share_market_facts.py` 覆盖：

1. E/S/D 窗口选择、三证券连续 session、H00300.CSI benchmark 与 portable identity；
2. bar 公司行动与 FULL_DAY 公司行动两条合法路径，以及缺 ledger 的反向 closure 攻击；
3. 生命周期中途退市、缺 limit、缺 benchmark fail closed；
4. fresh 调用顺序 `G1 -> G7B -> facts` 与 hostile upstream 脱敏；
5. capability 私有 seal，caller 不能公开构造 formal facts。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，隔离 `PYTHONPATH=src`：

```text
ruff check [白名单三文件]                         PASS
mypy [两个生产文件]                              PASS
pytest formal-facts + G7B + development facts + G7E
29 passed, 12504 warnings in 145.51s              PASS
cold import quant.backtest                         PASS
```

WSL Miniforge base，工作区解析为
`/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`：

```text
ruff check [白名单三文件]                         PASS
mypy [两个生产文件]                              PASS
pytest formal-facts + G7B + development facts + G7E
29 passed, 12504 warnings in 70.82s               PASS
cold import quant.backtest（无 Qlib/LightGBM/MLflow） PASS
```

warnings 为既有 Pandera Polars deprecation 与工作区 `.pytest_cache` 权限告警；无测试失败。该 WSL 路径是
DrvFS `/mnt/f`，只构成 Linux runtime 兼容证据，不是 ext4 Gate。

## 5. 白名单与剩余风险

- 修改仅限任务白名单：两个 backtest 生产文件、新增 formal facts 测试、任务状态和本报告。
- 工作树内大量 G4-G7A/G7B 既有未提交变更与临时目录均保持原状；未 add、commit、删除或清理。
- 当前测试对 fresh verifier 使用真实 G7B 邻接回归，并对 loader 调用顺序做定向隔离测试；独立初验仍须按任务单
  补一个实现测试未覆盖的未落盘 root/file replacement 或 FULL_DAY whole-rehash 对抗反例。
- 未运行真实正式 G1 release 全窗口折验、Linux ext4、全量 pytest；这些属于独立初验/主验与后续 Gate。
