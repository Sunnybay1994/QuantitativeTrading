# M3 G3B 开发示例标签全量对账主 Agent 最终验收报告

日期：2026-08-01
结论：**Windows 开发契约 PASS；WSL 平台验证待恢复；正式 G1/G3 Gate 未关闭。**

## 边界

- 本轮只在隔离 worktree 中实现和验证 G3B，没有写入正式 G1 发布根、journal、候选目录或正式候选映射。
- development example 只接受并返回 `VerifiedDevelopmentExample*` 名义类型，身份 key 使用
  `development/example` 独立域，`formal_gate_eligible=False`；不产生、伪装或代替
  `VerifiedG1Release`。
- 结果只证明极小、确定、无网络 fixture 的公开契约可被 G2+ 正常消费；不构成真实数据性能结论、
  Linux Gate 或正式发布证据。

## 实现与合同

- 新增 G3B reconciliation spec、summary、result、receipt paths 以及 formal/development strict
  verifier；发布物固定为 `reconciliation.parquet` 与 `reconciliation.json` 两文件。
- parent 在启动 fresh worker 前验证 G1 release、snapshot、provider、provider validation、experiment、
  label 五类 receipt 的精确输入/输出闭包，并重算完整 identity preimage；worker 只接收显式
  provider URI、全量 row keys 与身份摘要。
- parent 不 import Qlib；worker request/response/details 每次使用全新临时目录。worker echo、JSON、
  Parquet、行键、MultiIndex、日期和非有限值均 fail closed，stdout/stderr/路径及异常上下文不越过稳定
  `M3LabelReconciliationError` 边界。
- parent 从原始 details 独立重建 summary：逐行比较 Qlib expression、provider direct、G1 benchmark、
  G3A raw/relative label，并使用冻结 tolerance 与 nearest-rank p99；worker 自报结论不被信任。
- 标签基准继续固定为用户批准的 `510300.SH` ETF HFQ 总回报代理；文档中 mapper 的当前公开签名和
  `fund_daily + fund_adj + fund_div` 输入职责已与代码同步。

## 对抗性验证

核心反例覆盖：

- receipt 缺真实输入、同 basename/同 SHA 的 request decoy、receipt/identity/horizon/experiment 混配；
- expression 正确/direct 错及反向、benchmark 错用 t+2、start/end 交换、Float32 正常量化；
- missing/extra/duplicate keys、NaN/正负 Inf/signed zero、p99 n=1/100/101、summary 重签漂移；
- worker timeout、坏 JSON、坏 Parquet、echo drift、MultiIndex 顺序；
- parent 预加载 Qlib 与 worker 污染 parent；A→B 第二次科学结果变化，证明不得复用 A 的缓存结果；
- `str`、`repr`、异常参数/上下文四类公开观察面脱敏。

## 验证

Windows 原生 Miniforge（显式 `PYTHONPATH=src` 指向隔离 worktree）：

- Ruff：`src/quant/research/m3` 与 G3B tests，PASS。
- mypy：`src/quant/research/m3`，19 source files，PASS。
- G3B pytest：`16 passed`。
- 独立只读复验：`16 passed`，Ruff/mypy/`git diff --check` PASS，无剩余 P0/P1/P2。
- G3A/provider 相邻回归：`85 passed, 5 skipped`；skip 均为当前 Windows 会话不提供的
  symlink/平台特有用例。

WSL Miniforge `base`：

- 桌面 runner 在创建 WSL instance 时返回
  `Wsl/Service/CreateInstance/E_ACCESSDENIED`；按环境阻塞处理，未循环重试，也未使用 Windows 结果
  代替 Linux 平台验证。

## 正式 G1 与剩余风险

验收期间正式 G1 watcher PID 4204 与 PREPARE PID 9756 均存活、响应且持续累计 CPU；REFERENCE
已经完成，PREPARE 尚未产出完成 JSON，PUBLISH 尚未开始。正式进程、journal、候选和发布目录均未改动。

仍待完成：

- 正式 G1 的 PREPARE → Windows PUBLISH → STATUS/磁盘 `verify_g1_release`；
- WSL runner 恢复后的 base 定向验证，以及正式路径的 Linux/ext4 Gate；
- 正式 `VerifiedG1Release` 上的 G2/G3 产物、真实 Qlib h=5/10 对账与性能结论；
- 正式 G3/G9 Gate 关闭。
