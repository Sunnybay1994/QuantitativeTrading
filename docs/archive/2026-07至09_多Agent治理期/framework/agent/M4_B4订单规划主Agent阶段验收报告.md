# M4-B4 订单规划主 Agent 阶段验收报告

日期：2026-08-02（Asia/Shanghai）

结论：**Target 到 `OrderPlan` 的纯内存工程合同通过。** 该结论不关闭正式 M4 Gate，
也不代替 Linux/ext4 Gate、正式 G7 输入链或 PAPER/SHADOW 持续运行证据。

## 实现边界

- 港股通 route 由 target 显式提供，并绑定 intent/plan identity；不按证券代码猜 route。
- 输入重验 market/account/config identity，缺市场状态、缺 route context、多币种混池或配置有效期不闭合时 fail closed。
- 先处理卖出并释放预计现金，再按稳定证券顺序分配买入；规则、费用和 FX 复用 B1/B2/B3 公共接口。
- 每个 target 产生数量守恒的 `OrderPlanDecision`，accepted intent、rejection diagnostics、residual cash 与 plan identity 闭包。
- 规划函数只处理内存对象，不读取数据目录、不发网络请求、不产生订单命令。

## 验证

- Windows Miniforge：B4 与 B1/B2/B3 合并定向 pytest `73 passed`，Ruff、mypy 和公共导入通过。
- WSL Miniforge `base`：对应定向 pytest、Ruff、mypy 通过（记录于提交验证输出）。
- `git diff --check` 通过。

## 剩余边界

- `target_identity` 由上游已验证 target 发布物提供；B4 不重新定义 M3 target 文件 identity。
- 正式 G7、真实费率/FX 发布、B5 账本、B6 事件回测、P4 执行服务及 P8 四周运行仍是后续前置。
