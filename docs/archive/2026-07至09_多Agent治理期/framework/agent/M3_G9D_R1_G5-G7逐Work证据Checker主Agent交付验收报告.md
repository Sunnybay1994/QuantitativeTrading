# M3 G9D R1 G5–G7 逐 Work 证据 Checker 主 Agent 交付验收报告

日期：2026-08-13
结论：**工程实现完成；允许继续 G9E；不代表真实 G9 或 M3 Gate 通过**

## 1. 目标与技术边界

本轮新增逐 `(fold, horizon)` 的 G5–G7 本地准入 checker。它只消费 G9B 的 verified subject、确定性
EvidencePlan、当前严格配置和显式 artifact root registry，不接 caller 自报 GateResult，不扫描工作区，也不复制
训练、IC、目标权重、撮合、公司行动或七表账户公式。

G9B 构造 subject 时已经逐 work fresh 验证 feature、alignment 和两次独立 reproducibility；G9D 再验证计划
receipt 字节，并通过生产 strict reader 把后续 manifest/metrics 读回，形成 model→prediction→evaluation→
summary→target→plan→三场景 backtest 的交叉哈希闭包。

## 2. 实现

- 新增 `src/quant/research/m3/acceptance_work.py`：
  - `audit_acceptance_work` 与稳定脱敏错误 `M3_ACCEPTANCE_WORK_INVALID`；
  - EvidencePlan 必须由当前 subject/config 重建后精确相等；
  - G5–G7 每个 locator 都先走 `verify_stage_receipt_with_bytes`；
  - G5 校验同 fold 共享 feature、alignment/model/prediction 链，并再次调用正式 reproducibility verifier；
  - G6 校验 evaluation identity、四项 coverage、computable IC ratio、两个 required evaluation metrics，以及每
    horizon 唯一 summary 对各 fold evaluation manifest/receipt 的精确闭包；
  - G7 校验 target→prediction、plan→target/fold/G1、数量规则版本、三场景共同 target/market facts、严格
    `BacktestMetricsV1`、21 项 input 和生产 SSOT 的 29 项 output；
  - G7 从 readiness receipt 中唯一匹配当前 `raw_config_sha256` 的 config digest 恢复 project root 与配置
    相对路径，逐 work 调用 `resolve_formal_backtest_cli_inputs` 和 `verify_backtest_artifact`，以实际三场景
    fresh replay 拒绝“修改全 bundle 后同步重签 manifest/receipt”的伪证据；
  - required metrics 固定为任务书允许的五项，负值合法，但 required nullable/non-finite 值失败；
  - 费用倍数、只缩放三组件和四个 scientific rounding/annualization 字段均从 config SSOT 核对；
  - 一个 work 失败不会抹掉其他 work 的证据，G6 失败会使同 work G7 以稳定 dependency issue fail closed。
- `quant.research.m3` 继续使用 lazy import 安全导出 G9D 两个公共符号。

## 3. 验证与反例

Windows Miniforge，显式绑定当前工作树 `src`：

- G9C/G9D/acceptance contracts 合并定向测试：**21 passed**；
- G9D 正向覆盖两个 horizon 的 G5/G6/G7 全 PASS；
- 单 work evaluation coverage 漂移：G5 保持 PASS，G6 FAIL，同 work G7 dependency FAIL；
- 发布 receipt 后篡改一个 `1p0x/nav.parquet`：只使 G7 fail closed，G5/G6 不被污染；
- 静态 bundle/receipt 全部自洽但 fresh replay 返回不一致：G7 仍以 `WORK_INVALID` 拒绝；
- 非法 caller：稳定 `M3_ACCEPTANCE_WORK_INVALID`，`__cause__`/`__context__` 均为 `None`；
- Ruff、mypy、fresh cold import 均通过；cold import 未加载 Qlib、LightGBM、MLflow；
- `git diff --check` 退出 0，仅有 Windows LF/CRLF 提示。

测试中的 acceptance 编排边界使用既有 G9C strict subject fixture，并替换各生产 reader 的返回值；reader、
reproducibility verifier、backtest verifier 自身的严格解析和经济公式由各自既有测试负责，本测试不复制它们。

## 4. 尚未关闭

- G9E–G9G 尚未实现；
- honest 300 public chain 仍需在最终 integration revision 上重跑首次发布与 completed resume；
- 本轮是工程 checker 证据，不是实际 300 证券、真实数据或真实 tracking 的 Gate 证据；
- Linux/ext4 按用户当前目标暂不作为本轮阻断。
