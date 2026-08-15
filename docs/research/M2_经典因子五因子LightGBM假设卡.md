# M2 经典因子五因子 LightGBM 假设卡

日期：2026-08-15
Hypothesis ID：`m2-classic-five-factor-lightgbm-510300-v1`
状态：已运行；`REJECTED`

## 1. 假设

仅使用此前已经诚实实现的五个日频因子：

- `STD20`、`ROC20`、`RSV20`：第一批组合中的三个机制；
- `CORR20`、`WVMA20`：第二批中与既有因子相关性较低的两个机制；
- 明确排除与 `RSV20/ROC20` 高度冗余的 `MA20`。

假设为：五个因子的每日截面 rank 经仅在训练期拟合的 LightGBM 非线性组合，能在
validation early stopping 后改善 20-session 样本外排序，并在冻结的 510300 风险控制与
2x 成本下保持正收益。

## 2. 防泄漏合同

1. `as_of` 为当日收盘，标签为下一开市日开盘进入、20 个 session 后开盘退出；
2. 每折只用 `exit_date_20 <= train_end` 的 train 标签拟合；
3. validation 只用于 LightGBM early stopping，不搜索特征、窗口、Top-K、风险参数或成本；
4. test 在 best iteration 冻结后只预测、评估一次，不参与方向、超参或轮次选择；
5. 输入只做每日截面 average-rank 后中心化，缺失值不填充；
6. 三折、Top-50、20-session 调仓、历史费用与 510300 风险控制均沿用已冻结配置。

本实验是在第一、二批及三因子组合结果可见后提出，已经存在累计多重检验。因此即使通过
门槛也最多为 `RESEARCH_ONLY`，不得修改 2026-08-15 已冻结的前向观察候选，更不得生成
`PAPER_CANDIDATE` 或启动 PAPER。

## 3. 模型与资源边界

- LightGBM 参数沿用项目已版本化的保守 CPU 基线：learning rate 0.05、31 leaves、最多
  500 rounds、50 rounds early stopping、固定 seed、deterministic/force-col-wise；
- 最多 4 个 CPU 线程，为桌面其他工作保留资源；
- 2026-08-15 的 Windows LightGBM GPU 小探针未取得稳定成功终态，进程以非零码退出，
  因此本轮不重复消耗 GPU 调试预算，也不把 GPU 声称为可用；
- 模型按折保存文本、best iteration、特征重要度、validation/test prediction，均进入不可覆盖
  lightweight run。

## 4. 判定

沿用既有研究门槛：三折平均 test RankIC >= 0.01、至少两折为正、2x 成本三折串联
绝对收益为正，并要求风险控制后不存在全现金 period。满足时为 `RESEARCH_ONLY`，否则
`REJECTED`。无论结果如何，不进行同一 test 上的二次调参。

## 5. 运行结论

Run `a4359202a4a93135cd011fda298bf0eedc64be49c8b8adb542257a5fe77262bb`
已发布并逐字节重放为 `reused=true`。三折 20-session test RankIC 均为正，平均约
0.02293；但 1x/2x 三折串联收益约为 -13.00%/-17.99%，未通过成本后绝对收益门槛，
因此结论为 `REJECTED`。

第一、二折 validation 在第 1 棵树即停止，第三折在第 87 棵树停止，说明当前固定模型的
复杂度需求跨期不稳定。该信息只作为否证证据，不据此回头调 learning rate、leaf 数或
early stopping；任何新模型必须建立新假设并使用新的前向证据。
