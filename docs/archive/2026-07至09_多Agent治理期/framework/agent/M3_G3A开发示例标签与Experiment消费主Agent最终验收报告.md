# M3 G3A 开发示例标签与 Experiment 消费主 Agent 最终验收报告

日期：2026-08-01
结论：**开发契约 PASS；正式 G1/G3 Gate 未关闭。**

## 边界

- 本轮只在隔离 worktree 中实现 G3A，没有写入正式 G1 发布根、journal 或候选目录。
- development example 只生成 `VerifiedDevelopmentExample*`名义类型，`release_kind="development_example"`、
  `formal_gate_eligible=False`；不产生、伪装或代替 `VerifiedG1Release`。
- 标签基准按用户批准的 `510300.SH` ETF HFQ 总回报代理冻结；当前结果不是真实数据
  性能结论，也不是 Linux Gate 或正式发布证据。

## 实现与根因闭环

- 新增独立 Float64 前向相对收益标签 artifact：`labels.parquet`、`diagnostics.parquet`、
  `label_manifest.json` 和严格 stage receipt 闭包，支持 `h=5/10`。
- 标签从已验真 G1 bars/benchmark/eligible keys 与 snapshot session calendar 重建，覆盖 tail、
  benchmark/asset entry/exit bar、adj-factor 等固定优先级诊断。
- G8 Experiment identity 的 strict reader/consumer verifier 只消费公开契约；build/verify 均强制接收
  可信 `ExperimentIdentitySpec`，重算 formal/development experiment key，并闭合 scientific config、
  dependency fingerprint 和 code version。
- 将 receipt 原始字节/hash 需求收敛到共享 `verify_stage_receipt_with_bytes`：parse/hash 使用
  同一稳定 FD 的字节，完整 root registry 先验真，嵌套 root 选最具体 alias，拒绝
  symlink/reparse、重复物理 root、hard-link 重复与自引用。
- Windows junction 曾可绕过仅 `S_ISLNK` 的目录检查；修复后 root、祖先、内部组件和 leaf
  统一检查 `FILE_ATTRIBUTE_REPARSE_POINT`，并在 `fstat-read-fstat` 后再验 parent chain 与 leaf
  物理身份。

## 验证

Windows 原生 Miniforge：

- Ruff：定向 source/tests，PASS。
- mypy：`run_state.py`、`labels.py`、`contracts.py`、`development_example.py`，PASS。
- pytest G3A：`43 passed, 1 skipped`；skip 为当前 Windows 会话不提供的 symlink 创建，
  Windows junction 实测反例已 PASS。
- snapshot/provider/orchestration 相邻回归：`85 passed, 4 skipped`。

WSL Miniforge `base`：

- Ruff/mypy 同范围：PASS。
- E3 + G3A pytest：`106 passed, 1 skipped`；skip 为 Windows-only junction 用例。
- snapshot/provider/orchestration 相邻回归：`87 passed, 2 skipped`。

独立只读复验经四轮“问题—根因—反例—修复—复验”闭环，最终 **PASS**，未发现剩余
P1/P2。关键额外反例为 Windows unused junction root 与 Experiment manifest/key/receipt 整体替换后
重签 label receipt，均已失败关闭。

## 正式 G1 与剩余风险

验收期间正式 G1 watcher 与 PREPARE 进程仍存活且持续累计 CPU，无 stderr 失败证据；
其将依既定链路继续 PREPARE → Windows PUBLISH → STATUS/磁盘验收。下列事项仍受正式
G1 阻塞：

- 正式 `VerifiedG1Release` 消费与真实 A 股数据重跑；
- 正式 G2/G3 产物、性能结论与 Gate 关闭；
- Linux/ext4 等价不可变发布结论。
